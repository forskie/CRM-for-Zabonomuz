import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.accounts.models import UserRole

from .models import Attendance, AttendanceStatus, Course, Enrollment, EnrollmentStatus, Group, Lesson, LessonStatus, Payment, PaymentStatus, Schedule, Student, Teacher


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
        fields = ("full_name", "phone")
        labels = {"full_name": "ФИО", "phone": "Телефон"}

    def clean_full_name(self):
        full_name = self.cleaned_data["full_name"].strip()
        if not full_name:
            raise ValidationError("Укажите ФИО преподавателя.")
        return full_name


class TeacherCreateForm(PhoneValidationMixin, UserCreationForm):
    full_name = forms.CharField(max_length=255, label="ФИО")
    phone = forms.CharField(max_length=32, required=False, label="Телефон")

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        courses = Course.objects.filter(status="ACTIVE")
        teachers = Teacher.objects.filter(status="ACTIVE")
        if self.instance.pk:
            courses = Course.objects.filter(Q(status="ACTIVE") | Q(pk=self.instance.course_id))
            teachers = Teacher.objects.filter(Q(status="ACTIVE") | Q(pk=self.instance.teacher_id))
        self.fields["course"].queryset = courses
        self.fields["teacher"].queryset = teachers


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
        fields = ("weekday", "start_time", "end_time", "is_active")
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"}), "end_time": forms.TimeInput(attrs={"type": "time"})}

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
        if cleaned.get("is_active") and start and end and cleaned.get("weekday") is not None:
            conflicts = Schedule.objects.filter(group__teacher=self.group.teacher, weekday=cleaned["weekday"], is_active=True, start_time__lt=end, end_time__gt=start).exclude(pk=self.instance.pk)
            if conflicts.exists():
                self.add_error("start_time", "Расписание пересекается с другим занятием этого преподавателя.")
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
            conflicts = Lesson.objects.filter(group__teacher=group.teacher, date=lesson_date).exclude(status=LessonStatus.CANCELLED).filter(start_time__lt=end, end_time__gt=start).exclude(pk=self.instance.pk)
            if conflicts.exists():
                self.add_error("start_time", "Занятие пересекается с другим занятием этого преподавателя.")
        return cleaned


class LessonFromScheduleForm(forms.Form):
    date = forms.DateField(label="Дата", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, schedule: Schedule, **kwargs):
        super().__init__(*args, **kwargs)
        self.schedule = schedule

    def save(self):
        lesson = Lesson(group=self.schedule.group, schedule=self.schedule, date=self.cleaned_data["date"], start_time=self.schedule.start_time, end_time=self.schedule.end_time)
        lesson.full_clean()
        lesson.save()
        return lesson


class AttendanceBulkForm(forms.Form):
    """One server-defined field pair per eligible student; client ids are never trusted."""

    def __init__(self, *args, lesson: Lesson, **kwargs):
        super().__init__(*args, **kwargs)
        self.lesson = lesson
        active_students = lesson.active_students()
        existing = Attendance.objects.filter(lesson=lesson).select_related("student")
        students = {student.pk: student for student in active_students}
        students.update({record.student_id: record.student for record in existing})
        self.students = students
        records = {record.student_id: record for record in existing}
        for student_id, student in sorted(students.items(), key=lambda item: item[1].full_name):
            record = records.get(student_id)
            self.fields[f"status_{student_id}"] = forms.ChoiceField(choices=[("", "Не отмечено")] + list(AttendanceStatus.choices), required=False, initial=record.status if record else "", label=student.full_name)
            self.fields[f"note_{student_id}"] = forms.CharField(required=False, initial=record.note if record else "", label="Примечание")

    def rows(self):
        """Yield (student, status_field, note_field) triplets for a table layout."""
        for student_id, student in sorted(self.students.items(), key=lambda item: item[1].full_name):
            yield (student, self[f"status_{student_id}"], self[f"note_{student_id}"])

    def save(self):
        if self.lesson.status == LessonStatus.CANCELLED:
            raise ValidationError("Нельзя изменять посещаемость отменённого занятия.")
        for student_id, student in self.students.items():
            status = self.cleaned_data[f"status_{student_id}"]
            if not status:
                continue
            record, created = Attendance.objects.get_or_create(lesson=self.lesson, student=student, defaults={"status": status, "note": self.cleaned_data[f"note_{student_id}"]})
            if not created:
                record.status = status
                record.note = self.cleaned_data[f"note_{student_id}"]
                record.full_clean()
                record.save(update_fields=("status", "note", "updated_at"))


class PaymentForm(forms.ModelForm):
    """Student/group come from the form fields or are fixed from the URL route.

    Fixed student/group are rendered as disabled fields so a crafted POST can
    never replace them; the enrollment-history check runs in clean().
    """

    class Meta:
        model = Payment
        fields = ("student", "group", "amount", "paid_at", "period", "note")
        widgets = {
            "paid_at": forms.DateInput(attrs={"type": "date"}),
            "period": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "student": "Ученик",
            "group": "Группа",
            "amount": "Сумма (TJS)",
            "paid_at": "Дата оплаты",
            "period": "Период (месяц)",
            "note": "Заметка",
        }

    def __init__(self, *args, student=None, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed_student = student
        self.fixed_group = group
        if student is not None:
            self.fields["student"].disabled = True
            self.fields["student"].initial = student
            self.fields["group"].queryset = Group.objects.filter(enrollments__student=student).distinct()
        if group is not None:
            self.fields["group"].disabled = True
            self.fields["group"].initial = group
            self.fields["student"].queryset = Student.objects.filter(enrollments__group=group).distinct()

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
    class Meta(PaymentForm.Meta):
        fields = ("student", "group", "amount", "paid_at", "period", "status", "note")
        labels = {**PaymentForm.Meta.labels, "status": "Статус"}
