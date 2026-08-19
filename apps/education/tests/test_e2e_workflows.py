from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

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
    Teacher,
)


User = get_user_model()
PASSWORD = "Secure-e2e-password-2026"


def _today():
    return timezone.localdate()


class E2EBase(TestCase):
    password = PASSWORD

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_a_user = User.objects.create_user("teacher_a", password=self.password, role=UserRole.TEACHER)
        self.teacher_b_user = User.objects.create_user("teacher_b", password=self.password, role=UserRole.TEACHER)
        self.teacher_a = self.teacher_a_user.teacher_profile
        self.teacher_b = self.teacher_b_user.teacher_profile
        self.course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group_a = Group.objects.create(name="English A1", course=self.course, teacher=self.teacher_a, monthly_fee=Decimal("350.00"))
        self.group_b = Group.objects.create(name="English B1", course=self.course, teacher=self.teacher_b, monthly_fee=Decimal("420.00"))
        self.student_a = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        self.student_b = Student.objects.create(full_name="Бобоева Дилноза", phone="900123457")
        self.enrollment_a = Enrollment.objects.create(student=self.student_a, group=self.group_a, started_at=date(2026, 7, 1))
        self.enrollment_b = Enrollment.objects.create(student=self.student_b, group=self.group_b, started_at=date(2026, 7, 1))
        self.schedule_a = Schedule.objects.create(group=self.group_a, weekday=0, start_time=time(18, 0), end_time=time(19, 0))
        self.schedule_b = Schedule.objects.create(group=self.group_b, weekday=1, start_time=time(18, 0), end_time=time(19, 0))
        self.lesson_a = Lesson.objects.create(group=self.group_a, date=date(2026, 8, 17), start_time=time(18, 0), end_time=time(19, 0), schedule=self.schedule_a)
        self.lesson_b = Lesson.objects.create(group=self.group_b, date=date(2026, 8, 18), start_time=time(18, 0), end_time=time(19, 0), schedule=self.schedule_b)
        self.attendance_a = Attendance.objects.create(lesson=self.lesson_a, student=self.student_a, status=AttendanceStatus.PRESENT)
        self.payment_a = Payment.objects.create(student=self.student_a, group=self.group_a, amount=Decimal("350.00"), paid_at=date(2026, 8, 5), period=date(2026, 8, 1))
        self.payment_b = Payment.objects.create(student=self.student_b, group=self.group_b, amount=Decimal("420.00"), paid_at=date(2026, 8, 5), period=date(2026, 8, 1))

    def login(self, user):
        self.assertTrue(self.client.login(username=user.username, password=self.password))


