from collections import OrderedDict
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.formats import date_format

from apps.accounts.models import UserRole
from apps.education.models import (
    Attendance,
    AttendanceStatus,
    AuditLog,
    EnrollmentStatus,
    Group,
    Lesson,
    LessonStatus,
    Payment,
    PaymentStatus,
    RecordStatus,
    Student,
    Teacher,
)


WEEKDAYS_RU = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

ACTION_LABELS = {
    "PAYMENT_CREATE": ("Оплата", "Платёж получен"),
    "PAYMENT_EDIT": ("Оплата", "Платёж изменён"),
    "PAYMENT_CANCEL": ("Оплата", "Платёж отменён"),
    "ATTENDANCE_CHANGE": ("Посещаемость", "Отметка посещаемости"),
    "ENROLLMENT_CREATE": ("Зачисление", "Новое зачисление"),
    "ENROLLMENT_END": ("Зачисление", "Обучение завершено"),
    "STUDENT_CREATE": ("Ученик", "Новый ученик"),
    "STUDENT_ARCHIVE": ("Ученик", "Ученик архивирован"),
    "STUDENT_RESTORE": ("Ученик", "Ученик восстановлен"),
    "LESSON_CREATE": ("Занятие", "Новое занятие"),
    "LESSON_EDIT": ("Занятие", "Занятие изменено"),
    "LESSON_CANCEL": ("Занятие", "Занятие отменено"),
    "LESSON_COMPLETE": ("Занятие", "Занятие завершено"),
    "LESSON_RESCHEDULE": ("Занятие", "Занятие перенесено"),
    "LESSON_REPORT": ("Занятие", "Отчёт о занятии"),
    "SCHEDULE_CREATE": ("Расписание", "Расписание создано"),
    "SCHEDULE_EDIT": ("Расписание", "Расписание изменено"),
    "SCHEDULE_DEACTIVATE": ("Расписание", "Расписание деактивировано"),
    "SCHEDULE_GENERATE": ("Расписание", "Занятия сгенерированы"),
    "COURSE_CREATE": ("Курс", "Новый курс"),
    "COURSE_EDIT": ("Курс", "Курс изменён"),
    "COURSE_STATUS": ("Курс", "Статус курса изменён"),
    "GROUP_CREATE": ("Группа", "Новая группа"),
    "GROUP_EDIT": ("Группа", "Группа изменена"),
    "GROUP_STATUS": ("Группа", "Статус группы изменён"),
    "TEACHER_EDIT": ("Преподаватель", "Преподаватель изменён"),
    "TEACHER_STATUS": ("Преподаватель", "Статус преподавателя изменён"),
}


def _is_teacher(request) -> bool:
    return request.user.role == UserRole.TEACHER


def _format_lesson_datetime(lesson) -> str:
    """Return 'Пн, 17 авг' or 'Сегодня' / 'Завтра' for the lesson date."""
    return date_format(lesson.date, "D, j E")


