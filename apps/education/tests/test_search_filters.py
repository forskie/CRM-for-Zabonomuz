from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import Attendance, Course, Enrollment, EnrollmentStatus, Group, Lesson, LessonStatus, Payment, PaymentStatus, RecordStatus, Student


User = get_user_model()


class SearchFilterTestCase(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_user = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)
        self.other_teacher_user = User.objects.create_user("other", password=self.password, role=UserRole.TEACHER)
        self.teacher_user.teacher_profile.full_name = "Учитель Один"
        self.teacher_user.teacher_profile.phone = "900000001"
        self.teacher_user.teacher_profile.save()
        self.other_teacher_user.teacher_profile.full_name = "Учитель Два"
        self.other_teacher_user.teacher_profile.save()
        self.course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.archived_course = Course.objects.create(name="French", default_monthly_fee=Decimal("300.00"), status=RecordStatus.ARCHIVED)
        self.group = Group.objects.create(name="English A1", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"))
        self.other_group = Group.objects.create(name="Russian A1", course=self.course, teacher=self.other_teacher_user.teacher_profile, monthly_fee=Decimal("300.00"))
        self.archived_group = Group.objects.create(name="Old Group", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("350.00"), status=RecordStatus.ARCHIVED)
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        self.student_2 = Student.objects.create(full_name="Каримова Мадина", phone="900123457")
        self.archived_student = Student.objects.create(full_name="Архивный Ученик", phone="900123458", status=RecordStatus.ARCHIVED)
        self.other_student = Student.objects.create(full_name="Чужой Ученик", phone="900123999")
        Enrollment.objects.create(student=self.student, group=self.group, started_at=date(2026, 8, 1))
        Enrollment.objects.create(student=self.student_2, group=self.group, started_at=date(2026, 8, 1))
        Enrollment.objects.create(student=self.other_student, group=self.other_group, started_at=date(2026, 8, 1))
        self.lesson = Lesson.objects.create(group=self.group, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        self.other_lesson = Lesson.objects.create(group=self.other_group, date=date(2026, 8, 20), start_time=time(10), end_time=time(11))
        Payment.objects.create(student=self.student, group=self.group, amount=Decimal("350.00"), paid_at=date(2026, 8, 5), period=date(2026, 8, 1))
        Payment.objects.create(student=self.student_2, group=self.group, amount=Decimal("150.00"), paid_at=date(2026, 8, 10), period=date(2026, 8, 1))
        Payment.objects.create(student=self.student, group=self.group, amount=Decimal("200.00"), paid_at=date(2026, 7, 5), period=date(2026, 7, 1))

    def _bulk_students(self, count=22):
        for i in range(count):
            Student.objects.create(full_name=f"Ученик Батч {i}", phone="90012%04d" % i)

    def _bulk_groups(self, count=23):
        for i in range(count):
            Group.objects.create(name=f"Группа Батч {i}", course=self.course, teacher=self.teacher_user.teacher_profile, monthly_fee=Decimal("300.00"))

    def _bulk_teachers(self, count=23):
        for i in range(count):
            User.objects.create_user(f"batch{i}", password=self.password, role=UserRole.TEACHER)

    def _bulk_payments(self, count=23):
        for i in range(count):
            Payment.objects.create(student=self.student, group=self.group, amount=Decimal("100.00"), paid_at=date(2026, 8, 1), period=date(2026, 8, 1))

    # ---------- Students ----------

    def test_student_search_finds_by_name_and_phone(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-list"), {"q": "Алиев"})
        self.assertContains(response, "Алиев Рустам")
        self.assertNotContains(response, "Каримова Мадина")
        response = self.client.get(reverse("education:student-list"), {"q": "900123457"})
        self.assertContains(response, "Каримова Мадина")

    def test_student_status_filter(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-list"), {"status": RecordStatus.ARCHIVED})
        self.assertContains(response, "Архивный Ученик")
        self.assertNotContains(response, "Алиев Рустам")
        response = self.client.get(reverse("education:student-list"), {"status": RecordStatus.ACTIVE})
        self.assertContains(response, "Алиев Рустам")
        self.assertNotContains(response, "Архивный Ученик")

    def test_student_pagination(self):
        self._bulk_students()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-list"))
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(response.context["page_obj"]), 20)
        response = self.client.get(reverse("education:student-list"), {"page": "2"})
        self.assertEqual(len(response.context["page_obj"]), 5)

    def test_student_query_params_preserved_in_pagination(self):
        self._bulk_students()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-list"), {"q": "90012", "status": RecordStatus.ACTIVE})
        self.assertContains(response, "q=90012&amp;status=ACTIVE&amp;page=2")

    # ---------- Teachers ----------

    def test_teacher_search_by_name_username_email_and_phone(self):
        User.objects.create_user("mailuser", email="mail@test.com", password=self.password, role=UserRole.TEACHER)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:teacher-list"), {"q": "Учитель"})
        self.assertContains(response, "Учитель Один")
        self.assertContains(response, "Учитель Два")
        response = self.client.get(reverse("education:teacher-list"), {"q": "teacher"})
        self.assertContains(response, "Учитель Один")
        response = self.client.get(reverse("education:teacher-list"), {"q": "mail@test.com"})
        self.assertContains(response, "mailuser")
        response = self.client.get(reverse("education:teacher-list"), {"q": "900000001"})
        self.assertContains(response, "Учитель Один")

    def test_teacher_status_filter(self):
        self.teacher_user.teacher_profile.status = RecordStatus.ARCHIVED
        self.teacher_user.teacher_profile.save()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:teacher-list"), {"status": RecordStatus.ARCHIVED})
        self.assertContains(response, "Учитель Один")
        self.assertNotContains(response, "Учитель Два")

    def test_teacher_pagination(self):
        self._bulk_teachers()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:teacher-list"))
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(response.context["page_obj"]), 20)
        response = self.client.get(reverse("education:teacher-list"), {"page": "2"})
        self.assertEqual(len(response.context["page_obj"]), 5)

    # ---------- Groups ----------

    def test_group_search_by_name(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:group-list"), {"q": "English"})
        self.assertContains(response, "English A1")
        self.assertNotContains(response, "Russian A1")

    def test_group_filters_by_course_teacher_and_status(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:group-list"), {"course": self.course.pk, "status": RecordStatus.ACTIVE})
        self.assertContains(response, "English A1")
        self.assertContains(response, "Russian A1")
        self.assertNotContains(response, "Old Group")
        response = self.client.get(reverse("education:group-list"), {"teacher": self.teacher_user.teacher_profile.pk})
        self.assertContains(response, "English A1")
        self.assertNotContains(response, "Russian A1")
        response = self.client.get(reverse("education:group-list"), {"status": RecordStatus.ARCHIVED})
        self.assertContains(response, "Old Group")
        self.assertNotContains(response, "English A1")

    def test_group_pagination(self):
        self._bulk_groups()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:group-list"), {"status": RecordStatus.ACTIVE})
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        response = self.client.get(reverse("education:group-list"), {"status": RecordStatus.ACTIVE, "page": "2"})
        self.assertEqual(len(response.context["page_obj"]), 5)

    # ---------- Courses ----------

    def test_course_search_by_name(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:course-list"), {"q": "Eng"})
        self.assertContains(response, "English")
        self.assertNotContains(response, "French")

    def test_course_status_filter(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:course-list"), {"status": RecordStatus.ARCHIVED})
        self.assertContains(response, "French")
        self.assertNotContains(response, "English")

    # ---------- Lessons ----------

    def test_lesson_filter_by_group(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:lesson-list"), {"group": self.group.pk})
        lesson_pks = [l.pk for l in response.context["page_obj"]]
        self.assertEqual(lesson_pks, [self.lesson.pk])
        self.assertNotIn(self.other_lesson.pk, lesson_pks)

    def test_lesson_filter_by_status_and_date(self):
        cancelled = Lesson.objects.create(group=self.group, date=date(2026, 8, 25), start_time=time(18), end_time=time(19), status=LessonStatus.CANCELLED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:lesson-list"), {"status": LessonStatus.CANCELLED})
        lesson_pks = [l.pk for l in response.context["page_obj"]]
        self.assertEqual(lesson_pks, [cancelled.pk])
        response = self.client.get(reverse("education:lesson-list"), {"date_from": "2026-08-01", "date_to": "2026-08-18"})
        lesson_pks = [l.pk for l in response.context["page_obj"]]
        self.assertEqual(lesson_pks, [self.lesson.pk])

    # ---------- Payments ----------

    def test_payment_filters_still_work(self):
        Payment.objects.create(student=self.student, group=self.group, amount=Decimal("300.00"), paid_at=date(2026, 8, 15), period=date(2026, 8, 1), status=PaymentStatus.CANCELLED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:payment-list"), {"q": "Алиев"})
        self.assertContains(response, "Алиев Рустам")
        self.assertNotContains(response, "Каримова Мадина")
        response = self.client.get(reverse("education:payment-list"), {"group": self.group.pk})
        self.assertContains(response, "Алиев Рустам")
        self.assertContains(response, "Каримова Мадина")
        response = self.client.get(reverse("education:payment-list"), {"status": PaymentStatus.CANCELLED})
        self.assertContains(response, "300,00 TJS")
        response = self.client.get(reverse("education:payment-list"), {"month": "2026-08"})
        self.assertContains(response, "350,00 TJS")
        self.assertNotContains(response, "200,00 TJS")

    def test_payment_pagination(self):
        self._bulk_payments()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:payment-list"))
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(response.context["page_obj"]), 20)
        response = self.client.get(reverse("education:payment-list"), {"page": "2"})
        self.assertEqual(len(response.context["page_obj"]), 6)

    def test_teacher_cannot_get_financial_data_via_query_params(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:payment-list"), {"q": "Алиев", "group": self.group.pk, "status": PaymentStatus.PAID, "month": "2026-08"})
        self.assertEqual(response.status_code, 403)

    # ---------- Permissions: no bypass ----------

    def test_teacher_cannot_bypass_group_isolation_with_filters(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("education:group-list"), {"teacher": self.other_teacher_user.teacher_profile.pk})
        self.assertContains(response, "English A1")
        self.assertNotContains(response, "Russian A1")
        response = self.client.get(reverse("education:lesson-list"), {"group": self.other_group.pk})
        lesson_pks = [l.pk for l in response.context["page_obj"]]
        self.assertEqual(lesson_pks, [self.lesson.pk])
        self.assertNotIn(self.other_lesson.pk, lesson_pks)
        response = self.client.get(reverse("education:student-list"), {"q": "Чужой"})
        self.assertNotContains(response, "Чужой Ученик")

    # ---------- Empty states ----------

    def test_empty_list_shows_nothing_found(self):
        Payment.objects.all().delete()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:payment-list"))
        self.assertContains(response, "Ничего не найдено.")
        self.assertNotContains(response, "По заданным фильтрам ничего не найдено.")

    def test_search_no_results_shows_filters_message(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:student-list"), {"q": "zzz-nonexistent"})
        self.assertContains(response, "По заданным фильтрам ничего не найдено.")
