from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import Attendance, AttendanceStatus, Course, Enrollment, EnrollmentStatus, Group, Lesson, Payment, PaymentStatus, RecordStatus, Student


User = get_user_model()


class DashboardTestCase(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.other_teacher_user = User.objects.create_user("other", password=self.password, role=UserRole.TEACHER)
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.other_group = Group.objects.create(name="Russian A1", course=course, teacher=self.other_teacher_user.teacher_profile, monthly_fee=Decimal("300.00"))
        self.archived_group = Group.objects.create(name="Archived A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"), status=RecordStatus.ARCHIVED)
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        self.student_2 = Student.objects.create(full_name="Каримова Мадина", phone="900123457")
        self.archived_student = Student.objects.create(full_name="Архивный Ученик", phone="900123458", status=RecordStatus.ARCHIVED)
        self.other_student = Student.objects.create(full_name="Чужой Ученик", phone="900123459")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        Enrollment.objects.create(student=self.student_2, group=self.group, started_at=date(2026, 8, 1))
        Enrollment.objects.create(student=self.archived_student, group=self.archived_group, started_at=date(2026, 8, 1))
        Enrollment.objects.create(student=self.other_student, group=self.other_group, started_at=date(2026, 8, 1))
        self.lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        self.other_lesson = Lesson.objects.create(group=self.other_group, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        Attendance.objects.create(lesson=self.lesson, student=self.student_2, status=AttendanceStatus.LATE)
        Attendance.objects.create(lesson=self.other_lesson, student=self.other_student, status=AttendanceStatus.ABSENT)

        self.today = date.today()
        self.period_start = self.today.replace(day=1)
        self.last_month_start = (self.period_start - timedelta(days=1)).replace(day=1)
        Payment.objects.create(student=self.student, group=self.group, amount=Decimal("350.75"), paid_at=self.today, period=self.period_start)
        Payment.objects.create(student=self.student_2, group=self.group, amount=Decimal("149.25"), paid_at=self.today, period=self.period_start)
        Payment.objects.create(student=self.student, group=self.group, amount=Decimal("999.00"), paid_at=self.today, period=self.period_start, status=PaymentStatus.CANCELLED)
        Payment.objects.create(student=self.student, group=self.group, amount=Decimal("200.00"), paid_at=self.last_month_start, period=self.last_month_start)

    def _get(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard"))

    def test_owner_can_open_dashboard(self):
        self.assertEqual(self._get(self.owner).status_code, 200)

    def test_admin_can_open_dashboard(self):
        self.assertEqual(self._get(self.admin).status_code, 200)

    def test_teacher_can_open_dashboard(self):
        self.assertEqual(self._get(self.teacher_user).status_code, 200)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_students_total_count_is_correct(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["students_total"], 4)

    def test_active_students_count_is_correct(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["students_active"], 3)

    def test_active_groups_count_is_correct(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["groups_active"], 2)

    def test_teachers_count_is_correct(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["teachers_count"], 2)

    def test_current_month_payment_total_is_correct(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["payments_total"], Decimal("500.00"))
        self.assertContains(response, "500,00 TJS")

    def test_cancelled_payment_is_excluded_from_total(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["payments_total"], Decimal("500.00"))

    def test_other_month_payment_is_excluded(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["payments_total"], Decimal("500.00"))

    def test_multiple_payments_in_one_period_are_counted(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["payments_count"], 3)
        self.assertEqual(response.context["payments_total"], Decimal("500.00"))

    def test_attendance_counts_are_correct_for_owner(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["attendance_present"], 1)
        self.assertEqual(response.context["attendance_absent"], 1)
        self.assertEqual(response.context["attendance_late"], 1)

    def test_recent_payments_shown_to_owner(self):
        response = self._get(self.owner)
        self.assertContains(response, self.student.full_name)
        self.assertContains(response, "350,75 TJS")
        self.assertContains(response, "Recent Payments")

    def test_recent_payments_shown_to_admin(self):
        response = self._get(self.admin)
        self.assertContains(response, self.student.full_name)
        self.assertContains(response, "350,75 TJS")
        self.assertContains(response, "Recent Payments")

    def test_teacher_gets_no_financial_data(self):
        response = self._get(self.teacher_user)
        self.assertEqual(response.context["payments_count"], 0)
        self.assertEqual(response.context["payments_total"], Decimal("0"))
        self.assertEqual(list(response.context["recent_payments"]), [])
        self.assertNotContains(response, "Recent Payments")
        self.assertNotContains(response, "TJS")
        self.assertNotContains(response, "Оплачено")

    def test_teacher_sees_only_own_groups(self):
        response = self._get(self.teacher_user)
        group_names = [g.name for g in response.context["active_groups"]]
        self.assertIn("English A1", group_names)
        self.assertNotIn("Russian A1", group_names)
        self.assertNotIn("Archived A1", group_names)
        self.assertContains(response, "English A1")
        self.assertNotContains(response, "Russian A1")

    def test_teacher_sees_only_own_groups_attendance(self):
        response = self._get(self.teacher_user)
        self.assertEqual(response.context["attendance_present"], 1)
        self.assertEqual(response.context["attendance_late"], 1)
        self.assertEqual(response.context["attendance_absent"], 0)
        records = response.context["recent_attendance"]
        self.assertTrue(all(r.lesson_id == self.lesson.pk for r in records))
        self.assertNotContains(response, self.other_student.full_name)
        self.assertContains(response, self.student.full_name)

    def test_recent_attendance_shown_to_owner(self):
        response = self._get(self.owner)
        self.assertContains(response, "Recent Attendance")
        self.assertContains(response, self.other_student.full_name)

    def test_group_student_count_only_counts_active_enrollments(self):
        count_group = Group.objects.create(name="Count A1", course=Course.objects.get(name="English"), teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("300.00"))
        active_a = Student.objects.create(full_name="Активный А")
        active_b = Student.objects.create(full_name="Активный Б")
        ended = Student.objects.create(full_name="Завершённый В")
        Enrollment.objects.create(student=active_a, group=count_group, started_at=date(2025, 1, 1), ended_at=date(2025, 6, 1), status=EnrollmentStatus.ENDED)
        Enrollment.objects.create(student=active_a, group=count_group, started_at=date(2026, 1, 1))
        Enrollment.objects.create(student=active_b, group=count_group, started_at=date(2026, 1, 1))
        Enrollment.objects.create(student=ended, group=count_group, started_at=date(2025, 1, 1), ended_at=date(2025, 6, 1), status=EnrollmentStatus.ENDED)
        response = self._get(self.owner)
        groups = {g.name: g.student_count for g in response.context["active_groups"]}
        self.assertEqual(groups["Count A1"], 2)

    def test_archived_group_is_not_listed(self):
        response = self._get(self.owner)
        group_names = [g.name for g in response.context["active_groups"]]
        self.assertNotIn("Archived A1", group_names)
