from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import UserRole
from apps.accounts.permissions import operational_required

from .forms import AttendanceBulkForm, CourseForm, EnrollmentCreateForm, EnrollmentEndForm, GroupForm, LessonForm, LessonFromScheduleForm, ScheduleForm, StudentForm, TeacherCreateForm, TeacherForm
from .models import Attendance, AttendanceStatus, Course, Enrollment, EnrollmentStatus, Group, Lesson, LessonStatus, RecordStatus, Schedule, Student, Teacher


def _page(request: HttpRequest, queryset):
    return Paginator(queryset, 20).get_page(request.GET.get("page"))


def _is_teacher(request: HttpRequest) -> bool:
    return request.user.role == UserRole.TEACHER


@login_required
def student_list(request: HttpRequest) -> HttpResponse:
    if _is_teacher(request):
        students = Student.objects.filter(enrollments__group__teacher=request.user.teacher_profile, enrollments__status=EnrollmentStatus.ACTIVE).distinct()
    else:
        students = Student.objects.all()
        query = request.GET.get("q", "").strip()
        status = request.GET.get("status", RecordStatus.ACTIVE)
        if query:
            students = students.filter(Q(full_name__icontains=query) | Q(phone__icontains=query))
        if status in RecordStatus.values:
            students = students.filter(status=status)
    return render(request, "education/student_list.html", {"page_obj": _page(request, students), "statuses": RecordStatus, "selected_status": request.GET.get("status", RecordStatus.ACTIVE)})


@login_required
def student_detail(request: HttpRequest, pk: int) -> HttpResponse:
    student = get_object_or_404(Student, pk=pk)
    enrollments = student.enrollments.select_related("group__course", "group__teacher__user")
    if _is_teacher(request):
        enrollments = enrollments.filter(group__teacher=request.user.teacher_profile)
        if not enrollments.filter(status=EnrollmentStatus.ACTIVE).exists():
            raise PermissionDenied
    attendance = student.attendance_records.select_related("lesson__group").order_by("-lesson__date")
    if _is_teacher(request):
        attendance = attendance.filter(lesson__group__teacher=request.user.teacher_profile)
    return render(request, "education/student_detail.html", {"student": student, "active_enrollments": enrollments.filter(status=EnrollmentStatus.ACTIVE), "history_enrollments": enrollments.filter(status=EnrollmentStatus.ENDED), "attendance_history": attendance})


@operational_required
def student_create(request: HttpRequest) -> HttpResponse:
    form = StudentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        student = form.save()
        return redirect("education:student-detail", pk=student.pk)
    return render(request, "education/form.html", {"form": form, "title": "Новый ученик"})


@operational_required
def student_edit(request: HttpRequest, pk: int) -> HttpResponse:
    student = get_object_or_404(Student, pk=pk)
    form = StudentForm(request.POST or None, instance=student)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("education:student-detail", pk=student.pk)
    return render(request, "education/form.html", {"form": form, "title": "Изменить ученика"})


@operational_required
def student_set_status(request: HttpRequest, pk: int, status: str) -> HttpResponse:
    if request.method != "POST" or status not in RecordStatus.values:
        raise PermissionDenied
    student = get_object_or_404(Student, pk=pk)
    student.status = status
    student.save(update_fields=("status", "updated_at"))
    return redirect("education:student-detail", pk=pk)


@login_required
def teacher_list(request: HttpRequest) -> HttpResponse:
    teachers = Teacher.objects.all() if not _is_teacher(request) else Teacher.objects.filter(user=request.user)
    return render(request, "education/teacher_list.html", {"page_obj": _page(request, teachers)})


@login_required
def teacher_detail(request: HttpRequest, pk: int) -> HttpResponse:
    teacher = get_object_or_404(Teacher, pk=pk)
    if _is_teacher(request) and teacher.user_id != request.user.id:
        raise PermissionDenied
    return render(request, "education/teacher_detail.html", {"teacher": teacher})


