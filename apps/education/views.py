from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import UserRole
from apps.accounts.permissions import operational_required

from .audit import record_audit
from .forms import AttendanceBulkForm, CourseForm, EnrollmentCreateForm, EnrollmentEndForm, GroupForm, LessonForm, LessonFromScheduleForm, PaymentEditForm, PaymentForm, ScheduleForm, StudentForm, TeacherCreateForm, TeacherForm
from .models import Attendance, AttendanceStatus, AuditAction, AuditLog, Course, Enrollment, EnrollmentStatus, Group, Lesson, LessonStatus, Payment, PaymentStatus, RecordStatus, Schedule, Student, Teacher


def _page(request: HttpRequest, queryset):
    return Paginator(queryset, 20).get_page(request.GET.get("page"))


def _parse_date(value: str):
    try:
        return timezone.datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _is_teacher(request: HttpRequest) -> bool:
    return request.user.role == UserRole.TEACHER


def _pagination_qs(request: HttpRequest) -> str:
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def _has_active_filters(request: HttpRequest) -> bool:
    return any(request.GET.get(key) for key in request.GET if key != "page")


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
    return render(request, "education/student_list.html", {"page_obj": _page(request, students), "statuses": RecordStatus, "selected_status": request.GET.get("status", RecordStatus.ACTIVE), "pagination_qs": _pagination_qs(request), "has_filters": _has_active_filters(request)})


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
        payments = Payment.objects.none()
    else:
        payments = student.payments.select_related("group").order_by("-paid_at", "-pk")
    return render(request, "education/student_detail.html", {"student": student, "active_enrollments": enrollments.filter(status=EnrollmentStatus.ACTIVE), "history_enrollments": enrollments.filter(status=EnrollmentStatus.ENDED), "attendance_history": attendance, "payments": payments})


@operational_required
def student_create(request: HttpRequest) -> HttpResponse:
    form = StudentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        student = form.save()
        record_audit(request.user, AuditAction.STUDENT_CREATE, "Student", student.pk, student.full_name)
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
    previous = student.status
    student.status = status
    student.save(update_fields=("status", "updated_at"))
    if previous != status:
        action = AuditAction.STUDENT_ARCHIVE if status == RecordStatus.ARCHIVED else AuditAction.STUDENT_RESTORE
        record_audit(request.user, action, "Student", student.pk, student.full_name)
    return redirect("education:student-detail", pk=pk)


@login_required
def teacher_list(request: HttpRequest) -> HttpResponse:
    if _is_teacher(request):
        teachers = Teacher.objects.filter(user=request.user)
    else:
        teachers = Teacher.objects.select_related("user")
        query = request.GET.get("q", "").strip()
        if query:
            teachers = teachers.filter(Q(full_name__icontains=query) | Q(phone__icontains=query) | Q(user__username__icontains=query) | Q(user__email__icontains=query))
        status = request.GET.get("status")
        if status in RecordStatus.values:
            teachers = teachers.filter(status=status)
    return render(request, "education/teacher_list.html", {"page_obj": _page(request, teachers.order_by("pk")), "statuses": RecordStatus, "selected_status": request.GET.get("status", ""), "pagination_qs": _pagination_qs(request), "has_filters": _has_active_filters(request)})


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
    if _is_teacher(request):
        courses = Course.objects.filter(status=RecordStatus.ACTIVE)
    else:
        courses = Course.objects.all()
        query = request.GET.get("q", "").strip()
        if query:
            courses = courses.filter(name__icontains=query)
        status = request.GET.get("status")
        if status in RecordStatus.values:
            courses = courses.filter(status=status)
    return render(request, "education/course_list.html", {"page_obj": _page(request, courses), "statuses": RecordStatus, "selected_status": request.GET.get("status", ""), "pagination_qs": _pagination_qs(request), "has_filters": _has_active_filters(request)})


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
    return render(request, "education/group_list.html", {"page_obj": _page(request, groups), "courses": Course.objects.all(), "teachers": Teacher.objects.all(), "statuses": RecordStatus, "selected_status": request.GET.get("status", RecordStatus.ACTIVE), "pagination_qs": _pagination_qs(request), "has_filters": _has_active_filters(request)})


def _group_for_request(request: HttpRequest, pk: int) -> Group:
    group = get_object_or_404(_group_queryset_for(request), pk=pk)
    return group


