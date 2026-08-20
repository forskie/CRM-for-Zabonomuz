import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import UserRole

from .models import Attendance, AttendanceStatus, Course, Discount, Enrollment, EnrollmentStatus, Group, Lesson, LessonStatus, OverrideType, Payment, PaymentStatus, Schedule, ScheduleOverride, Student, Teacher


PHONE_PATTERN = re.compile(r"^[0-9+()\-\s]{5,32}$")


class PhoneValidationMixin:
    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if phone and not PHONE_PATTERN.fullmatch(phone):
            raise ValidationError("Введите корректный номер телефона.")
        return phone


class StudentForm(PhoneValidationMixin, forms.ModelForm):
    class Meta:
        model = Student
        fields = ("full_name", "phone")
        labels = {"full_name": "ФИО", "phone": "Телефон"}


class TeacherForm(PhoneValidationMixin, forms.ModelForm):
    class Meta:
        model = Teacher
        fields = ("full_name", "phone", "photo")
        labels = {"full_name": "ФИО", "phone": "Телефон", "photo": "Фото лица"}
        widgets = {"photo": forms.ClearableFileInput(attrs={"accept": "image/*"})}

    def clean_full_name(self):
        full_name = self.cleaned_data["full_name"].strip()
        if not full_name:
            raise ValidationError("Укажите ФИО преподавателя.")
        return full_name


