import json
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDay, TruncMonth
from django.shortcuts import render
from django.utils import timezone
from django.utils.formats import date_format

from apps.accounts.models import UserRole
from apps.accounts.permissions import owner_required
from apps.education.materialize import materialize_range
from apps.education.models import (
    Attendance,
    AttendanceStatus,
    AuditLog,
    Enrollment,
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


LESSON_ROSTER_Q = Q(group__enrollments__started_at__lte=F("date")) & (
    Q(group__enrollments__ended_at__isnull=True) |
    Q(group__enrollments__ended_at__gte=F("date"))
)


def _occurred_lessons(queryset, now):
    today = timezone.localdate(now)
    current_time = timezone.localtime(now).time()
    return queryset.filter(Q(date__lt=today) | Q(date=today, end_time__lte=current_time))


def _attendance_metrics(lesson_queryset):
    rows = list(lesson_queryset.exclude(status=LessonStatus.CANCELLED).annotate(
        expected_count=Count("group__enrollments", filter=LESSON_ROSTER_Q, distinct=True),
        marked_count=Count("attendance_records", distinct=True),
        present_count=Count("attendance_records", filter=Q(attendance_records__status=AttendanceStatus.PRESENT), distinct=True),
        absent_count=Count("attendance_records", filter=Q(attendance_records__status=AttendanceStatus.ABSENT), distinct=True),
        late_count=Count("attendance_records", filter=Q(attendance_records__status=AttendanceStatus.LATE), distinct=True),
    ).values("expected_count", "marked_count", "present_count", "absent_count", "late_count"))
    expected = sum(row["expected_count"] for row in rows)
    marked = sum(min(row["marked_count"], row["expected_count"]) for row in rows)
    present = sum(row["present_count"] for row in rows)
    absent = sum(row["absent_count"] for row in rows)
    late = sum(row["late_count"] for row in rows)
    return {
        "expected": expected,
        "marked": marked,
        "unmarked": max(0, expected - marked),
        "present": present,
        "absent": absent,
        "late": late,
        "completion_rate": round(marked / expected * 100) if expected else None,
        "present_rate": round(present / expected * 100) if expected else None,
    }


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
    now = timezone.now()
    period_start = today.replace(day=1)
    next_month = (period_start + timedelta(days=32)).replace(day=1)

    today_weekday = WEEKDAYS_RU[today.weekday()]
    today_display = f"{today_weekday}, {date_format(today, 'j E Y')}"

    # ── role-scoped base querysets ──────────────────────────────────
    if _is_teacher(request):
        student_qs = Student.objects.filter(
            enrollments__group__teacher=request.user.teacher_profile,
            enrollments__status=EnrollmentStatus.ACTIVE,
        )
        group_qs = Group.objects.filter(teacher=request.user.teacher_profile, status=RecordStatus.ACTIVE)
        teacher = request.user.teacher_profile
        payments_total = Decimal("0")
        payments_count = 0
        recent_payments = Payment.objects.none()
    else:
        student_qs = Student.objects.all()
        group_qs = Group.objects.filter(status=RecordStatus.ACTIVE)
        month_stats = Payment.objects.filter(paid_at__gte=period_start, paid_at__lt=next_month).aggregate(
            total=Sum("amount", filter=Q(status=PaymentStatus.PAID)),
            count=Count("id", filter=Q(status=PaymentStatus.PAID)),
        )
        payments_total = (month_stats["total"] or Decimal("0")).quantize(Decimal("0.01"))
        payments_count = month_stats["count"] or 0
        recent_payments = Payment.objects.filter(status=PaymentStatus.PAID).select_related("student", "group__course").order_by("-paid_at", "-pk")[:5]

    # ── students / attendance aggregates ────────────────────────────
    students = student_qs.aggregate(
        total=Count("id", distinct=True),
        active=Count("id", filter=Q(status=RecordStatus.ACTIVE), distinct=True),
    )

    # ── active groups ───────────────────────────────────────────────
    active_groups = (
        group_qs.select_related("course", "teacher__user")
        .annotate(student_count=Count("enrollments", filter=Q(enrollments__status=EnrollmentStatus.ACTIVE), distinct=True))
        .order_by("name")
    )

    # Dashboard owns a small, bounded materialization horizon and therefore
    # never depends on Calendar having been opened first.
    materialize_to = today + timedelta(days=14)
    for group in active_groups:
        materialize_range(group, today, materialize_to)

    # ── lessons ─────────────────────────────────────────────────────
    lesson_qs = Lesson.objects.select_related("group__course", "group__teacher__user")
    if _is_teacher(request):
        teacher = request.user.teacher_profile
        lesson_qs = lesson_qs.filter(Q(teacher=teacher) | Q(teacher__isnull=True, group__teacher=teacher))

    attendance_lesson_qs = _occurred_lessons(
        lesson_qs.filter(date__gte=period_start, date__lt=next_month), now
    )
    attendance = _attendance_metrics(attendance_lesson_qs)
    attendance_qs = Attendance.objects.filter(lesson__in=attendance_lesson_qs)

    today_lessons = list(
        lesson_qs.filter(date=today)
        .annotate(marked=Count("attendance_records", distinct=True))
        .annotate(student_count=Count("group__enrollments", filter=LESSON_ROSTER_Q, distinct=True))
        .order_by("start_time")[:10]
    )

    today_lessons_total = len(today_lessons)
    today_lessons_completed = sum(1 for l in today_lessons if l.status == LessonStatus.COMPLETED)
    today_lessons_pending = [
        l for l in today_lessons
        if l.status != LessonStatus.CANCELLED and l.end_time <= timezone.localtime(now).time() and l.marked < l.student_count
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
    pending_queryset = (
        _occurred_lessons(lesson_qs.exclude(status=LessonStatus.CANCELLED), now)
        .annotate(marked=Count("attendance_records", distinct=True))
        .annotate(student_count=Count("group__enrollments", filter=LESSON_ROSTER_Q, distinct=True))
        .filter(marked__lt=F("student_count"))
        .order_by("date", "start_time")
    )
    attendance_pending = list(pending_queryset[:10])
    recent_lessons = []
    if _is_teacher(request):
        recent_lessons = list(
            lesson_qs.filter(date__lt=today)
            .annotate(marked=Count("attendance_records", distinct=True))
            .annotate(student_count=Count("group__enrollments", filter=LESSON_ROSTER_Q, distinct=True))
            .order_by("-date", "start_time")[:5]
        )

    # ── action required count (for all roles) ───────────────────────
    pending_attendance_count = pending_queryset.count()

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
        "teachers_count": Teacher.objects.filter(status=RecordStatus.ACTIVE).count(),
        "groups_active": active_groups.count(),
        "attendance_present": attendance["present"],
        "attendance_absent": attendance["absent"],
        "attendance_late": attendance["late"],
        "attendance_expected": attendance["expected"],
        "attendance_marked": attendance["marked"],
        "attendance_unmarked": attendance["unmarked"],
        "attendance_completion_rate": attendance["completion_rate"],
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
        "attendance_total": attendance["expected"],
        "attendance_rate": attendance["present_rate"],
        "recent_activity": recent_activity,
    }
    return render(request, "core/dashboard.html", context)


MONTH_NAMES_RU = {
    1: "Янв", 2: "Фев", 3: "Мар", 4: "Апр", 5: "Май", 6: "Июн",
    7: "Июл", 8: "Авг", 9: "Сен", 10: "Окт", 11: "Ноя", 12: "Дек",
}


def _parse_analytics_date(value):
    try:
        return timezone.datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_analytics_period(period, today, request):
    if period == "today":
        return today, today + timedelta(days=1)
    elif period == "this-week":
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1)
    elif period == "last-month":
        first_this = today.replace(day=1)
        return (first_this - timedelta(days=1)).replace(day=1), first_this
    elif period == "last-30-days":
        return today - timedelta(days=30), today + timedelta(days=1)
    elif period == "last-90-days":
        return today - timedelta(days=90), today + timedelta(days=1)
    elif period == "custom":
        df = _parse_analytics_date(request.GET.get("date_from"))
        dt = _parse_analytics_date(request.GET.get("date_to"))
        return (df or today.replace(day=1)), ((dt or today) + timedelta(days=1))
    else:
        start = today.replace(day=1)
        return start, (start + timedelta(days=32)).replace(day=1)


