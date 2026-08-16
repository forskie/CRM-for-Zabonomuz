from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import Attendance, AttendanceStatus, Course, Enrollment, EnrollmentStatus, Group, Lesson, LessonStatus, Student


User = get_user_model()


class AttendanceTestCase(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.other_teacher_user = User.objects.create_user("other", password=self.password, role=UserRole.TEACHER)
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.other_group = Group.objects.create(name="Russian A1", course=course, teacher=self.other_teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        self.student_2 = Student.objects.create(full_name="Каримова Мадина", phone="900123457")
        self.other_student = Student.objects.create(full_name="Чужой ученик", phone="900123458")
        self.lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        self.other_lesson = Lesson.objects.create(group=self.other_group, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        Enrollment.objects.create(student=self.student_2, group=self.group, started_at=date(2026, 8, 1))

    def _mark_fields(self, lesson):
        return {
            f"status_{self.student.pk}": AttendanceStatus.PRESENT,
            f"note_{self.student.pk}": "",
            f"status_{self.student_2.pk}": AttendanceStatus.LATE,
            f"note_{self.student_2.pk}": "15 минут",
        }

    def test_attendance_stores_each_status_with_note(self):
        for status in AttendanceStatus.values:
            record = Attendance.objects.create(lesson=self.lesson, student=Student.objects.create(full_name=f"Ученик {status}"), status=status, note="Заметка")
            self.assertEqual(record.status, status)
            self.assertEqual(record.note, "Заметка")

    def test_unique_lesson_student_constraint(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.ABSENT)

    def test_cannot_mark_student_without_active_enrollment(self):
        record = Attendance(lesson=self.lesson, student=self.other_student, status=AttendanceStatus.PRESENT)
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_cannot_mark_student_with_ended_enrollment(self):
        ended = Student.objects.create(full_name="Завершивший")
        Enrollment.objects.create(student=ended, group=self.group, started_at=date(2026, 6, 1), ended_at=date(2026, 7, 1), status=EnrollmentStatus.ENDED)
        record = Attendance(lesson=self.lesson, student=ended, status=AttendanceStatus.PRESENT)
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_cannot_mark_student_from_another_group(self):
        Enrollment.objects.create(student=self.other_student, group=self.other_group, started_at=date(2026, 8, 1))
        record = Attendance(lesson=self.lesson, student=self.other_student, status=AttendanceStatus.PRESENT)
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_owner_can_mark_attendance_via_lesson_detail(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson.pk]), self._mark_fields(self.lesson))
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.assertEqual(Attendance.objects.get(lesson=self.lesson, student=self.student).status, AttendanceStatus.PRESENT)
        late = Attendance.objects.get(lesson=self.lesson, student=self.student_2)
        self.assertEqual(late.status, AttendanceStatus.LATE)
        self.assertEqual(late.note, "15 минут")

    def test_admin_can_mark_all_statuses_in_one_submission(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson.pk]), {
            f"status_{self.student.pk}": AttendanceStatus.PRESENT,
            f"note_{self.student.pk}": "",
            f"status_{self.student_2.pk}": AttendanceStatus.ABSENT,
            f"note_{self.student_2.pk}": "Болел",
        })
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.assertEqual(Attendance.objects.filter(lesson=self.lesson).count(), 2)
        self.assertEqual(Attendance.objects.get(lesson=self.lesson, student=self.student).status, AttendanceStatus.PRESENT)
        absent = Attendance.objects.get(lesson=self.lesson, student=self.student_2)
        self.assertEqual(absent.status, AttendanceStatus.ABSENT)
        self.assertEqual(absent.note, "Болел")

    def test_bulk_save_updates_existing_attendance(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT, note="Был")
        self.client.force_login(self.admin)
        self.client.post(reverse("education:lesson-detail", args=[self.lesson.pk]), {
            f"status_{self.student.pk}": AttendanceStatus.ABSENT,
            f"note_{self.student.pk}": "Болел",
        })
        record = Attendance.objects.get(lesson=self.lesson, student=self.student)
        self.assertEqual(record.status, AttendanceStatus.ABSENT)
        self.assertEqual(record.note, "Болел")
        self.assertEqual(Attendance.objects.filter(lesson=self.lesson).count(), 1)

    def test_teacher_cannot_modify_attendance(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson.pk]), {
            f"status_{self.student.pk}": AttendanceStatus.PRESENT,
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Attendance.objects.filter(lesson=self.lesson).exists())

    def test_teacher_cannot_modify_foreign_lesson(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("education:lesson-detail", args=[self.other_lesson.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("education:lesson-detail", args=[self.other_lesson.pk]), {
            f"status_{self.student.pk}": AttendanceStatus.PRESENT,
        }).status_code, 404)

    def test_teacher_sees_only_own_group_attendance(self):
        Enrollment.objects.create(student=self.other_student, group=self.other_group, started_at=date(2026, 8, 1))
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        Attendance.objects.create(lesson=self.other_lesson, student=self.other_student, status=AttendanceStatus.ABSENT)
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.assertContains(response, "Присутствовал")
        response = self.client.get(reverse("education:student-detail", args=[self.student.pk]))
        self.assertContains(response, "Присутствовал")

    def test_lesson_detail_shows_attendance_and_summary(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.assertContains(response, self.student.full_name)
        self.assertContains(response, self.student_2.full_name)
        self.assertContains(response, "Присутствовал")

    def test_student_detail_shows_attendance_history(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.LATE, note="Опоздал на 10 минут")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-detail", args=[self.student.pk]))
        self.assertContains(response, "Attendance history")
        self.assertContains(response, "Опоздал на 10 минут")
        self.assertContains(response, "Опоздал")

    def test_lesson_list_shows_attendance_indicator(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:lesson-list"))
        self.assertContains(response, "1 / 2")

    def test_cancelled_lesson_attendance_is_blocked(self):
        self.lesson.status = LessonStatus.CANCELLED
        self.lesson.save(update_fields=("status", "updated_at"))
        record = Attendance(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        with self.assertRaises(ValidationError):
            record.full_clean()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson.pk]), {
            f"status_{self.student.pk}": AttendanceStatus.PRESENT,
        })
        self.assertContains(response, "Нельзя изменять посещаемость отменённого занятия.")
        self.assertFalse(Attendance.objects.filter(lesson=self.lesson).exists())
