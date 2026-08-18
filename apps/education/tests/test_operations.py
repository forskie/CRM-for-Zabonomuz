from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import Course, RecordStatus, Student, Teacher


User = get_user_model()


class OperationalBaseTestCase(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.teacher = self.teacher_user.teacher_profile


class StudentTests(OperationalBaseTestCase):
    def test_admin_can_create_and_edit_student(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:student-create"), {"full_name": "Алиев Рустам", "phone": "+992 90 123 4567"})
        student = Student.objects.get(full_name="Алиев Рустам")
        self.assertRedirects(response, reverse("education:student-detail", args=[student.pk]))
        self.client.post(reverse("education:student-edit", args=[student.pk]), {"full_name": "Алиев Рустам Б.", "phone": "900000000"})
        student.refresh_from_db()
        self.assertEqual(student.full_name, "Алиев Рустам Б.")

    def test_archive_and_restore_student(self):
        student = Student.objects.create(full_name="Каримова Мадина")
        self.client.force_login(self.owner)
        self.client.post(reverse("education:student-status", args=[student.pk, RecordStatus.ARCHIVED]))
        student.refresh_from_db()
        self.assertEqual(student.status, RecordStatus.ARCHIVED)
        self.assertFalse(Student.objects.filter(status=RecordStatus.ACTIVE, pk=student.pk).exists())
        self.client.post(reverse("education:student-status", args=[student.pk, RecordStatus.ACTIVE]))
        student.refresh_from_db()
        self.assertEqual(student.status, RecordStatus.ACTIVE)

    def test_student_search_and_status_filter(self):
        matching = Student.objects.create(full_name="Саидов Фарид", phone="900123456")
        archived = Student.objects.create(full_name="Другой ученик", status=RecordStatus.ARCHIVED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-list"), {"q": "900123", "status": RecordStatus.ACTIVE})
        self.assertContains(response, matching.full_name)
        self.assertNotContains(response, archived.full_name)
        response = self.client.get(reverse("education:student-list"), {"status": RecordStatus.ARCHIVED})
        self.assertContains(response, archived.full_name)

    def test_teacher_cannot_view_or_change_students_by_direct_url(self):
        student = Student.objects.create(full_name="Алиев Рустам")
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("education:student-detail", args=[student.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("education:student-edit", args=[student.pk]), {"full_name": "Изменён", "phone": ""}).status_code, 403)


class TeacherTests(OperationalBaseTestCase):
    def test_admin_can_create_edit_archive_and_restore_teacher(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:teacher-create"), {"username": "teacher-two", "full_name": "Иванова Лола", "phone": "900123456", "password1": self.password, "password2": self.password})
        teacher = Teacher.objects.get(user__username="teacher-two")
        self.assertRedirects(response, reverse("education:teacher-detail", args=[teacher.pk]))
        self.assertEqual(teacher.user.role, UserRole.TEACHER)
        self.client.post(reverse("education:teacher-edit", args=[teacher.pk]), {"full_name": "Иванова Лола А.", "phone": "901234567"})
        self.client.post(reverse("education:teacher-status", args=[teacher.pk, RecordStatus.ARCHIVED]))
        teacher.refresh_from_db()
        self.assertEqual(teacher.status, RecordStatus.ARCHIVED)
        self.client.post(reverse("education:teacher-status", args=[teacher.pk, RecordStatus.ACTIVE]))
        teacher.refresh_from_db()
        self.assertEqual(teacher.status, RecordStatus.ACTIVE)

    def test_teacher_only_sees_own_profile(self):
        other_user = User.objects.create_user("other-teacher", password=self.password, role=UserRole.TEACHER)
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("education:teacher-detail", args=[self.teacher.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("education:teacher-detail", args=[other_user.teacher_profile.pk])).status_code, 403)


class CourseTests(OperationalBaseTestCase):
    def test_admin_can_create_edit_archive_and_restore_course(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:course-create"), {"name": "English", "description": "A1", "default_monthly_fee": "300.00"})
        course = Course.objects.get(name="English")
        self.assertRedirects(response, reverse("education:course-detail", args=[course.pk]))
        self.assertEqual(course.default_monthly_fee, Decimal("300.00"))
        self.client.post(reverse("education:course-edit", args=[course.pk]), {"name": "English A1", "description": "", "default_monthly_fee": "350"})
        self.client.post(reverse("education:course-status", args=[course.pk, RecordStatus.ARCHIVED]))
        course.refresh_from_db()
        self.assertEqual(course.status, RecordStatus.ARCHIVED)
        self.client.post(reverse("education:course-status", args=[course.pk, RecordStatus.ACTIVE]))
        course.refresh_from_db()
        self.assertEqual(course.status, RecordStatus.ACTIVE)

    def test_course_fee_is_decimal_and_cannot_be_negative(self):
        field = Course._meta.get_field("default_monthly_fee")
        self.assertEqual(field.decimal_places, 2)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("education:course-create"), {"name": "Russian", "description": "", "default_monthly_fee": "-1"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Course.objects.filter(name="Russian").exists())

    def test_teacher_can_only_view_active_courses_and_cannot_edit(self):
        active = Course.objects.create(name="English", default_monthly_fee=Decimal("300"))
        archived = Course.objects.create(name="Russian", status=RecordStatus.ARCHIVED)
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:course-list"))
        self.assertContains(response, active.name)
        self.assertNotContains(response, archived.name)
        self.assertEqual(self.client.post(reverse("education:course-edit", args=[active.pk]), {"name": "Changed", "description": "", "default_monthly_fee": "1"}).status_code, 403)
