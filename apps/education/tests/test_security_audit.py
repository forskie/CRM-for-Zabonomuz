from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
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
    Student,
)


User = get_user_model()


class SecurityAuditTestCase(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.other_teacher = User.objects.create_user("other", password=self.password, role=UserRole.TEACHER)
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.other_group = Group.objects.create(name="Russian A1", course=course, teacher=self.other_teacher.teacher_profile, monthly_fee=Decimal("300.00"))
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        self.other_student = Student.objects.create(full_name="Чужой Ученик", phone="900123999")
        self.enrollment = Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        self.lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        self.other_lesson = Lesson.objects.create(group=self.other_group, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        self.payment = Payment.objects.create(student=self.student, group=self.group, amount=Decimal("350.00"), paid_at=date(2026, 8, 5), period=date(2026, 8, 1))

    def _payment_post(self, **overrides):
        data = {
            "student": self.student.pk,
            "group": self.group.pk,
            "amount": "350.00",
            "paid_at": "2026-08-05",
            "period": "2026-08-01",
            "note": "",
        }
        data.update(overrides)
        return data

    # ---------------------------------------------------------------- auth

    def test_anonymous_redirected_to_login(self):
        protected = [
            reverse("dashboard"),
            reverse("education:student-list"),
            reverse("education:teacher-list"),
            reverse("education:course-list"),
            reverse("education:group-list"),
            reverse("education:lesson-list"),
            reverse("education:payment-list"),
            reverse("education:audit-list"),
            reverse("education:student-detail", args=[self.student.pk]),
            reverse("education:payment-detail", args=[self.payment.pk]),
            reverse("accounts:user-list"),
        ]
        for url in protected:
            response = self.client.get(url)
            self.assertIn(response.status_code, (302, 403), url)
            self.assertNotEqual(response.status_code, 500)

    def test_owner_can_access_all_sections(self):
        self.client.force_login(self.owner)
        urls = [
            reverse("dashboard"),
            reverse("education:student-list"),
            reverse("education:teacher-list"),
            reverse("education:course-list"),
            reverse("education:group-list"),
            reverse("education:lesson-list"),
            reverse("education:payment-list"),
            reverse("education:audit-list"),
            reverse("accounts:user-list"),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_admin_can_access_operations_but_not_user_management(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("education:payment-list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("education:audit-list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:user-list")).status_code, 403)

    def test_teacher_role_limits(self):
        self.client.force_login(self.teacher_user)
        allowed = [
            reverse("dashboard"),
            reverse("education:student-list"),
            reverse("education:group-list"),
            reverse("education:lesson-list"),
            reverse("education:course-list"),
            reverse("education:teacher-list"),
        ]
        for url in allowed:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        denied = [
            reverse("education:payment-list"),
            reverse("education:payment-detail", args=[self.payment.pk]),
            reverse("education:payment-create"),
            reverse("education:payment-edit", args=[self.payment.pk]),
            reverse("education:payment-cancel", args=[self.payment.pk]),
            reverse("education:audit-list"),
            reverse("education:student-create"),
            reverse("education:teacher-create"),
            reverse("education:course-create"),
            reverse("education:group-create"),
            reverse("education:lesson-create"),
            reverse("accounts:user-list"),
        ]
        for url in denied:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(reverse("education:payment-cancel", args=[self.payment.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("education:payment-create")).status_code, 403)

    # -------------------------------------------------------- object level

    def test_object_level_isolation_for_teacher(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("education:group-detail", args=[self.other_group.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("education:lesson-detail", args=[self.other_lesson.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("education:teacher-detail", args=[self.other_teacher.teacher_profile.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:student-detail", args=[self.other_student.pk])).status_code, 403)

    def test_teacher_cannot_edit_foreign_objects_by_direct_url(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.post(reverse("education:lesson-status", args=[self.other_lesson.pk, LessonStatus.COMPLETED])).status_code, 403)

    # ------------------------------------------------------ financial data

    def test_teacher_has_no_financial_data_in_querysets(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:group-detail", args=[self.group.pk]))
        self.assertEqual(len(response.context["payments"]), 0)
        self.assertEqual(response.context["payments_total"], Decimal("0"))
        self.assertNotContains(response, "350,00 TJS")
        response = self.client.get(reverse("education:student-detail", args=[self.student.pk]))
        self.assertEqual(len(response.context["payments"]), 0)
        self.assertNotContains(response, "350,00 TJS")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["payments_total"], Decimal("0"))
        self.assertEqual(response.context["payments_count"], 0)
        self.assertEqual(len(response.context["recent_payments"]), 0)

    def test_teacher_financial_data_blocked_via_query_params(self):
        self.client.force_login(self.teacher_user)
        for params in ({"q": "Алиев"}, {"student": self.student.pk}, {"month": "2026-08"}):
            self.assertEqual(self.client.get(reverse("education:payment-list"), params).status_code, 403, params)

    # ------------------------------------------------------ forged inputs

    def test_forged_student_id_ignored_in_student_payment_create(self):
        self.client.force_login(self.admin)
        data = self._payment_post(student=self.other_student.pk)
        self.client.post(reverse("education:student-payment-create", args=[self.student.pk]), data)
        created = Payment.objects.filter(pk=self.payment.pk + 1).first()
        self.assertIsNotNone(created)
        self.assertEqual(created.student_id, self.student.pk)

    def test_forged_group_id_ignored_in_group_payment_create(self):
        self.client.force_login(self.admin)
        data = self._payment_post(group=self.other_group.pk)
        self.client.post(reverse("education:group-payment-create", args=[self.group.pk]), data)
        created = Payment.objects.filter(pk=self.payment.pk + 1).first()
        self.assertIsNotNone(created)
        self.assertEqual(created.group_id, self.group.pk)

    def test_forged_student_in_enrollment_create_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("education:enrollment-create", args=[self.group.pk]),
            {"student": self.student.pk, "started_at": "2026-09-01"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже активно зачислен")

    def test_payment_rejects_student_without_enrollment_history(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:payment-create"), self._payment_post(student=self.other_student.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "не был связан с этой группой")
        self.assertEqual(Payment.objects.count(), 1)

    # --------------------------------------------------------------- CSRF

    def test_post_without_csrf_token_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(reverse("education:student-create"), {"full_name": "XSS", "phone": "900000000"})
        self.assertEqual(response.status_code, 403)
        response = client.post(reverse("education:student-status", args=[self.student.pk, "ARCHIVED"]))
        self.assertEqual(response.status_code, 403)
        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "ACTIVE")

    def test_post_with_csrf_token_accepted(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        client.get(reverse("education:student-create"))
        token = client.cookies["csrftoken"].value
        response = client.post(
            reverse("education:student-create"),
            {"full_name": "Новый Ученик", "phone": "900111222", "csrfmiddlewaretoken": token},
        )
        self.assertNotEqual(response.status_code, 403)
        self.assertTrue(Student.objects.filter(full_name="Новый Ученик").exists())

    # ------------------------------------------------------- GET no mutate

    def test_get_cannot_mutate_state(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("education:student-status", args=[self.student.pk, "ARCHIVED"])).status_code, 403)
        self.student.refresh_from_db()
        self.assertEqual(self.student.status, "ACTIVE")
        self.assertEqual(self.client.get(reverse("education:payment-cancel", args=[self.payment.pk])).status_code, 403)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PAID)
        self.assertEqual(self.client.get(reverse("education:lesson-status", args=[self.lesson.pk, LessonStatus.COMPLETED])).status_code, 403)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)

    # --------------------------------------------------------------- audit

    def test_audit_payment_create(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:payment-create"), self._payment_post(amount="400.00"))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.PAYMENT_CREATE)
        self.assertEqual(log.target_type, "Payment")
        self.assertEqual(log.target_id, self.payment.pk + 1)
        self.assertEqual(log.actor_id, self.admin.pk)
        self.assertIn("400.00", log.description)

    def test_audit_payment_edit(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:payment-edit", args=[self.payment.pk]), self._payment_post(amount="400.00", status=PaymentStatus.PAID))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.PAYMENT_EDIT)
        self.assertEqual(log.target_id, self.payment.pk)

    def test_audit_payment_cancel(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:payment-cancel", args=[self.payment.pk]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.PAYMENT_CANCEL)
        self.assertEqual(log.target_id, self.payment.pk)
        self.assertEqual(log.actor_id, self.admin.pk)

    def test_audit_attendance_change(self):
        self.client.force_login(self.admin)
        data = {f"status_{self.student.pk}": AttendanceStatus.PRESENT, f"note_{self.student.pk}": ""}
        self.client.post(reverse("education:lesson-detail", args=[self.lesson.pk]), data)
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.ATTENDANCE_CHANGE)
        self.assertEqual(log.target_type, "Lesson")
        self.assertEqual(log.target_id, self.lesson.pk)
        self.assertIn("отмечено 1", log.description)

    def test_audit_enrollment_create_and_end(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:enrollment-create", args=[self.group.pk]), {"student": self.other_student.pk, "started_at": "2026-08-10"})
        created = Enrollment.objects.get(student=self.other_student, group=self.group)
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.ENROLLMENT_CREATE)
        self.assertEqual(log.target_id, created.pk)
        self.client.post(reverse("education:enrollment-end", args=[created.pk]), {"ended_at": "2026-09-01"})
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.ENROLLMENT_END)
        self.assertEqual(log.target_id, created.pk)

    def test_audit_student_archive_and_restore(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:student-status", args=[self.student.pk, "ARCHIVED"]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.STUDENT_ARCHIVE)
        self.assertEqual(log.target_id, self.student.pk)
        self.client.post(reverse("education:student-status", args=[self.student.pk, "ACTIVE"]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.STUDENT_RESTORE)

    def test_audit_no_record_when_status_unchanged(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:student-status", args=[self.student.pk, "ACTIVE"]))
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_teacher_cannot_read_audit_logs(self):
        AuditLog.objects.create(actor=self.admin, action=AuditAction.PAYMENT_CREATE, target_type="Payment", target_id=1, description="x")
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("education:audit-list")).status_code, 403)

    def test_audit_log_append_only(self):
        log = AuditLog.objects.create(actor=self.admin, action=AuditAction.PAYMENT_CREATE, target_type="Payment", target_id=1, description="x")
        log.action = AuditAction.PAYMENT_CANCEL
        with self.assertRaises(ValidationError):
            log.save()
        log.refresh_from_db()
        self.assertEqual(log.action, AuditAction.PAYMENT_CREATE)

    def test_audit_page_does_not_accept_modification(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:audit-list"))
        self.assertEqual(response.status_code, 200)
        self.client.post(reverse("education:audit-list"))
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_audit_page_pagination_and_action_filter(self):
        for i in range(25):
            AuditLog.objects.create(actor=self.admin, action=AuditAction.ENROLLMENT_CREATE, target_type="Enrollment", target_id=i, description=f"Запись {i}")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:audit-list"))
        self.assertEqual(len(response.context["page_obj"]), 20)
        self.assertTrue(response.context["page_obj"].has_next)
        response = self.client.get(reverse("education:audit-list"), {"action": AuditAction.PAYMENT_CREATE})
        self.assertEqual(len(response.context["page_obj"]), 0)
        self.assertContains(response, "ничего не найдено")

    # ------------------------------------------------- settings & headers

    def test_production_settings_values(self):
        self.assertEqual(settings.SECURE_CONTENT_TYPE_NOSNIFF, True)
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")
        self.assertEqual(settings.SECURE_REFERRER_POLICY, "same-origin")
        self.assertIsInstance(settings.CSRF_TRUSTED_ORIGINS, list)
        self.assertEqual(settings.SECURE_HSTS_SECONDS, 0)

    @override_settings(SECURE_HSTS_SECONDS=3600, SECURE_HSTS_INCLUDE_SUBDOMAINS=True)
    def test_hsts_header_emitted_when_enabled(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"), secure=True)
        self.assertEqual(response["Strict-Transport-Security"], "max-age=3600; includeSubDomains")

    @override_settings(SECURE_HSTS_SECONDS=0)
    def test_no_hsts_header_by_default(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertNotIn("Strict-Transport-Security", response)

    def test_security_headers_present(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["Referrer-Policy"], "same-origin")

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_secure_cookie_flags(self):
        self.client.get(reverse("accounts:login"))
        self.assertTrue(self.client.cookies["csrftoken"]["secure"])
        response = self.client.post(reverse("accounts:login"), {"username": "admin", "password": self.password})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.cookies["sessionid"]["secure"])