@operational_required
def teacher_create(request: HttpRequest) -> HttpResponse:
    form = TeacherCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        teacher = form.save()
        return redirect("education:teacher-detail", pk=teacher.pk)
    return render(request, "education/form.html", {"form": form, "title": "Новый преподаватель"})


@operational_required
def teacher_edit(request: HttpRequest, pk: int) -> HttpResponse:
    teacher = get_object_or_404(Teacher, pk=pk)
    form = TeacherForm(request.POST or None, instance=teacher)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("education:teacher-detail", pk=teacher.pk)
    return render(request, "education/form.html", {"form": form, "title": "Изменить преподавателя"})


@operational_required
def teacher_set_status(request: HttpRequest, pk: int, status: str) -> HttpResponse:
    if request.method != "POST" or status not in RecordStatus.values:
        raise PermissionDenied
    teacher = get_object_or_404(Teacher, pk=pk)
    teacher.status = status
    teacher.save(update_fields=("status", "updated_at"))
    return redirect("education:teacher-detail", pk=pk)


@login_required
def course_list(request: HttpRequest) -> HttpResponse:
    courses = Course.objects.filter(status=RecordStatus.ACTIVE) if _is_teacher(request) else Course.objects.all()
    return render(request, "education/course_list.html", {"page_obj": _page(request, courses)})


@operational_required
def course_create(request: HttpRequest) -> HttpResponse:
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        course = form.save()
        return redirect("education:course-list")
    return render(request, "education/form.html", {"form": form, "title": "Новый курс"})


