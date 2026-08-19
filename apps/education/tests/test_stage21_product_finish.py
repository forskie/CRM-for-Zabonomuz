from datetime import time
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.education.models import Course, Enrollment, Group, Lesson, Payment, Student


class Stage21ProductFinishTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner21", password="safe-pass", role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher21", password="safe-pass", role=UserRole.TEACHER)
        self.substitute_user = User.objects.create_user("substitute21", password="safe-pass", role=UserRole.TEACHER)
        self.course = Course.objects.create(name="Product Finish", default_monthly_fee=Decimal("777"))
        self.group = Group.objects.create(
            name="Finished group", course=self.course, teacher=self.teacher_user.teacher_profile,
            monthly_fee=Decimal("777"),
        )
        self.student = Student.objects.create(full_name="Готовый интерфейс")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=timezone.localdate())

    def test_teacher_group_list_does_not_render_financial_column_or_amount(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:group-list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Стоимость")
        self.assertNotContains(response, "777,00 TJS")

    def test_substitute_is_shown_as_effective_teacher_in_calendar_and_lesson_list(self):
        lesson = Lesson.objects.create(
            group=self.group, teacher=self.substitute_user.teacher_profile,
            date=timezone.localdate(), start_time=time(10), end_time=time(11),
        )
        self.client.force_login(self.owner)
        calendar = self.client.get(reverse("education:calendar"), {"view": "day", "date": lesson.date.isoformat()})
        lessons = self.client.get(reverse("education:lesson-list"))
        self.assertContains(calendar, "substitute21")
        self.assertContains(lessons, "substitute21")

    def test_payment_feedback_is_human_readable(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("education:payment-create"), {
            "student": self.student.pk,
            "group": self.group.pk,
            "amount": "777.00",
            "paid_at": timezone.localdate().isoformat(),
            "period": timezone.localdate().strftime("%Y-%m"),
            "status": "PAID",
            "note": "",
        }, follow=True)
        self.assertContains(response, "Оплата добавлена.")
        payment = Payment.objects.get()
        response = self.client.post(reverse("education:payment-cancel", args=[payment.pk]), follow=True)
        self.assertContains(response, "Оплата отменена и исключена из финансовых итогов.")

    def test_operational_navigation_uses_single_payment_vocabulary(self):
        self.client.force_login(self.owner)
        for url in (reverse("dashboard"), reverse("education:payment-list")):
            response = self.client.get(url)
            self.assertContains(response, "Оплаты")
            self.assertNotContains(response, ">Платежи<")

    def test_templates_have_no_static_inline_layout_overrides(self):
        templates = settings.BASE_DIR / "templates"
        offenders = []
        for path in templates.rglob("*.html"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "style=" in line and "attendance_rate" not in line:
                    offenders.append(f"{path.relative_to(templates)}:{number}")
        self.assertEqual(offenders, [])

    def test_mobile_calendar_and_filters_keep_compact_layout(self):
        css = (settings.BASE_DIR / "static" / "css" / "crm.css").read_text(encoding="utf-8")
        self.assertIn(".calendar-grid--month { grid-template-columns: repeat(2, 1fr); }", css)
        self.assertNotIn(".calendar-grid--month { grid-template-columns: 1fr; }", css)
        self.assertIn(".toolbar--filters { display: grid;", css)
        self.assertIn(".dash-kpi-grid { grid-template-columns: repeat(2", css)

