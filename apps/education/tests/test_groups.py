from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import Course, Enrollment, EnrollmentStatus, Group, RecordStatus, Student


User = get_user_model()


class GroupEnrollmentTests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.other_teacher_user = User.objects.create_user("other-teacher", password=self.password, role=UserRole.TEACHER)
        self.course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group = Group.objects.create(name="English A1", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")

    def test_admin_creates_group_with_course_teacher_and_independent_fee(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:group-create"), {"name": "English A2", "course": self.course.pk, "teacher": self.teacher_user.teacher_profile.pk, "monthly_fee": "400.00"})
        group = Group.objects.get(name="English A2")
        self.assertRedirects(response, reverse("education:group-detail", args=[group.pk]))
        self.assertEqual(group.course, self.course)
        self.assertEqual(group.teacher, self.teacher_user.teacher_profile)
        self.course.default_monthly_fee = Decimal("999.00")
        self.course.save()
        group.refresh_from_db()
        self.assertEqual(group.monthly_fee, Decimal("400.00"))

    def test_admin_edits_archives_and_restores_group(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:group-edit", args=[self.group.pk]), {"name": "English A1 Evening", "course": self.course.pk, "teacher": self.teacher_user.teacher_profile.pk, "monthly_fee": "360"})
        self.client.post(reverse("education:group-status", args=[self.group.pk, RecordStatus.ARCHIVED]))
        self.group.refresh_from_db()
        self.assertEqual(self.group.status, RecordStatus.ARCHIVED)
        self.client.post(reverse("education:group-status", args=[self.group.pk, RecordStatus.ACTIVE]))
        self.group.refresh_from_db()
        self.assertEqual(self.group.status, RecordStatus.ACTIVE)

    def test_admin_can_create_end_and_reenroll(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:enrollment-create", args=[self.group.pk]), {"student": self.student.pk, "started_at": "2026-08-01"})
        enrollment = Enrollment.objects.get(student=self.student, group=self.group, status=EnrollmentStatus.ACTIVE)
        self.assertRedirects(response, reverse("education:group-detail", args=[self.group.pk]))
        self.client.post(reverse("education:enrollment-end", args=[enrollment.pk]), {"ended_at": "2026-09-01"})
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, EnrollmentStatus.ENDED)
        self.assertEqual(enrollment.ended_at, date(2026, 9, 1))
        self.client.post(reverse("education:enrollment-create", args=[self.group.pk]), {"student": self.student.pk, "started_at": "2026-09-02"})
        self.assertEqual(Enrollment.objects.filter(student=self.student, group=self.group).count(), 2)
        self.assertEqual(Enrollment.objects.filter(student=self.student, group=self.group, status=EnrollmentStatus.ACTIVE).count(), 1)

    def test_student_can_have_active_enrollments_in_multiple_groups(self):
        second_group = Group.objects.create(name="English B1", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=300)
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        Enrollment.objects.create(student=self.student, group=second_group, started_at=date(2026, 8, 1))
        self.assertEqual(self.student.enrollments.filter(status=EnrollmentStatus.ACTIVE).count(), 2)

    def test_duplicate_active_enrollment_is_rejected_by_form_and_database(self):
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:enrollment-create", args=[self.group.pk]), {"student": self.student.pk, "started_at": "2026-08-02"})
        self.assertContains(response, "уже активно зачислен")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Enrollment.objects.bulk_create([Enrollment(student=self.student, group=self.group, started_at=date(2026, 8, 2))])

    def test_invalid_enrollment_dates_are_rejected(self):
        enrollment = Enrollment(student=self.student, group=self.group, started_at=date(2026, 8, 2), ended_at=date(2026, 8, 1), status=EnrollmentStatus.ENDED)
        with self.assertRaises(ValidationError):
            enrollment.full_clean()
        self.client.force_login(self.admin)
        active = Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 2))
        response = self.client.post(reverse("education:enrollment-end", args=[active.pk]), {"ended_at": "2026-08-01"})
        self.assertContains(response, "не может быть раньше")

    def test_student_page_shows_active_and_history(self):
        current = Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        old_group = Group.objects.create(name="English Pre-A1", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=300)
        Enrollment.objects.create(student=self.student, group=old_group, started_at=date(2026, 6, 1), ended_at=date(2026, 7, 1), status=EnrollmentStatus.ENDED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-detail", args=[self.student.pk]))
        self.assertContains(response, current.group.name)
        self.assertContains(response, old_group.name)

    def test_group_page_counts_only_active_students(self):
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        old_student = Student.objects.create(full_name="Исторический")
        Enrollment.objects.create(student=old_student, group=self.group, started_at=date(2026, 6, 1), ended_at=date(2026, 7, 1), status=EnrollmentStatus.ENDED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:group-detail", args=[self.group.pk]))
        self.assertContains(response, "Активные ученики (1)")
        self.assertContains(response, self.student.full_name)

    def test_teacher_only_sees_own_groups_and_cannot_manage_enrollment(self):
        other_group = Group.objects.create(name="Russian A1", course=self.course, teacher=self.other_teacher_user.teacher_profile, monthly_fee=300)
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:group-list"))
        self.assertContains(response, self.group.name)
        self.assertNotContains(response, other_group.name)
        self.assertEqual(self.client.get(reverse("education:group-detail", args=[other_group.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("education:enrollment-create", args=[self.group.pk]), {"student": self.student.pk, "started_at": "2026-08-01"}).status_code, 403)

    def test_teacher_sees_students_in_own_group_only(self):
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        unrelated = Student.objects.create(full_name="Чужой ученик")
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:student-list"))
        self.assertContains(response, self.student.full_name)
        self.assertNotContains(response, unrelated.full_name)
