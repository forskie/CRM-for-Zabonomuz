from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Sum
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
    Payment,
    PaymentStatus,
    RecordStatus,
    Schedule,
    Student,
)


User = get_user_model()


class BusinessWorkflowBase(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.teacher = self.teacher_user.teacher_profile

    def login(self, user):
        self.client.force_login(user)


class FullBusinessCycleTests(BusinessWorkflowBase):
    """Stage 14 section 2: complete owner workflow — Course → Group → Enrollment →
    Schedule → generated Lessons → Attendance → Complete → Report → Payment — with
    HTTP/redirect, DB-state and dashboard-consistency checks after every step."""

    def test_full_monthly_business_cycle(self):
        self.login(self.owner)

        # 1. Course
        response = self.client.post(reverse("education:course-create"), {"name": "Математика", "description": "", "default_monthly_fee": "250.00"})
        course = Course.objects.get(name="Математика")
        self.assertRedirects(response, reverse("education:course-detail", args=[course.pk]))
        self.assertEqual(course.default_monthly_fee, Decimal("250.00"))

        # 2. Group with its own fee independent of the course
        response = self.client.post(
            reverse("education:group-create"),
            {"name": "Математика A1", "course": course.pk, "teacher": self.teacher.pk, "monthly_fee": "280.00"},
        )
        group = Group.objects.get(name="Математика A1")
        self.assertRedirects(response, reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(group.monthly_fee, Decimal("280.00"))

        # 3. Student + enrollment
        response = self.client.post(reverse("education:student-create"), {"full_name": "Каримов Искандер", "phone": "900888999"})
        student = Student.objects.get(full_name="Каримов Искандер")
        self.assertRedirects(response, reverse("education:student-detail", args=[student.pk]))
        response = self.client.post(reverse("education:enrollment-create", args=[group.pk]), {"student": student.pk, "started_at": "2026-08-01"})
        enrollment = Enrollment.objects.get(student=student, group=group)
        self.assertRedirects(response, reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(enrollment.status, EnrollmentStatus.ACTIVE)
        self.assertIsNone(enrollment.ended_at)

        # 4. Schedule: Tuesdays 18:00–19:00 with a bounded period
        response = self.client.post(
            reverse("education:schedule-create", args=[group.pk]),
            {"weekday": 1, "start_time": "18:00", "end_time": "19:00", "is_active": "on", "start_date": "2026-08-04", "end_date": "2026-08-25"},
        )
        schedule = Schedule.objects.get(group=group)
        self.assertRedirects(response, reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(schedule.start_date, date(2026, 8, 4))
        self.assertEqual(schedule.end_date, date(2026, 8, 25))

        # 5. Generate page pre-fills the schedule period and generation honours it
        response = self.client.get(reverse("education:schedule-generate", args=[schedule.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["date_from"], date(2026, 8, 4))
        self.assertEqual(response.context["form"].initial["date_to"], date(2026, 8, 25))
        response = self.client.post(reverse("education:schedule-generate", args=[schedule.pk]), {"date_from": "2026-08-04", "date_to": "2026-08-25"})
        self.assertRedirects(response, reverse("education:group-detail", args=[group.pk]))
        lessons = list(Lesson.objects.filter(schedule=schedule).order_by("date"))
        self.assertEqual([lesson.date for lesson in lessons], [date(2026, 8, 4), date(2026, 8, 11), date(2026, 8, 18), date(2026, 8, 25)])
        self.assertTrue(all(lesson.status == LessonStatus.SCHEDULED for lesson in lessons))

        # 6. Generated lessons appear in the calendar
        response = self.client.get(reverse("education:calendar"), {"view": "week", "date": "2026-08-04"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, group.name)

        # 7. Attendance on the first generated lesson
        first = lessons[0]
        response = self.client.post(
            reverse("education:lesson-detail", args=[first.pk]),
            {f"status_{student.pk}": AttendanceStatus.PRESENT, f"note_{student.pk}": ""},
        )
        self.assertRedirects(response, reverse("education:lesson-detail", args=[first.pk]))
        record = Attendance.objects.get(lesson=first, student=student)
        self.assertEqual(record.status, AttendanceStatus.PRESENT)

        # 8. Complete the lesson and write the teacher report
        response = self.client.post(reverse("education:lesson-complete", args=[first.pk]))
        self.assertRedirects(response, reverse("education:lesson-detail", args=[first.pk]))
        first.refresh_from_db()
        self.assertEqual(first.status, LessonStatus.COMPLETED)
        response = self.client.post(
            reverse("education:lesson-report", args=[first.pk]),
            {"topic": "Линейные уравнения", "teacher_note": "Хорошо", "homework": "№ 1–5"},
        )
        self.assertRedirects(response, reverse("education:lesson-detail", args=[first.pk]))
        first.refresh_from_db()
        self.assertEqual(first.topic, "Линейные уравнения")

        # 9. Payment for the current period (shown on the dashboard)
        today = date.today()
        period = today.replace(day=1)
        response = self.client.post(
            reverse("education:payment-create"),
            {"student": student.pk, "group": group.pk, "amount": "280.00", "paid_at": today.isoformat(), "period": period.isoformat(), "note": ""},
        )
        payment = Payment.objects.get(student=student, group=group)
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))
        self.assertEqual(payment.amount, Decimal("280.00"))
        self.assertEqual(payment.period, period)

        # 10. Student detail aggregates
        response = self.client.get(reverse("education:student-detail", args=[student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["active_enrollments"]), [enrollment])
        self.assertEqual(list(response.context["attendance_history"]), [record])
        self.assertEqual(list(response.context["payments"]), [payment])

        # 11. Group detail aggregates
        response = self.client.get(reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["active_enrollments"]), [enrollment])
        self.assertEqual(response.context["payments_total"], Decimal("280.00"))
        self.assertEqual(response.context["attendance_stats"]["present"], 1)

        # 12. Dashboard matches the database
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["students_total"], Student.objects.count())
        self.assertEqual(response.context["groups_active"], Group.objects.filter(status=RecordStatus.ACTIVE).count())
        self.assertEqual(response.context["attendance_present"], Attendance.objects.filter(status=AttendanceStatus.PRESENT).count())
        expected_total = Payment.objects.filter(period=period, status=PaymentStatus.PAID).aggregate(total=Sum("amount"))["total"]
        self.assertEqual(response.context["payments_total"], expected_total)

        # 13. Audit trail covers the whole cycle
        actions = set(AuditLog.objects.filter(actor=self.owner).values_list("action", flat=True))
        required = {
            AuditAction.STUDENT_CREATE,
            AuditAction.ENROLLMENT_CREATE,
            AuditAction.SCHEDULE_CREATE,
            AuditAction.SCHEDULE_GENERATE,
            AuditAction.ATTENDANCE_CHANGE,
            AuditAction.LESSON_COMPLETE,
            AuditAction.LESSON_REPORT,
            AuditAction.PAYMENT_CREATE,
        }
        self.assertTrue(required <= actions, required - actions)

        # 14. Re-running generation is idempotent
        self.client.post(reverse("education:schedule-generate", args=[schedule.pk]), {"date_from": "2026-08-04", "date_to": "2026-08-25"})
        self.assertEqual(Lesson.objects.filter(schedule=schedule).count(), 4)


class LessonFromScheduleTests(BusinessWorkflowBase):
    """Stage 14 sections 3 & 9: lesson-from-schedule must be audited and must never
    crash with a 500 on duplicates or teacher conflicts."""

    def setUp(self):
        super().setUp()
        self.course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=self.course, teacher=self.teacher, monthly_fee=Decimal("350.00"))
        self.schedule = Schedule.objects.create(group=self.group, weekday=1, start_time=time(18), end_time=time(19))

    def _create_from_schedule(self, lesson_date):
        self.login(self.admin)
        return self.client.post(reverse("education:lesson-from-schedule", args=[self.schedule.pk]), {"date": lesson_date})

    def test_lesson_from_schedule_is_audited(self):
        response = self._create_from_schedule("2026-08-11")
        lesson = Lesson.objects.get(schedule=self.schedule)
        self.assertRedirects(response, reverse("education:lesson-detail", args=[lesson.pk]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.LESSON_CREATE)
        self.assertEqual(log.target_type, "Lesson")
        self.assertEqual(log.target_id, lesson.pk)
        self.assertEqual(log.actor, self.admin)

    def test_duplicate_slot_returns_form_error_not_500(self):
        Lesson.objects.create(group=self.group, date=date(2026, 8, 11), start_time=time(18), end_time=time(19))
        response = self._create_from_schedule("2026-08-11")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 0)

    def test_teacher_conflict_returns_form_error_not_500(self):
        other_group = Group.objects.create(name="English B1", course=self.course, teacher=self.teacher, monthly_fee=Decimal("300.00"))
        Lesson.objects.create(group=other_group, date=date(2026, 8, 11), start_time=time(17, 30), end_time=time(18, 30))
        response = self._create_from_schedule("2026-08-11")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 0)

    def test_conflicting_schedule_date_returns_form_error_not_500(self):
        Lesson.objects.create(group=self.group, schedule=self.schedule, date=date(2026, 8, 11), start_time=time(18), end_time=time(19))
        response = self._create_from_schedule("2026-08-11")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 1)

    def test_successful_creation_copies_schedule_times(self):
        response = self._create_from_schedule("2026-08-11")
        lesson = Lesson.objects.get(schedule=self.schedule)
        self.assertRedirects(response, reverse("education:lesson-detail", args=[lesson.pk]))
        self.assertEqual(lesson.date, date(2026, 8, 11))
        self.assertEqual(lesson.start_time, time(18))
        self.assertEqual(lesson.end_time, time(19))
        self.assertEqual(lesson.status, LessonStatus.SCHEDULED)


class PaymentDoubleCancelTests(BusinessWorkflowBase):
    """Stage 14 sections 5 & 9: cancelling an already-cancelled payment keeps the
    record but must not spam the audit journal."""

    def setUp(self):
        super().setUp()
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        self.payment = Payment.objects.create(student=self.student, group=self.group, amount=Decimal("350.00"), paid_at=date(2026, 8, 5), period=date(2026, 8, 1))

    def test_double_cancel_keeps_record_and_audits_once(self):
        self.login(self.admin)
        self.client.post(reverse("education:payment-cancel", args=[self.payment.pk]))
        self.client.post(reverse("education:payment-cancel", args=[self.payment.pk]))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.CANCELLED)
        self.assertEqual(Payment.objects.filter(pk=self.payment.pk).count(), 1)
        self.assertEqual(
            AuditLog.objects.filter(action=AuditAction.PAYMENT_CANCEL, target_type="Payment", target_id=self.payment.pk).count(),
            1,
        )

    def test_cancelled_payment_can_be_corrected_back_to_paid_via_edit(self):
        self.login(self.admin)
        self.client.post(reverse("education:payment-cancel", args=[self.payment.pk]))
        response = self.client.post(reverse("education:payment-edit", args=[self.payment.pk]), {
            "student": self.student.pk, "group": self.group.pk, "amount": "350.00",
            "paid_at": "2026-08-05", "period": "2026-08-01", "status": PaymentStatus.PAID, "note": "",
        })
        self.assertRedirects(response, reverse("education:payment-detail", args=[self.payment.pk]))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PAID)
        self.assertEqual(
            AuditLog.objects.filter(action=AuditAction.PAYMENT_EDIT, target_type="Payment", target_id=self.payment.pk).count(),
            1,
        )


