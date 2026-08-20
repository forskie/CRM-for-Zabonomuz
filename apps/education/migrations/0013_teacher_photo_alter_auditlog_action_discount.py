import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("education", "0012_stage17_occurrence_teacher")]

    operations = [
        migrations.AddField(
            model_name="teacher",
            name="photo",
            field=models.ImageField(blank=True, upload_to="teachers/%Y/%m/"),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(choices=[("STUDENT_TRANSFER", "Перевод ученика"), ("DISCOUNT_CREATE", "Создание скидки"), ("DISCOUNT_EDIT", "Изменение скидки"), ("PAYMENT_CREATE", "Создание платежа"), ("PAYMENT_EDIT", "Изменение платежа"), ("PAYMENT_CANCEL", "Отмена платежа"), ("ATTENDANCE_CHANGE", "Изменение посещаемости"), ("ENROLLMENT_CREATE", "Зачисление ученика"), ("ENROLLMENT_END", "Завершение обучения"), ("STUDENT_CREATE", "Создание ученика"), ("STUDENT_ARCHIVE", "Архивация ученика"), ("STUDENT_RESTORE", "Восстановление ученика"), ("LESSON_CREATE", "Создание занятия"), ("LESSON_EDIT", "Изменение занятия"), ("LESSON_CANCEL", "Отмена занятия"), ("LESSON_COMPLETE", "Завершение занятия"), ("LESSON_RESCHEDULE", "Перенос занятия"), ("LESSON_REPORT", "Отчёт о занятии"), ("SCHEDULE_CREATE", "Создание расписания"), ("SCHEDULE_EDIT", "Изменение расписания"), ("SCHEDULE_DEACTIVATE", "Деактивация расписания"), ("SCHEDULE_GENERATE", "Генерация занятий"), ("OVERRIDE_CREATE", "Создание исключения расписания"), ("OVERRIDE_EDIT", "Изменение исключения расписания"), ("OVERRIDE_DELETE", "Удаление исключения расписания"), ("COURSE_CREATE", "Создание курса"), ("COURSE_EDIT", "Изменение курса"), ("COURSE_STATUS", "Изменение статуса курса"), ("GROUP_CREATE", "Создание группы"), ("GROUP_EDIT", "Изменение группы"), ("GROUP_STATUS", "Изменение статуса группы"), ("TEACHER_EDIT", "Изменение преподавателя"), ("TEACHER_STATUS", "Изменение статуса преподавателя")], db_index=True, max_length=32),
        ),
        migrations.CreateModel(
            name="Discount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150)),
                ("percentage", models.DecimalField(decimal_places=2, max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("starts_at", models.DateField(default=django.utils.timezone.localdate)),
                ("ends_at", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("group", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="discounts", to="education.group")),
                ("student", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="discounts", to="education.student")),
            ],
            options={"ordering": ("-is_active", "-starts_at", "name")},
        ),
    ]