@login_required
def dashboard(request):
    """Operational dashboard.

    TEACHER sees only their own groups and attendance; financial data is never exposed.
    OWNER/ADMIN sees everything including financials and audit activity.
    """
    today = timezone.localdate()
    period_start = today.replace(day=1)

    today_weekday = WEEKDAYS_RU[today.weekday()]
    today_display = f"{today_weekday}, {date_format(today, 'j E Y')}"

    # ── role-scoped base querysets ──────────────────────────────────
    if _is_teacher(request):
        student_qs = Student.objects.filter(
            enrollments__group__teacher=request.user.teacher_profile,
            enrollments__status=EnrollmentStatus.ACTIVE,
        )
        group_qs = Group.objects.filter(teacher=request.user.teacher_profile, status=RecordStatus.ACTIVE)
        attendance_qs = Attendance.objects.filter(lesson__group__teacher=request.user.teacher_profile)
        payments_total = Decimal("0")
        payments_count = 0
        recent_payments = Payment.objects.none()
    else:
        student_qs = Student.objects.all()
        group_qs = Group.objects.filter(status=RecordStatus.ACTIVE)
        attendance_qs = Attendance.objects.all()
        month_stats = Payment.objects.filter(period=period_start).aggregate(
            total=Sum("amount", filter=Q(status=PaymentStatus.PAID)),
            count=Count("id"),
        )
        payments_total = (month_stats["total"] or Decimal("0")).quantize(Decimal("0.01"))
        payments_count = month_stats["count"] or 0
        recent_payments = Payment.objects.select_related("student", "group__course").order_by("-paid_at", "-pk")[:5]

    # ── students / attendance aggregates ────────────────────────────
    students = student_qs.aggregate(
        total=Count("id", distinct=True),
        active=Count("id", filter=Q(status=RecordStatus.ACTIVE), distinct=True),
    )

    attendance = attendance_qs.aggregate(
        present=Count("id", filter=Q(status=AttendanceStatus.PRESENT)),
        absent=Count("id", filter=Q(status=AttendanceStatus.ABSENT)),
        late=Count("id", filter=Q(status=AttendanceStatus.LATE)),
    )
    attendance_total = attendance["present"] + attendance["absent"] + attendance["late"]
    attendance_rate = (
        round(attendance["present"] / attendance_total * 100)
        if attendance_total
        else None
    )

    # ── active groups ───────────────────────────────────────────────
    active_groups = (
        group_qs.select_related("course", "teacher__user")
        .annotate(student_count=Count("enrollments", filter=Q(enrollments__status=EnrollmentStatus.ACTIVE), distinct=True))
        .order_by("name")
    )

    # ── lessons ─────────────────────────────────────────────────────
    lesson_qs = Lesson.objects.select_related("group__course", "group__teacher__user")
    if _is_teacher(request):
        lesson_qs = lesson_qs.filter(group__teacher=request.user.teacher_profile)

    today_lessons = list(
        lesson_qs.filter(date=today)
        .annotate(marked=Count("attendance_records", distinct=True))
        .annotate(student_count=Count("group__enrollments", filter=Q(group__enrollments__status=EnrollmentStatus.ACTIVE), distinct=True))
        .order_by("start_time")[:10]
    )

    today_lessons_total = len(today_lessons)
    today_lessons_completed = sum(1 for l in today_lessons if l.status == LessonStatus.COMPLETED)
    today_lessons_pending = [
        l for l in today_lessons
        if l.status != LessonStatus.CANCELLED and l.marked < l.student_count
    ]

    upcoming_lessons = list(
        lesson_qs.filter(date__gte=today)
        .exclude(status=LessonStatus.CANCELLED)
        .order_by("date", "start_time")[:14]
    )

    # Group upcoming by date (skip today)
    upcoming_grouped = OrderedDict()
    for lesson in upcoming_lessons:
        if lesson.date == today:
            continue
        d = lesson.date
        if d not in upcoming_grouped:
            upcoming_grouped[d] = []
        if len(upcoming_grouped[d]) < 5:
            upcoming_grouped[d].append(lesson)
        if len(upcoming_grouped) >= 5:
            break

    # ── teacher-specific: attendance pending + recent lessons ───────
    attendance_pending = []
    recent_lessons = []
    if _is_teacher(request):
        attendance_pending = list(
            lesson_qs.filter(date__gte=today, status=LessonStatus.SCHEDULED)
            .annotate(marked=Count("attendance_records", distinct=True))
            .annotate(student_count=Count("group__enrollments", filter=Q(group__enrollments__status=EnrollmentStatus.ACTIVE), distinct=True))
            .filter(marked__lt=F("student_count"))
            .order_by("date", "start_time")[:10]
        )
        recent_lessons = list(
            lesson_qs.filter(date__lt=today)
            .annotate(marked=Count("attendance_records", distinct=True))
            .annotate(student_count=Count("group__enrollments", filter=Q(group__enrollments__status=EnrollmentStatus.ACTIVE), distinct=True))
            .order_by("-date", "start_time")[:5]
        )

    # ── action required count (for all roles) ───────────────────────
    pending_attendance_count = len(attendance_pending)
    if not _is_teacher(request):
        pending_attendance_count = (
            lesson_qs.filter(date__gte=today, status=LessonStatus.SCHEDULED)
            .annotate(marked=Count("attendance_records", distinct=True))
            .annotate(student_count=Count("group__enrollments", filter=Q(group__enrollments__status=EnrollmentStatus.ACTIVE), distinct=True))
            .filter(marked__lt=F("student_count"))
            .count()
        )

    # ── recent activity (admin/owner only) ──────────────────────────
    recent_activity = []
    if not _is_teacher(request):
        audit_logs = AuditLog.objects.select_related("actor").order_by("-created_at", "-pk")[:8]
        for log in audit_logs:
            category, label = ACTION_LABELS.get(log.action, (log.action, log.description))
            recent_activity.append({
                "category": category,
                "label": label,
                "description": log.description,
                "actor": log.actor.get_full_name() or log.actor.username,
                "time": log.created_at,
                "action": log.action,
            })

    context = {
        "students_total": students["total"],
        "students_active": students["active"],
        "teachers_count": Teacher.objects.count(),
        "groups_active": active_groups.count(),
        "attendance_present": attendance["present"],
        "attendance_absent": attendance["absent"],
        "attendance_late": attendance["late"],
        "payments_total": payments_total,
        "payments_count": payments_count,
        "period_start": period_start,
        "recent_payments": recent_payments,
        "recent_attendance": attendance_qs.select_related("student", "lesson__group").order_by("-lesson__date", "-pk")[:5],
        "active_groups": active_groups,
        "today_lessons": today_lessons,
        "upcoming_lessons": upcoming_lessons,
        "attendance_pending": attendance_pending,
        "recent_lessons": recent_lessons,
        "is_teacher": _is_teacher(request),
        # ── new keys ─────────────────────────────
        "today": today,
        "today_display": today_display,
        "today_lessons_total": today_lessons_total,
        "today_lessons_completed": today_lessons_completed,
        "today_lessons_pending": today_lessons_pending,
        "upcoming_grouped": upcoming_grouped,
        "pending_attendance_count": pending_attendance_count,
        "attendance_total": attendance_total,
        "attendance_rate": attendance_rate,
        "recent_activity": recent_activity,
    }
    return render(request, "core/dashboard.html", context)
