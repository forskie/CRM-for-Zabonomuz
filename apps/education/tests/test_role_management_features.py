from datetime import timedelta, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.education.models import Attendance, Course, Discount, Enrollment, EnrollmentStatus, Group, Lesson, Student


class RoleManagementFeatureTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("feature-owner", password="password", role=UserRole.OWNER)
        self.admin = User.objects.create_user("feature-admin", password="password", role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("feature-teacher", password="password", role=UserRole.TEACHER)
        self.course = Course.objects.create(name="Feature course", default_monthly_fee=Decimal("100"))
        self.source = Group.objects.create(name="Source", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("100"))
        self.target = Group.objects.create(name="Target", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("120"))
        self.student = Student.objects.create(full_name="Feature student")
        self.started_at = timezone.localdate() - timedelta(days=10)
        self.enrollment = Enrollment.objects.create(student=self.student, group=self.source, started_at=self.started_at)
        self.lesson = Lesson.objects.create(group=self.source, date=timezone.localdate(), start_time=time(10), end_time=time(11))

    def test_admin_has_dashboard_but_not_analytics(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:analytics")).status_code, 403)

    def test_teacher_can_only_submit_present_or_absent(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse("education:lesson-detail", args=[self.lesson.pk]), {
            f"status_{self.student.pk}": "LATE",
            "topic": "Crafted topic",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Attendance.objects.filter(lesson=self.lesson).exists())
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.topic, "")

    def test_admin_transfers_student_atomically(self):
        self.client.force_login(self.admin)
        transfer_date = timezone.localdate()
        response = self.client.post(reverse("education:student-transfer", args=[self.student.pk]), {
            "enrollment": self.enrollment.pk,
            "target_group": self.target.pk,
            "transfer_date": transfer_date.isoformat(),
        })
        self.assertRedirects(response, reverse("education:student-detail", args=[self.student.pk]))
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, EnrollmentStatus.ENDED)
        self.assertEqual(self.enrollment.ended_at, transfer_date - timedelta(days=1))
        self.assertTrue(Enrollment.objects.filter(student=self.student, group=self.target, status=EnrollmentStatus.ACTIVE).exists())

    def test_admin_creates_student_discount(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:discount-create"), {
            "name": "Family",
            "student": self.student.pk,
            "group": "",
            "percentage": "15",
            "starts_at": timezone.localdate().isoformat(),
            "ends_at": "",
            "is_active": "on",
        })
        self.assertRedirects(response, reverse("education:discount-list"))
        self.assertTrue(Discount.objects.filter(student=self.student, percentage=Decimal("15")).exists())
