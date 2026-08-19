import json
from datetime import date, time, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.education.models import (
    Attendance, AttendanceStatus, Course, Enrollment, Group, Lesson,
    LessonStatus, Payment, PaymentStatus, Schedule, Student,
)


class Stage18Base(TestCase):
    password = "Stage18-secure-password"

    def setUp(self):
        self.owner = User.objects.create_user("owner18", password=self.password, role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher18", password=self.password, role=UserRole.TEACHER)
        self.teacher = self.teacher_user.teacher_profile
        self.course = Course.objects.create(name="Stage 18", default_monthly_fee=Decimal("100"))
        self.group = Group.objects.create(
            name="Stage 18 group", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100")
        )
        self.student = Student.objects.create(full_name="Stage 18 student")
        Enrollment.objects.create(
            student=self.student, group=self.group, started_at=timezone.localdate() - timedelta(days=30)
        )

    def get_dashboard(self, user=None):
        self.client.force_login(user or self.owner)
        return self.client.get(reverse("dashboard"))

    def get_analytics(self, user=None, **params):
        self.client.force_login(user or self.owner)
        return self.client.get(reverse("core:analytics"), params)


class DashboardCorrectnessTests(Stage18Base):
    def test_pending_contains_past_but_not_future_or_cancelled(self):
        today = timezone.localdate()
        Lesson.objects.create(group=self.group, date=today - timedelta(days=1), start_time=time(8), end_time=time(9))
        Lesson.objects.create(group=self.group, date=today + timedelta(days=1), start_time=time(8), end_time=time(9))
        Lesson.objects.create(
            group=self.group, date=today - timedelta(days=2), start_time=time(8), end_time=time(9),
            status=LessonStatus.CANCELLED,
        )
        self.assertEqual(self.get_dashboard().context["pending_attendance_count"], 1)
        self.assertEqual(self.get_dashboard(self.teacher_user).context["pending_attendance_count"], 1)

    def test_dashboard_materializes_today_idempotently(self):
        today = timezone.localdate()
        schedule = Schedule.objects.create(
            group=self.group, weekday=today.weekday(), start_time=time(8), end_time=time(9),
            start_date=today, end_date=today + timedelta(days=14),
        )
        first = self.get_dashboard()
        self.assertTrue(first.context["today_lessons"])
        count = Lesson.objects.filter(schedule=schedule).count()
        self.get_dashboard()
        self.assertEqual(Lesson.objects.filter(schedule=schedule).count(), count)

    def test_payment_and_recent_payment_semantics_are_paid_only(self):
        today = timezone.localdate()
        period = today.replace(day=1)
        paid = Payment.objects.create(
            student=self.student, group=self.group, amount=Decimal("120"), paid_at=today, period=period
        )
        Payment.objects.create(
            student=self.student, group=self.group, amount=Decimal("900"), paid_at=today, period=period,
            status=PaymentStatus.CANCELLED,
        )
        context = self.get_dashboard().context
        self.assertEqual(context["payments_total"], Decimal("120.00"))
        self.assertEqual(context["payments_count"], 1)
        self.assertEqual([payment.pk for payment in context["recent_payments"]], [paid.pk])

    def test_attendance_uses_expected_roster_and_never_fake_hundred_percent(self):
        second = Student.objects.create(full_name="Second")
        today = timezone.localdate()
        Enrollment.objects.create(student=second, group=self.group, started_at=today - timedelta(days=1))
        lesson = Lesson.objects.create(group=self.group, date=today, start_time=time(0), end_time=time(0, 1))
        Attendance.objects.create(lesson=lesson, student=self.student, status=AttendanceStatus.PRESENT)
        context = self.get_dashboard().context
        self.assertEqual(context["attendance_expected"], 2)
        self.assertEqual(context["attendance_marked"], 1)
        self.assertEqual(context["attendance_unmarked"], 1)
        self.assertEqual(context["attendance_rate"], 50)
        self.assertEqual(context["attendance_completion_rate"], 50)


class AnalyticsCorrectnessTests(Stage18Base):
    def test_reverse_custom_range_is_rejected(self):
        response = self.get_analytics(
            period="custom", date_from="2026-08-20", date_to="2026-08-01"
        )
        self.assertContains(response, "Дата начала не может быть позже даты окончания")
        self.assertIsNotNone(response.context["period_error"])

    def test_entities_keep_page_nonempty_without_period_transactions(self):
        context = self.get_analytics(
            period="custom", date_from="2099-01-01", date_to="2099-01-31"
        ).context
        self.assertTrue(context["system_has_entities"])
        self.assertFalse(context["period_has_data"])
        self.assertTrue(context["has_data"])

    def test_teacher_scope_excludes_foreign_and_financial_data(self):
        foreign_user = User.objects.create_user("foreign18", password=self.password, role=UserRole.TEACHER)
        foreign_group = Group.objects.create(
            name="Foreign", course=self.course, teacher=foreign_user.teacher_profile, monthly_fee=Decimal("100")
        )
        foreign_student = Student.objects.create(full_name="Foreign student")
        Enrollment.objects.create(student=foreign_student, group=foreign_group, started_at=timezone.localdate())
        Lesson.objects.create(group=foreign_group, date=timezone.localdate(), start_time=time(0), end_time=time(0, 1))
        Payment.objects.create(
            student=foreign_student, group=foreign_group, amount=Decimal("500"),
            paid_at=timezone.localdate(), period=timezone.localdate().replace(day=1),
        )
        context = self.get_analytics(self.teacher_user).context
        self.assertEqual(context["active_students"], 1)
        self.assertEqual(context["active_groups"], 1)
        self.assertEqual(context["active_teachers"], 1)
        self.assertEqual(context["payments_sum"], Decimal("0.00"))
        self.assertEqual(json.loads(context["revenue_data_json"]), [])
        self.assertNotIn("Foreign", json.loads(context["groups_labels_json"]))

    def test_selected_period_controls_metrics_and_chart_lengths(self):
        Lesson.objects.create(group=self.group, date=date(2025, 1, 10), start_time=time(8), end_time=time(9))
        Lesson.objects.create(group=self.group, date=date(2025, 2, 10), start_time=time(8), end_time=time(9))
        context = self.get_analytics(
            period="custom", date_from="2025-01-01", date_to="2025-01-31"
        ).context
        self.assertEqual(context["lessons_count"], 1)
        for labels_key, values_key in (
            ("payment_trend_labels_json", "payment_trend_amounts_json"),
            ("teacher_workload_labels_json", "teacher_workload_data_json"),
            ("group_att_labels_json", "group_att_data_json"),
            ("students_labels_json", "students_data_json"),
            ("revenue_labels_json", "revenue_data_json"),
            ("groups_labels_json", "groups_data_json"),
        ):
            self.assertEqual(len(json.loads(context[labels_key])), len(json.loads(context[values_key])))


class AnalyticsQueryBudgetTests(Stage18Base):
    def query_count(self):
        self.client.force_login(self.owner)
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("core:analytics"))
            self.assertEqual(response.status_code, 200)
        return len(captured)

    def test_group_and_teacher_tables_have_bounded_query_count(self):
        small = self.query_count()
        for index in range(6):
            user = User.objects.create_user(
                f"extra-teacher-{index}", password=self.password, role=UserRole.TEACHER
            )
            group = Group.objects.create(
                name=f"Extra group {index}", course=self.course, teacher=user.teacher_profile,
                monthly_fee=Decimal("100"),
            )
            student = Student.objects.create(full_name=f"Extra student {index}")
            Enrollment.objects.create(student=student, group=group, started_at=timezone.localdate())
            Lesson.objects.create(group=group, date=timezone.localdate(), start_time=time(10), end_time=time(11))
        large = self.query_count()
        self.assertLessEqual(large, small + 2)
