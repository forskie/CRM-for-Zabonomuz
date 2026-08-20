from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.education.models import (
    Attendance, AttendanceStatus, Course, Enrollment, Group, Lesson,
    LessonStatus, Student,
)


class Stage19LessonWorkspaceTests(TestCase):
    password = "Stage19-secure-password"

    def setUp(self):
        self.owner = User.objects.create_user("owner19", password=self.password, role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher19", password=self.password, role=UserRole.TEACHER)
        self.teacher = self.teacher_user.teacher_profile
        self.other_user = User.objects.create_user("other19", password=self.password, role=UserRole.TEACHER)
        self.other_teacher = self.other_user.teacher_profile
        self.course = Course.objects.create(name="Stage 19", default_monthly_fee=Decimal("100"))
        self.group = Group.objects.create(name="Stage 19 group", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100"))
        self.other_group = Group.objects.create(name="Other group", course=self.course, teacher=self.other_teacher, monthly_fee=Decimal("100"))
        self.student_one = Student.objects.create(full_name="Анна Первая")
        self.student_two = Student.objects.create(full_name="Борис Второй")
        start = timezone.localdate() - timedelta(days=30)
        Enrollment.objects.create(student=self.student_one, group=self.group, started_at=start)
        Enrollment.objects.create(student=self.student_two, group=self.group, started_at=start)
        self.lesson = Lesson.objects.create(
            group=self.group, date=timezone.localdate(), start_time=time(10), end_time=time(11)
        )

    def url(self, lesson=None):
        return reverse("education:lesson-detail", args=[(lesson or self.lesson).pk])

    def payload(self, *, action="save", second=AttendanceStatus.ABSENT):
        return {
            "topic": "Новая тема", "teacher_note": "Работа в классе", "homework": "Упражнение 4",
            f"status_{self.student_one.pk}": AttendanceStatus.PRESENT,
            f"note_{self.student_one.pk}": "",
            f"status_{self.student_two.pk}": second,
            f"note_{self.student_two.pk}": "Причина",
            "action": action,
        }

    def test_workspace_has_safe_mark_all_and_mobile_controls(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(self.url())
        self.assertContains(response, "Отметить пустые как присутствующие")
        self.assertContains(response, 'type="button"')
        self.assertContains(response, "if (!select.value)")
        self.assertContains(response, 'class="attendance-status"')
        self.assertContains(response, 'data-label="Статус"')
        self.assertNotContains(response, "Сохранить и завершить")

    def test_mark_all_is_client_only_and_get_does_not_mutate(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student_one, status=AttendanceStatus.ABSENT)
        self.client.force_login(self.teacher_user)
        response = self.client.get(self.url())
        self.assertContains(response, 'value="ABSENT" selected')
        self.assertEqual(Attendance.objects.count(), 1)

    def test_save_updates_attendance_and_report_without_completing(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url(), self.payload())
        self.assertRedirects(response, self.url())
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)
        self.assertEqual(self.lesson.topic, "Новая тема")
        self.assertEqual(Attendance.objects.get(lesson=self.lesson, student=self.student_one).status, AttendanceStatus.PRESENT)

    def test_save_and_complete_is_atomic_happy_path(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url(), self.payload(action="save_complete"))
        self.assertRedirects(response, self.url())
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.COMPLETED)
        self.assertEqual(self.lesson.homework, "Упражнение 4")
        self.assertEqual(Attendance.objects.filter(lesson=self.lesson).count(), 2)

    def test_save_and_complete_rejects_incomplete_roster_without_partial_save(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url(), self.payload(action="save_complete", second=""))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "не отмечено учеников — 1")
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)
        self.assertEqual(self.lesson.topic, "")
        self.assertFalse(Attendance.objects.filter(lesson=self.lesson).exists())

    def test_unexpected_report_failure_rolls_back_attendance(self):
        self.client.force_login(self.owner)
        with patch("apps.education.views.LessonReportForm.save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url(), self.payload(action="save_complete"))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)
        self.assertFalse(Attendance.objects.filter(lesson=self.lesson).exists())

    def test_teacher_cannot_open_foreign_lesson(self):
        foreign = Lesson.objects.create(group=self.other_group, date=timezone.localdate(), start_time=time(12), end_time=time(13))
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(self.url(foreign)).status_code, 404)

    def test_next_lesson_is_scoped_to_teacher(self):
        foreign = Lesson.objects.create(group=self.other_group, date=self.lesson.date, start_time=time(11), end_time=time(12))
        own_next = Lesson.objects.create(group=self.group, date=self.lesson.date, start_time=time(12), end_time=time(13))
        self.client.force_login(self.teacher_user)
        response = self.client.get(self.url())
        self.assertEqual(response.context["next_lesson"], own_next)
        self.assertNotContains(response, self.url(foreign))

    def test_substitute_teacher_can_use_workspace(self):
        substitute_lesson = Lesson.objects.create(
            group=self.other_group, teacher=self.teacher, date=timezone.localdate(), start_time=time(14), end_time=time(15)
        )
        self.client.force_login(self.teacher_user)
        response = self.client.get(self.url(substitute_lesson))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_edit"])

    def test_cancelled_lesson_cannot_be_changed_or_completed(self):
        self.lesson.status = LessonStatus.CANCELLED
        self.lesson.save(update_fields=("status", "updated_at"))
        self.client.force_login(self.teacher_user)
        response = self.client.post(self.url(), self.payload(action="save_complete"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Нельзя изменять посещаемость отменённого занятия")
        self.assertFalse(Attendance.objects.filter(lesson=self.lesson).exists())

    def test_dashboard_pending_action_links_to_exact_scoped_lesson(self):
        self.lesson.date = timezone.localdate() - timedelta(days=1)
        self.lesson.save(update_fields=("date", "updated_at"))
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["attendance_pending"][0], self.lesson)
        self.assertContains(response, self.url())
        self.assertNotContains(response, "Оплачено за")
