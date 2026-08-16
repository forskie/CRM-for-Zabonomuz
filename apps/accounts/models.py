from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class UserRole(models.TextChoices):
    OWNER = "OWNER", "Владелец"
    ADMIN = "ADMIN", "Администратор"
    TEACHER = "TEACHER", "Преподаватель"


class User(AbstractUser):
    """Internal CRM account using Django's standard password hashing."""

    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.TEACHER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    class Meta:
        ordering = ("username",)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = UserRole.OWNER
        super().save(*args, **kwargs)

    @property
    def is_owner(self) -> bool:
        return self.role == UserRole.OWNER
