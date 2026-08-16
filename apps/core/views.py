from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.education.models import Attendance, AttendanceStatus, EnrollmentStatus, Group, Payment, PaymentStatus, RecordStatus, Student, Teacher


def _is_teacher(request) -> bool:
    return request.user.role == UserRole.TEACHER


@login_required
def dashboard(request):
    """Operational dashboard. TEACHER sees only their own groups and attendance; financial data is never exposed."""
    today = timezone.localdate()
    period_start = today.replace(day=1)

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
        recent_payments = Payment.objects.select_related("student", "group__course").order_by("-paid_at", "-pk")[:10]

    students = student_qs.aggregate(
        total=Count("id", distinct=True),
        active=Count("id", filter=Q(status=RecordStatus.ACTIVE), distinct=True),
    )

    attendance = attendance_qs.aggregate(
        present=Count("id", filter=Q(status=AttendanceStatus.PRESENT)),
        absent=Count("id", filter=Q(status=AttendanceStatus.ABSENT)),
        late=Count("id", filter=Q(status=AttendanceStatus.LATE)),
    )

    active_groups = (
        group_qs.select_related("course", "teacher__user")
        .annotate(student_count=Count("enrollments", filter=Q(enrollments__status=EnrollmentStatus.ACTIVE), distinct=True))
        .order_by("name")
    )

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
        "recent_attendance": attendance_qs.select_related("student", "lesson__group").order_by("-lesson__date", "-pk")[:10],
        "active_groups": active_groups,
    }
    return render(request, "core/dashboard.html", context)