class TeacherCreateForm(PhoneValidationMixin, UserCreationForm):
    full_name = forms.CharField(max_length=255, label="ФИО")
    phone = forms.CharField(max_length=32, required=False, label="Телефон")
    photo = forms.ImageField(required=False, label="Фото лица", widget=forms.ClearableFileInput(attrs={"accept": "image/*"}))

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = UserRole.TEACHER
        if commit:
            user.save()
            teacher = user.teacher_profile
            teacher.full_name = self.cleaned_data["full_name"]
            teacher.phone = self.cleaned_data["phone"]
            teacher.photo = self.cleaned_data.get("photo")
            teacher.save()
        return user.teacher_profile


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ("name", "description", "default_monthly_fee")
        labels = {"name": "Название", "description": "Описание", "default_monthly_fee": "Стоимость в месяц (TJS)"}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise ValidationError("Укажите название курса.")
        return name


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ("name", "course", "teacher", "monthly_fee")
        labels = {"name": "Название", "course": "Курс", "teacher": "Преподаватель", "monthly_fee": "Стоимость в месяц (TJS)"}

    class Media:
        js = ("js/group_form.js",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        courses = Course.objects.filter(status="ACTIVE")
        teachers = Teacher.objects.filter(status="ACTIVE")
        if self.instance.pk:
            courses = Course.objects.filter(Q(status="ACTIVE") | Q(pk=self.instance.course_id))
            teachers = Teacher.objects.filter(Q(status="ACTIVE") | Q(pk=self.instance.teacher_id))
        self.fields["course"].queryset = courses
        self.fields["teacher"].queryset = teachers
        if not self.instance.pk:
            fee_choices = {str(c.pk): str(c.default_monthly_fee) for c in courses}
            self.fields["course"].widget.attrs["data-fee-choices"] = ",".join(f"{k}:{v}" for k, v in fee_choices.items())


class EnrollmentCreateForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ("student", "started_at")
        widgets = {"started_at": forms.DateInput(attrs={"type": "date"})}
        labels = {"student": "Ученик", "started_at": "Дата начала"}

    def __init__(self, *args, group: Group, **kwargs):
        super().__init__(*args, **kwargs)
        self.group = group
        self.fields["student"].queryset = Student.objects.filter(status="ACTIVE")

    def clean(self):
        cleaned_data = super().clean()
        student = cleaned_data.get("student")
        if student and Enrollment.objects.filter(student=student, group=self.group, status=EnrollmentStatus.ACTIVE).exists():
            raise ValidationError("Этот ученик уже активно зачислен в группу.")
        return cleaned_data

    def save(self, commit=True):
        enrollment = super().save(commit=False)
        enrollment.group = self.group
        enrollment.status = EnrollmentStatus.ACTIVE
        enrollment.ended_at = None
        if commit:
            enrollment.save()
        return enrollment


class EnrollmentEndForm(forms.Form):
    ended_at = forms.DateField(label="Дата окончания", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, enrollment: Enrollment, **kwargs):
        super().__init__(*args, **kwargs)
        self.enrollment = enrollment

    def clean_ended_at(self):
        ended_at = self.cleaned_data["ended_at"]
        if ended_at < self.enrollment.started_at:
            raise ValidationError("Дата окончания не может быть раньше даты начала.")
        return ended_at


class ScheduleForm(forms.ModelForm):
    class Meta:
        model = Schedule
        fields = ("weekday", "start_time", "end_time", "start_date", "end_date", "is_active")
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {"start_date": "Период: с", "end_date": "Период: по"}

    def __init__(self, *args, group: Group, **kwargs):
        super().__init__(*args, **kwargs)
        self.group = group

    def save(self, commit=True):
        schedule = super().save(commit=False)
        schedule.group = self.group
        if commit:
            schedule.full_clean()
            schedule.save()
        return schedule

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_time"), cleaned.get("end_time")
        if start and end and start >= end:
            self.add_error("end_time", "Время окончания должно быть позже времени начала.")
        start_date, end_date = cleaned.get("start_date"), cleaned.get("end_date")
        if start_date and end_date and start_date > end_date:
            self.add_error("end_date", "Дата окончания периода не может быть раньше даты начала.")
        if cleaned.get("is_active") and start and end and cleaned.get("weekday") is not None:
            conflicts = Schedule.objects.filter(group__teacher=self.group.teacher, weekday=cleaned["weekday"], is_active=True, start_time__lt=end, end_time__gt=start).exclude(pk=self.instance.pk)
            if conflicts.exists():
                self.add_error("start_time", "Расписание пересекается с другим занятием этого преподавателя.")
        return cleaned


class ScheduleGenerateForm(forms.Form):
    date_from = forms.DateField(label="Дата начала", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label="Дата окончания", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            self.add_error("date_to", "Дата окончания не может быть раньше даты начала.")
        return cleaned


class LessonRescheduleForm(forms.Form):
    date = forms.DateField(label="Новая дата", widget=forms.DateInput(attrs={"type": "date"}))
    start_time = forms.TimeField(label="Новое время начала", widget=forms.TimeInput(attrs={"type": "time"}))
    end_time = forms.TimeField(label="Новое время окончания", widget=forms.TimeInput(attrs={"type": "time"}))

    def __init__(self, *args, lesson: Lesson, **kwargs):
        super().__init__(*args, **kwargs)
        self.lesson = lesson
        if not kwargs.get("data") and not kwargs.get("files"):
            self.initial["date"] = lesson.date
            self.initial["start_time"] = lesson.start_time
            self.initial["end_time"] = lesson.end_time

    def clean(self):
        cleaned = super().clean()
        lesson = self.lesson
        lesson_date = cleaned.get("date")
        start, end = cleaned.get("start_time"), cleaned.get("end_time")
        if start and end and start >= end:
            self.add_error("end_time", "Время окончания должно быть позже времени начала.")
        if lesson.status == LessonStatus.CANCELLED:
            self.add_error(None, "Нельзя переносить отменённое занятие.")
        if lesson_date and start and end:
            if Lesson.objects.filter(group=lesson.group, date=lesson_date, start_time=start).exclude(pk=lesson.pk).exists():
                self.add_error("start_time", "В этот день в это время уже есть занятие этой группы.")
            probe = Lesson(group=lesson.group, schedule=lesson.schedule, teacher=lesson.teacher, date=lesson_date, start_time=start, end_time=end, status=lesson.status)
            try:
                probe.full_clean()
            except ValidationError as exc:
                for field, errors in exc.message_dict.items():
                    self.add_error(field if field in ("start_time", "end_time", "date") else None, errors[0])
        return cleaned


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ("group", "date", "start_time", "end_time", "schedule")
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "start_time": forms.TimeInput(attrs={"type": "time"}), "end_time": forms.TimeInput(attrs={"type": "time"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = Group.objects.filter(status="ACTIVE")
        self.fields["schedule"].queryset = Schedule.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        schedule = cleaned.get("schedule")
        group = cleaned.get("group")
        if schedule and group and schedule.group_id != group.id:
            self.add_error("schedule", "Расписание должно принадлежать выбранной группе.")
        start, end, lesson_date = cleaned.get("start_time"), cleaned.get("end_time"), cleaned.get("date")
        if start and end and start >= end:
            self.add_error("end_time", "Время окончания должно быть позже времени начала.")
        if group and lesson_date and start and end:
            conflicts = Lesson.objects.filter(date=lesson_date).exclude(status=LessonStatus.CANCELLED).filter(
                Q(teacher=group.teacher) | Q(teacher__isnull=True, group__teacher=group.teacher),
                start_time__lt=end,
                end_time__gt=start,
            ).exclude(pk=self.instance.pk)
            if conflicts.exists():
                self.add_error("start_time", "Занятие пересекается с другим занятием этого преподавателя.")
            if Lesson.objects.filter(group=group, date=lesson_date, start_time=start).exclude(pk=self.instance.pk).exists():
                self.add_error("start_time", "В этот день в это время уже есть занятие этой группы.")
        return cleaned


class LessonReportForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ("topic", "teacher_note", "homework")
        labels = {
            "topic": "Тема занятия",
            "teacher_note": "Заметка преподавателя",
            "homework": "Домашнее задание",
        }
        widgets = {
            "topic": forms.TextInput(attrs={"placeholder": "Например: Present Perfect"}),
            "teacher_note": forms.Textarea(attrs={"rows": 3, "placeholder": "Как прошло занятие, сложности учеников"}),
            "homework": forms.Textarea(attrs={"rows": 3, "placeholder": "Например: Exercises 4–6"}),
        }


class LessonFromScheduleForm(forms.Form):
    date = forms.DateField(label="Дата", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, schedule: Schedule, **kwargs):
        super().__init__(*args, **kwargs)
        self.schedule = schedule

    def clean(self):
        cleaned = super().clean()
        lesson_date = cleaned.get("date")
        schedule = self.schedule
        if lesson_date:
            if Lesson.objects.filter(group=schedule.group, date=lesson_date, start_time=schedule.start_time).exists():
                self.add_error("date", "В этот день в это время уже есть занятие этой группы.")
            probe = Lesson(group=schedule.group, schedule=schedule, date=lesson_date, start_time=schedule.start_time, end_time=schedule.end_time)
            try:
                probe.full_clean()
            except ValidationError as exc:
                for errors in exc.message_dict.values():
                    self.add_error(None, errors[0])
        return cleaned

    def save(self):
        lesson = Lesson(
            group=self.schedule.group,
            schedule=self.schedule,
            occurrence_date=self.cleaned_data["date"],
            teacher=self.schedule.group.teacher,
            date=self.cleaned_data["date"],
            start_time=self.schedule.start_time,
            end_time=self.schedule.end_time,
        )
        lesson.full_clean()
        lesson.save()
        return lesson


class AttendanceBulkForm(forms.Form):
    """One server-defined field pair per eligible student; client ids are never trusted."""

    def __init__(self, *args, lesson: Lesson, teacher_mode=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.lesson = lesson
        self.teacher_mode = teacher_mode
        active_students = lesson.active_students()
        existing = Attendance.objects.filter(lesson=lesson).select_related("student")
        students = {student.pk: student for student in active_students}
        students.update({record.student_id: record.student for record in existing})
        self.students = students
        records = {record.student_id: record for record in existing}
        for student_id, student in sorted(students.items(), key=lambda item: item[1].full_name):
            record = records.get(student_id)
            self.fields[f"status_{student_id}"] = forms.ChoiceField(
                choices=[("", "Не отмечено")] + ([(AttendanceStatus.PRESENT, "Был"), (AttendanceStatus.ABSENT, "Не был")] if teacher_mode else list(AttendanceStatus.choices)),
                required=False,
                initial=record.status if record else "",
                label=student.full_name,
                widget=forms.Select(attrs={"class": "attendance-status"}),
            )
            if not teacher_mode:
                self.fields[f"note_{student_id}"] = forms.CharField(
                required=False,
                initial=record.note if record else "",
                    label="Примечание",
                    widget=forms.TextInput(attrs={"class": "attendance-note"}),
                )

    def rows(self):
        """Yield (student, status_field, note_field) triplets for a table layout."""
        for student_id, student in sorted(self.students.items(), key=lambda item: item[1].full_name):
            yield (student, self[f"status_{student_id}"], None if self.teacher_mode else self[f"note_{student_id}"])

    def save(self):
        if self.lesson.status == LessonStatus.CANCELLED:
            raise ValidationError("Нельзя изменять посещаемость отменённого занятия.")
        for student_id, student in self.students.items():
            status = self.cleaned_data[f"status_{student_id}"]
            if not status:
                continue
            note = "" if self.teacher_mode else self.cleaned_data[f"note_{student_id}"]
            record, created = Attendance.objects.get_or_create(lesson=self.lesson, student=student, defaults={"status": status, "note": note})
            if not created:
                record.status = status
                if not self.teacher_mode:
                    record.note = note
                record.full_clean()
                record.save(update_fields=("status", "note", "updated_at"))


class StudentTransferForm(forms.Form):
    enrollment = forms.ModelChoiceField(queryset=Enrollment.objects.none(), label="Текущая группа")
    target_group = forms.ModelChoiceField(queryset=Group.objects.none(), label="Новая группа")
    transfer_date = forms.DateField(label="Дата перевода", widget=forms.DateInput(attrs={"type": "date"}), initial=timezone.localdate)

    def __init__(self, *args, student: Student, **kwargs):
        super().__init__(*args, **kwargs)
        self.student = student
        self.fields["enrollment"].queryset = student.enrollments.filter(status=EnrollmentStatus.ACTIVE).select_related("group")
        self.fields["target_group"].queryset = Group.objects.filter(status="ACTIVE")

    def clean(self):
        cleaned = super().clean()
        source, target, transfer_date = cleaned.get("enrollment"), cleaned.get("target_group"), cleaned.get("transfer_date")
        if source and source.student_id != self.student.pk:
            raise ValidationError("Выбрано чужое зачисление.")
        if source and target and source.group_id == target.pk:
            self.add_error("target_group", "Выберите другую группу.")
        if source and transfer_date and transfer_date <= source.started_at:
            self.add_error("transfer_date", "Дата перевода должна быть позже даты начала обучения.")
        if target and Enrollment.objects.filter(student=self.student, group=target, status=EnrollmentStatus.ACTIVE).exists():
            self.add_error("target_group", "Ученик уже состоит в этой группе.")
        return cleaned


class DiscountForm(forms.ModelForm):
    class Meta:
        model = Discount
        fields = ("name", "student", "group", "percentage", "starts_at", "ends_at", "is_active")
        labels = {"name": "Название акции", "student": "Ученик", "group": "Группа", "percentage": "Скидка, %", "starts_at": "Начало", "ends_at": "Окончание", "is_active": "Активна"}
        widgets = {"starts_at": forms.DateInput(attrs={"type": "date"}), "ends_at": forms.DateInput(attrs={"type": "date"})}


class PaymentForm(forms.ModelForm):
    """Student/group come from the form fields or are fixed from the URL route.

    Fixed student/group are rendered as disabled fields so a crafted POST can
    never replace them; the enrollment-history check runs in clean().
    """

    class Meta:
        model = Payment
        fields = ("student", "group", "amount", "paid_at", "period", "status", "note")
        widgets = {
            "paid_at": forms.DateInput(attrs={"type": "date"}),
            "period": forms.DateInput(attrs={"type": "month"}, format="%Y-%m"),
            "note": forms.Textarea(attrs={"rows": 3, "placeholder": "Необязательно"}),
        }
        labels = {
            "student": "Ученик",
            "group": "Группа",
            "amount": "Сумма (TJS)",
            "paid_at": "Дата оплаты",
            "period": "Период (месяц)",
            "status": "Статус",
            "note": "Заметка",
        }
        help_texts = {
            "paid_at": "Дата, когда деньги фактически были получены.",
            "period": "Месяц обучения, за который внесена оплата.",
        }

    def __init__(self, *args, student=None, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed_student = student
        self.fixed_group = group
        self.fields["status"].required = False
        self.fields["period"].input_formats = ["%Y-%m", "%Y-%m-%d"]
        if not self.is_bound and not self.instance.pk:
            today = timezone.localdate()
            self.initial.setdefault("paid_at", today)
            self.initial.setdefault("period", today.replace(day=1))
            self.initial.setdefault("status", PaymentStatus.PAID)
        if student is not None:
            self.fields["student"].disabled = True
            self.fields["student"].initial = student
            self.fields["group"].queryset = Group.objects.filter(enrollments__student=student).distinct()
            active_groups = list(Group.objects.filter(
                enrollments__student=student,
                enrollments__status=EnrollmentStatus.ACTIVE,
                status="ACTIVE",
            ).distinct()[:2])
            if not self.is_bound and not self.instance.pk and len(active_groups) == 1:
                self.initial["group"] = active_groups[0]
                self.initial["amount"] = active_groups[0].monthly_fee
        if group is not None:
            self.fields["group"].disabled = True
            self.fields["group"].initial = group
            self.fields["student"].queryset = Student.objects.filter(enrollments__group=group).distinct()
            if not self.is_bound and not self.instance.pk:
                self.initial["amount"] = group.monthly_fee

    def clean_status(self):
        return self.cleaned_data.get("status") or PaymentStatus.PAID

    def clean_period(self):
        period = self.cleaned_data["period"]
        return period.replace(day=1)

    def clean(self):
        cleaned = super().clean()
        student = cleaned.get("student") or self.fixed_student
        group = cleaned.get("group") or self.fixed_group
        if student and group and not Enrollment.objects.filter(student=student, group=group).exists():
            self.add_error("group", "Ученик не был связан с этой группой через зачисление.")
        return cleaned

    def save(self, commit=True):
        payment = super().save(commit=False)
        if self.fixed_student is not None:
            payment.student = self.fixed_student
        if self.fixed_group is not None:
            payment.group = self.fixed_group
        if commit:
            payment.save()
        return payment


class PaymentEditForm(PaymentForm):
    pass


class ScheduleOverrideForm(forms.ModelForm):
    class Meta:
        model = ScheduleOverride
        fields = ("date", "override_type", "new_date", "new_start_time", "new_end_time", "substitute_teacher", "reason", "note")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "new_date": forms.DateInput(attrs={"type": "date"}),
            "new_start_time": forms.TimeInput(attrs={"type": "time"}),
            "new_end_time": forms.TimeInput(attrs={"type": "time"}),
            "reason": forms.TextInput(attrs={"placeholder": "Например: праздничный день"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "date": "Дата",
            "override_type": "Тип исключения",
            "new_date": "Новая дата",
            "new_start_time": "Новое время начала",
            "new_end_time": "Новое время окончания",
            "substitute_teacher": "Заменяющий преподаватель",
            "reason": "Причина",
            "note": "Примечание",
        }

    def __init__(self, *args, schedule: Schedule, **kwargs):
        super().__init__(*args, **kwargs)
        self.schedule = schedule
        teachers = Teacher.objects.filter(status="ACTIVE").exclude(pk=schedule.group.teacher_id)
        self.fields["substitute_teacher"].queryset = teachers

    def save(self, commit=True):
        override = super().save(commit=False)
        override.schedule = self.schedule
        if commit:
            override.save()
        return override