@operational_required
def course_edit(request: HttpRequest, pk: int) -> HttpResponse:
    course = get_object_or_404(Course, pk=pk)
    form = CourseForm(request.POST or None, instance=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("education:course-list")
    return render(request, "education/form.html", {"form": form, "title": "Изменить курс"})


@operational_required
def course_set_status(request: HttpRequest, pk: int, status: str) -> HttpResponse:
    if request.method != "POST" or status not in RecordStatus.values:
        raise PermissionDenied
    course = get_object_or_404(Course, pk=pk)
    course.status = status
    course.save(update_fields=("status", "updated_at"))
    return redirect("education:course-list")


def _group_queryset_for(request: HttpRequest):
    groups = Group.objects.select_related("course", "teacher__user").annotate(active_students_count=Count("enrollments", filter=Q(enrollments__status=EnrollmentStatus.ACTIVE))).order_by("name")
    if _is_teacher(request):
        return groups.filter(teacher=request.user.teacher_profile)
    return groups


@login_required
def group_list(request: HttpRequest) -> HttpResponse:
    groups = _group_queryset_for(request)
    if not _is_teacher(request):
        query = request.GET.get("q", "").strip()
        if query:
            groups = groups.filter(name__icontains=query)
        for field, model in (("course", Course), ("teacher", Teacher)):
            value = request.GET.get(field)
            if value and value.isdigit():
                groups = groups.filter(**{f"{field}_id": value})
        status = request.GET.get("status", RecordStatus.ACTIVE)
        if status in RecordStatus.values:
            groups = groups.filter(status=status)
    return render(request, "education/group_list.html", {"page_obj": _page(request, groups), "courses": Course.objects.all(), "teachers": Teacher.objects.all(), "statuses": RecordStatus, "selected_status": request.GET.get("status", RecordStatus.ACTIVE)})


def _group_for_request(request: HttpRequest, pk: int) -> Group:
    group = get_object_or_404(_group_queryset_for(request), pk=pk)
    return group


@login_required
def group_detail(request: HttpRequest, pk: int) -> HttpResponse:
    group = _group_for_request(request, pk)
    active_enrollments = group.enrollments.filter(status=EnrollmentStatus.ACTIVE).select_related("student")
    today = timezone.localdate()
    attendance = Attendance.objects.filter(lesson__group=group)
    return render(request, "education/group_detail.html", {"group": group, "active_enrollments": active_enrollments, "history_enrollments": group.enrollments.filter(status=EnrollmentStatus.ENDED).select_related("student"), "schedules": group.schedules.all(), "upcoming_lessons": group.lessons.filter(date__gte=today).exclude(status=LessonStatus.CANCELLED)[:10], "past_lessons": group.lessons.filter(date__lt=today)[:10], "attendance_stats": {"lessons": group.lessons.count(), "present": attendance.filter(status=AttendanceStatus.PRESENT).count(), "absent": attendance.filter(status=AttendanceStatus.ABSENT).count(), "excused": attendance.filter(status=AttendanceStatus.EXCUSED).count()}})


@operational_required
def group_create(request: HttpRequest) -> HttpResponse:
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = form.save()
        return redirect("education:group-detail", pk=group.pk)
    return render(request, "education/form.html", {"form": form, "title": "Новая группа"})


@operational_required
def group_edit(request: HttpRequest, pk: int) -> HttpResponse:
    group = get_object_or_404(Group, pk=pk)
    form = GroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("education:group-detail", pk=group.pk)
    return render(request, "education/form.html", {"form": form, "title": "Изменить группу"})


@operational_required
def group_set_status(request: HttpRequest, pk: int, status: str) -> HttpResponse:
    if request.method != "POST" or status not in RecordStatus.values:
        raise PermissionDenied
    group = get_object_or_404(Group, pk=pk)
    group.status = status
    group.save(update_fields=("status", "updated_at"))
    return redirect("education:group-detail", pk=pk)


@operational_required
def enrollment_create(request: HttpRequest, group_pk: int) -> HttpResponse:
    group = get_object_or_404(Group, pk=group_pk)
    form = EnrollmentCreateForm(request.POST or None, group=group)
    if request.method == "POST" and form.is_valid():
        enrollment = form.save()
        return redirect("education:group-detail", pk=enrollment.group_id)
    return render(request, "education/form.html", {"form": form, "title": f"Добавить ученика в группу {group.name}"})


@operational_required
def enrollment_end(request: HttpRequest, pk: int) -> HttpResponse:
    enrollment = get_object_or_404(Enrollment, pk=pk, status=EnrollmentStatus.ACTIVE)
    form = EnrollmentEndForm(request.POST or None, enrollment=enrollment)
    if request.method == "POST" and form.is_valid():
        enrollment.status = EnrollmentStatus.ENDED
        enrollment.ended_at = form.cleaned_data["ended_at"]
        enrollment.full_clean()
        enrollment.save(update_fields=("status", "ended_at", "updated_at"))
        return redirect("education:student-detail", pk=enrollment.student_id)
    return render(request, "education/form.html", {"form": form, "title": f"Завершить обучение: {enrollment.group.name}"})


@operational_required
def schedule_create(request: HttpRequest, group_pk: int) -> HttpResponse:
    group = get_object_or_404(Group, pk=group_pk)
    form = ScheduleForm(request.POST or None, group=group)
    if request.method == "POST" and form.is_valid():
        schedule = form.save()
        return redirect("education:group-detail", pk=schedule.group_id)
    return render(request, "education/form.html", {"form": form, "title": f"Расписание: {group.name}"})


@operational_required
def schedule_edit(request: HttpRequest, pk: int) -> HttpResponse:
    schedule = get_object_or_404(Schedule, pk=pk)
    form = ScheduleForm(request.POST or None, instance=schedule, group=schedule.group)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("education:group-detail", pk=schedule.group_id)
    return render(request, "education/form.html", {"form": form, "title": "Изменить расписание"})


@operational_required
def schedule_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        raise PermissionDenied
    schedule = get_object_or_404(Schedule, pk=pk)
    schedule.is_active = False
    schedule.save(update_fields=("is_active", "updated_at"))
    return redirect("education:group-detail", pk=schedule.group_id)


def _lessons_for_request(request: HttpRequest):
    lessons = Lesson.objects.select_related("group__course", "group__teacher__user", "schedule")
    if _is_teacher(request):
        lessons = lessons.filter(group__teacher=request.user.teacher_profile)
    return lessons


@login_required
def lesson_list(request: HttpRequest) -> HttpResponse:
    lessons = _lessons_for_request(request)
    if not _is_teacher(request):
        for field in ("group", "teacher"):
            value = request.GET.get(field)
            if value and value.isdigit():
                lessons = lessons.filter(**{f"group__teacher_id" if field == "teacher" else "group_id": value})
        status = request.GET.get("status")
        if status in LessonStatus.values:
            lessons = lessons.filter(status=status)
        if request.GET.get("date_from"):
            lessons = lessons.filter(date__gte=request.GET["date_from"])
        if request.GET.get("date_to"):
            lessons = lessons.filter(date__lte=request.GET["date_to"])
    return render(request, "education/lesson_list.html", {"page_obj": _page(request, lessons.order_by("date", "start_time")), "groups": Group.objects.all(), "teachers": Teacher.objects.all(), "statuses": LessonStatus})


@login_required
def lesson_detail(request: HttpRequest, pk: int) -> HttpResponse:
    lesson = get_object_or_404(_lessons_for_request(request), pk=pk)
    form = AttendanceBulkForm(request.POST or None, lesson=lesson)
    if request.method == "POST":
        if lesson.status == LessonStatus.CANCELLED:
            form.add_error(None, "Нельзя изменять посещаемость отменённого занятия.")
        elif form.is_valid():
            form.save()
            return redirect("education:lesson-detail", pk=pk)
    active_count = lesson.active_students().count()
    records = lesson.attendance_records.all()
    summary = {"total": active_count, "present": records.filter(status=AttendanceStatus.PRESENT).count(), "absent": records.filter(status=AttendanceStatus.ABSENT).count(), "excused": records.filter(status=AttendanceStatus.EXCUSED).count(), "not_marked": max(0, active_count - records.filter(student__in=lesson.active_students()).count())}
    return render(request, "education/lesson_detail.html", {"lesson": lesson, "attendance_form": form, "summary": summary})


@operational_required
def lesson_create(request: HttpRequest) -> HttpResponse:
    form = LessonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lesson = form.save(commit=False)
        lesson.full_clean()
        lesson.save()
        return redirect("education:lesson-detail", pk=lesson.pk)
    return render(request, "education/form.html", {"form": form, "title": "Новое занятие"})


@operational_required
def lesson_edit(request: HttpRequest, pk: int) -> HttpResponse:
    lesson = get_object_or_404(Lesson, pk=pk)
    form = LessonForm(request.POST or None, instance=lesson)
    if request.method == "POST" and form.is_valid():
        updated = form.save(commit=False)
        updated.full_clean()
        updated.save()
        return redirect("education:lesson-detail", pk=pk)
    return render(request, "education/form.html", {"form": form, "title": "Изменить занятие"})


@operational_required
def lesson_from_schedule(request: HttpRequest, schedule_pk: int) -> HttpResponse:
    schedule = get_object_or_404(Schedule, pk=schedule_pk, is_active=True)
    form = LessonFromScheduleForm(request.POST or None, schedule=schedule)
    if request.method == "POST" and form.is_valid():
        lesson = form.save()
        return redirect("education:lesson-detail", pk=lesson.pk)
    return render(request, "education/form.html", {"form": form, "title": f"Занятие из расписания: {schedule}"})


@operational_required
def lesson_set_status(request: HttpRequest, pk: int, status: str) -> HttpResponse:
    if request.method != "POST" or status not in LessonStatus.values:
        raise PermissionDenied
    lesson = get_object_or_404(Lesson, pk=pk)
    lesson.status = status
    lesson.full_clean()
    lesson.save(update_fields=("status", "updated_at"))
    return redirect("education:lesson-detail", pk=pk)
