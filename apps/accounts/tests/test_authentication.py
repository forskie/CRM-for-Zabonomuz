from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole


User = get_user_model()


class AuthenticationAndRoleTests(TestCase):
    password = "Secure-test-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher = User.objects.create_user("teacher", password=self.password, role=UserRole.TEACHER)

    def test_login_accepts_correct_password(self):
        response = self.client.post(reverse("accounts:login"), {"username": "owner", "password": self.password})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(self.client.session["_auth_user_id"], str(self.owner.pk))

    def test_login_rejects_incorrect_password(self):
        response = self.client.post(reverse("accounts:login"), {"username": "owner", "password": "wrong-password"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('dashboard')}")

    def test_owner_can_access_user_management(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("accounts:user-list")).status_code, 200)

    def test_admin_cannot_access_user_management(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("accounts:user-list")).status_code, 403)

    def test_teacher_cannot_access_user_management(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("accounts:user-list")).status_code, 403)

    def test_inactive_user_cannot_log_in(self):
        self.teacher.is_active = False
        self.teacher.save()
        response = self.client.post(reverse("accounts:login"), {"username": "teacher", "password": self.password})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_teacher_cannot_access_other_user_through_direct_url(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("accounts:user-edit", args=[self.admin.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owner_cannot_create_another_owner_in_management_form(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("accounts:user-create"),
            {"username": "forged-owner", "role": UserRole.OWNER, "password1": self.password, "password2": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="forged-owner").exists())

    def test_teacher_account_has_profile_but_owner_and_admin_do_not(self):
        self.assertTrue(hasattr(self.teacher, "teacher_profile"))
        self.assertFalse(hasattr(self.owner, "teacher_profile"))
        self.assertFalse(hasattr(self.admin, "teacher_profile"))

    def test_owner_creating_teacher_account_populates_teacher_profile(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("accounts:user-create"),
            {"username": "new-teacher", "role": UserRole.TEACHER, "teacher_full_name": "Новый Преподаватель", "teacher_phone": "900123456", "password1": self.password, "password2": self.password},
        )
        self.assertRedirects(response, reverse("accounts:user-list"))
        self.assertEqual(User.objects.get(username="new-teacher").teacher_profile.full_name, "Новый Преподаватель")
