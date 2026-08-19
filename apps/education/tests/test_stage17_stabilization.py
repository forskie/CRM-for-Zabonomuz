from datetime import date, time
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User, UserRole
from apps.education.materialize import materialize_range, reconcile_occurrence
from apps.education.models import (
    Attendance, AttendanceStatus, AuditAction, AuditLog, Course, Enrollment,
    EnrollmentStatus, Group, Lesson, LessonStatus, OverrideType, RecordStatus,
    Schedule, ScheduleOverride, Student,
)
from apps.education.services import generate_lessons


class Stage17Base(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner17", password="StrongPass123!", role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher17", password="StrongPass123!", role=UserRole.TEACHER)
        self.teacher = self.teacher_user.teacher_profile
        self.teacher.full_name = "Teacher 17"
        self.teacher.save()
        self.course = Course.objects.create(name="Stage 17", default_monthly_fee=Decimal("100"))
        self.group = Group.objects.create(
            name="Stage 17 group", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100")
        )
        self.schedule = Schedule.objects.create(
            group=self.group, weekday=0, start_time=time(18), end_time=time(19),
            start_date=date(2026, 8, 17), end_date=date(2026, 9, 7),
        )


class RecurrenceReconciliationTests(Stage17Base):
    def test_normal_and_repeated_materialization_are_idempotent(self):
        materialize_range(self.group, date(2026, 8, 17), date(2026, 8, 31))
        materialize_range(self.group, date(2026, 8, 17), date(2026, 8, 31))
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 3)

    def test_cancel_before_and_after_materialization(self):
        ScheduleOverride.objects.create(
            schedule=self.schedule, date=date(2026, 8, 17), override_type=OverrideType.CANCELLED
        )
        before = reconcile_occurrence(self.schedule, date(2026, 8, 17))
        self.assertEqual(before.status, LessonStatus.CANCELLED)
        normal = reconcile_occurrence(self.schedule, date(2026, 8, 24))
        ScheduleOverride.objects.create(
            schedule=self.schedule, date=date(2026, 8, 24), override_type=OverrideType.CANCELLED
        )
        after = reconcile_occurrence(self.schedule, date(2026, 8, 24))
        self.assertEqual(after.pk, normal.pk)
        self.assertEqual(after.status, LessonStatus.CANCELLED)

    def test_reschedule_before_materialization_is_repeatable(self):
        ScheduleOverride.objects.create(
            schedule=self.schedule, date=date(2026, 8, 17), override_type=OverrideType.RESCHEDULED,
            new_date=date(2026, 8, 18), new_start_time=time(19), new_end_time=time(20),
        )
        first = reconcile_occurrence(self.schedule, date(2026, 8, 17))
        second = reconcile_occurrence(self.schedule, date(2026, 8, 17))
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.occurrence_date, date(2026, 8, 17))
        self.assertEqual(first.date, date(2026, 8, 18))
        self.assertFalse(Lesson.objects.filter(schedule=self.schedule, date=date(2026, 8, 17)).exists())

    def test_reschedule_after_materialization_reconciles_same_row(self):
        lesson = reconcile_occurrence(self.schedule, date(2026, 8, 17))
        ScheduleOverride.objects.create(
            schedule=self.schedule, date=date(2026, 8, 17), override_type=OverrideType.RESCHEDULED,
            new_date=date(2026, 8, 18), new_start_time=time(19), new_end_time=time(20),
        )
        reconciled = reconcile_occurrence(self.schedule, date(2026, 8, 17))
        self.assertEqual(reconciled.pk, lesson.pk)
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 1)

    def test_substitute_is_assigned_only_to_occurrence(self):
        substitute_user = User.objects.create_user("sub17", password="StrongPass123!", role=UserRole.TEACHER)
        substitute = substitute_user.teacher_profile
        ScheduleOverride.objects.create(
            schedule=self.schedule, date=date(2026, 8, 17), override_type=OverrideType.SUBSTITUTE,
            substitute_teacher=substitute,
        )
        lesson = reconcile_occurrence(self.schedule, date(2026, 8, 17))
        self.assertEqual(lesson.teacher, substitute)
        self.assertEqual(self.group.teacher, self.teacher)

    def test_manual_generation_uses_overrides_and_bounds(self):
        ScheduleOverride.objects.create(
            schedule=self.schedule, date=date(2026, 8, 17), override_type=OverrideType.RESCHEDULED,
            new_date=date(2026, 8, 18), new_start_time=time(19), new_end_time=time(20),
        )
        generate_lessons(self.schedule, date(2026, 8, 1), date(2026, 9, 30))
        lesson = Lesson.objects.get(schedule=self.schedule, occurrence_date=date(2026, 8, 17))
        self.assertEqual(lesson.date, date(2026, 8, 18))
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 4)

    def test_completed_history_is_not_rewritten(self):
        lesson = reconcile_occurrence(self.schedule, date(2026, 8, 17))
        lesson.status = LessonStatus.COMPLETED
        lesson.save(update_fields=("status",))
        ScheduleOverride.objects.create(
            schedule=self.schedule, date=date(2026, 8, 17), override_type=OverrideType.CANCELLED
        )
        reconciled = reconcile_occurrence(self.schedule, date(2026, 8, 17))
        self.assertEqual(reconciled.status, LessonStatus.COMPLETED)


