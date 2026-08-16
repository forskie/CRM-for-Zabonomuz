from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import User, UserRole

from .models import Teacher


@receiver(post_save, sender=User)
def create_teacher_profile(sender, instance: User, created: bool, **kwargs) -> None:
    """Only TEACHER accounts receive a profile; OWNER and ADMIN never do."""
    if instance.role == UserRole.TEACHER:
        Teacher.objects.get_or_create(user=instance)