class CalendarNavigationTests(BusinessWorkflowBase):
    """Stage 14 sections 6 & 14: calendar navigation must carry the view mode and
    preserve active filters; previous/next anchors must be correct."""

    def setUp(self):
        super().setUp()
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher, monthly_fee=Decimal("350.00"))
        Lesson.objects.create(group=self.group, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))

    def _get(self, **params):
        self.login(self.owner)
        return self.client.get(reverse("education:calendar"), params)

    def test_day_navigation(self):
        response = self._get(view="day", date="2026-08-17")
        self.assertContains(response, "?view=day&amp;date=2026-08-16")
        self.assertContains(response, "?view=day&amp;date=2026-08-18")

    def test_week_navigation(self):
        response = self._get(view="week", date="2026-08-17")
        self.assertContains(response, "?view=week&amp;date=2026-08-10")
        self.assertContains(response, "?view=week&amp;date=2026-08-24")

    def test_month_navigation(self):
        response = self._get(view="month", date="2026-08-17")
        self.assertContains(response, "?view=month&amp;date=2026-07-01")
        self.assertContains(response, "?view=month&amp;date=2026-09-01")

    def test_today_link_keeps_view_mode(self):
        response = self._get(view="week", date="2026-08-17")
        self.assertContains(response, "view=week")

    def test_filters_preserved_in_navigation(self):
        response = self._get(view="week", date="2026-08-17", group=str(self.group.pk))
        self.assertContains(response, "date=2026-08-10&amp;group={}".format(self.group.pk))

    def test_teacher_navigation_has_no_filter_controls(self):
        self.login(self.teacher_user)
        response = self.client.get(reverse("education:calendar"), {"view": "week", "date": "2026-08-17"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Фильтровать")


class QueryCountStabilityTests(BusinessWorkflowBase):
    """Stage 14 section 15: list pages must not execute per-row queries (N+1)."""

    def setUp(self):
        super().setUp()
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))

    def _queries(self, url, **params):
        self.login(self.owner)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def test_student_list_query_count_does_not_grow_with_rows(self):
        small = self._queries(reverse("education:student-list"))
        for i in range(40):
            Student.objects.create(full_name=f"Ученик {i}", phone=f"9000000{i:03d}")
        large = self._queries(reverse("education:student-list"))
        self.assertLess(large - small, 5)

    def test_group_list_query_count_does_not_grow_with_rows(self):
        small = self._queries(reverse("education:group-list"))
        for i in range(40):
            Group.objects.create(name=f"Группа {i}", course=Course.objects.first(), teacher=self.teacher, monthly_fee=Decimal("300.00"))
        large = self._queries(reverse("education:group-list"))
        self.assertLess(large - small, 5)


