from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import Attendance, AttendanceStatus, AuditLog, AuditAction, Course, Enrollment, EnrollmentStatus, Group, Lesson, LessonStatus, Payment, PaymentStatus, RecordStatus, Student


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
        self.assertEqual(response.context["payments_count"], 2)
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
        self.assertContains(response, "Финансы")

    def test_recent_payments_shown_to_admin(self):
        response = self._get(self.admin)
        self.assertContains(response, self.student.full_name)
        self.assertContains(response, "350,75 TJS")
        self.assertContains(response, "Финансы")

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

    def test_recent_attendance_shown_to_owner(self):
        response = self._get(self.owner)
        self.assertContains(response, "Посещаемость")

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


class DashboardTodayLessonsTests(TestCase):
    """Test the new TODAY section of the dashboard."""

    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        course = Course.objects.create(name="Math", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="Math A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("300.00"))
        self.student = Student.objects.create(full_name="Тест Ученик", phone="900100001")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        self.today = date.today()
        self.lesson = Lesson.objects.create(group=self.group, date=self.today, start_time=time(9, 0), end_time=time(10, 0))
        self.tomorrow_lesson = Lesson.objects.create(
            group=self.group,
            date=self.today + timedelta(days=1),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )

    def _get(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard"))

    def test_today_display_contains_weekday(self):
        response = self._get(self.owner)
        self.assertIn("today_display", response.context)
        display = response.context["today_display"]
        self.assertTrue(len(display) > 5)

    def test_today_lessons_total_count(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["today_lessons_total"], 1)

    def test_today_lessons_completed_count(self):
        self.lesson.status = LessonStatus.COMPLETED
        self.lesson.save(update_fields=("status",))
        response = self._get(self.owner)
        self.assertEqual(response.context["today_lessons_completed"], 1)

    def test_today_lessons_pending_has_unmarked(self):
        response = self._get(self.owner)
        self.assertEqual(len(response.context["today_lessons_pending"]), 1)

    def test_today_lessons_empty_when_no_lessons(self):
        self.lesson.delete()
        response = self._get(self.owner)
        self.assertEqual(response.context["today_lessons_total"], 0)
        self.assertEqual(len(response.context["today_lessons_pending"]), 0)

    def test_teacher_today_scoped(self):
        other = User.objects.create_user("othert", password=self.password, role=UserRole.TEACHER)
        other_group = Group.objects.create(name="Other G", course=Course.objects.get(name="Math"), teacher=other.teacher_profile, monthly_fee=Decimal("200.00"))
        Lesson.objects.create(group=other_group, date=self.today, start_time=time(11, 0), end_time=time(12, 0))
        response = self._get(self.teacher_user)
        self.assertEqual(response.context["today_lessons_total"], 1)

    def test_upcoming_grouped_skips_today(self):
        response = self._get(self.owner)
        grouped = response.context["upcoming_grouped"]
        for day_lessons in grouped.values():
            for lesson in day_lessons:
                self.assertNotEqual(lesson.date, self.today)

    def test_upcoming_grouped_has_tomorrow(self):
        response = self._get(self.owner)
        grouped = response.context["upcoming_grouped"]
        self.assertIn(self.today + timedelta(days=1), grouped)


class DashboardActionRequiredTests(TestCase):
    """Test the ACTION REQUIRED section."""

    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="Ученик Тест", phone="900200001")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        self.today = date.today()
        self.lesson = Lesson.objects.create(group=self.group, date=self.today, start_time=time(18, 0), end_time=time(19, 0))

    def _get(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard"))

    def test_pending_attendance_count_for_owner(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["pending_attendance_count"], 1)

    def test_pending_attendance_count_for_teacher(self):
        response = self._get(self.teacher_user)
        self.assertEqual(response.context["pending_attendance_count"], 1)

    def test_no_pending_when_attendance_marked(self):
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        response = self._get(self.owner)
        self.assertEqual(response.context["pending_attendance_count"], 0)

    def test_action_required_section_rendered(self):
        response = self._get(self.owner)
        self.assertContains(response, "Требует внимания")


class DashboardKPITests(TestCase):
    """Test the compact KPI row."""

    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="Тест К", phone="900300001")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        today = date.today()
        self.lesson = Lesson.objects.create(group=self.group, date=today, start_time=time(18, 0), end_time=time(19, 0))
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)

    def _get(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard"))

    def test_attendance_rate_for_owner(self):
        response = self._get(self.owner)
        self.assertIsNotNone(response.context["attendance_rate"])
        self.assertEqual(response.context["attendance_rate"], 100)

    def test_attendance_rate_none_when_no_data(self):
        Attendance.objects.all().delete()
        response = self._get(self.owner)
        self.assertEqual(response.context["attendance_rate"], 0)
        self.assertEqual(response.context["attendance_completion_rate"], 0)

    def test_attendance_total_for_owner(self):
        response = self._get(self.owner)
        self.assertEqual(response.context["attendance_total"], 1)

    def test_kpi_rendered_in_html(self):
        response = self._get(self.owner)
        self.assertContains(response, "dash-kpi")

    def test_teacher_no_money_in_kpi(self):
        response = self._get(self.teacher_user)
        self.assertNotContains(response, "Оплачено")


class DashboardRecentActivityTests(TestCase):
    """Test the RECENT ACTIVITY feed (admin/owner only)."""

    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="Активный Студент", phone="900400001")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        AuditLog.objects.create(
            actor=self.owner,
            action=AuditAction.STUDENT_CREATE,
            target_type="Student",
            target_id=self.student.pk,
            description="Создание ученика",
        )

    def _get(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard"))

    def test_owner_sees_recent_activity(self):
        response = self._get(self.owner)
        self.assertEqual(len(response.context["recent_activity"]), 1)
        self.assertContains(response, "Последняя активность")
        self.assertContains(response, "Новый ученик")

    def test_teacher_no_recent_activity(self):
        response = self._get(self.teacher_user)
        self.assertEqual(response.context["recent_activity"], [])
        self.assertNotContains(response, "Последняя активность")


class DashboardEmptyStatesTests(TestCase):
    """Test empty state handling across all new dashboard sections."""

    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)

    def _get(self):
        self.client.force_login(self.owner)
        return self.client.get(reverse("dashboard"))

    def test_empty_today_lessons(self):
        response = self._get()
        self.assertContains(response, "Занятий на сегодня нет.")

    def test_empty_upcoming_lessons(self):
        response = self._get()
        self.assertContains(response, "Ближайших занятий нет.")

    def test_empty_attendance(self):
        response = self._get()
        self.assertContains(response, "Нет данных о посещаемости.")

    def test_empty_groups(self):
        response = self._get()
        self.assertContains(response, "Нет активных групп.")

    def test_empty_recent_activity(self):
        response = self._get()
        self.assertContains(response, "Нет последней активности.")

    def test_empty_action_required_ok(self):
        response = self._get()
        self.assertContains(response, "Всё в порядке")


