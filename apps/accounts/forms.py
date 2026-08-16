from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import User, UserRole


MANAGEABLE_ROLES = [(UserRole.ADMIN, UserRole.ADMIN.label), (UserRole.TEACHER, UserRole.TEACHER.label)]


class ManagedUserCreateForm(UserCreationForm):
    role = forms.ChoiceField(choices=MANAGEABLE_ROLES, label="Роль")
    teacher_full_name = forms.CharField(max_length=255, required=False, label="ФИО преподавателя")
    teacher_phone = forms.CharField(max_length=32, required=False, label="Телефон преподавателя")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "role")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("role") == UserRole.TEACHER and not cleaned_data.get("teacher_full_name", "").strip():
            self.add_error("teacher_full_name", "Укажите ФИО преподавателя.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.role == UserRole.TEACHER:
            teacher = user.teacher_profile
            teacher.full_name = self.cleaned_data["teacher_full_name"].strip()
            teacher.phone = self.cleaned_data["teacher_phone"].strip()
            teacher.save(update_fields=("full_name", "phone", "updated_at"))
        return user


class ManagedUserUpdateForm(forms.ModelForm):
    role = forms.ChoiceField(choices=MANAGEABLE_ROLES, label="Роль")
    teacher_full_name = forms.CharField(max_length=255, required=False, label="ФИО преподавателя")
    teacher_phone = forms.CharField(max_length=32, required=False, label="Телефон преподавателя")

    class Meta:
        model = User
        fields = ("role", "is_active")
        labels = {"is_active": "Активен"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.role == UserRole.TEACHER:
            # A teacher profile may later have attendance and group history.
            # Its conversion needs a dedicated, audited business operation.
            self.fields["role"].choices = [(UserRole.TEACHER, UserRole.TEACHER.label)]
            self.fields["teacher_full_name"].initial = self.instance.teacher_profile.full_name
            self.fields["teacher_phone"].initial = self.instance.teacher_profile.phone

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("role") == UserRole.TEACHER and not cleaned_data.get("teacher_full_name", "").strip():
            self.add_error("teacher_full_name", "Укажите ФИО преподавателя.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.role == UserRole.TEACHER:
            teacher = user.teacher_profile
            teacher.full_name = self.cleaned_data["teacher_full_name"].strip()
            teacher.phone = self.cleaned_data["teacher_phone"].strip()
            teacher.save(update_fields=("full_name", "phone", "updated_at"))
        return user
