import json
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
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
    Payment,
    PaymentStatus,
    RecordStatus,
    Student,
    Teacher,
)

User = get_user_model()


class AnalyticsRegressionTests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.teacher = self.teacher_user.teacher_profile

    def _get(self, **params):
        self.client.force_login(self.owner)
        return self.client.get(reverse("core:analytics"), params)

    def test_groups_count_includes_groups_without_students(self):
        Group.objects.create(name="Empty Group", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100.00"))
        response = self._get()
        self.assertEqual(response.context["groups_count"], 1)

    def test_groups_count_excludes_archived_groups(self):
        Group.objects.create(name="Archived", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100.00"), status=RecordStatus.ARCHIVED)
        Group.objects.create(name="Active", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100.00"))
        response = self._get()
        self.assertEqual(response.context["groups_count"], 1)

    def test_groups_count_with_multiple_active_groups(self):
        for i in range(3):
            g = Group.objects.create(name=f"G{i}", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100.00"))
        student = Student.objects.create(full_name="T", phone="900900001")
        Enrollment.objects.create(student=student, group=Group.objects.first(), started_at=date.today())
        response = self._get()
        self.assertEqual(response.context["groups_count"], 3)

    def test_groups_count_zero_when_no_groups(self):
        response = self._get()
        self.assertEqual(response.context["groups_count"], 0)

    def test_groups_chart_filters_empty_groups(self):
        Group.objects.create(name="Empty", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100.00"))
        g_full = Group.objects.create(name="Full", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100.00"))
        student = Student.objects.create(full_name="T", phone="900900001")
        Enrollment.objects.create(student=student, group=g_full, started_at=date.today())
        response = self._get()
        labels = json.loads(response.context["groups_labels_json"])
        self.assertIn("Full", labels)
        self.assertNotIn("Empty", labels)


class AnalyticsPeriodFilterTests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.teacher = self.teacher_user.teacher_profile
        self.course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=self.course, teacher=self.teacher, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="A", phone="900100001")
        self.student2 = Student.objects.create(full_name="B", phone="900100002")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 1, 1))
        Enrollment.objects.create(student=self.student2, group=self.group, started_at=date(2026, 1, 1))

        self.today = date.today()
        self.ps = self.today.replace(day=1)

        self.lesson_today = Lesson.objects.create(
            group=self.group, date=self.today,
            start_time=time(10), end_time=time(11),
        )
        self.lesson_prev = Lesson.objects.create(
            group=self.group, date=self.ps - timedelta(days=5),
            start_time=time(10), end_time=time(11),
        )
        Attendance.objects.create(lesson=self.lesson_today, student=self.student, status=AttendanceStatus.PRESENT)
        Attendance.objects.create(lesson=self.lesson_today, student=self.student2, status=AttendanceStatus.ABSENT)
        Attendance.objects.create(lesson=self.lesson_prev, student=self.student, status=AttendanceStatus.LATE)

        Payment.objects.create(student=self.student, group=self.group, amount=Decimal("350.00"), paid_at=self.today, period=self.ps)
        Payment.objects.create(student=self.student, group=self.group, amount=Decimal("200.00"), paid_at=self.ps - timedelta(days=5), period=self.ps - timedelta(days=30))

    def _get(self, period="this-month", **extra):
        self.client.force_login(self.owner)
        params = {"period": period}
        params.update(extra)
        return self.client.get(reverse("core:analytics"), params)

    def test_this_month_lessons_count(self):
        self.assertEqual(self._get("this-month").context["lessons_count"], 1)

    def test_last_30_days_includes_previous(self):
        self.assertGreaterEqual(self._get("last-30-days").context["lessons_count"], 1)

    def test_this_month_attendance_scoped(self):
        ctx = self._get("this-month").context
        self.assertEqual(ctx["att_present"], 1)
        self.assertEqual(ctx["att_absent"], 1)
        self.assertEqual(ctx["att_late"], 0)

    def test_payments_scoped_to_period(self):
        ctx = self._get("this-month").context
        self.assertEqual(ctx["payments_sum"], Decimal("350.00"))
        self.assertEqual(ctx["payments_count"], 1)

    def test_empty_period_has_no_data(self):
        ctx = self._get("custom", date_from="2099-01-01", date_to="2099-01-31").context
        self.assertTrue(ctx["has_data"])
        self.assertFalse(ctx["period_has_data"])
        self.assertEqual(ctx["lessons_count"], 0)
        self.assertEqual(ctx["att_total"], 0)

    def test_period_labels(self):
        self.assertIn("Этот месяц", self._get("this-month").context["period_label"])
        self.assertIn("Последние 30 дней", self._get("last-30-days").context["period_label"])
        self.assertIn("Сегодня", self._get("today").context["period_label"])
        self.assertIn("Эта неделя", self._get("this-week").context["period_label"])
        self.assertIn("Прошлый месяц", self._get("last-month").context["period_label"])
        self.assertIn("Последние 90 дней", self._get("last-90-days").context["period_label"])

    def test_today_period_only_today_lesson(self):
        self.assertEqual(self._get("today").context["lessons_count"], 1)

    def test_last_month_only_prev_lesson(self):
        self.assertEqual(self._get("last-month").context["lessons_count"], 1)

    def test_invalid_period_defaults_to_this_month(self):
        ctx = self._get("bogus").context
        self.assertEqual(ctx["period"], "this-month")
        self.assertIn("Этот месяц", ctx["period_label"])


class AnalyticsKPITests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.t1 = User.objects.create_user("t1", password=self.password, role=UserRole.TEACHER)
        self.t2 = User.objects.create_user("t2", password=self.password, role=UserRole.TEACHER)
        self.course = Course.objects.create(name="Math", default_monthly_fee=Decimal("300.00"))
        self.g1 = Group.objects.create(name="G1", course=self.course, teacher=self.t1.teacher_profile, monthly_fee=Decimal("300.00"))
        self.g2 = Group.objects.create(name="G2", course=self.course, teacher=self.t2.teacher_profile, monthly_fee=Decimal("300.00"))
        s1 = Student.objects.create(full_name="S1", phone="900100001")
        s2 = Student.objects.create(full_name="S2", phone="900100002")
        Enrollment.objects.create(student=s1, group=self.g1, started_at=date.today())
        Enrollment.objects.create(student=s2, group=self.g2, started_at=date.today())

    def _get(self):
        self.client.force_login(self.owner)
        return self.client.get(reverse("core:analytics"))

    def test_active_students_count(self):
        self.assertEqual(self._get().context["active_students"], 2)

    def test_active_groups_count(self):
        self.assertEqual(self._get().context["active_groups"], 2)

    def test_active_teachers_count(self):
        self.assertEqual(self._get().context["active_teachers"], 2)

    def test_all_kpi_keys_present(self):
        ctx = self._get().context
        for key in [
            "active_students", "active_groups", "active_teachers",
            "payments_sum", "payments_count", "payments_delta",
            "lessons_count", "lessons_completed", "lessons_cancelled",
            "lessons_scheduled", "lessons_delta",
            "att_rate", "att_present", "att_absent", "att_late", "att_total",
            "att_delta", "pending_attendance",
            "has_data", "period_label", "period",
            "top_groups", "teacher_perf", "recent_payments",
            "period_options",
        ]:
            self.assertIn(key, ctx, f"Missing key: {key}")

    def test_has_data_true_when_no_lessons_but_payments(self):
        today = date.today()
        ps = today.replace(day=1)
        student = Student.objects.create(full_name="P", phone="900100099")
        Enrollment.objects.create(student=student, group=self.g1, started_at=date.today())
        Payment.objects.create(student=student, group=self.g1, amount=Decimal("100.00"), paid_at=today, period=ps)
        ctx = self._get().context
        self.assertTrue(ctx["has_data"])

    def test_has_data_true_when_active_teacher_exists_without_transactions(self):
        Payment.objects.all().delete()
        Attendance.objects.all().delete()
        Lesson.objects.all().delete()
        Enrollment.objects.all().delete()
        Student.objects.all().delete()
        Group.objects.all().delete()
        ctx = self._get().context
        self.assertTrue(ctx["has_data"])
        self.assertFalse(ctx["period_has_data"])


class AnalyticsEmptyStateTests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)

    def _get(self, **extra):
        self.client.force_login(self.owner)
        params = {"period": "this-month"}
        params.update(extra)
        return self.client.get(reverse("core:analytics"), params)

    def test_empty_top_groups(self):
        ctx = self._get().context
        self.assertEqual(len(ctx["top_groups"]), 0)

    def test_empty_teacher_perf(self):
        ctx = self._get().context
        self.assertEqual(len(ctx["teacher_perf"]), 0)

    def test_empty_recent_payments(self):
        ctx = self._get().context
        self.assertEqual(len(ctx["recent_payments"]), 0)

    def test_att_rate_none_when_no_data(self):
        ctx = self._get().context
        self.assertIsNone(ctx["att_rate"])

    def test_payments_sum_zero(self):
        ctx = self._get().context
        self.assertEqual(ctx["payments_sum"], Decimal("0.00"))


class AnalyticsTeacherAccessTests(TestCase):
    password = "Secure-test-password-2026"

    def test_teacher_cannot_access_analytics(self):
        teacher = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.client.force_login(teacher)
        response = self.client.get(reverse("core:analytics"))
        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_access(self):
        admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.client.force_login(admin)
        response = self.client.get(reverse("core:analytics"))
        self.assertEqual(response.status_code, 403)

    def test_owner_can_access(self):
        owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.client.force_login(owner)
        response = self.client.get(reverse("core:analytics"))
        self.assertEqual(response.status_code, 200)

    def test_anonymous_redirected(self):
        response = self.client.get(reverse("core:analytics"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)


class AnalyticsLessonStatusTests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER).teacher_profile
        self.course = Course.objects.create(name="E", default_monthly_fee=Decimal("100"))
        self.group = Group.objects.create(name="G", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100"))
        today = date.today()
        self.l1 = Lesson.objects.create(group=self.group, date=today, start_time=time(10), end_time=time(11), status=LessonStatus.COMPLETED)
        self.l2 = Lesson.objects.create(group=self.group, date=today, start_time=time(11), end_time=time(12), status=LessonStatus.SCHEDULED)
        self.l3 = Lesson.objects.create(group=self.group, date=today, start_time=time(12), end_time=time(13), status=LessonStatus.CANCELLED)

    def _get(self):
        self.client.force_login(self.owner)
        return self.client.get(reverse("core:analytics"))

    def test_lesson_status_counts(self):
        ctx = self._get().context
        self.assertEqual(ctx["lessons_completed"], 1)
        self.assertEqual(ctx["lessons_scheduled"], 1)
        self.assertEqual(ctx["lessons_cancelled"], 1)
        self.assertEqual(ctx["lessons_count"], 3)

    def test_lesson_status_json(self):
        ctx = self._get().context
        data = json.loads(ctx["lesson_status_data_json"])
        self.assertEqual(data, [1, 1, 1])


class AnalyticsPendingAttendanceTests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER).teacher_profile
        self.course = Course.objects.create(name="E", default_monthly_fee=Decimal("100"))
        self.group = Group.objects.create(name="G", course=self.course, teacher=self.teacher, monthly_fee=Decimal("100"))
        self.student = Student.objects.create(full_name="S", phone="900100001")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date.today())
        today = date.today()
        self.lesson = Lesson.objects.create(group=self.group, date=today, start_time=time(10), end_time=time(11), status=LessonStatus.SCHEDULED)

    def _get(self):
        self.client.force_login(self.owner)
        return self.client.get(reverse("core:analytics"))

    def test_pending_attendance_count(self):
        self.assertEqual(self._get().context["pending_attendance"], 1)

    def test_no_pending_when_completed(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        self.assertEqual(self._get().context["pending_attendance"], 0)

    def test_no_pending_when_cancelled(self):
        self.lesson.status = LessonStatus.CANCELLED
        self.lesson.save(update_fields=("status",))
        self.assertEqual(self._get().context["pending_attendance"], 0)