class GroupAttendanceStatsRegressionTests(TestCase):
    """Group detail attendance_stats must exclude CANCELLED lessons from denominator."""

    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER).teacher_profile
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher, monthly_fee=Decimal("300.00"))
        self.student = Student.objects.create(full_name="Тест Ученик", phone="900100001")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))

    def _get_stats(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("education:group-detail", args=[self.group.pk]))
        return resp.context["attendance_stats"]

    def test_cancelled_lesson_not_counted_in_denominator(self):
        l1 = Lesson.objects.create(group=self.group, date=date(2026, 8, 10), start_time=time(9), end_time=time(10))
        Lesson.objects.create(group=self.group, date=date(2026, 8, 12), start_time=time(9), end_time=time(10), status=LessonStatus.CANCELLED)
        Attendance.objects.create(lesson=l1, student=self.student, status=AttendanceStatus.PRESENT)
        stats = self._get_stats()
        self.assertEqual(stats["lessons"], 1)
        self.assertEqual(stats["present"], 1)

    def test_all_cancelled_zero_lessons(self):
        Lesson.objects.create(group=self.group, date=date(2026, 8, 10), start_time=time(9), end_time=time(10), status=LessonStatus.CANCELLED)
        stats = self._get_stats()
        self.assertEqual(stats["lessons"], 0)
        self.assertEqual(stats["present"], 0)

    def test_mixed_statuses_correct_counts(self):
        l1 = Lesson.objects.create(group=self.group, date=date(2026, 8, 10), start_time=time(9), end_time=time(10))
        l2 = Lesson.objects.create(group=self.group, date=date(2026, 8, 11), start_time=time(9), end_time=time(10))
        l3 = Lesson.objects.create(group=self.group, date=date(2026, 8, 12), start_time=time(9), end_time=time(10))
        Lesson.objects.create(group=self.group, date=date(2026, 8, 13), start_time=time(9), end_time=time(10), status=LessonStatus.CANCELLED)
        Attendance.objects.create(lesson=l1, student=self.student, status=AttendanceStatus.PRESENT)
        Attendance.objects.create(lesson=l2, student=self.student, status=AttendanceStatus.LATE)
        Attendance.objects.create(lesson=l3, student=self.student, status=AttendanceStatus.ABSENT)
        stats = self._get_stats()
        self.assertEqual(stats["lessons"], 3)
        self.assertEqual(stats["present"], 1)
        self.assertEqual(stats["late"], 1)
        self.assertEqual(stats["absent"], 1)
