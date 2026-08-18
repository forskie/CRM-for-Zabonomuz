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
    AuditAction,
    AuditLog,
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
        Attendance.objects.create(lesson=lesson, student=student, status=AttendanceStatus.PRESENT)
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


class LessonCompletionRequiresAttendanceTests(Stage14RegressionBase):
    """P0-2: Lesson cannot be completed without at least one attendance record."""

    def setUp(self):
        super().setUp()
        self.student = self._enrolled("Алиев Рустам", "900123456")
        self.lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 4), start_time=time(18, 0), end_time=time(19, 0))

    def test_complete_rejected_without_attendance(self):
        self.login(self.owner)
        response = self.client.post(reverse("education:lesson-complete", args=[self.lesson.pk]))
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)

    def test_lesson_status_unchanged_after_rejection(self):
        self.login(self.owner)
        self.client.post(reverse("education:lesson-complete", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)

    def test_complete_succeeds_after_attendance(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        self.login(self.owner)
        response = self.client.post(reverse("education:lesson-complete", args=[self.lesson.pk]))
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.COMPLETED)

    def test_teacher_complete_rejected_without_attendance(self):
        self.login(self.teacher_user)
        response = self.client.post(reverse("education:lesson-complete", args=[self.lesson.pk]))
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)

    def test_cannot_complete_cancelled_lesson(self):
        self.lesson.status = LessonStatus.CANCELLED
        self.lesson.save(update_fields=("status", "updated_at"))
        self.login(self.owner)
        response = self.client.post(reverse("education:lesson-complete", args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 403)


class TeacherAttendanceTests(Stage14RegressionBase):
    """P0-1: Teacher can mark attendance on own lessons; cannot on foreign."""

    def setUp(self):
        super().setUp()
        self.other_teacher_user = User.objects.create_user("other_teacher", password=self.password, role=UserRole.TEACHER)
        self.other_group = Group.objects.create(name="English B1", course=self.course, teacher=self.other_teacher_user.teacher_profile, monthly_fee=Decimal("400.00"))
        self.student = self._enrolled("Алиев Рустам", "900123456")
        self.lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 4), start_time=time(18, 0), end_time=time(19, 0))
        self.other_lesson = Lesson.objects.create(group=self.other_group, date=date(2026, 8, 4), start_time=time(19, 0), end_time=time(20, 0))

    def test_teacher_marks_attendance_on_own_lesson(self):
        self.login(self.teacher_user)
        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson.pk]), {
            f"status_{self.student.pk}": AttendanceStatus.PRESENT,
        })
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        record = Attendance.objects.get(lesson=self.lesson, student=self.student)
        self.assertEqual(record.status, AttendanceStatus.PRESENT)

    def test_teacher_sees_can_edit_true_on_own_lesson(self):
        self.login(self.teacher_user)
        response = self.client.get(reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.assertEqual(response.context["can_edit"], True)

    def test_teacher_cannot_access_foreign_lesson(self):
        self.login(self.teacher_user)
        response = self.client.get(reverse("education:lesson-detail", args=[self.other_lesson.pk]))
        self.assertEqual(response.status_code, 404)

    def test_teacher_cannot_post_to_foreign_lesson(self):
        self.login(self.teacher_user)
        response = self.client.post(reverse("education:lesson-detail", args=[self.other_lesson.pk]), {
            f"status_{self.student.pk}": AttendanceStatus.PRESENT,
        })
        self.assertEqual(response.status_code, 404)


class TeacherDetailTests(Stage14RegressionBase):
    """P1-3: Teacher Detail page shows groups, schedule, and upcoming lessons."""

    def setUp(self):
        super().setUp()
        self.student = self._enrolled("Алиев Рустам", "900123456")
        self.schedule = Schedule.objects.create(group=self.group, weekday=0, start_time=time(18, 0), end_time=time(19, 0))
        self.lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 18), start_time=time(18, 0), end_time=time(19, 0))

    def test_admin_sees_groups_on_teacher_detail(self):
        self.login(self.owner)
        response = self.client.get(reverse("education:teacher-detail", args=[self.teacher.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["active_groups"]), 1)
        self.assertEqual(response.context["active_groups"][0].active_students_count, 1)

    def test_admin_sees_schedule_on_teacher_detail(self):
        self.login(self.owner)
        response = self.client.get(reverse("education:teacher-detail", args=[self.teacher.pk]))
        self.assertEqual(len(response.context["schedules"]), 1)

    def test_admin_sees_upcoming_lessons_on_teacher_detail(self):
        self.login(self.owner)
        response = self.client.get(reverse("education:teacher-detail", args=[self.teacher.pk]))
        self.assertGreaterEqual(len(response.context["upcoming_lessons"]), 1)

    def test_teacher_can_view_own_detail(self):
        self.login(self.teacher_user)
        response = self.client.get(reverse("education:teacher-detail", args=[self.teacher.pk]))
        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_view_other_teacher_detail(self):
        self.login(self.teacher_user)
        other = User.objects.create_user("other", password=self.password, role=UserRole.TEACHER)
        response = self.client.get(reverse("education:teacher-detail", args=[other.teacher_profile.pk]))
        self.assertEqual(response.status_code, 403)


class AuditCoverageTests(Stage14RegressionBase):
    """P1-4: Course, Group, and Teacher changes are audited."""

    def test_course_create_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:course-create"), {"name": "Физика", "description": "", "default_monthly_fee": "200.00"})
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.COURSE_CREATE)
        self.assertEqual(log.target_type, "Course")

    def test_course_edit_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:course-edit", args=[self.course.pk]), {"name": "Математика", "description": "", "default_monthly_fee": "300.00"})
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.COURSE_EDIT)

    def test_course_status_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:course-status", args=[self.course.pk, "ARCHIVED"]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.COURSE_STATUS)

    def test_group_create_audited(self):
        self.login(self.owner)
        teacher = User.objects.create_user("g_teacher", password=self.password, role=UserRole.TEACHER)
        self.client.post(reverse("education:group-create"), {
            "name": "New Group", "course": self.course.pk, "teacher": teacher.teacher_profile.pk, "monthly_fee": "300.00",
        })
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.GROUP_CREATE)
        self.assertEqual(log.target_type, "Group")

    def test_group_edit_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:group-edit", args=[self.group.pk]), {
            "name": "Math A1 Updated", "course": self.course.pk, "teacher": self.teacher.pk, "monthly_fee": "350.00",
        })
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.GROUP_EDIT)

    def test_group_status_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:group-status", args=[self.group.pk, "ARCHIVED"]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.GROUP_STATUS)

    def test_teacher_edit_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:teacher-edit", args=[self.teacher.pk]), {"full_name": "New Name", "phone": "900111222"})
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.TEACHER_EDIT)
        self.assertEqual(log.target_type, "Teacher")

    def test_teacher_status_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:teacher-status", args=[self.teacher.pk, "ARCHIVED"]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.TEACHER_STATUS)

    def test_teacher_status_not_audited_when_unchanged(self):
        self.login(self.owner)
        self.client.post(reverse("education:teacher-status", args=[self.teacher.pk, "ACTIVE"]))
        self.assertEqual(AuditLog.objects.count(), 0)


class CourseDetailTests(Stage14RegressionBase):
    """P2-6: Course Detail page shows course info and its active groups."""

    def test_course_detail_shows_groups(self):
        self.login(self.owner)
        response = self.client.get(reverse("education:course-detail", args=[self.course.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.course.name)
        self.assertEqual(len(response.context["groups"]), 1)

    def test_course_detail_accessible_to_owner(self):
        self.login(self.owner)
        response = self.client.get(reverse("education:course-detail", args=[self.course.pk]))
        self.assertEqual(response.status_code, 200)

    def test_course_detail_accessible_to_teacher(self):
        self.login(self.teacher_user)
        response = self.client.get(reverse("education:course-detail", args=[self.course.pk]))
        self.assertEqual(response.status_code, 200)