class E2EOwnerWorkflow(E2EBase):
    def test_full_owner_business_flow(self):
        self.login(self.owner)
        owner = self.owner

        # 1-2. Teacher
        response = self.client.post(reverse("education:teacher-create"), {
            "username": "new_teacher",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "full_name": "Новый Учитель",
            "phone": "900555666",
        })
        new_teacher = Teacher.objects.get(user__username="new_teacher")
        self.assertRedirects(response, reverse("education:teacher-detail", args=[new_teacher.pk]))
        self.assertEqual(new_teacher.user.role, UserRole.TEACHER)
        self.assertEqual(new_teacher.full_name, "Новый Учитель")

        # 3. Course
        response = self.client.post(reverse("education:course-create"), {"name": "Math", "description": "", "default_monthly_fee": "250.00"})
        course = Course.objects.get(name="Math")
        self.assertRedirects(response, reverse("education:course-detail", args=[course.pk]))
        self.assertEqual(course.default_monthly_fee, Decimal("250.00"))

        # 4. Group
        response = self.client.post(reverse("education:group-create"), {
            "name": "Math A1", "course": course.pk, "teacher": new_teacher.pk, "monthly_fee": "280.00",
        })
        group = Group.objects.get(name="Math A1")
        self.assertRedirects(response, reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(group.course_id, course.pk)
        self.assertEqual(group.teacher_id, new_teacher.pk)
        self.assertEqual(group.monthly_fee, Decimal("280.00"))

        # 5. Student
        response = self.client.post(reverse("education:student-create"), {"full_name": "Каримов Искандер", "phone": "900888999"})
        student = Student.objects.get(full_name="Каримов Искандер")
        self.assertRedirects(response, reverse("education:student-detail", args=[student.pk]))

        # 6. Enrollment
        response = self.client.post(reverse("education:enrollment-create", args=[group.pk]), {"student": student.pk, "started_at": "2026-08-01"})
        enrollment = Enrollment.objects.get(student=student, group=group)
        self.assertRedirects(response, reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(enrollment.status, EnrollmentStatus.ACTIVE)
        self.assertIsNone(enrollment.ended_at)

        # 7. Schedule
        response = self.client.post(reverse("education:schedule-create", args=[group.pk]), {
            "weekday": 2, "start_time": "18:00", "end_time": "19:00", "is_active": "on",
        })
        schedule = Schedule.objects.get(group=group)
        self.assertRedirects(response, reverse("education:group-detail", args=[group.pk]))

        # 8-9. Lesson + detail page
        response = self.client.post(reverse("education:lesson-create"), {
            "group": group.pk, "date": "2026-08-24", "start_time": "18:00", "end_time": "19:00", "schedule": schedule.pk,
        })
        lesson = Lesson.objects.get(group=group, date=date(2026, 8, 24))
        self.assertRedirects(response, reverse("education:lesson-detail", args=[lesson.pk]))
        response = self.client.get(reverse("education:lesson-detail", args=[lesson.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["lesson"], lesson)
        self.assertEqual(response.context["summary"]["total"], 1)

        # 10. Attendance PRESENT
        response = self.client.post(reverse("education:lesson-detail", args=[lesson.pk]), {
            f"status_{student.pk}": AttendanceStatus.PRESENT, f"note_{student.pk}": "",
        })
        self.assertRedirects(response, reverse("education:lesson-detail", args=[lesson.pk]))
        record = Attendance.objects.get(lesson=lesson, student=student)
        self.assertEqual(record.status, AttendanceStatus.PRESENT)
        self.assertEqual(
            AuditLog.objects.filter(actor=owner, action=AuditAction.ATTENDANCE_CHANGE, target_type="Lesson", target_id=lesson.pk).count(), 1,
        )

        # 11. Payment PAID
        response = self.client.post(reverse("education:payment-create"), {
            "student": student.pk, "group": group.pk, "amount": "280.00", "paid_at": "2026-08-25", "period": "2026-08-01", "note": "",
        })
        payment = Payment.objects.get(student=student, group=group)
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))
        self.assertEqual(payment.amount, Decimal("280.00"))
        self.assertEqual(payment.status, PaymentStatus.PAID)
        self.assertTrue(AuditLog.objects.filter(actor=owner, action=AuditAction.PAYMENT_CREATE, target_type="Payment", target_id=payment.pk).exists())

        # 12-15. Student detail
        response = self.client.get(reverse("education:student-detail", args=[student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["active_enrollments"]), [enrollment])
        self.assertEqual(list(response.context["history_enrollments"]), [])
        self.assertEqual(list(response.context["attendance_history"]), [record])
        self.assertEqual(list(response.context["payments"]), [payment])
        self.assertContains(response, "280,00 TJS")

        # 16-18. Group detail
        response = self.client.get(reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["active_enrollments"]), [enrollment])
        self.assertEqual(list(response.context["history_enrollments"]), [])
        self.assertEqual(list(response.context["payments"]), [payment])
        self.assertEqual(response.context["payments_total"], Decimal("280.00"))
        self.assertContains(response, "280,00 TJS")

        # 19-20. Dashboard aggregates against DB
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["students_total"], Student.objects.count())
        self.assertEqual(response.context["students_active"], Student.objects.filter(status=RecordStatus.ACTIVE).count())
        self.assertEqual(response.context["teachers_count"], Teacher.objects.count())
        self.assertEqual(response.context["groups_active"], Group.objects.filter(status=RecordStatus.ACTIVE).count())

        # 21-22. Audit log
        response = self.client.get(reverse("education:audit-list"))
        self.assertEqual(response.status_code, 200)
        actions = set(AuditLog.objects.filter(actor=owner).values_list("action", flat=True))
        self.assertTrue({AuditAction.ENROLLMENT_CREATE, AuditAction.ATTENDANCE_CHANGE, AuditAction.PAYMENT_CREATE} <= actions)


class E2EAdminWorkflow(E2EBase):
    def test_admin_can_run_operations_workflow(self):
        self.login(self.admin)
        admin = self.admin

        response = self.client.post(reverse("education:student-create"), {"full_name": "Юсуфов Темур", "phone": "900777888"})
        student = Student.objects.get(full_name="Юсуфов Темур")
        self.assertRedirects(response, reverse("education:student-detail", args=[student.pk]))

        response = self.client.post(reverse("education:student-edit", args=[student.pk]), {"full_name": "Юсуфов Темур Б.", "phone": "900777888"})
        self.assertRedirects(response, reverse("education:student-detail", args=[student.pk]))
        student.refresh_from_db()
        self.assertEqual(student.full_name, "Юсуфов Темур Б.")

        response = self.client.post(reverse("education:enrollment-create", args=[self.group_a.pk]), {"student": student.pk, "started_at": "2026-08-01"})
        enrollment = Enrollment.objects.get(student=student, group=self.group_a)
        self.assertRedirects(response, reverse("education:group-detail", args=[self.group_a.pk]))
        self.assertEqual(enrollment.status, EnrollmentStatus.ACTIVE)

        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson_a.pk]), {
            f"status_{student.pk}": AttendanceStatus.LATE, f"note_{student.pk}": "пробки",
        })
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson_a.pk]))
        record = Attendance.objects.get(lesson=self.lesson_a, student=student)
        self.assertEqual(record.status, AttendanceStatus.LATE)

        response = self.client.post(reverse("education:payment-create"), {
            "student": student.pk, "group": self.group_a.pk, "amount": "350.00", "paid_at": "2026-08-27", "period": "2026-08-01", "note": "",
        })
        payment = Payment.objects.get(student=student, group=self.group_a)
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))

        response = self.client.post(reverse("education:payment-edit", args=[payment.pk]), {
            "student": student.pk, "group": self.group_a.pk, "amount": "380.00", "paid_at": "2026-08-27", "period": "2026-08-01", "status": PaymentStatus.PAID, "note": "",
        })
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("380.00"))

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["students_total"], Student.objects.count())

        response = self.client.get(reverse("education:audit-list"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(actor=admin, action=AuditAction.ENROLLMENT_CREATE).exists())
        self.assertTrue(AuditLog.objects.filter(actor=admin, action=AuditAction.ATTENDANCE_CHANGE).exists())
        self.assertTrue(AuditLog.objects.filter(actor=admin, action=AuditAction.PAYMENT_CREATE).exists())
        self.assertTrue(AuditLog.objects.filter(actor=admin, action=AuditAction.PAYMENT_EDIT).exists())

    def test_admin_has_no_owner_only_access(self):
        self.login(self.admin)
        for url in (reverse("accounts:user-list"), reverse("accounts:user-create"), reverse("accounts:user-edit", args=[self.owner.pk])):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, url)
            self.client.post(url)
            self.assertEqual(self.client.post(url).status_code, 403, url)


