from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import Course, Enrollment, EnrollmentStatus, Group, Payment, PaymentStatus, Student


User = get_user_model()


class PaymentTestCase(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.other_group = Group.objects.create(name="Russian A1", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("300.00"))
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        self.other_student = Student.objects.create(full_name="Чужой ученик", phone="900123457")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 7, 1))

    def _post(self, **overrides):
        data = {
            "student": self.student.pk,
            "group": self.group.pk,
            "amount": "350.00",
            "paid_at": "2026-07-05",
            "period": "2026-07-01",
            "note": "",
        }
        data.update(overrides)
        return data

    def _payment(self, **overrides):
        data = {
            "student": self.student,
            "group": self.group,
            "amount": Decimal("350.00"),
            "paid_at": date(2026, 7, 5),
            "period": date(2026, 7, 1),
        }
        data.update(overrides)
        return Payment.objects.create(**data)

    def test_creation_with_decimal_amount(self):
        payment = self._payment(amount=Decimal("350.50"))
        self.assertIsInstance(payment.amount, Decimal)
        self.assertEqual(payment.amount, Decimal("350.50"))
        self.assertEqual(payment.paid_at, date(2026, 7, 5))
        self.assertEqual(payment.period, date(2026, 7, 1))

    def test_status_paid_default_and_cancelled(self):
        payment = self._payment()
        self.assertEqual(payment.status, PaymentStatus.PAID)
        payment.status = PaymentStatus.CANCELLED
        payment.save()
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.CANCELLED)
        self.assertEqual(Payment.objects.filter(pk=payment.pk).count(), 1)

    def test_amount_must_be_positive(self):
        for bad in (Decimal("0"), Decimal("-1"), Decimal("-0.01")):
            payment = Payment(student=self.student, group=self.group, amount=bad, paid_at=date(2026, 7, 5), period=date(2026, 7, 1))
            with self.assertRaises(ValidationError):
                payment.full_clean()

    def test_payment_requires_prior_enrollment(self):
        payment = Payment(student=self.other_student, group=self.group, amount=Decimal("350.00"), paid_at=date(2026, 7, 5), period=date(2026, 7, 1))
        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_payment_remains_valid_after_enrollment_ends(self):
        payment = self._payment()
        enrollment = Enrollment.objects.get(student=self.student, group=self.group)
        enrollment.status = EnrollmentStatus.ENDED
        enrollment.ended_at = date(2026, 7, 31)
        enrollment.save()
        payment.full_clean()
        payment.save()
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("350.00"))
        self.assertEqual(payment.status, PaymentStatus.PAID)

    def test_owner_can_create_payment(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("education:payment-create"), self._post())
        payment = Payment.objects.get(student=self.student, group=self.group)
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))

    def test_admin_can_create_payment(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:payment-create"), self._post())
        payment = Payment.objects.get(student=self.student, group=self.group)
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))

    def test_teacher_cannot_create_or_view_payments(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("education:payment-list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("education:payment-create"), self._post()).status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_teacher_does_not_see_financial_data(self):
        self._payment()
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:student-detail", args=[self.student.pk]))
        self.assertContains(response, "Attendance history")
        self.assertNotContains(response, "Добавить оплату")
        response = self.client.get(reverse("education:group-detail", args=[self.group.pk]))
        self.assertNotContains(response, "Оплачено")
        self.assertNotContains(response, "Payments")

    def test_teacher_direct_url_is_blocked(self):
        payment = self._payment()
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("education:payment-detail", args=[payment.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("education:payment-edit", args=[payment.pk]), {"amount": "1"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("education:payment-cancel", args=[payment.pk])).status_code, 403)

    def test_edit_payment(self):
        payment = self._payment()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:payment-edit", args=[payment.pk]), {
            "amount": "400.00",
            "paid_at": "2026-07-10",
            "period": "2026-08-20",
            "status": PaymentStatus.PAID,
            "note": "исправлено",
        })
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("400.00"))
        self.assertEqual(payment.paid_at, date(2026, 7, 10))
        self.assertEqual(payment.period, date(2026, 8, 1))
        self.assertEqual(payment.note, "исправлено")
        self.assertEqual(payment.student, self.student)
        self.assertEqual(payment.group, self.group)

    def test_cancel_payment_keeps_record(self):
        payment = self._payment()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:payment-cancel", args=[payment.pk]))
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.CANCELLED)
        self.assertEqual(Payment.objects.count(), 1)

    def test_student_detail_shows_payments(self):
        self._payment(amount=Decimal("350.00"))
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-detail", args=[self.student.pk]))
        self.assertContains(response, "350,00")
        self.assertContains(response, "Добавить оплату")

    def test_group_detail_shows_count_and_total_of_paid(self):
        self._payment(amount=Decimal("350.00"), paid_at=date(2026, 7, 5))
        self._payment(amount=Decimal("150.00"), paid_at=date(2026, 7, 20))
        self._payment(amount=Decimal("999.00"), paid_at=date(2026, 6, 1), period=date(2026, 6, 1), status=PaymentStatus.CANCELLED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:group-detail", args=[self.group.pk]))
        self.assertContains(response, "Payments (3)")
        self.assertContains(response, "500,00 TJS")

    def test_multiple_payments_per_period_allowed(self):
        self._payment(amount=Decimal("200.00"), paid_at=date(2026, 7, 5))
        self._payment(amount=Decimal("150.00"), paid_at=date(2026, 7, 20))
        self.assertEqual(Payment.objects.filter(student=self.student, group=self.group, period=date(2026, 7, 1)).count(), 2)

    def test_decimal_calculations_are_correct(self):
        self._payment(amount=Decimal("350.75"))
        self._payment(amount=Decimal("149.25"))
        total = Payment.objects.filter(student=self.student, group=self.group, status=PaymentStatus.PAID).aggregate(total=Sum("amount"))["total"]
        self.assertEqual(total, Decimal("500.00"))

    def test_student_from_another_group_rejected(self):
        Enrollment.objects.create(student=self.other_student, group=self.other_group, started_at=date(2026, 7, 1))
        payment = Payment(student=self.other_student, group=self.group, amount=Decimal("350.00"), paid_at=date(2026, 7, 5), period=date(2026, 7, 1))
        with self.assertRaises(ValidationError):
            payment.full_clean()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:payment-create"), self._post(student=self.other_student.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "не был связан")
        self.assertFalse(Payment.objects.exists())

    def test_zero_amount_rejected_by_form(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:payment-create"), self._post(amount="0"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.exists())
        response = self.client.post(reverse("education:payment-create"), self._post(amount="-100"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.exists())

    def test_student_route_blocks_group_swap(self):
        Enrollment.objects.create(student=self.other_student, group=self.other_group, started_at=date(2026, 7, 1))
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:student-payment-create", args=[self.student.pk]), {
            "student": self.other_student.pk,
            "group": self.other_group.pk,
            "amount": "350.00",
            "paid_at": "2026-07-05",
            "period": "2026-07-01",
            "note": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.exists())

    def test_student_route_cannot_swap_student(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:student-payment-create", args=[self.student.pk]), {
            "student": self.other_student.pk,
            "group": self.group.pk,
            "amount": "350.00",
            "paid_at": "2026-07-05",
            "period": "2026-07-01",
            "note": "",
        })
        self.assertRedirects(response, reverse("education:payment-detail", args=[Payment.objects.get().pk]))
        payment = Payment.objects.get()
        self.assertEqual(payment.student, self.student)
        self.assertEqual(payment.group, self.group)

    def test_group_route_cannot_swap_group(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:group-payment-create", args=[self.group.pk]), {
            "group": self.other_group.pk,
            "student": self.student.pk,
            "amount": "350.00",
            "paid_at": "2026-07-05",
            "period": "2026-07-01",
            "note": "",
        })
        self.assertRedirects(response, reverse("education:payment-detail", args=[Payment.objects.get().pk]))
        payment = Payment.objects.get()
        self.assertEqual(payment.student, self.student)
        self.assertEqual(payment.group, self.group)

    def test_period_is_normalized_to_first_of_month(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:payment-create"), self._post(period="2026-07-25"))
        payment = Payment.objects.get()
        self.assertEqual(payment.period, date(2026, 7, 1))

    def test_group_monthly_fee_not_changed_by_payment(self):
        self._payment(amount=Decimal("700.00"))
        self.group.refresh_from_db()
        self.assertEqual(self.group.monthly_fee, Decimal("350.00"))