class DashboardRegressionTests(TestCase):
    """Regression tests for root-cause fixes: payment paid_at vs period, archived teacher count."""

    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.archived_teacher_user = User.objects.create_user("archived_t", password=self.password, role=UserRole.TEACHER)
        self.archived_teacher_user.teacher_profile.status = RecordStatus.ARCHIVED
        self.archived_teacher_user.teacher_profile.save(update_fields=("status",))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="Тест Ученик", phone="900900001")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        self.today = date.today()
        self.period_start = self.today.replace(day=1)
        self.last_month_start = (self.period_start - timedelta(days=1)).replace(day=1)

    def _get(self, user=None):
        self.client.force_login(user or self.owner)
        return self.client.get(reverse("dashboard"))

    def test_paid_at_current_month_counted_even_if_period_is_future(self):
        Payment.objects.create(
            student=self.student, group=self.group,
            amount=Decimal("250.00"), paid_at=self.today,
            period=self.period_start + timedelta(days=40),
        )
        response = self._get()
        self.assertEqual(response.context["payments_total"], Decimal("250.00"))

    def test_period_current_month_not_counted_if_paid_at_is_other_month(self):
        Payment.objects.create(
            student=self.student, group=self.group,
            amount=Decimal("100.00"), paid_at=self.last_month_start,
            period=self.period_start,
        )
        response = self._get()
        self.assertEqual(response.context["payments_total"], Decimal("0.00"))

    def test_cancelled_payment_excluded_regardless_of_paid_at(self):
        Payment.objects.create(
            student=self.student, group=self.group,
            amount=Decimal("300.00"), paid_at=self.today,
            period=self.period_start, status=PaymentStatus.CANCELLED,
        )
        response = self._get()
        self.assertEqual(response.context["payments_total"], Decimal("0.00"))
        self.assertEqual(response.context["payments_count"], 0)

    def test_archived_teacher_not_counted(self):
        response = self._get()
        self.assertEqual(response.context["teachers_count"], 1)

    def test_dashboard_attendance_only_current_month(self):
        """Attendance stats must reflect current month only, not lifetime."""
        from datetime import date as _date
        today = _date.today()
        period_start = today.replace(day=1)
        last_month_start = (period_start - timedelta(days=1)).replace(day=1)
        last_month_day = (period_start - timedelta(days=1))
        self.client.force_login(self.owner)
        other_group = Group.objects.create(
            name="Math A1", course=Course.objects.first(),
            teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("300.00"),
        )
        s1 = Student.objects.create(full_name="Прошлый Месяц", phone="900100001")
        s2 = Student.objects.create(full_name="Текущий Месяц", phone="900100002")
        e1 = Enrollment.objects.create(student=s1, group=other_group, started_at=last_month_start)
        e2 = Enrollment.objects.create(student=s2, group=other_group, started_at=period_start)
        lesson_last = Lesson.objects.create(group=other_group, date=last_month_day, start_time=time(9), end_time=time(10))
        lesson_this = Lesson.objects.create(group=other_group, date=today, start_time=time(9), end_time=time(10))
        Attendance.objects.create(lesson=lesson_last, student=s1, status=AttendanceStatus.PRESENT)
        Attendance.objects.create(lesson=lesson_this, student=s2, status=AttendanceStatus.ABSENT)
        response = self._get()
        self.assertEqual(response.context["attendance_present"], 0)
        self.assertEqual(response.context["attendance_absent"], 1)
        self.assertEqual(response.context["attendance_late"], 0)

    def test_dashboard_attendance_teacher_scoped(self):
        """Teacher dashboard attendance must only count their own lessons, current month."""
        from datetime import date as _date
        today = _date.today()
        period_start = today.replace(day=1)
        self.client.force_login(self.teacher_user)
        other_group = Group.objects.create(
            name="Math A1", course=Course.objects.first(),
            teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("300.00"),
        )
        other_group_2 = Group.objects.create(
            name="Math B1", course=Course.objects.first(),
            teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("300.00"),
        )
        s1 = Student.objects.create(full_name="Ученик Титч", phone="900200001")
        Enrollment.objects.create(student=s1, group=other_group, started_at=period_start)
        Enrollment.objects.create(student=s1, group=other_group_2, started_at=period_start)
        l1 = Lesson.objects.create(group=other_group, date=today, start_time=time(9), end_time=time(10))
        l2 = Lesson.objects.create(group=other_group_2, date=today, start_time=time(11), end_time=time(12))
        Attendance.objects.create(lesson=l1, student=s1, status=AttendanceStatus.PRESENT)
        Attendance.objects.create(lesson=l2, student=s1, status=AttendanceStatus.LATE)
        response = self._get(user=self.teacher_user)
        self.assertEqual(response.context["attendance_present"], 1)
        self.assertEqual(response.context["attendance_late"], 1)
        self.assertEqual(response.context["attendance_absent"], 0)