class E2ETeacherWorkflow(E2EBase):
    def test_teacher_sees_own_group_students_lessons_attendance(self):
        self.login(self.teacher_a_user)
        self.assertEqual(self.client.get(reverse("education:group-detail", args=[self.group_a.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("education:student-detail", args=[self.student_a.pk])).status_code, 200)
        response = self.client.get(reverse("education:lesson-detail", args=[self.lesson_a.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["can_edit"], True)
        self.assertEqual(list(response.context["lesson"].attendance_records.all()), [self.attendance_a])

    def test_teacher_cannot_see_foreign_data_by_url(self):
        self.login(self.teacher_a_user)
        self.assertEqual(self.client.get(reverse("education:group-detail", args=[self.group_b.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("education:student-detail", args=[self.student_b.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:lesson-detail", args=[self.lesson_b.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("education:teacher-detail", args=[self.teacher_b.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:payment-detail", args=[self.payment_a.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:audit-list")).status_code, 403)

    def test_teacher_cannot_see_foreign_data_by_query_parameters(self):
        self.login(self.teacher_a_user)
        response = self.client.get(reverse("education:lesson-list"), {"group": self.group_b.pk, "status": LessonStatus.SCHEDULED})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["page_obj"]), [self.lesson_a])
        response = self.client.get(reverse("education:student-list"), {"q": "Бобоева", "status": RecordStatus.ACTIVE})
        self.assertEqual(list(response.context["page_obj"]), [self.student_a])
        self.assertNotIn(self.student_b, response.context["page_obj"])
        response = self.client.get(reverse("education:payment-list"), {"q": "Алиев"})
        self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("education:group-list"), {"q": "B1"})
        self.assertEqual(list(response.context["page_obj"]), [self.group_a])
        self.assertNotIn(self.group_b, response.context["page_obj"])

    def test_teacher_has_no_financial_data_anywhere(self):
        self.login(self.teacher_a_user)
        response = self.client.get(reverse("education:group-detail", args=[self.group_a.pk]))
        self.assertNotIn("payments_total", response.context)
        self.assertNotIn("payments", response.context)
        self.assertNotContains(response, "350,00 TJS")
        response = self.client.get(reverse("education:student-detail", args=[self.student_a.pk]))
        self.assertNotIn("payments", response.context)
        self.assertNotContains(response, "350,00 TJS")
        response = self.client.get(reverse("education:course-list"))
        self.assertNotContains(response, "300,00 TJS")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["payments_total"], Decimal("0"))
        self.assertEqual(response.context["payments_count"], 0)
        self.assertEqual(len(response.context["recent_payments"]), 0)


class E2EEnrollmentLifecycle(E2EBase):
    def test_enrollment_end_preserves_history_and_validity(self):
        self.login(self.admin)
        student = self.student_a
        group = self.group_a

        self.client.post(reverse("education:enrollment-end", args=[self.enrollment_a.pk]), {"ended_at": "2026-08-31"})
        self.enrollment_a.refresh_from_db()
        self.assertEqual(self.enrollment_a.status, EnrollmentStatus.ENDED)
        self.assertEqual(self.enrollment_a.ended_at, date(2026, 8, 31))
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.ENROLLMENT_END, target_id=self.enrollment_a.pk).exists())

        self.payment_a.full_clean()
        self.payment_a.save()
        self.assertEqual(Payment.objects.filter(student=student, group=group).count(), 1)

        self.assertEqual(Attendance.objects.filter(student=student, lesson__group=group).count(), 1)

        response = self.client.get(reverse("education:student-detail", args=[student.pk]))
        self.assertEqual(list(response.context["history_enrollments"]), [self.enrollment_a])
        self.assertEqual(list(response.context["active_enrollments"]), [])
        self.assertEqual(len(response.context["attendance_history"]), 1)
        self.assertEqual(len(response.context["payments"]), 1)

        response = self.client.get(reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(list(response.context["active_enrollments"]), [])
        self.assertEqual(list(response.context["history_enrollments"]), [self.enrollment_a])
        group.refresh_from_db()
        self.assertEqual(group.enrollments.filter(status=EnrollmentStatus.ACTIVE).count(), 0)

        response = self.client.get(reverse("dashboard"))
        active_group = next(g for g in response.context["active_groups"] if g.pk == group.pk)
        self.assertEqual(active_group.student_count, 0)


class E2EPaymentLifecycle(E2EBase):
    def setUp(self):
        super().setUp()
        today = _today()
        self.period = today.replace(day=1)
        self.payment_b.period = date(2026, 7, 1)
        self.payment_b.paid_at = date(2026, 7, 5)
        self.payment_b.save()

    def test_two_payments_same_period_dashboard_consistency(self):
        self.payment_a.period = self.period
        self.payment_a.paid_at = _today()
        self.payment_a.save()
        second = Payment.objects.create(student=self.student_a, group=self.group_a, amount=Decimal("100.00"), paid_at=_today(), period=self.period)
        cancelled = Payment.objects.create(student=self.student_a, group=self.group_a, amount=Decimal("50.00"), paid_at=_today(), period=self.period, status=PaymentStatus.CANCELLED)

        db_total = Payment.objects.filter(student=self.student_a, period=self.period, status=PaymentStatus.PAID).aggregate(total=Sum("amount"))["total"]
        self.assertEqual(db_total, Decimal("450.00"))

        self.login(self.owner)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["payments_total"], Decimal("450.00"))
        self.assertEqual(response.context["payments_count"], 2)
        recent_ids = {p.pk for p in response.context["recent_payments"]}
        self.assertTrue({self.payment_a.pk, second.pk}.issubset(recent_ids))

        self.assertEqual(Payment.objects.filter(student=self.student_a, group=self.group_a, period=self.period).count(), 3)
        for p in (self.payment_a, second, cancelled):
            self.assertIsInstance(p.amount, Decimal)
            self.assertGreater(p.amount, 0)

    def test_cancelled_payment_excluded_from_total_but_kept(self):
        self.payment_a.period = self.period
        self.payment_a.paid_at = _today()
        self.payment_a.save()
        cancelled = Payment.objects.create(student=self.student_a, group=self.group_a, amount=Decimal("200.00"), paid_at=_today(), period=self.period)

        self.login(self.admin)
        self.client.post(reverse("education:payment-cancel", args=[cancelled.pk]))
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, PaymentStatus.CANCELLED)

        db_total = Payment.objects.filter(student=self.student_a, group=self.group_a, status=PaymentStatus.PAID).aggregate(total=Sum("amount"))["total"]
        self.assertEqual(db_total, Decimal("350.00"))
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["payments_total"], Decimal("350.00"))
        self.assertEqual(Payment.objects.filter(pk=cancelled.pk).count(), 1)

    def test_payment_survives_enrollment_end_via_ui(self):
        self.login(self.admin)
        self.client.post(reverse("education:enrollment-end", args=[self.enrollment_a.pk]), {"ended_at": "2026-08-31"})
        response = self.client.post(reverse("education:payment-create"), {
            "student": self.student_a.pk, "group": self.group_a.pk, "amount": "350.00", "paid_at": "2026-09-05", "period": "2026-09-01", "note": "",
        })
        payment = Payment.objects.get(student=self.student_a, group=self.group_a, period=date(2026, 9, 1))
        self.assertRedirects(response, reverse("education:payment-detail", args=[payment.pk]))
        self.assertEqual(payment.amount, Decimal("350.00"))

    def test_forged_ids_in_route_scoped_forms(self):
        self.login(self.admin)

        self.client.post(reverse("education:student-payment-create", args=[self.student_a.pk]), {
            "student": self.student_b.pk, "group": self.group_a.pk, "amount": "100.00", "paid_at": "2026-08-10", "period": "2026-08-01", "note": "",
        })
        payment = Payment.objects.order_by("-pk").first()
        self.assertEqual(payment.student_id, self.student_a.pk)
        self.assertEqual(payment.group_id, self.group_a.pk)

        before = Payment.objects.count()
        self.client.post(reverse("education:student-payment-create", args=[self.student_a.pk]), {
            "student": self.student_b.pk, "group": self.group_b.pk, "amount": "100.00", "paid_at": "2026-08-10", "period": "2026-08-01", "note": "",
        })
        self.assertEqual(Payment.objects.count(), before)

        before = Payment.objects.count()
        self.client.post(reverse("education:group-payment-create", args=[self.group_a.pk]), {
            "group": self.group_b.pk, "student": self.student_b.pk, "amount": "100.00", "paid_at": "2026-08-10", "period": "2026-08-01", "note": "",
        })
        self.assertEqual(Payment.objects.count(), before)


class E2EAttendanceLifecycle(E2EBase):
    def setUp(self):
        super().setUp()
        self.second_student = Student.objects.create(full_name="Саидов Фарход", phone="900123458")
        self.second_enrollment = Enrollment.objects.create(student=self.second_student, group=self.group_a, started_at=date(2026, 7, 1))

    def _mark(self, statuses):
        self.login(self.admin)
        data = {}
        for student, status in statuses:
            data[f"status_{student.pk}"] = status
            data[f"note_{student.pk}"] = ""
        return self.client.post(reverse("education:lesson-detail", args=[self.lesson_a.pk]), data)

    def test_multi_student_attendance_summary(self):
        response = self._mark([(self.student_a, AttendanceStatus.PRESENT), (self.second_student, AttendanceStatus.ABSENT)])
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson_a.pk]))
        self.assertEqual(Attendance.objects.filter(lesson=self.lesson_a).count(), 2)

        response = self.client.get(reverse("education:lesson-detail", args=[self.lesson_a.pk]))
        self.assertEqual(response.context["summary"]["total"], 2)
        self.assertEqual(response.context["summary"]["present"], 1)
        self.assertEqual(response.context["summary"]["absent"], 1)
        self.assertEqual(response.context["summary"]["late"], 0)
        self.assertEqual(response.context["summary"]["not_marked"], 0)

    def test_attendance_is_unique_per_lesson_student(self):
        self._mark([(self.student_a, AttendanceStatus.PRESENT)])
        self._mark([(self.student_a, AttendanceStatus.LATE)])
        records = Attendance.objects.filter(lesson=self.lesson_a, student=self.student_a)
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.get().status, AttendanceStatus.LATE)

    def test_attendance_surfaces_in_student_history_group_and_dashboard(self):
        self._mark([(self.student_a, AttendanceStatus.LATE), (self.second_student, AttendanceStatus.PRESENT)])
        self.login(self.admin)
        response = self.client.get(reverse("education:student-detail", args=[self.student_a.pk]))
        self.assertEqual(len(response.context["attendance_history"]), 1)
        self.assertEqual(response.context["attendance_history"][0].status, AttendanceStatus.LATE)
        response = self.client.get(reverse("education:group-detail", args=[self.group_a.pk]))
        self.assertEqual(response.context["attendance_stats"]["present"], 1)
        self.assertEqual(response.context["attendance_stats"]["late"], 1)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["attendance_present"], 1)
        self.assertEqual(response.context["attendance_late"], 1)

    def test_teacher_can_mark_attendance_on_own_lesson(self):
        self.login(self.teacher_a_user)
        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson_a.pk]), {
            f"status_{self.student_a.pk}": AttendanceStatus.PRESENT,
        })
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson_a.pk]))
        self.assertEqual(Attendance.objects.filter(lesson=self.lesson_a, student=self.student_a).count(), 1)
        self.assertEqual(Attendance.objects.get(lesson=self.lesson_a, student=self.student_a).status, AttendanceStatus.PRESENT)
        response = self.client.get(reverse("education:lesson-detail", args=[self.lesson_a.pk]))
        self.assertEqual(response.context["can_edit"], True)

    def test_cancelled_lesson_attendance_is_immutable(self):
        self._mark([(self.student_a, AttendanceStatus.PRESENT)])
        self.login(self.admin)
        self.client.post(reverse("education:lesson-status", args=[self.lesson_a.pk, LessonStatus.CANCELLED]))
        self.lesson_a.refresh_from_db()
        self.assertEqual(self.lesson_a.status, LessonStatus.CANCELLED)

        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson_a.pk]), {
            f"status_{self.student_a.pk}": AttendanceStatus.ABSENT,
        })
        self.assertEqual(response.status_code, 200)
        self.lesson_a.attendance_records.get(student=self.student_a).refresh_from_db()
        self.assertEqual(self.lesson_a.attendance_records.get(student=self.student_a).status, AttendanceStatus.PRESENT)

        record = Attendance.objects.get(lesson=self.lesson_a, student=self.student_a)
        record.status = AttendanceStatus.ABSENT
        with self.assertRaises(ValidationError):
            record.full_clean()


