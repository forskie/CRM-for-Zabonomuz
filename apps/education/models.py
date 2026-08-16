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
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("weekday", "start_time")

    def clean(self) -> None:
        errors = {}
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = "Время окончания должно быть позже времени начала."
        if self.is_active and self.group_id and self.weekday is not None and self.start_time and self.end_time:
            conflicts = Schedule.objects.filter(group__teacher=self.group.teacher, weekday=self.weekday, is_active=True, start_time__lt=self.end_time, end_time__gt=self.start_time).exclude(pk=self.pk)
            if conflicts.exists():
                errors["start_time"] = "Расписание пересекается с другим занятием этого преподавателя."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.group}: {self.get_weekday_display()} {self.start_time}–{self.end_time}"


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("date", "start_time")

    def clean(self) -> None:
        errors = {}
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = "Время окончания должно быть позже времени начала."
        if self.status != LessonStatus.CANCELLED and self.group_id and self.date and self.start_time and self.end_time:
            conflicts = Lesson.objects.filter(group__teacher=self.group.teacher, date=self.date).exclude(status=LessonStatus.CANCELLED).filter(start_time__lt=self.end_time, end_time__gt=self.start_time).exclude(pk=self.pk)
            if conflicts.exists():
                errors["start_time"] = "Занятие пересекается с другим занятием этого преподавателя."
        if errors:
            raise ValidationError(errors)

    def active_students(self):
        return Student.objects.filter(enrollments__group=self.group, enrollments__status=EnrollmentStatus.ACTIVE).distinct()

    def __str__(self) -> str:
        return f"{self.group} — {self.date} {self.start_time}"


class AttendanceStatus(models.TextChoices):
    PRESENT = "PRESENT", _("Присутствовал")
    ABSENT = "ABSENT", _("Отсутствовал")
    EXCUSED = "EXCUSED", _("Уважительная причина")


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
        # Only creation depends on the current active enrollment. Existing records are history.
        if not self.pk and self.lesson_id and self.student_id:
            eligible = Enrollment.objects.filter(student=self.student, group=self.lesson.group, status=EnrollmentStatus.ACTIVE).exists()
            if not eligible:
                errors["student"] = "Ученик не имеет активного зачисления в группу занятия."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.lesson}: {self.student}"
