from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class RecordStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Активен")
    ARCHIVED = "ARCHIVED", _("В архиве")


class Student(models.Model):
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    status = models.CharField(max_length=16, choices=RecordStatus.choices, default=RecordStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("full_name",)

    def clean(self) -> None:
        if not self.full_name.strip():
            raise ValidationError({"full_name": "Укажите ФИО ученика."})

    def __str__(self) -> str:
        return self.full_name


class Teacher(models.Model):
    """Teacher account profile and contact record."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="teacher_profile")
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    status = models.CharField(max_length=16, choices=RecordStatus.choices, default=RecordStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.full_name or self.user.get_full_name() or self.user.username


class Course(models.Model):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=RecordStatus.choices, default=RecordStatus.ACTIVE, db_index=True)
    default_monthly_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Group(models.Model):
    name = models.CharField(max_length=150)
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="groups")
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, related_name="groups")
    monthly_fee = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=16, choices=RecordStatus.choices, default=RecordStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class EnrollmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Активно")
    ENDED = "ENDED", _("Завершено")


class Enrollment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="enrollments")
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="enrollments")
    started_at = models.DateField()
    ended_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-started_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("student", "group"),
                condition=Q(status=EnrollmentStatus.ACTIVE),
                name="unique_active_enrollment_per_student_group",
            ),
            models.CheckConstraint(
                check=(Q(status=EnrollmentStatus.ACTIVE, ended_at__isnull=True) | Q(status=EnrollmentStatus.ENDED, ended_at__isnull=False)),
                name="enrollment_status_matches_end_date",
            ),
            models.CheckConstraint(
                check=Q(ended_at__isnull=True) | Q(ended_at__gte=models.F("started_at")),
                name="enrollment_end_not_before_start",
            ),
        ]

    def clean(self) -> None:
        errors = {}
        if self.status == EnrollmentStatus.ACTIVE and self.ended_at is not None:
            errors["ended_at"] = "Для активного зачисления дата окончания должна быть пустой."
        if self.status == EnrollmentStatus.ENDED and self.ended_at is None:
            errors["ended_at"] = "Укажите дату окончания обучения."
        if self.ended_at and self.ended_at < self.started_at:
            errors["ended_at"] = "Дата окончания не может быть раньше даты начала."
        if self.status == EnrollmentStatus.ACTIVE and self.student_id and self.group_id:
            duplicate_exists = Enrollment.objects.filter(student=self.student, group=self.group, status=EnrollmentStatus.ACTIVE).exclude(pk=self.pk).exists()
            if duplicate_exists:
                errors["student"] = "Ученик уже активно зачислен в эту группу."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.student} — {self.group}"


class Schedule(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, _("Понедельник")
        TUESDAY = 1, _("Вторник")
        WEDNESDAY = 2, _("Среда")
        THURSDAY = 3, _("Четверг")
        FRIDAY = 4, _("Пятница")
        SATURDAY = 5, _("Суббота")
        SUNDAY = 6, _("Воскресенье")

    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="schedules", db_index=True)
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices, db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("weekday", "start_time")

    def clean(self) -> None:
        errors = {}
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = "Время окончания должно быть позже времени начала."
        if self.start_date and self.end_date and self.start_date > self.end_date:
            errors["end_date"] = "Дата окончания периода не может быть раньше даты начала."
        if self.is_active and self.group_id and self.weekday is not None and self.start_time and self.end_time:
            conflicts = Schedule.objects.filter(group__teacher=self.group.teacher, weekday=self.weekday, is_active=True, start_time__lt=self.end_time, end_time__gt=self.start_time).exclude(pk=self.pk)
            if conflicts.exists():
                errors["start_time"] = "Расписание пересекается с другим занятием этого преподавателя."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.group}: {self.get_weekday_display()} {self.start_time}–{self.end_time}"


class OverrideType(models.TextChoices):
    CANCELLED = "CANCELLED", _("Отменено")
    RESCHEDULED = "RESCHEDULED", _("Перенесено")
    SUBSTITUTE = "SUBSTITUTE", _("Замена преподавателя")


class ScheduleOverride(models.Model):
    """Specific date exception for a Schedule rule.

    One Schedule can have multiple overrides, but only one per date.
    When an override exists for a date, it replaces the normal schedule
    behavior for that single occurrence.
    """

    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="overrides", db_index=True)
    date = models.DateField(db_index=True)
    override_type = models.CharField(max_length=16, choices=OverrideType.choices, db_index=True)

    # For RESCHEDULED: new date/time
    new_date = models.DateField(null=True, blank=True)
    new_start_time = models.TimeField(null=True, blank=True)
    new_end_time = models.TimeField(null=True, blank=True)

    # For SUBSTITUTE: temporary teacher replacement
    substitute_teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, null=True, blank=True, related_name="substitute_overrides")

    reason = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("date",)
        constraints = [
            models.UniqueConstraint(fields=("schedule", "date"), name="unique_override_per_schedule_date"),
        ]

    def clean(self) -> None:
        errors = {}
        if self.override_type == OverrideType.RESCHEDULED:
            if not self.new_date:
                errors["new_date"] = "Укажите новую дату для переноса."
            if not self.new_start_time or not self.new_end_time:
                errors["new_start_time"] = "Укажите новое время."
            if self.new_start_time and self.new_end_time and self.new_start_time >= self.new_end_time:
                errors["new_end_time"] = "Время окончания должно быть позже времени начала."
        if self.override_type == OverrideType.SUBSTITUTE:
            if not self.substitute_teacher_id:
                errors["substitute_teacher"] = "Укажите заменяющего преподавателя."
            elif self.schedule_id and self.substitute_teacher_id == self.schedule.group.teacher_id:
                errors["substitute_teacher"] = "Замена должна быть другим преподавателем."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.schedule.group}: {self.date} — {self.get_override_type_display()}"


class LessonStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", _("Запланировано")
    COMPLETED = "COMPLETED", _("Завершено")
    CANCELLED = "CANCELLED", _("Отменено")


class Lesson(models.Model):
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="lessons", db_index=True)
    date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(max_length=16, choices=LessonStatus.choices, default=LessonStatus.SCHEDULED, db_index=True)
    schedule = models.ForeignKey(Schedule, on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons")
    occurrence_date = models.DateField(null=True, blank=True, db_index=True)
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_lessons",
    )
    source = models.CharField(max_length=16, choices=[("NORMAL", "Расписание"), ("OVERRIDE", "Исключение")], default="NORMAL", db_index=True)
    topic = models.CharField(max_length=255, blank=True)
    teacher_note = models.TextField(blank=True)
    homework = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("date", "start_time")
        constraints = [
            models.UniqueConstraint(fields=("group", "date", "start_time"), name="unique_lesson_group_date_time"),
            models.UniqueConstraint(
                fields=("schedule", "occurrence_date"),
                condition=Q(schedule__isnull=False, occurrence_date__isnull=False),
                name="unique_lesson_schedule_occurrence",
            ),
        ]

    def clean(self) -> None:
        errors = {}
        if self.schedule_id and self.group_id and self.schedule.group_id != self.group_id:
            errors["schedule"] = "Расписание должно принадлежать группе занятия."
        if self.schedule_id and self.occurrence_date is None:
            self.occurrence_date = self.date
        if self.group_id and self.teacher_id is None:
            self.teacher = self.group.teacher
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = "Время окончания должно быть позже времени начала."
        if self.status != LessonStatus.CANCELLED and self.group_id and self.date and self.start_time and self.end_time:
            teacher_id = self.teacher_id or self.group.teacher_id
            conflicts = Lesson.objects.filter(date=self.date).exclude(status=LessonStatus.CANCELLED).filter(
                Q(teacher_id=teacher_id) | Q(teacher__isnull=True, group__teacher_id=teacher_id),
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            ).exclude(pk=self.pk)
            if conflicts.exists():
                errors["start_time"] = "Занятие пересекается с другим занятием этого преподавателя."
            group_conflicts = Lesson.objects.filter(
                group_id=self.group_id,
                date=self.date,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            ).exclude(status=LessonStatus.CANCELLED).exclude(pk=self.pk)
            if group_conflicts.exists():
                errors["start_time"] = "Занятие пересекается с другим занятием этой группы."
        if errors:
            raise ValidationError(errors)

    def active_students(self):
        return Student.objects.filter(
            enrollments__group=self.group,
            enrollments__started_at__lte=self.date,
        ).filter(
            Q(enrollments__ended_at__isnull=True) | Q(enrollments__ended_at__gte=self.date)
        ).distinct()

    @property
    def effective_teacher(self):
        return self.teacher or self.group.teacher

    def __str__(self) -> str:
        return f"{self.group} — {self.date} {self.start_time}"


class AttendanceStatus(models.TextChoices):
    PRESENT = "PRESENT", _("Присутствовал")
    ABSENT = "ABSENT", _("Отсутствовал")
    LATE = "LATE", _("Опоздал")


class Attendance(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT, related_name="attendance_records", db_index=True)
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="attendance_records", db_index=True)
    status = models.CharField(max_length=16, choices=AttendanceStatus.choices, db_index=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("student__full_name",)
        constraints = [models.UniqueConstraint(fields=("lesson", "student"), name="unique_attendance_per_lesson_student")]

    def clean(self) -> None:
        errors = {}
        if self.lesson_id and self.lesson.status == LessonStatus.CANCELLED:
            errors["lesson"] = "Нельзя изменять посещаемость отменённого занятия."
        # Only creation checks membership on the lesson date. Existing records are history.
        if not self.pk and self.lesson_id and self.student_id:
            eligible = Enrollment.objects.filter(
                student=self.student,
                group=self.lesson.group,
                started_at__lte=self.lesson.date,
            ).filter(
                Q(ended_at__isnull=True) | Q(ended_at__gte=self.lesson.date)
            ).exists()
            if not eligible:
                errors["student"] = "Ученик не имеет активного зачисления в группу занятия."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.lesson}: {self.student}"


class PaymentStatus(models.TextChoices):
    PAID = "PAID", _("Оплачено")
    CANCELLED = "CANCELLED", _("Отменён")


class Payment(models.Model):
    """Payment tied to a student and a group via its enrollment history."""

    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="payments", db_index=True)
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="payments", db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    paid_at = models.DateField(db_index=True)
    period = models.DateField(db_index=True)
    status = models.CharField(max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PAID, db_index=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-paid_at", "-pk")
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def clean(self) -> None:
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Сумма должна быть больше нуля."
        if self.student_id and self.group_id and not Enrollment.objects.filter(student=self.student, group=self.group).exists():
            errors["student"] = "Ученик не был связан с этой группой через зачисление."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.student}: {self.amount} ({self.period:%m.%Y})"


class AuditAction(models.TextChoices):
    PAYMENT_CREATE = "PAYMENT_CREATE", _("Создание платежа")
    PAYMENT_EDIT = "PAYMENT_EDIT", _("Изменение платежа")
    PAYMENT_CANCEL = "PAYMENT_CANCEL", _("Отмена платежа")
    ATTENDANCE_CHANGE = "ATTENDANCE_CHANGE", _("Изменение посещаемости")
    ENROLLMENT_CREATE = "ENROLLMENT_CREATE", _("Зачисление ученика")
    ENROLLMENT_END = "ENROLLMENT_END", _("Завершение обучения")
    STUDENT_CREATE = "STUDENT_CREATE", _("Создание ученика")
    STUDENT_ARCHIVE = "STUDENT_ARCHIVE", _("Архивация ученика")
    STUDENT_RESTORE = "STUDENT_RESTORE", _("Восстановление ученика")
    LESSON_CREATE = "LESSON_CREATE", _("Создание занятия")
    LESSON_EDIT = "LESSON_EDIT", _("Изменение занятия")
    LESSON_CANCEL = "LESSON_CANCEL", _("Отмена занятия")
    LESSON_COMPLETE = "LESSON_COMPLETE", _("Завершение занятия")
    LESSON_RESCHEDULE = "LESSON_RESCHEDULE", _("Перенос занятия")
    LESSON_REPORT = "LESSON_REPORT", _("Отчёт о занятии")
    SCHEDULE_CREATE = "SCHEDULE_CREATE", _("Создание расписания")
    SCHEDULE_EDIT = "SCHEDULE_EDIT", _("Изменение расписания")
    SCHEDULE_DEACTIVATE = "SCHEDULE_DEACTIVATE", _("Деактивация расписания")
    SCHEDULE_GENERATE = "SCHEDULE_GENERATE", _("Генерация занятий")
    OVERRIDE_CREATE = "OVERRIDE_CREATE", _("Создание исключения расписания")
    OVERRIDE_EDIT = "OVERRIDE_EDIT", _("Изменение исключения расписания")
    OVERRIDE_DELETE = "OVERRIDE_DELETE", _("Удаление исключения расписания")
    COURSE_CREATE = "COURSE_CREATE", _("Создание курса")
    COURSE_EDIT = "COURSE_EDIT", _("Изменение курса")
    COURSE_STATUS = "COURSE_STATUS", _("Изменение статуса курса")
    GROUP_CREATE = "GROUP_CREATE", _("Создание группы")
    GROUP_EDIT = "GROUP_EDIT", _("Изменение группы")
    GROUP_STATUS = "GROUP_STATUS", _("Изменение статуса группы")
    TEACHER_EDIT = "TEACHER_EDIT", _("Изменение преподавателя")
    TEACHER_STATUS = "TEACHER_STATUS", _("Изменение статуса преподавателя")


class AuditLog(models.Model):
    """Append-only journal for sensitive operations. Never stores credentials."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="audit_logs")
    action = models.CharField(max_length=32, choices=AuditAction.choices, db_index=True)
    target_type = models.CharField(max_length=32, db_index=True)
    target_id = models.PositiveBigIntegerField(db_index=True)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Записи журнала аудита нельзя изменять.")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_action_display()} — {self.target_type} #{self.target_id}"
