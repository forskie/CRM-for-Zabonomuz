from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase, Client
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


class CRMUserCreationLoginTests(TestCase):
    password = "CrmTest2026!"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)

    def _crm_create(self, data):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:user-create"), data)
        self.assertRedirects(response, reverse("accounts:user-list"))
        self.client.logout()

    def test_admin_created_via_form_can_authenticate(self):
        self._crm_create({"username": "crm-admin", "role": UserRole.ADMIN, "password1": self.password, "password2": self.password})
        user = User.objects.get(username="crm-admin")
        self.assertTrue(user.has_usable_password())
        self.assertTrue(user.check_password(self.password))
        self.assertIsNotNone(authenticate(username="crm-admin", password=self.password))

    def test_admin_created_via_form_can_login_via_endpoint(self):
        self._crm_create({"username": "crm-admin", "role": UserRole.ADMIN, "password1": self.password, "password2": self.password})
        response = self.client.post(reverse("accounts:login"), {"username": "crm-admin", "password": self.password})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_teacher_created_via_form_can_authenticate(self):
        self._crm_create({
            "username": "crm-teacher", "role": UserRole.TEACHER,
            "teacher_full_name": "Тестовый Преподаватель", "teacher_phone": "+992900111",
            "password1": self.password, "password2": self.password,
        })
        user = User.objects.get(username="crm-teacher")
        self.assertTrue(user.has_usable_password())
        self.assertTrue(user.check_password(self.password))
        self.assertIsNotNone(authenticate(username="crm-teacher", password=self.password))
        self.assertTrue(hasattr(user, "teacher_profile"))

    def test_teacher_created_via_form_can_login_via_endpoint(self):
        self._crm_create({
            "username": "crm-teacher", "role": UserRole.TEACHER,
            "teacher_full_name": "Тестовый Преподаватель", "teacher_phone": "+992900111",
            "password1": self.password, "password2": self.password,
        })
        response = self.client.post(reverse("accounts:login"), {"username": "crm-teacher", "password": self.password})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_password_rejected_for_form_created_user(self):
        self._crm_create({"username": "crm-admin", "role": UserRole.ADMIN, "password1": self.password, "password2": self.password})
        response = self.client.post(reverse("accounts:login"), {"username": "crm-admin", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_form_created_user_cannot_login(self):
        self._crm_create({"username": "crm-admin", "role": UserRole.ADMIN, "password1": self.password, "password2": self.password})
        user = User.objects.get(username="crm-admin")
        user.is_active = False
        user.save()
        response = self.client.post(reverse("accounts:login"), {"username": "crm-admin", "password": self.password})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_owner_admin_teacher_authentication_still_works(self):
        admin = User.objects.create_user("existing-admin", password=self.password, role=UserRole.ADMIN)
        teacher = User.objects.create_user("existing-teacher", password=self.password, role=UserRole.TEACHER)
        for uname in ["owner", "existing-admin", "existing-teacher"]:
            self.client.logout()
            resp = self.client.post(reverse("accounts:login"), {"username": uname, "password": self.password})
            self.assertRedirects(resp, reverse("dashboard"), msg_prefix=f"Login failed for {uname}")
            self.assertIn("_auth_user_id", self.client.session)

    def test_password_hash_algorithm_is_pbkdf2(self):
        self._crm_create({"username": "crm-admin", "role": UserRole.ADMIN, "password1": self.password, "password2": self.password})
        user = User.objects.get(username="crm-admin")
        self.assertTrue(user.password.startswith("pbkdf2_"))

    def test_form_created_user_is_active(self):
        self._crm_create({"username": "crm-admin", "role": UserRole.ADMIN, "password1": self.password, "password2": self.password})
        user = User.objects.get(username="crm-admin")
        self.assertTrue(user.is_active)
