from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.education.models import Course, Enrollment, Group, Payment, PaymentStatus, Student


class Stage20FinancialPolishTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner20", password="safe-pass", role=UserRole.OWNER)
        self.teacher_user = User.objects.create_user("teacher20", password="safe-pass", role=UserRole.TEACHER)
        self.course = Course.objects.create(name="Stage 20", default_monthly_fee=Decimal("400"))
        self.group = Group.objects.create(
            name="Stage 20 group", course=self.course, teacher=self.teacher_user.teacher_profile,
            monthly_fee=Decimal("450"),
        )
        self.student = Student.objects.create(full_name="Ученик Stage 20")
        Enrollment.objects.create(
            student=self.student, group=self.group, started_at=timezone.localdate() - timedelta(days=60)
        )
        self.month_start = timezone.localdate().replace(day=1)

    def payment(self, amount, *, paid_at=None, period=None, status=PaymentStatus.PAID, note=""):
        return Payment.objects.create(
            student=self.student, group=self.group, amount=Decimal(amount),
            paid_at=paid_at or timezone.localdate(), period=period or self.month_start,
            status=status, note=note,
        )

    def test_student_summary_uses_paid_at_and_excludes_cancelled(self):
        current = self.payment("200", period=self.month_start - timedelta(days=1))
        self.payment("900", status=PaymentStatus.CANCELLED)
        self.payment("100", paid_at=self.month_start - timedelta(days=1))
        self.client.force_login(self.owner)
        response = self.client.get(reverse("education:student-detail", args=[self.student.pk]))
        self.assertEqual(response.context["finance_received"], Decimal("200.00"))
        self.assertEqual(response.context["finance_payment_count"], 1)
        self.assertEqual(response.context["last_paid_payment"], current)
        self.assertNotContains(response, "900,00 TJS")

    def test_group_summary_is_current_cash_month_without_fake_debt(self):
        self.payment("450")
        self.payment("300", paid_at=self.month_start - timedelta(days=1), period=self.month_start)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("education:group-detail", args=[self.group.pk]))
        self.assertEqual(response.context["payments_total"], Decimal("450.00"))
        self.assertEqual(response.context["paid_payments_count"], 1)
        self.assertNotContains(response, "Долг")

    def test_teacher_context_and_html_contain_no_finance(self):
        self.payment("450")
        self.client.force_login(self.teacher_user)
        for url in (
            reverse("education:student-detail", args=[self.student.pk]),
            reverse("education:group-detail", args=[self.group.pk]),
        ):
            response = self.client.get(url)
            self.assertNotIn("finance_received", response.context)
            self.assertNotIn("payments_total", response.context)
            self.assertNotContains(response, "450,00 TJS")
            self.assertNotContains(response, "Добавить оплату")

    def test_student_payment_form_autoselects_only_active_group_and_fee(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("education:student-payment-create", args=[self.student.pk]))
        form = response.context["form"]
        self.assertEqual(form.initial["group"], self.group)
        self.assertEqual(form.initial["amount"], self.group.monthly_fee)
        self.assertEqual(form.fields["period"].widget.input_type, "month")
        self.assertContains(response, "Дата, когда деньги фактически были получены")
        self.assertContains(response, "Месяц обучения, за который внесена оплата")

    def test_manual_amount_is_never_overwritten_on_submit(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("education:student-payment-create", args=[self.student.pk]), {
            "group": self.group.pk,
            "amount": "275.50",
            "paid_at": timezone.localdate().isoformat(),
            "period": self.month_start.strftime("%Y-%m"),
            "status": PaymentStatus.PAID,
            "note": "Ручная сумма",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.get().amount, Decimal("275.50"))

    def test_generic_form_query_context_can_prefill_student_group_and_fee(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("education:payment-create"), {"student": self.student.pk})
        form = response.context["form"]
        self.assertEqual(form.initial["student"], self.student)
        self.assertEqual(form.initial["group"], self.group)
        self.assertEqual(form.initial["amount"], Decimal("450"))

    def test_payment_list_explains_period_and_shows_note_and_cancelled_state(self):
        self.payment("450", status=PaymentStatus.CANCELLED, note="Ошибочная операция")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("education:payment-list"))
        self.assertContains(response, "Период обучения")
        self.assertContains(response, "Ошибочная операция")
        self.assertContains(response, "badge--cancelled")

    def test_teacher_navigation_has_analytics_but_no_payment_link(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, reverse("core:analytics"))
        self.assertNotContains(response, reverse("education:payment-list"))

    def test_design_system_keeps_light_dark_and_responsive_breakpoints(self):
        css = (settings.BASE_DIR / "static" / "css" / "crm.css").read_text(encoding="utf-8")
        self.assertIn("Stage 20 — calm, light-first education product refinement", css)
        self.assertIn('[data-theme="dark"]', css)
        for width in (340, 430, 600, 768, 1024):
            self.assertIn(f"max-width: {width}px", css)
        self.assertIn(".summary-strip", css)
        self.assertIn(".period-picker", css)
