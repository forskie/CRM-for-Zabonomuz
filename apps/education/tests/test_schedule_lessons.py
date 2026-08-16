from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import Course, Enrollment, EnrollmentStatus, Group, Lesson, LessonStatus, Schedule, Student


User = get_user_model()


class ScheduleLessonTests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.other_teacher = User.objects.create_user("other", password=self.password, role=UserRole.TEACHER)
        course = Course.objects.create(name="English", default_monthly_fee=300)
        self.group = Group.objects.create(name="A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("300"))
        self.other_group = Group.objects.create(name="B1", course=course, teacher=self.other_teacher.teacher_profile, monthly_fee=300)

    def test_schedule_validation_conflicts_and_adjacent_times(self):
        Schedule.objects.create(group=self.group, weekday=0, start_time=time(18), end_time=time(19, 30))
        adjacent = Schedule(group=self.group, weekday=0, start_time=time(19, 30), end_time=time(21))
        adjacent.full_clean()
        adjacent.save()
        conflict = Schedule(group=self.group, weekday=0, start_time=time(19), end_time=time(20))
        with self.assertRaises(ValidationError):
            conflict.full_clean()
        invalid = Schedule(group=self.group, weekday=1, start_time=time(20), end_time=time(20))
        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_admin_creates_edits_and_deactivates_schedule(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:schedule-create", args=[self.group.pk]), {"weekday": 0, "start_time": "18:00", "end_time": "19:30", "is_active": "on"})
        schedule = Schedule.objects.get(group=self.group)
        self.assertRedirects(response, reverse("education:group-detail", args=[self.group.pk]))
        self.client.post(reverse("education:schedule-edit", args=[schedule.pk]), {"weekday": 2, "start_time": "18:00", "end_time": "19:30", "is_active": "on"})
        self.client.post(reverse("education:schedule-deactivate", args=[schedule.pk]))
        schedule.refresh_from_db()
        self.assertFalse(schedule.is_active)

    def test_lesson_create_from_schedule_is_independent(self):
        schedule = Schedule.objects.create(group=self.group, weekday=0, start_time=time(18), end_time=time(19, 30))
        self.client.force_login(self.admin)
        self.client.post(reverse("education:lesson-from-schedule", args=[schedule.pk]), {"date": "2026-08-17"})
        lesson = Lesson.objects.get(schedule=schedule)
        schedule.start_time = time(19)
        schedule.end_time = time(20)
        schedule.save()
        lesson.refresh_from_db()
        self.assertEqual(lesson.start_time, time(18))

    def test_lesson_conflict_invalid_time_and_status_changes(self):
        Lesson.objects.create(group=self.group, date=date(2026, 8, 18), start_time=time(18), end_time=time(19, 30))
        conflicting = Lesson(group=self.group, date=date(2026, 8, 18), start_time=time(19), end_time=time(20))
        with self.assertRaises(ValidationError):
            conflicting.full_clean()
        invalid = Lesson(group=self.group, date=date(2026, 8, 19), start_time=time(18), end_time=time(18))
        with self.assertRaises(ValidationError):
            invalid.full_clean()
        self.client.force_login(self.admin)
        lesson = Lesson.objects.first()
        self.client.post(reverse("education:lesson-status", args=[lesson.pk, LessonStatus.COMPLETED]))
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonStatus.COMPLETED)
        self.client.post(reverse("education:lesson-status", args=[lesson.pk, LessonStatus.CANCELLED]))
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonStatus.CANCELLED)

    def test_teacher_sees_only_own_lessons_and_cannot_modify(self):
        own = Lesson.objects.create(group=self.group, date=date(2026, 8, 18), start_time=time(18), end_time=time(19))
        other = Lesson.objects.create(group=self.other_group, date=date(2026, 8, 18), start_time=time(18), end_time=time(19))
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:lesson-list"))
        self.assertContains(response, own.group.name)
        lesson_pks = [lesson.pk for lesson in response.context["page_obj"]]
        self.assertIn(own.pk, lesson_pks)
        self.assertNotIn(other.pk, lesson_pks)
        self.assertEqual(self.client.get(reverse("education:lesson-detail", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("education:lesson-status", args=[own.pk, LessonStatus.CANCELLED])).status_code, 403)

    def test_group_page_and_active_students_preparation(self):
        schedule = Schedule.objects.create(group=self.group, weekday=0, start_time=time(18), end_time=time(19))
        Lesson.objects.create(group=self.group, date=date(2026, 12, 1), start_time=time(18), end_time=time(19), schedule=schedule)
        active = Student.objects.create(full_name="Активный")
        ended = Student.objects.create(full_name="Завершённый")
        Enrollment.objects.create(student=active, group=self.group, started_at=date(2026, 8, 1))
        Enrollment.objects.create(student=ended, group=self.group, started_at=date(2026, 6, 1), ended_at=date(2026, 7, 1), status=EnrollmentStatus.ENDED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:group-detail", args=[self.group.pk]))
        self.assertContains(response, "Понедельник")
        lesson = Lesson.objects.get(group=self.group)
        self.assertEqual(list(lesson.active_students()), [active])