@login_required
def group_detail(request: HttpRequest, pk: int) -> HttpResponse:
    group = _group_for_request(request, pk)
    active_enrollments = group.enrollments.filter(status=EnrollmentStatus.ACTIVE).select_related("student")
    today = timezone.localdate()
    attendance = Attendance.objects.filter(lesson__group=group)
    if _is_teacher(request):
        payments = Payment.objects.none()
        payments_total = Decimal("0")
    else:
        payments = group.payments.select_related("student").order_by("-paid_at", "-pk")
        payments_total = payments.filter(status=PaymentStatus.PAID).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        payments_total = payments_total.quantize(Decimal("0.01"))
    return render(request, "education/group_detail.html", {"group": group, "active_enrollments": active_enrollments, "history_enrollments": group.enrollments.filter(status=EnrollmentStatus.ENDED).select_related("student"), "schedules": group.schedules.all(), "upcoming_lessons": group.lessons.filter(date__gte=today).exclude(status=LessonStatus.CANCELLED)[:10], "past_lessons": group.lessons.filter(date__lt=today)[:10], "attendance_stats": {"lessons": group.lessons.count(), "present": attendance.filter(status=AttendanceStatus.PRESENT).count(), "absent": attendance.filter(status=AttendanceStatus.ABSENT).count(), "late": attendance.filter(status=AttendanceStatus.LATE).count()}, "payments": payments, "payments_total": payments_total})


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
        record_audit(request.user, AuditAction.ENROLLMENT_CREATE, "Enrollment", enrollment.pk, f"{enrollment.student} → {enrollment.group}")
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
        record_audit(request.user, AuditAction.ENROLLMENT_END, "Enrollment", enrollment.pk, f"{enrollment.student} → {enrollment.group}")
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
    lessons = _lessons_for_request(request).annotate(
        attendance_marked=Count("attendance_records", distinct=True),
        group_active_students=Count("group__enrollments", filter=Q(group__enrollments__status=EnrollmentStatus.ACTIVE), distinct=True),
    )
    if not _is_teacher(request):
        for field in ("group", "teacher"):
            value = request.GET.get(field)
            if value and value.isdigit():
                lessons = lessons.filter(**{f"group__teacher_id" if field == "teacher" else "group_id": value})
        status = request.GET.get("status")
        if status in LessonStatus.values:
            lessons = lessons.filter(status=status)
        date_from = _parse_date(request.GET.get("date_from"))
        if date_from:
            lessons = lessons.filter(date__gte=date_from)
        date_to = _parse_date(request.GET.get("date_to"))
        if date_to:
            lessons = lessons.filter(date__lte=date_to)
    return render(request, "education/lesson_list.html", {"page_obj": _page(request, lessons.order_by("date", "start_time")), "groups": Group.objects.all(), "teachers": Teacher.objects.all(), "statuses": LessonStatus, "selected_group": request.GET.get("group", ""), "selected_teacher": request.GET.get("teacher", ""), "selected_status": request.GET.get("status", ""), "date_from": request.GET.get("date_from", ""), "date_to": request.GET.get("date_to", ""), "pagination_qs": _pagination_qs(request), "has_filters": _has_active_filters(request)})


@login_required
def lesson_detail(request: HttpRequest, pk: int) -> HttpResponse:
    lesson = get_object_or_404(_lessons_for_request(request), pk=pk)
    can_edit = not _is_teacher(request)
    form = AttendanceBulkForm(request.POST or None, lesson=lesson)
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if lesson.status == LessonStatus.CANCELLED:
            form.add_error(None, "Нельзя изменять посещаемость отменённого занятия.")
        elif form.is_valid():
            marked = len([value for key, value in form.cleaned_data.items() if key.startswith("status_") and value])
            form.save()
            record_audit(request.user, AuditAction.ATTENDANCE_CHANGE, "Lesson", lesson.pk, f"{lesson.group}: {lesson.date} — отмечено {marked} учеников")
            return redirect("education:lesson-detail", pk=pk)
    active_count = lesson.active_students().count()
    records = lesson.attendance_records.all()
    summary = {"total": active_count, "present": records.filter(status=AttendanceStatus.PRESENT).count(), "absent": records.filter(status=AttendanceStatus.ABSENT).count(), "late": records.filter(status=AttendanceStatus.LATE).count(), "not_marked": max(0, active_count - records.filter(student__in=lesson.active_students()).count())}
    return render(request, "education/lesson_detail.html", {"lesson": lesson, "attendance_form": form, "summary": summary, "can_edit": can_edit})


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