class TeacherDeactivationTests(Stage17Base):
    def test_active_groups_block_archive(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("education:teacher-status", args=[self.teacher.pk, RecordStatus.ARCHIVED]))
        self.teacher.refresh_from_db()
        self.teacher_user.refresh_from_db()
        self.assertEqual(self.teacher.status, RecordStatus.ACTIVE)
        self.assertTrue(self.teacher_user.is_active)

    def test_archive_blocks_login_and_existing_access_then_restore_works(self):
        historical = Lesson.objects.create(
            group=self.group, teacher=self.teacher, date=date(2026, 8, 10), start_time=time(18), end_time=time(19)
        )
        self.group.status = RecordStatus.ARCHIVED
        self.group.save(update_fields=("status",))
        existing_session = Client()
        existing_session.force_login(self.teacher_user)
        self.client.force_login(self.owner)
        self.client.post(reverse("education:teacher-status", args=[self.teacher.pk, RecordStatus.ARCHIVED]))
        self.teacher_user.refresh_from_db()
        self.assertFalse(self.teacher_user.is_active)
        self.assertEqual(existing_session.get(reverse("dashboard")).status_code, 302)
        self.assertTrue(Lesson.objects.filter(pk=historical.pk).exists())
        self.client.logout()
        self.assertFalse(self.client.login(username="teacher17", password="StrongPass123!"))
        self.client.force_login(self.owner)
        self.client.post(reverse("education:teacher-status", args=[self.teacher.pk, RecordStatus.ACTIVE]))
        self.teacher_user.refresh_from_db()
        self.assertTrue(self.teacher_user.is_active)
        self.assertTrue(self.client.login(username="teacher17", password="StrongPass123!"))
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.TEACHER_STATUS, target_id=self.teacher.pk).exists())


class HistoricalAttendanceTests(Stage17Base):
    def setUp(self):
        super().setUp()
        self.past = Student.objects.create(full_name="Past")
        self.future = Student.objects.create(full_name="Future")
        self.current = Student.objects.create(full_name="Current")
        self.ended_before = Student.objects.create(full_name="Ended before")
        Enrollment.objects.create(
            student=self.past, group=self.group, started_at=date(2026, 8, 1), ended_at=date(2026, 8, 20),
            status=EnrollmentStatus.ENDED,
        )
        Enrollment.objects.create(
            student=self.future, group=self.group, started_at=date(2026, 9, 1), status=EnrollmentStatus.ACTIVE
        )
        Enrollment.objects.create(
            student=self.current, group=self.group, started_at=date(2026, 8, 1), status=EnrollmentStatus.ACTIVE
        )
        Enrollment.objects.create(
            student=self.ended_before, group=self.group, started_at=date(2026, 7, 1), ended_at=date(2026, 8, 10),
            status=EnrollmentStatus.ENDED,
        )
        self.lesson = Lesson.objects.create(
            group=self.group, teacher=self.teacher, date=date(2026, 8, 17), start_time=time(18), end_time=time(19)
        )

    def test_roster_uses_enrollment_interval_and_preserves_history(self):
        self.assertSetEqual(set(self.lesson.active_students()), {self.past, self.current})
        record = Attendance.objects.create(lesson=self.lesson, student=self.past, status=AttendanceStatus.PRESENT)
        Enrollment.objects.create(
            student=self.past, group=self.group, started_at=date(2026, 9, 10), status=EnrollmentStatus.ACTIVE
        )
        self.assertTrue(Attendance.objects.filter(pk=record.pk).exists())
        self.assertSetEqual(set(self.lesson.active_students()), {self.past, self.current})

    def test_complete_requires_full_roster(self):
        self.client.force_login(self.owner)
        Attendance.objects.create(lesson=self.lesson, student=self.past, status=AttendanceStatus.PRESENT)
        self.client.post(reverse("education:lesson-complete", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)
        Attendance.objects.create(lesson=self.lesson, student=self.current, status=AttendanceStatus.ABSENT)
        self.client.post(reverse("education:lesson-complete", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.COMPLETED)