class E2ESearchFilters(E2EBase):
    def setUp(self):
        super().setUp()
        self.lesson_a2 = Lesson.objects.create(group=self.group_a, date=date(2026, 9, 1), start_time=time(18, 0), end_time=time(19, 0))
        for i in range(22):
            Student.objects.create(full_name=f"Фильтруемый Ученик {i:02d}", phone=f"900100{i:03d}")

    def test_student_q_status_page(self):
        self.login(self.admin)
        response = self.client.get(reverse("education:student-list"), {"q": "Фильтруемый", "status": RecordStatus.ACTIVE})
        self.assertEqual(len(response.context["page_obj"]), 20)
        self.assertTrue(response.context["page_obj"].has_next)
        self.assertIn("status=ACTIVE", response.context["pagination_qs"])
        self.assertIn("q=%D0%A4%D0%B8%D0%BB%D1%8C%D1%82%D1%80%D1%83%D0%B5%D0%BC%D1%8B%D0%B9", response.context["pagination_qs"])
        response = self.client.get(reverse("education:student-list"), {"q": "Фильтруемый", "status": RecordStatus.ACTIVE, "page": 2})
        self.assertEqual(len(response.context["page_obj"]), 2)
        response = self.client.get(reverse("education:student-list"), {"q": "Несуществующий", "status": RecordStatus.ACTIVE})
        self.assertEqual(list(response.context["page_obj"]), [])
        self.assertTrue(response.context["has_filters"])

    def test_group_q_status_course_teacher_page(self):
        self.login(self.admin)
        base = {"status": RecordStatus.ACTIVE, "course": self.course.pk, "teacher": self.teacher_a.pk}
        response = self.client.get(reverse("education:group-list"), {**base, "q": "A1"})
        self.assertEqual(list(response.context["page_obj"]), [self.group_a])
        self.assertEqual(response.context["selected_status"], RecordStatus.ACTIVE)
        response = self.client.get(reverse("education:group-list"), {**base, "q": "ZZZ"})
        self.assertEqual(list(response.context["page_obj"]), [])
        qs = response.context["pagination_qs"]
        self.assertIn("course={}".format(self.course.pk), qs)
        self.assertIn("q=ZZZ", qs)
        self.assertIn("status=ACTIVE", qs)
        self.assertIn("teacher={}".format(self.teacher_a.pk), qs)
        self.assertNotIn("page", qs)

    def test_lesson_combined_filters(self):
        self.login(self.admin)
        self.lesson_b.date = date(2026, 9, 1)
        self.lesson_b.save()
        self.client.post(reverse("education:lesson-status", args=[self.lesson_b.pk, LessonStatus.COMPLETED]))
        params = {"group": self.group_a.pk, "teacher": self.teacher_a.pk, "status": LessonStatus.SCHEDULED, "date_from": "2026-08-01", "date_to": "2026-08-31"}
        response = self.client.get(reverse("education:lesson-list"), params)
        self.assertEqual(list(response.context["page_obj"]), [self.lesson_a])
        response = self.client.get(reverse("education:lesson-list"), {**params, "date_from": "2026-09-01"})
        self.assertEqual(list(response.context["page_obj"]), [])
        response = self.client.get(reverse("education:lesson-list"), {"date_from": "2026-08-01", "date_to": "2026-12-31"})
        self.assertEqual(len(response.context["page_obj"]), 3)

    def test_invalid_dates_are_ignored_not_fatal(self):
        self.login(self.admin)
        response = self.client.get(reverse("education:lesson-list"), {"date_from": "garbage", "date_to": "31-08-2026"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), Lesson.objects.count())

    def test_payment_filters_combined(self):
        self.login(self.admin)
        self.payment_a.period = date(2026, 7, 1)
        self.payment_a.save()
        self.payment_b.period = date(2026, 7, 1)
        self.payment_b.save()
        response = self.client.get(reverse("education:payment-list"), {"q": "Алиев", "group": self.group_a.pk, "status": PaymentStatus.PAID, "month": "2026-07"})
        self.assertEqual(list(response.context["page_obj"]), [self.payment_a])
        response = self.client.get(reverse("education:payment-list"), {"month": "2026-12"})
        self.assertEqual(list(response.context["page_obj"]), [])
        response = self.client.get(reverse("education:payment-list"), {"month": "bad-month"})
        self.assertEqual(response.status_code, 200)

    def test_filters_do_not_bypass_permissions(self):
        self.login(self.teacher_a_user)
        response = self.client.get(reverse("education:lesson-list"), {"group": self.group_b.pk})
        self.assertEqual(list(response.context["page_obj"]), [self.lesson_a, self.lesson_a2])
        response = self.client.get(reverse("education:student-list"), {"q": "Бобоева"})
        self.assertEqual(list(response.context["page_obj"]), [self.student_a])
        self.login(self.admin)
        response = self.client.get(reverse("education:group-list"), {"teacher": self.teacher_b.pk})
        self.assertEqual(list(response.context["page_obj"]), [self.group_b])