def _payment_queryset():
    return Payment.objects.select_related("student", "group__course")


@operational_required
def payment_list(request: HttpRequest) -> HttpResponse:
    payments = _payment_queryset()
    query = request.GET.get("q", "").strip()
    if query:
        payments = payments.filter(student__full_name__icontains=query)
    for field in ("student", "group"):
        value = request.GET.get(field)
        if value and value.isdigit():
            payments = payments.filter(**{f"{field}_id": value})
    status = request.GET.get("status")
    if status in PaymentStatus.values:
        payments = payments.filter(status=status)
    month = request.GET.get("month", "").strip()
    if len(month) == 7 and month[:4].isdigit() and month[5:7].isdigit():
        payments = payments.filter(period__year=int(month[:4]), period__month=int(month[5:7]))
    return render(request, "education/payment_list.html", {"page_obj": _page(request, payments), "students": Student.objects.all(), "groups": Group.objects.all(), "statuses": PaymentStatus, "selected_status": request.GET.get("status", ""), "selected_month": month, "pagination_qs": _pagination_qs(request), "has_filters": _has_active_filters(request)})


@operational_required
def payment_detail(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(_payment_queryset(), pk=pk)
    return render(request, "education/payment_detail.html", {"payment": payment})


@operational_required
def payment_create(request: HttpRequest) -> HttpResponse:
    form = PaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        payment = form.save()
        record_audit(request.user, AuditAction.PAYMENT_CREATE, "Payment", payment.pk, f"{payment.student}: {payment.amount} ({payment.period:%m.%Y})")
        return redirect("education:payment-detail", pk=payment.pk)
    return render(request, "education/form.html", {"form": form, "title": "Новая оплата"})


@operational_required
def student_payment_create(request: HttpRequest, student_pk: int) -> HttpResponse:
    student = get_object_or_404(Student, pk=student_pk)
    form = PaymentForm(request.POST or None, student=student)
    if request.method == "POST" and form.is_valid():
        payment = form.save()
        record_audit(request.user, AuditAction.PAYMENT_CREATE, "Payment", payment.pk, f"{payment.student}: {payment.amount} ({payment.period:%m.%Y})")
        return redirect("education:payment-detail", pk=payment.pk)
    return render(request, "education/form.html", {"form": form, "title": f"Оплата: {student.full_name}"})


@operational_required
def group_payment_create(request: HttpRequest, group_pk: int) -> HttpResponse:
    group = get_object_or_404(Group, pk=group_pk)
    form = PaymentForm(request.POST or None, group=group)
    if request.method == "POST" and form.is_valid():
        payment = form.save()
        record_audit(request.user, AuditAction.PAYMENT_CREATE, "Payment", payment.pk, f"{payment.student}: {payment.amount} ({payment.period:%m.%Y})")
        return redirect("education:payment-detail", pk=payment.pk)
    return render(request, "education/form.html", {"form": form, "title": f"Оплата в группу: {group.name}"})


@operational_required
def payment_edit(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Payment, pk=pk)
    form = PaymentEditForm(request.POST or None, instance=payment, student=payment.student, group=payment.group)
    if request.method == "POST" and form.is_valid():
        form.save()
        record_audit(request.user, AuditAction.PAYMENT_EDIT, "Payment", payment.pk, f"{payment.student}: {payment.amount} ({payment.period:%m.%Y}) — {payment.get_status_display()}")
        return redirect("education:payment-detail", pk=payment.pk)
    return render(request, "education/form.html", {"form": form, "title": "Изменить оплату"})


@operational_required
def payment_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        raise PermissionDenied
    payment = get_object_or_404(Payment, pk=pk)
    payment.status = PaymentStatus.CANCELLED
    payment.save(update_fields=("status", "updated_at"))
    record_audit(request.user, AuditAction.PAYMENT_CANCEL, "Payment", payment.pk, f"{payment.student}: {payment.amount} ({payment.period:%m.%Y})")
    return redirect("education:payment-detail", pk=pk)


@operational_required
def audit_list(request: HttpRequest) -> HttpResponse:
    logs = AuditLog.objects.select_related("actor")
    action = request.GET.get("action")
    if action in AuditAction.values:
        logs = logs.filter(action=action)
    return render(request, "education/audit_list.html", {"page_obj": _page(request, logs), "actions": AuditAction, "selected_action": request.GET.get("action", ""), "pagination_qs": _pagination_qs(request), "has_filters": _has_active_filters(request)})
