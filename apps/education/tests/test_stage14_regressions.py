from datetime import date, time
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import (
    Attendance,
    AttendanceStatus,
    Course,
    Enrollment,
    EnrollmentStatus,
    Group,
    Lesson,
    LessonStatus,
    Schedule,
    Student,
)
from apps.education.services import generate_lessons

User = get_user_model()


class Stage14RegressionBase(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.teacher = self.teacher_user.teacher_profile
        self.course = Course.objects.create(name="Math", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="Math A1", course=self.course, teacher=self.teacher, monthly_fee=Decimal("350.00"))

    def login(self, user):
        self.client.force_login(user)

    def _enrolled(self, name, phone):
        student = Student.objects.create(full_name=name, phone=phone)
        Enrollment.objects.create(student=student, group=self.group, started_at=date(2026, 8, 1))
        return student


class LessonDetailQueryStabilityTests(Stage14RegressionBase):
    """Section 15: lesson detail must not execute per-row (N+1) queries."""

    def setUp(self):
        super().setUp()
        self.lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 4), start_time=time(18, 0), end_time=time(19, 0))

    def _queries(self, user, url):
        self.login(user)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def _grow(self, count=30):
        for i in range(count):
            student = self._enrolled(f"Ученик {i}", f"9000000{i:03d}")
            Attendance.objects.create(lesson=self.lesson, student=student, status=AttendanceStatus.PRESENT)

    def test_owner_lesson_detail_query_count_is_constant(self):
        small = self._queries(self.owner, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self._grow()
        large = self._queries(self.owner, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.assertLess(large - small, 5)

    def test_teacher_lesson_detail_query_count_does_not_grow_with_records(self):
        small = self._queries(self.teacher_user, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self._grow()
        large = self._queries(self.teacher_user, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.assertLess(large - small, 5)


class LessonDetailSummaryTests(Stage14RegressionBase):
    """Section 5: summary counts active students while keeping full attendance history."""

    def test_summary_with_historical_students(self):
        active = [self._enrolled(f"Активный {i}", f"9000000{i:03d}") for i in range(3)]
        historical = Student.objects.create(full_name="Бывший", phone="900777777")
        Enrollment.objects.create(
            student=historical,
            group=self.group,
            started_at=date(2026, 5, 1),
            ended_at=date(2026, 7, 31),
            status=EnrollmentStatus.ENDED,
        )
        lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 4), start_time=time(18, 0), end_time=time(19, 0))
        Attendance.objects.create(lesson=lesson, student=active[0], status=AttendanceStatus.PRESENT)
        Attendance.objects.create(lesson=lesson, student=historical, status=AttendanceStatus.PRESENT)

        self.login(self.owner)
        response = self.client.get(reverse("education:lesson-detail", args=[lesson.pk]))
        self.assertEqual(response.status_code, 200)
        summary = response.context["summary"]
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["present"], 2)
        self.assertEqual(summary["absent"], 0)
        self.assertEqual(summary["late"], 0)
        self.assertEqual(summary["not_marked"], 2)


class CompletedLessonAttendanceTests(Stage14RegressionBase):
    """Section 5: completed lessons may still be corrected; cancelled ones are frozen."""

    def test_completed_lesson_allows_attendance_marking(self):
        student = self._enrolled("Алиев Рустам", "900123456")
        lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 4), start_time=time(18, 0), end_time=time(19, 0))
        self.login(self.owner)
        self.client.post(reverse("education:lesson-complete", args=[lesson.pk]))
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonStatus.COMPLETED)

        response = self.client.post(
            reverse("education:lesson-detail", args=[lesson.pk]),
            {f"status_{student.pk}": AttendanceStatus.ABSENT, f"note_{student.pk}": "Опоздал на час"},
        )
        self.assertRedirects(response, reverse("education:lesson-detail", args=[lesson.pk]))
        record = Attendance.objects.get(lesson=lesson, student=student)
        self.assertEqual(record.status, AttendanceStatus.ABSENT)

    def test_cancelled_lesson_never_creates_attendance(self):
        student = self._enrolled("Каримова Мадина", "900987654")
        lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 4), start_time=time(18, 0), end_time=time(19, 0))
        self.login(self.owner)
        self.client.post(reverse("education:lesson-status", args=[lesson.pk, LessonStatus.CANCELLED]))
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonStatus.CANCELLED)

        response = self.client.post(
            reverse("education:lesson-detail", args=[lesson.pk]),
            {f"status_{student.pk}": AttendanceStatus.PRESENT, f"note_{student.pk}": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Attendance.objects.filter(lesson=lesson, student=student).exists())


class GenerateLessonsAtomicityTests(Stage14RegressionBase):
    """Section 12: a partial failure during generation must roll back the whole batch."""

    def test_partial_failure_rolls_back_whole_generation(self):
        schedule = Schedule.objects.create(
            group=self.group,
            weekday=1,
            start_time=time(18, 0),
            end_time=time(19, 0),
            start_date=date(2026, 8, 4),
            end_date=date(2026, 8, 25),
        )
        real_save = Lesson.save
        state = {"calls": 0}

        def flaky_save(instance, *args, **kwargs):
            state["calls"] += 1
            if state["calls"] == 2:
                raise RuntimeError("boom")
            return real_save(instance, *args, **kwargs)

        with mock.patch.object(Lesson, "save", autospec=True, side_effect=flaky_save):
            with self.assertRaises(RuntimeError):
                generate_lessons(schedule, date(2026, 8, 4), date(2026, 8, 25))

        self.assertEqual(state["calls"], 2)
        self.assertEqual(Lesson.objects.count(), 0)