class E2EAuditLifecycle(E2EBase):
    def _latest(self, action):
        return AuditLog.objects.filter(action=action).order_by("-pk").first()

    def test_student_create_archive_restore_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:student-create"), {"full_name": "Аудируемый Ученик", "phone": "900333444"})
        student = Student.objects.get(full_name="Аудируемый Ученик")
        log = AuditLog.objects.get(action=AuditAction.STUDENT_CREATE, target_id=student.pk)
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.target_type, "Student")
        self.assertEqual(log.description, "Аудируемый Ученик")

        self.client.post(reverse("education:student-status", args=[student.pk, RecordStatus.ARCHIVED]))
        log = self._latest(AuditAction.STUDENT_ARCHIVE)
        self.assertEqual(log.target_id, student.pk)
        self.assertEqual(log.actor, self.owner)

        self.client.post(reverse("education:student-status", args=[student.pk, RecordStatus.ACTIVE]))
        log = self._latest(AuditAction.STUDENT_RESTORE)
        self.assertEqual(log.target_id, student.pk)

    def test_enrollment_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:enrollment-create", args=[self.group_a.pk]), {"student": self.student_b.pk, "started_at": "2026-08-01"})
        enrollment = Enrollment.objects.get(student=self.student_b, group=self.group_a)
        log = self._latest(AuditAction.ENROLLMENT_CREATE)
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.target_id, enrollment.pk)
        self.assertEqual(log.target_type, "Enrollment")
        self.assertIn(str(self.student_b), log.description)

        self.client.post(reverse("education:enrollment-end", args=[enrollment.pk]), {"ended_at": "2026-09-01"})
        log = self._latest(AuditAction.ENROLLMENT_END)
        self.assertEqual(log.target_id, enrollment.pk)

    def test_attendance_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:lesson-detail", args=[self.lesson_a.pk]), {
            f"status_{self.student_a.pk}": AttendanceStatus.ABSENT,
        })
        log = self._latest(AuditAction.ATTENDANCE_CHANGE)
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.target_type, "Lesson")
        self.assertEqual(log.target_id, self.lesson_a.pk)
        self.assertEqual(log.description, f"{self.lesson_a.group}: {self.lesson_a.date} — отмечено 1 учеников")

    def test_payment_create_edit_cancel_audited(self):
        self.login(self.owner)
        self.client.post(reverse("education:payment-create"), {
            "student": self.student_a.pk, "group": self.group_a.pk, "amount": "350.00", "paid_at": "2026-08-05", "period": "2026-08-01", "note": "",
        })
        payment = Payment.objects.order_by("pk").last()
        log = self._latest(AuditAction.PAYMENT_CREATE)
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.target_id, payment.pk)
        self.assertIn("350.00", log.description)

        self.client.post(reverse("education:payment-edit", args=[payment.pk]), {
            "amount": "400.00", "paid_at": "2026-08-06", "period": "2026-08-01", "status": PaymentStatus.PAID, "note": "",
        })
        log = self._latest(AuditAction.PAYMENT_EDIT)
        self.assertEqual(log.target_id, payment.pk)
        self.assertIn("400.00", log.description)

        self.client.post(reverse("education:payment-cancel", args=[payment.pk]))
        log = self._latest(AuditAction.PAYMENT_CANCEL)
        self.assertEqual(log.target_id, payment.pk)

    def test_audit_log_immutable_through_application_flow(self):
        self.login(self.owner)
        count_before = AuditLog.objects.count()
        response = self.client.post(reverse("education:audit-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuditLog.objects.count(), count_before)
        response = self.client.get(reverse("education:audit-list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Удалить")


class E2EDashboardConsistency(E2EBase):
    def test_dashboard_matches_database(self):
        today = _today()
        period = today.replace(day=1)
        Payment.objects.create(student=self.student_a, group=self.group_a, amount=Decimal("50.00"), paid_at=today, period=period)
        Payment.objects.create(student=self.student_b, group=self.group_b, amount=Decimal("80.00"), paid_at=today, period=period)
        Payment.objects.create(student=self.student_a, group=self.group_a, amount=Decimal("999.00"), paid_at=today, period=period, status=PaymentStatus.CANCELLED)

        self.login(self.owner)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["students_total"], Student.objects.count())
        self.assertEqual(response.context["students_active"], Student.objects.filter(status=RecordStatus.ACTIVE).count())
        self.assertEqual(response.context["teachers_count"], Teacher.objects.count())
        self.assertEqual(response.context["groups_active"], Group.objects.filter(status=RecordStatus.ACTIVE).count())
        self.assertEqual(response.context["attendance_present"], Attendance.objects.filter(status=AttendanceStatus.PRESENT).count())
        self.assertEqual(response.context["attendance_absent"], Attendance.objects.filter(status=AttendanceStatus.ABSENT).count())
        self.assertEqual(response.context["attendance_late"], Attendance.objects.filter(status=AttendanceStatus.LATE).count())
        expected_total = Payment.objects.filter(period=period, status=PaymentStatus.PAID).aggregate(total=Sum("amount"))["total"]
        self.assertEqual(response.context["payments_total"], expected_total)
        self.assertEqual(response.context["payments_count"], Payment.objects.filter(paid_at__year=period.year, paid_at__month=period.month, status=PaymentStatus.PAID).count())
        self.assertEqual(list(response.context["recent_payments"]), list(Payment.objects.filter(status=PaymentStatus.PAID).select_related("student", "group__course").order_by("-paid_at", "-pk")[:5]))
        self.assertEqual(list(response.context["recent_attendance"]), list(Attendance.objects.select_related("student", "lesson__group").order_by("-lesson__date", "-pk")[:10]))
        expected_groups = list(Group.objects.filter(status=RecordStatus.ACTIVE).annotate(student_count=Count("enrollments", filter=Q(enrollments__status=EnrollmentStatus.ACTIVE), distinct=True)).order_by("name"))
        self.assertEqual(list(response.context["active_groups"]), expected_groups)


class E2EDataIntegrity(E2EBase):
    def test_orphan_records_are_blocked_by_protected_relations(self):
        with self.assertRaises(ProtectedError):
            self.student_a.delete()
        with self.assertRaises(ProtectedError):
            self.group_a.delete()
        with self.assertRaises(ProtectedError):
            self.lesson_a.delete()
        with self.assertRaises(ProtectedError):
            self.course.delete()
        self.assertEqual(Student.objects.count(), 2)
        self.assertEqual(Group.objects.count(), 2)
        self.assertEqual(Lesson.objects.count(), 2)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(Attendance.objects.count(), 1)

    def test_payment_requires_positive_decimal_amount(self):
        self.login(self.admin)
        for amount in ("0", "-5", "-0.01"):
            self.client.post(reverse("education:payment-create"), {
                "student": self.student_a.pk, "group": self.group_a.pk, "amount": amount, "paid_at": "2026-08-05", "period": "2026-08-01", "note": "",
            })
            self.assertEqual(Payment.objects.filter(amount__lte=0).count(), 0)

    def test_archived_records_remain_consistent(self):
        self.login(self.owner)
        self.client.post(reverse("education:student-status", args=[self.student_a.pk, RecordStatus.ARCHIVED]))
        self.client.post(reverse("education:course-status", args=[self.course.pk, RecordStatus.ARCHIVED]))
        self.client.post(reverse("education:group-status", args=[self.group_a.pk, RecordStatus.ARCHIVED]))
        self.client.post(reverse("education:lesson-status", args=[self.lesson_a.pk, LessonStatus.CANCELLED]))

        self.student_a.refresh_from_db()
        self.course.refresh_from_db()
        self.group_a.refresh_from_db()
        self.lesson_a.refresh_from_db()
        self.assertEqual(self.student_a.status, RecordStatus.ARCHIVED)
        self.assertEqual(self.course.status, RecordStatus.ARCHIVED)
        self.assertEqual(self.group_a.status, RecordStatus.ARCHIVED)
        self.assertEqual(self.lesson_a.status, LessonStatus.CANCELLED)

        self.assertEqual(Enrollment.objects.filter(student=self.student_a, group=self.group_a).count(), 1)
        self.assertEqual(Payment.objects.filter(student=self.student_a).count(), 1)
        self.assertEqual(Attendance.objects.filter(student=self.student_a).count(), 1)

        self.assertFalse(Enrollment.objects.filter(student=self.student_a, group=self.group_a, status=EnrollmentStatus.ACTIVE).exclude(pk=self.enrollment_a.pk).exists())
        self.assertFalse(Lesson.objects.filter(group=self.group_a, date=self.lesson_a.date, status=LessonStatus.CANCELLED).exclude(pk=self.lesson_a.pk).exists())


class E2ENegative(E2EBase):
    def _payment_post(self, **overrides):
        data = {"student": self.student_a.pk, "group": self.group_a.pk, "amount": "350.00", "paid_at": "2026-08-05", "period": "2026-08-01", "note": ""}
        data.update(overrides)
        return data

    def test_anonymous_is_redirected_everywhere(self):
        for url in (
            reverse("dashboard"),
            reverse("education:student-list"),
            reverse("education:group-list"),
            reverse("education:lesson-list"),
            reverse("education:payment-list"),
            reverse("education:audit-list"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("accounts:login"), response.url)

    def test_teacher_foreign_objects(self):
        self.login(self.teacher_a_user)
        self.assertEqual(self.client.get(reverse("education:group-detail", args=[self.group_b.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("education:student-detail", args=[self.student_b.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:lesson-detail", args=[self.lesson_b.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("education:lesson-status", args=[self.lesson_b.pk, LessonStatus.COMPLETED])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:payment-detail", args=[self.payment_a.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:audit-list")).status_code, 403)

    def test_forged_ids_rejected(self):
        self.login(self.admin)
        response = self.client.post(reverse("education:group-create"), {
            "name": "Forge", "course": self.course.pk, "teacher": 999999, "monthly_fee": "300.00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Group.objects.filter(name="Forge").exists())
        response = self.client.post(reverse("education:group-create"), {
            "name": "Forge2", "course": 999999, "teacher": self.teacher_a.pk, "monthly_fee": "300.00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Group.objects.filter(name="Forge2").exists())
        response = self.client.post(reverse("education:payment-create"), self._payment_post(student=999999))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.count(), 2)
        response = self.client.post(reverse("education:enrollment-create", args=[self.group_a.pk]), {"student": self.student_a.pk, "started_at": "2026-08-01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Enrollment.objects.filter(student=self.student_a, group=self.group_a, status=EnrollmentStatus.ACTIVE).count(), 1)

    def test_get_state_changing_endpoints_are_blocked(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("education:student-status", args=[self.student_a.pk, RecordStatus.ARCHIVED])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:lesson-status", args=[self.lesson_a.pk, LessonStatus.COMPLETED])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:payment-cancel", args=[self.payment_a.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:schedule-deactivate", args=[self.schedule_a.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:course-status", args=[self.course.pk, RecordStatus.ARCHIVED])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:group-status", args=[self.group_a.pk, RecordStatus.ARCHIVED])).status_code, 403)
        self.assertEqual(self.client.get(reverse("education:teacher-status", args=[self.teacher_a.pk, RecordStatus.ARCHIVED])).status_code, 403)
        self.student_a.refresh_from_db()
        self.payment_a.refresh_from_db()
        self.lesson_a.refresh_from_db()
        self.schedule_a.refresh_from_db()
        self.assertEqual(self.student_a.status, RecordStatus.ACTIVE)
        self.assertEqual(self.payment_a.status, PaymentStatus.PAID)
        self.assertEqual(self.lesson_a.status, LessonStatus.SCHEDULED)
        self.assertTrue(self.schedule_a.is_active)

    def test_post_without_csrf_token_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(reverse("education:student-create"), {"full_name": "XSS", "phone": "900000000"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Student.objects.filter(full_name="XSS").exists())

    def test_invalid_and_negative_and_zero_amounts(self):
        self.login(self.admin)
        for amount in ("abc", "0", "-100", "-0.01"):
            self.client.post(reverse("education:payment-create"), self._payment_post(amount=amount))
            self.assertEqual(Payment.objects.count(), 2, amount)

    def test_cancelled_lesson_rejects_attendance(self):
        self.login(self.admin)
        self.client.post(reverse("education:lesson-status", args=[self.lesson_a.pk, LessonStatus.CANCELLED]))
        self.client.post(reverse("education:lesson-detail", args=[self.lesson_a.pk]), {
            f"status_{self.student_a.pk}": AttendanceStatus.ABSENT,
        })
        self.assertEqual(Attendance.objects.filter(lesson=self.lesson_a).count(), 1)
        record = Attendance.objects.get(lesson=self.lesson_a, student=self.student_a)
        self.assertEqual(record.status, AttendanceStatus.PRESENT)

    def test_inactive_enrollment_attendance_rejected(self):
        record = Attendance(lesson=self.lesson_a, student=self.student_b, status=AttendanceStatus.PRESENT)
        with self.assertRaises(ValidationError):
            record.full_clean()
        self.assertEqual(Attendance.objects.filter(student=self.student_b).count(), 0)
