from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CRMUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("CRM", {"fields": ("role", "created_at", "updated_at")} ),)
    readonly_fields = ("created_at", "updated_at")
    list_display = ("username", "email", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff")