def _previous_period(date_from, date_to):
    length = (date_to - date_from).days
    prev_to = date_from
    return prev_to - timedelta(days=length), prev_to


PERIOD_LABELS = {
    "today": "Сегодня",
    "this-week": "Эта неделя",
    "this-month": "Этот месяц",
    "last-month": "Прошлый месяц",
    "last-30-days": "Последние 30 дней",
    "last-90-days": "Последние 90 дней",
    "custom": "Произвольный период",
}


@owner_required
def analytics_view(request):
    is_teacher = _is_teacher(request)
    today = timezone.localdate()
    period = request.GET.get("period", "this-month")
    if period not in PERIOD_LABELS:
        period = "this-month"

    period_error = None
    date_from, date_to = _parse_analytics_period(period, today, request)
    if period == "custom":
        raw_from = _parse_analytics_date(request.GET.get("date_from"))
        raw_to = _parse_analytics_date(request.GET.get("date_to"))
        if raw_from and raw_to and raw_from > raw_to:
            period_error = "Дата начала не может быть позже даты окончания."
            date_from = today.replace(day=1)
            date_to = (date_from + timedelta(days=32)).replace(day=1)
    prev_from, prev_to = _previous_period(date_from, date_to)

    period_label = PERIOD_LABELS.get(period, period)
    if period == "custom":
        period_label = f"{date_format(date_from, 'j E')} — {date_format(date_to - timedelta(days=1), 'j E')}"

    def _fmt(d):
        return d.strftime("%Y-%m-%d") if d else ""

    # ── base querysets ─────────────────────────────────────────────
    lesson_qs = Lesson.objects.all()
    attendance_qs = Attendance.objects.all()
    payment_qs = Payment.objects.all()
    enrollment_qs = Enrollment.objects.all()
    student_qs = Student.objects.all()

    if is_teacher:
        teacher = request.user.teacher_profile
        lesson_qs = lesson_qs.filter(Q(teacher=teacher) | Q(teacher__isnull=True, group__teacher=teacher))
        attendance_qs = attendance_qs.filter(
            Q(lesson__teacher=teacher) | Q(lesson__teacher__isnull=True, lesson__group__teacher=teacher)
        )
        payment_qs = payment_qs.none()
        enrollment_qs = enrollment_qs.filter(group__teacher=teacher)
        student_qs = student_qs.filter(
            enrollments__group__teacher=teacher,
            enrollments__status=EnrollmentStatus.ACTIVE,
        ).distinct()

    # ── KPI: lifetime counts ───────────────────────────────────────
    active_students = student_qs.filter(status=RecordStatus.ACTIVE).count() if not is_teacher else student_qs.count()
    active_groups = Group.objects.filter(status=RecordStatus.ACTIVE).count() if not is_teacher else Group.objects.filter(status=RecordStatus.ACTIVE, teacher=teacher).count()
    active_teachers = 1 if is_teacher else Teacher.objects.filter(status=RecordStatus.ACTIVE).count()
    new_students = Student.objects.filter(
        pk__in=student_qs.values("pk"), created_at__date__gte=date_from, created_at__date__lt=date_to
    ).count()
    ended_students = enrollment_qs.filter(
        ended_at__gte=date_from, ended_at__lt=date_to, status=EnrollmentStatus.ENDED
    ).values("student_id").distinct().count()

    # ── KPI: period-scoped ─────────────────────────────────────────
    period_lessons = lesson_qs.filter(date__gte=date_from, date__lt=date_to)
    lessons_count = period_lessons.count()
    lessons_completed = period_lessons.filter(status=LessonStatus.COMPLETED).count()
    lessons_cancelled = period_lessons.filter(status=LessonStatus.CANCELLED).count()
    lessons_scheduled = period_lessons.filter(status=LessonStatus.SCHEDULED).count()
    lessons_rescheduled = period_lessons.exclude(occurrence_date=F("date")).filter(occurrence_date__isnull=False).count()

    period_attendance = attendance_qs.filter(lesson__date__gte=date_from, lesson__date__lt=date_to)
    attendance_metrics = _attendance_metrics(_occurred_lessons(period_lessons, timezone.now()))
    att_present = attendance_metrics["present"]
    att_absent = attendance_metrics["absent"]
    att_late = attendance_metrics["late"]
    att_total = attendance_metrics["expected"]
    att_marked = attendance_metrics["marked"]
    att_unmarked = attendance_metrics["unmarked"]
    att_rate = attendance_metrics["present_rate"]
    att_completion_rate = attendance_metrics["completion_rate"]

    period_payments = payment_qs.filter(paid_at__gte=date_from, paid_at__lt=date_to, status=PaymentStatus.PAID)
    payments_sum = (period_payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")).quantize(Decimal("0.01"))
    payments_count = period_payments.count()

    pending_attendance = (
        _occurred_lessons(period_lessons.exclude(status=LessonStatus.CANCELLED), timezone.now())
        .annotate(marked=Count("attendance_records", distinct=True))
        .annotate(student_count=Count("group__enrollments", filter=LESSON_ROSTER_Q, distinct=True))
        .filter(marked__lt=F("student_count"))
        .count()
    )

    # ── previous period KPIs (for delta) ───────────────────────────
    prev_lessons = lesson_qs.filter(date__gte=prev_from, date__lt=prev_to)
    prev_lessons_count = prev_lessons.count()
    prev_lessons_completed = prev_lessons.filter(status=LessonStatus.COMPLETED).count()
    prev_lessons_cancelled = prev_lessons.filter(status=LessonStatus.CANCELLED).count()

    prev_metrics = _attendance_metrics(_occurred_lessons(
        lesson_qs.filter(date__gte=prev_from, date__lt=prev_to), timezone.now()
    ))
    prev_att_rate = prev_metrics["present_rate"]

    prev_payments = payment_qs.filter(paid_at__gte=prev_from, paid_at__lt=prev_to, status=PaymentStatus.PAID)
    prev_payments_sum = (prev_payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")).quantize(Decimal("0.01"))

    def _delta(current, previous):
        if previous is None or previous == 0:
            return None
        change = current - previous
        pct = round(change / abs(previous) * 100) if previous else None
        return {"value": change, "pct": pct}

    payments_delta = _delta(float(payments_sum), float(prev_payments_sum)) if prev_payments_sum > 0 or payments_sum > 0 else None
    lessons_delta = _delta(lessons_count, prev_lessons_count)
    att_delta = None
    if att_rate is not None and prev_att_rate is not None:
        att_delta = {"value": att_rate - prev_att_rate, "pct": None}

    # ── CHART: payment trend (daily) ───────────────────────────────
    payment_trend_raw = (
        payment_qs.filter(paid_at__gte=date_from, paid_at__lt=date_to, status=PaymentStatus.PAID)
        .annotate(day=TruncDay("paid_at"))
        .values("day")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("day")
    )
    payment_trend_labels = [date_format(r["day"], "j E") for r in payment_trend_raw]
    payment_trend_amounts = [float(r["total"] or 0) for r in payment_trend_raw]
    payment_trend_counts = [r["count"] for r in payment_trend_raw]

    # ── CHART: attendance doughnut ──────────────────────────────────
    # (att_present, att_absent, att_late already computed above)

    # ── CHART: lesson status donut ──────────────────────────────────
    lesson_status_data = [lessons_completed, lessons_scheduled, lessons_cancelled]

    # ── CHART: teacher workload ─────────────────────────────────────
    workload = {}
    for row in period_lessons.exclude(status=LessonStatus.CANCELLED).annotate(
        effective_teacher_id=Coalesce("teacher_id", "group__teacher_id"),
        effective_teacher_name=Coalesce("teacher__full_name", "group__teacher__full_name"),
    ).values("effective_teacher_id", "effective_teacher_name", "start_time", "end_time"):
        item = workload.setdefault(row["effective_teacher_id"], {"name": row["effective_teacher_name"] or "—", "hours": 0.0})
        start_seconds = row["start_time"].hour * 3600 + row["start_time"].minute * 60 + row["start_time"].second
        end_seconds = row["end_time"].hour * 3600 + row["end_time"].minute * 60 + row["end_time"].second
        item["hours"] += max(0, end_seconds - start_seconds) / 3600
    workload_rows = sorted(workload.values(), key=lambda item: item["hours"], reverse=True)[:10]
    tw_labels = [item["name"] for item in workload_rows]
    tw_data = [round(item["hours"], 1) for item in workload_rows]

    # ── CHART: group attendance rate ────────────────────────────────
    group_attendance_chart = {}
    for row in _occurred_lessons(period_lessons, timezone.now()).exclude(status=LessonStatus.CANCELLED).annotate(
        expected=Count("group__enrollments", filter=LESSON_ROSTER_Q, distinct=True),
        present=Count("attendance_records", filter=Q(attendance_records__status=AttendanceStatus.PRESENT), distinct=True),
    ).values("group_id", "group__name", "expected", "present"):
        item = group_attendance_chart.setdefault(row["group_id"], {"name": row["group__name"], "expected": 0, "present": 0})
        item["expected"] += row["expected"]
        item["present"] += row["present"]
    group_attendance_rows = sorted(group_attendance_chart.values(), key=lambda item: item["present"], reverse=True)[:15]
    ga_labels = [item["name"] for item in group_attendance_rows]
    ga_data = [round(item["present"] / item["expected"] * 100) if item["expected"] else 0 for item in group_attendance_rows]

    # ── CHART: revenue by group ─────────────────────────────────────
    revenue_by_group_raw = (
        payment_qs.filter(paid_at__gte=date_from, paid_at__lt=date_to, status=PaymentStatus.PAID)
        .values(group_name=F("group__name"), group_pk=F("group_id"))
        .annotate(total=Sum("amount"))
        .order_by("-total")[:10]
    )
    rbg_labels = [r["group_name"] for r in revenue_by_group_raw]
    rbg_data = [float(r["total"] or 0) for r in revenue_by_group_raw]

    # ── CHARTS: selected-period growth/revenue ──────────────────────
    students_raw = (
        Student.objects.filter(pk__in=student_qs.values("pk"), created_at__date__gte=date_from, created_at__date__lt=date_to)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )
    sg_labels = [MONTH_NAMES_RU[r["month"].month] for r in students_raw]
    sg_data = [r["count"] for r in students_raw]

    revenue_raw = (
        payment_qs.filter(status=PaymentStatus.PAID, paid_at__gte=date_from, paid_at__lt=date_to)
        .annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )
    rv_labels = [MONTH_NAMES_RU[r["month"].month] for r in revenue_raw]
    rv_data = [float(r["total"] or 0) for r in revenue_raw]

    # ── CHART: group fill rate (lifetime) ───────────────────────────
    groups_scope = Group.objects.filter(status=RecordStatus.ACTIVE)
    if is_teacher:
        groups_scope = groups_scope.filter(teacher=teacher)
    groups_fill_raw = (
        groups_scope
        .annotate(student_count=Count("enrollments", filter=Q(enrollments__status=EnrollmentStatus.ACTIVE), distinct=True))
        .filter(student_count__gte=1)
        .values("name", "student_count")
        .order_by("-student_count")[:15]
    )
    gf_labels = [r["name"] for r in groups_fill_raw]
    gf_data = [r["student_count"] for r in groups_fill_raw]

    # ── TABLE: top groups ───────────────────────────────────────────
    top_group_rows = list(groups_scope.select_related("teacher__user").annotate(
        sc=Count("enrollments", filter=Q(enrollments__status=EnrollmentStatus.ACTIVE), distinct=True)
    ).order_by("-sc")[:10])
    group_ids = [group.pk for group in top_group_rows]
    group_lesson_counts = dict(period_lessons.filter(group_id__in=group_ids).values_list("group_id").annotate(total=Count("id")))
    group_attendance = {}
    for row in _occurred_lessons(period_lessons.filter(group_id__in=group_ids), timezone.now()).exclude(
        status=LessonStatus.CANCELLED
    ).annotate(
        expected=Count("group__enrollments", filter=LESSON_ROSTER_Q, distinct=True),
        present=Count("attendance_records", filter=Q(attendance_records__status=AttendanceStatus.PRESENT), distinct=True),
    ).values("group_id", "expected", "present"):
        totals = group_attendance.setdefault(row["group_id"], [0, 0])
        totals[0] += row["expected"]
        totals[1] += row["present"]
    group_payments = dict(
        period_payments.filter(group_id__in=group_ids).values_list("group_id").annotate(total=Sum("amount"))
    ) if not is_teacher else {}
    top_groups = []
    for g in top_group_rows:
        expected, present = group_attendance.get(g.pk, (0, 0))
        payment_total = group_payments.get(g.pk, Decimal("0"))
        top_groups.append({
            "pk": g.pk,
            "name": g.name,
            "students": g.sc,
            "lessons": group_lesson_counts.get(g.pk, 0),
            "attendance_rate": round(present / expected * 100) if expected else None,
            "payments": payment_total.quantize(Decimal("0.01")),
        })

    # ── TABLE: teacher performance ──────────────────────────────────
    tp_qs = Teacher.objects.filter(status=RecordStatus.ACTIVE).select_related("user")
    if is_teacher:
        tp_qs = tp_qs.filter(user=request.user)
    teachers = list(tp_qs[:10])
    teacher_ids = [teacher.pk for teacher in teachers]
    teacher_lesson_stats = {}
    for row in period_lessons.annotate(
        effective_teacher_id=Coalesce("teacher_id", "group__teacher_id")
    ).filter(effective_teacher_id__in=teacher_ids).values("effective_teacher_id", "start_time", "end_time"):
        stats = teacher_lesson_stats.setdefault(row["effective_teacher_id"], [0, 0.0])
        stats[0] += 1
        start_seconds = row["start_time"].hour * 3600 + row["start_time"].minute * 60 + row["start_time"].second
        end_seconds = row["end_time"].hour * 3600 + row["end_time"].minute * 60 + row["end_time"].second
        stats[1] += max(0, end_seconds - start_seconds) / 3600
    teacher_groups = dict(Group.objects.filter(
        teacher_id__in=teacher_ids, status=RecordStatus.ACTIVE
    ).values_list("teacher_id").annotate(total=Count("id")))
    teacher_students = dict(Enrollment.objects.filter(
        group__teacher_id__in=teacher_ids, status=EnrollmentStatus.ACTIVE
    ).values_list("group__teacher_id").annotate(total=Count("student_id", distinct=True)))
    teacher_attendance = {}
    for row in _occurred_lessons(period_lessons, timezone.now()).exclude(status=LessonStatus.CANCELLED).annotate(
        effective_teacher_id=Coalesce("teacher_id", "group__teacher_id"),
        expected=Count("group__enrollments", filter=LESSON_ROSTER_Q, distinct=True),
        present=Count("attendance_records", filter=Q(attendance_records__status=AttendanceStatus.PRESENT), distinct=True),
    ).filter(effective_teacher_id__in=teacher_ids).values("effective_teacher_id", "expected", "present"):
        totals = teacher_attendance.setdefault(row["effective_teacher_id"], [0, 0])
        totals[0] += row["expected"]
        totals[1] += row["present"]
    teacher_perf = []
    for t in teachers:
        lesson_count, workload_hours = teacher_lesson_stats.get(t.pk, (0, 0.0))
        expected, present = teacher_attendance.get(t.pk, (0, 0))
        teacher_perf.append({
            "pk": t.pk,
            "name": t.full_name or t.user.get_full_name() or t.user.username,
            "groups": teacher_groups.get(t.pk, 0),
            "lessons": lesson_count,
            "workload_hours": round(workload_hours, 1),
            "students": teacher_students.get(t.pk, 0),
            "attendance_rate": round(present / expected * 100) if expected else None,
        })

    # ── TABLE: recent payments ──────────────────────────────────────
    recent_payments = []
    if not is_teacher:
        for p in payment_qs.filter(paid_at__gte=date_from, paid_at__lt=date_to, status=PaymentStatus.PAID).select_related("student", "group")[:10]:
            recent_payments.append({
                "pk": p.pk,
                "student": str(p.student),
                "group": str(p.group),
                "amount": p.amount,
                "paid_at": p.paid_at,
            })

    # ── has_data flag ───────────────────────────────────────────────
    period_has_data = lessons_count > 0 or payments_count > 0 or att_marked > 0
    system_has_entities = active_students > 0 or active_groups > 0 or active_teachers > 0
    has_data = system_has_entities or period_has_data

    context = {
        "period": period,
        "period_label": period_label,
        "date_from": date_from,
        "date_to": date_to - timedelta(days=1),
        "is_teacher": is_teacher,
        "has_data": has_data,
        "period_has_data": period_has_data,
        "system_has_entities": system_has_entities,
        "period_error": period_error,
        # ── KPI ────────────────────────────────────────────────────
        "active_students": active_students,
        "active_groups": active_groups,
        "active_teachers": active_teachers,
        "new_students": new_students,
        "ended_students": ended_students,
        "payments_sum": payments_sum,
        "payments_count": payments_count,
        "payments_delta": payments_delta,
        "lessons_count": lessons_count,
        "lessons_completed": lessons_completed,
        "lessons_cancelled": lessons_cancelled,
        "lessons_scheduled": lessons_scheduled,
        "lessons_rescheduled": lessons_rescheduled,
        "lessons_delta": lessons_delta,
        "att_rate": att_rate,
        "att_present": att_present,
        "att_absent": att_absent,
        "att_late": att_late,
        "att_total": att_total,
        "att_marked": att_marked,
        "att_unmarked": att_unmarked,
        "att_completion_rate": att_completion_rate,
        "att_delta": att_delta,
        "pending_attendance": pending_attendance,
        # ── charts: period-scoped ───────────────────────────────────
        "payment_trend_labels_json": json.dumps(payment_trend_labels),
        "payment_trend_amounts_json": json.dumps(payment_trend_amounts),
        "payment_trend_counts_json": json.dumps(payment_trend_counts),
        "lesson_status_data_json": json.dumps(lesson_status_data),
        "teacher_workload_labels_json": json.dumps(tw_labels),
        "teacher_workload_data_json": json.dumps(tw_data),
        "group_att_labels_json": json.dumps(ga_labels),
        "group_att_data_json": json.dumps(ga_data),
        "revenue_by_group_labels_json": json.dumps(rbg_labels),
        "revenue_by_group_data_json": json.dumps(rbg_data),
        # ── charts: lifetime ────────────────────────────────────────
        "students_labels_json": json.dumps(sg_labels),
        "students_data_json": json.dumps(sg_data),
        "revenue_labels_json": json.dumps(rv_labels),
        "revenue_data_json": json.dumps(rv_data),
        "groups_labels_json": json.dumps(gf_labels),
        "groups_data_json": json.dumps(gf_data),
        "groups_count": active_groups,
        # ── tables ──────────────────────────────────────────────────
        "top_groups": top_groups,
        "teacher_perf": teacher_perf,
        "recent_payments": recent_payments,
        # ── period options for template ──────────────────────────────
        "period_options": PERIOD_LABELS,
    }
    return render(request, "core/analytics.html", context)
