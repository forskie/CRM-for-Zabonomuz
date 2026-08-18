from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.education.models import (
    Attendance,
    AttendanceStatus,
    AuditAction,
    AuditLog,
    Course,
    Enrollment,
    Group,
    Lesson,
    LessonStatus,
    Schedule,
    Student,
)
from apps.education.services import generate_lessons, preview_lessons, scheduled_dates


User = get_user_model()


class CalendarSchedulingBase(TestCase):
    password = "Secure-calendar-password-2026"

    def setUp(self):
        self.owner = User.objects.create_user("owner", password=self.password, role=UserRole.OWNER)
        self.admin = User.objects.create_user("admin", password=self.password, role=UserRole.ADMIN)
        self.teacher_a_user = User.objects.create_user("teacher_a", password=self.password, role=UserRole.TEACHER)
        self.teacher_b_user = User.objects.create_user("teacher_b", password=self.password, role=UserRole.TEACHER)
        self.teacher_a = self.teacher_a_user.teacher_profile
        self.teacher_b = self.teacher_b_user.teacher_profile
        course = Course.objects.create(name="English", default_monthly_fee=Decimal("300.00"))
        self.group_a = Group.objects.create(name="English A1", course=course, teacher=self.teacher_a, monthly_fee=Decimal("350.00"))
        self.group_b = Group.objects.create(name="English B1", course=course, teacher=self.teacher_b, monthly_fee=Decimal("420.00"))
        self.student = Student.objects.create(full_name="Алиев Рустам", phone="900123456")
        Enrollment.objects.create(student=self.student, group=self.group_a, started_at=date(2026, 8, 1))


class GenerationServiceTests(CalendarSchedulingBase):
    def setUp(self):
        super().setUp()
        self.schedule = Schedule.objects.create(group=self.group_a, weekday=0, start_time=time(18), end_time=time(19))

    def test_scheduled_dates_respects_weekday_and_range(self):
        dates = scheduled_dates(self.schedule, date(2026, 8, 3), date(2026, 8, 17))
        self.assertEqual(dates, [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17)])

    def test_generate_lessons_creates_weekly_occurrences(self):
        result = generate_lessons(self.schedule, date(2026, 8, 3), date(2026, 8, 17))
        self.assertEqual(result.created, 3)
        self.assertEqual(result.total, 3)
        lessons = Lesson.objects.filter(schedule=self.schedule).order_by("date")
        self.assertEqual([l.date for l in lessons], [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17)])
        self.assertTrue(all(l.start_time == time(18) and l.end_time == time(19) for l in lessons))
        self.assertTrue(all(l.status == LessonStatus.SCHEDULED for l in lessons))

    def test_generate_is_idempotent(self):
        first = generate_lessons(self.schedule, date(2026, 8, 3), date(2026, 8, 17))
        self.assertEqual(first.created, 3)
        second = generate_lessons(self.schedule, date(2026, 8, 3), date(2026, 8, 17))
        self.assertEqual(second.created, 0)
        self.assertEqual(second.skipped, 3)
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 3)

    def test_generate_skips_existing_dates(self):
        Lesson.objects.create(group=self.group_a, schedule=self.schedule, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        result = generate_lessons(self.schedule, date(2026, 8, 3), date(2026, 8, 17))
        self.assertEqual(result.created, 2)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 3)

    def test_generate_skips_teacher_conflicts(self):
        other_group = Group.objects.create(name="English C1", course=Course.objects.first(), teacher=self.teacher_a, monthly_fee=Decimal("300.00"))
        Lesson.objects.create(group=other_group, date=date(2026, 8, 10), start_time=time(18), end_time=time(19))
        result = generate_lessons(self.schedule, date(2026, 8, 3), date(2026, 8, 17))
        self.assertEqual(result.created, 2)
        self.assertEqual(result.conflicts, 1)
        self.assertEqual(result.skipped, 0)
        self.assertFalse(Lesson.objects.filter(schedule=self.schedule, date=date(2026, 8, 10)).exists())

    def test_preview_matches_generate(self):
        window = (date(2026, 8, 3), date(2026, 8, 24))
        preview = preview_lessons(self.schedule, *window)
        result = generate_lessons(self.schedule, *window)
        self.assertEqual(preview.created, result.created)
        self.assertEqual(preview.skipped, result.skipped)
        self.assertEqual(preview.conflicts, result.conflicts)
        self.assertEqual(preview.total, result.total)

    def test_generate_requires_active_schedule(self):
        self.schedule.is_active = False
        self.schedule.save()
        with self.assertRaises(ValidationError):
            generate_lessons(self.schedule, date(2026, 8, 3), date(2026, 8, 17))

    def test_generate_rejects_inverted_window(self):
        with self.assertRaises(ValidationError):
            generate_lessons(self.schedule, date(2026, 8, 17), date(2026, 8, 3))

    def test_unique_constraint_group_date_time(self):
        Lesson.objects.create(group=self.group_a, date=date(2026, 8, 18), start_time=time(18), end_time=time(19))
        with self.assertRaises(IntegrityError):
            Lesson.objects.create(group=self.group_a, date=date(2026, 8, 18), start_time=time(18), end_time=time(20))

    def test_unique_constraint_schedule_date(self):
        Lesson.objects.create(group=self.group_a, schedule=self.schedule, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        with self.assertRaises(IntegrityError):
            Lesson.objects.create(group=self.group_a, schedule=self.schedule, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))


class CalendarViewTests(CalendarSchedulingBase):
    def setUp(self):
        super().setUp()
        self.schedule_a = Schedule.objects.create(group=self.group_a, weekday=0, start_time=time(18), end_time=time(19))
        self.lesson_a = Lesson.objects.create(group=self.group_a, schedule=self.schedule_a, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        self.lesson_b = Lesson.objects.create(group=self.group_b, date=date(2026, 8, 18), start_time=time(18), end_time=time(19))

    def _get(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse("education:calendar"), params)

    def test_admin_day_view(self):
        response = self._get(self.admin, view="day", date="2026-08-17")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group_a.name)

    def test_admin_week_view(self):
        response = self._get(self.admin, view="week", date="2026-08-17")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group_a.name)
        self.assertContains(response, self.group_b.name)

    def test_admin_month_view(self):
        response = self._get(self.admin, view="month", date="2026-08-01")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group_a.name)
        self.assertContains(response, self.group_b.name)

    def test_invalid_mode_falls_back_to_week(self):
        response = self._get(self.admin, view="bogus", date="2026-08-17")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["view_mode"], "week")

    def test_teacher_sees_only_own_lessons(self):
        response = self._get(self.teacher_a_user, view="week", date="2026-08-17")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group_a.name)
        self.assertNotContains(response, self.group_b.name)

    def test_group_filter_for_admin(self):
        response = self._get(self.admin, view="week", date="2026-08-17", group=self.group_b.pk)
        self.assertEqual(response.status_code, 200)
        lesson_pks = [l.pk for lessons in response.context["lessons_by_day"].values() for l in lessons]
        self.assertIn(self.lesson_b.pk, lesson_pks)
        self.assertNotIn(self.lesson_a.pk, lesson_pks)

    def test_day_view_empty_state(self):
        response = self._get(self.admin, view="day", date="2026-08-20")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Занятий в этот день нет.")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("education:calendar"))
        self.assertIn(response.status_code, (302, 403))


class ScheduleGenerateViewTests(CalendarSchedulingBase):
    def setUp(self):
        super().setUp()
        self.schedule = Schedule.objects.create(group=self.group_a, weekday=0, start_time=time(18), end_time=time(19), start_date=date(2026, 8, 3), end_date=date(2026, 8, 17))

    def _post(self, user, data):
        self.client.force_login(user)
        return self.client.post(reverse("education:schedule-generate", args=[self.schedule.pk]), data)

    def test_admin_can_open_generate_page(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("education:schedule-generate", args=[self.schedule.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Генерация занятий")

    def test_generate_requires_operational_role(self):
        self.assertEqual(self._post(self.teacher_a_user, {"date_from": "2026-08-03", "date_to": "2026-08-17"}).status_code, 403)

    def test_preview_does_not_create_lessons(self):
        response = self._post(self.admin, {"date_from": "2026-08-03", "date_to": "2026-08-17", "preview": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"].created, 3)
        self.assertEqual(Lesson.objects.count(), 0)

    def test_generate_creates_lessons_and_audits(self):
        response = self._post(self.admin, {"date_from": "2026-08-03", "date_to": "2026-08-17"})
        self.assertRedirects(response, reverse("education:group-detail", args=[self.group_a.pk]))
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 3)
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.SCHEDULE_GENERATE)
        self.assertEqual(log.target_type, "Schedule")
        self.assertEqual(log.target_id, self.schedule.pk)

    def test_generate_twice_keeps_lessons_single(self):
        self._post(self.admin, {"date_from": "2026-08-03", "date_to": "2026-08-17"})
        self._post(self.admin, {"date_from": "2026-08-03", "date_to": "2026-08-17"})
        self.assertEqual(Lesson.objects.filter(schedule=self.schedule).count(), 3)

    def test_generate_inactive_schedule_is_404(self):
        self.schedule.is_active = False
        self.schedule.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("education:schedule-generate", args=[self.schedule.pk])).status_code, 404)


class LessonRescheduleTests(CalendarSchedulingBase):
    def setUp(self):
        super().setUp()
        self.lesson = Lesson.objects.create(group=self.group_a, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))

    def _post(self, user, lesson=None, **data):
        self.client.force_login(user)
        return self.client.post(reverse("education:lesson-reschedule", args=[(lesson or self.lesson).pk]), data)

    def test_admin_reschedules_lesson_and_audits(self):
        response = self._post(self.admin, date="2026-08-19", start_time="10:00", end_time="11:00")
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.date, date(2026, 8, 19))
        self.assertEqual(self.lesson.start_time, time(10))
        self.assertEqual(self.lesson.end_time, time(11))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.LESSON_RESCHEDULE)
        self.assertEqual(log.target_id, self.lesson.pk)

    def test_reschedule_requires_operational_role(self):
        self.assertEqual(self._post(self.teacher_a_user, date="2026-08-19", start_time="10:00", end_time="11:00").status_code, 403)

    def test_reschedule_rejects_teacher_conflict(self):
        other_group = Group.objects.create(name="English C1", course=Course.objects.first(), teacher=self.teacher_a, monthly_fee=Decimal("300.00"))
        Lesson.objects.create(group=other_group, date=date(2026, 8, 19), start_time=time(10), end_time=time(11))
        response = self._post(self.admin, date="2026-08-19", start_time="10:00", end_time="11:00")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "пересекается")
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.date, date(2026, 8, 17))

    def test_reschedule_rejects_group_slot_conflict(self):
        Lesson.objects.create(group=self.group_a, date=date(2026, 8, 19), start_time=time(10), end_time=time(11))
        response = self._post(self.admin, date="2026-08-19", start_time="10:00", end_time="11:00")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже есть занятие этой группы")
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.date, date(2026, 8, 17))

    def test_reschedule_rejects_cancelled_lesson(self):
        self.lesson.status = LessonStatus.CANCELLED
        self.lesson.save()
        response = self._post(self.admin, date="2026-08-19", start_time="10:00", end_time="11:00")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Нельзя переносить отменённое занятие")
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.CANCELLED)

    def test_reschedule_rejects_inverted_time(self):
        response = self._post(self.admin, date="2026-08-19", start_time="11:00", end_time="10:00")
        self.assertEqual(response.status_code, 200)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.start_time, time(18))


class LessonReportTests(CalendarSchedulingBase):
    def setUp(self):
        super().setUp()
        self.lesson = Lesson.objects.create(group=self.group_a, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        self.foreign_lesson = Lesson.objects.create(group=self.group_b, date=date(2026, 8, 18), start_time=time(18), end_time=time(19))

    def _post(self, user, lesson, **data):
        self.client.force_login(user)
        return self.client.post(reverse("education:lesson-report", args=[lesson.pk]), data)

    def test_teacher_writes_report_for_own_lesson(self):
        response = self._post(self.teacher_a_user, self.lesson, topic="Present Perfect", teacher_note="Хорошо", homework="Упражнения 4–6")
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.topic, "Present Perfect")
        self.assertEqual(self.lesson.teacher_note, "Хорошо")
        self.assertEqual(self.lesson.homework, "Упражнения 4–6")
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.LESSON_REPORT)
        self.assertEqual(log.target_id, self.lesson.pk)

    def test_teacher_cannot_report_foreign_lesson(self):
        self.assertEqual(self._post(self.teacher_a_user, self.foreign_lesson, topic="X").status_code, 404)

    def test_admin_reports_any_lesson(self):
        response = self._post(self.admin, self.foreign_lesson, topic="Тема")
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.foreign_lesson.pk]))
        self.foreign_lesson.refresh_from_db()
        self.assertEqual(self.foreign_lesson.topic, "Тема")

    def test_report_rejected_for_cancelled_lesson(self):
        self.lesson.status = LessonStatus.CANCELLED
        self.lesson.save()
        response = self._post(self.admin, self.lesson, topic="X")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Нельзя редактировать отчёт отменённого занятия")
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.topic, "")

    def test_report_page_shows_report_fields(self):
        self.lesson.topic = "Present Perfect"
        self.lesson.homework = "Упражнения"
        self.lesson.save()
        self.client.force_login(self.teacher_a_user)
        response = self.client.get(reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.assertContains(response, "Present Perfect")
        self.assertContains(response, "Отчёт о занятии")


class LessonCompleteTests(CalendarSchedulingBase):
    def setUp(self):
        super().setUp()
        self.lesson = Lesson.objects.create(group=self.group_a, date=date(2026, 8, 17), start_time=time(18), end_time=time(19))
        self.foreign_lesson = Lesson.objects.create(group=self.group_b, date=date(2026, 8, 18), start_time=time(18), end_time=time(19))
        Attendance.objects.create(lesson=self.lesson, student=self.student, status=AttendanceStatus.PRESENT)
        foreign_student = Student.objects.create(full_name="Чужой ученик", phone="900999999")
        Enrollment.objects.create(student=foreign_student, group=self.group_b, started_at=date(2026, 8, 1))
        Attendance.objects.create(lesson=self.foreign_lesson, student=foreign_student, status=AttendanceStatus.PRESENT)

    def _post(self, user, lesson):
        self.client.force_login(user)
        return self.client.post(reverse("education:lesson-complete", args=[lesson.pk]))

    def test_teacher_completes_own_lesson(self):
        response = self._post(self.teacher_a_user, self.lesson)
        self.assertRedirects(response, reverse("education:lesson-detail", args=[self.lesson.pk]))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.COMPLETED)
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.LESSON_COMPLETE)
        self.assertEqual(log.target_id, self.lesson.pk)

    def test_teacher_cannot_complete_foreign_lesson(self):
        self.assertEqual(self._post(self.teacher_a_user, self.foreign_lesson).status_code, 404)
        self.foreign_lesson.refresh_from_db()
        self.assertEqual(self.foreign_lesson.status, LessonStatus.SCHEDULED)

    def test_admin_completes_any_lesson(self):
        self.assertEqual(self._post(self.admin, self.foreign_lesson).status_code, 302)
        self.foreign_lesson.refresh_from_db()
        self.assertEqual(self.foreign_lesson.status, LessonStatus.COMPLETED)

    def test_complete_rejects_get(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("education:lesson-complete", args=[self.lesson.pk])).status_code, 403)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, LessonStatus.SCHEDULED)

    def test_complete_rejects_already_completed(self):
        self.lesson.status = LessonStatus.COMPLETED
        self.lesson.save()
        self.assertEqual(self._post(self.admin, self.lesson).status_code, 403)

    def test_complete_rejects_cancelled(self):
        self.lesson.status = LessonStatus.CANCELLED
        self.lesson.save()
        self.assertEqual(self._post(self.admin, self.lesson).status_code, 403)


class NewAuditActionTests(CalendarSchedulingBase):
    def test_lesson_create_edit_and_status_audited(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:lesson-create"), {"group": self.group_a.pk, "date": "2026-08-20", "start_time": "18:00", "end_time": "19:00"})
        lesson = Lesson.objects.get(date=date(2026, 8, 20))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.LESSON_CREATE)
        self.client.post(reverse("education:lesson-edit", args=[lesson.pk]), {"group": self.group_a.pk, "date": "2026-08-21", "start_time": "18:00", "end_time": "19:00"})
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.LESSON_EDIT)
        self.assertEqual(log.target_id, lesson.pk)

    def test_lesson_status_cancel_and_complete_audited(self):
        lesson = Lesson.objects.create(group=self.group_a, date=date(2026, 8, 20), start_time=time(18), end_time=time(19))
        self.client.force_login(self.admin)
        self.client.post(reverse("education:lesson-status", args=[lesson.pk, LessonStatus.CANCELLED]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.LESSON_CANCEL)
        lesson.status = LessonStatus.SCHEDULED
        lesson.save()
        self.client.post(reverse("education:lesson-status", args=[lesson.pk, LessonStatus.COMPLETED]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.LESSON_COMPLETE)

    def test_lesson_status_unchanged_not_audited(self):
        lesson = Lesson.objects.create(group=self.group_a, date=date(2026, 8, 20), start_time=time(18), end_time=time(19))
        self.client.force_login(self.admin)
        self.client.post(reverse("education:lesson-status", args=[lesson.pk, LessonStatus.SCHEDULED]))
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_schedule_create_edit_deactivate_audited(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("education:schedule-create", args=[self.group_a.pk]), {"weekday": 1, "start_time": "18:00", "end_time": "19:00", "is_active": "on"})
        schedule = Schedule.objects.get(group=self.group_a)
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.SCHEDULE_CREATE)
        self.client.post(reverse("education:schedule-edit", args=[schedule.pk]), {"weekday": 2, "start_time": "18:00", "end_time": "19:00", "is_active": "on"})
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.SCHEDULE_EDIT)
        self.client.post(reverse("education:schedule-deactivate", args=[schedule.pk]))
        log = AuditLog.objects.latest("pk")
        self.assertEqual(log.action, AuditAction.SCHEDULE_DEACTIVATE)
        self.assertEqual(log.target_id, schedule.pk)

    def test_schedule_period_fields_are_saved(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("education:schedule-create", args=[self.group_a.pk]),
            {"weekday": 1, "start_time": "18:00", "end_time": "19:00", "is_active": "on", "start_date": "2026-08-03", "end_date": "2026-08-31"},
        )
        schedule = Schedule.objects.get(group=self.group_a)
        self.assertEqual(schedule.start_date, date(2026, 8, 3))
        self.assertEqual(schedule.end_date, date(2026, 8, 31))


class DashboardSchedulingTests(CalendarSchedulingBase):
    def setUp(self):
        super().setUp()
        self.today = date.today()

    def test_owner_dashboard_has_today_and_upcoming_lessons(self):
        Lesson.objects.create(group=self.group_a, date=self.today, start_time=time(18), end_time=time(19))
        future = Lesson.objects.create(group=self.group_a, date=self.today + timedelta(days=2), start_time=time(18), end_time=time(19))
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(future, response.context["upcoming_lessons"])
        self.assertEqual(len(response.context["today_lessons"]), 1)
        self.assertContains(response, "Занятия сегодня")

    def test_teacher_dashboard_attendance_pending_and_recent(self):
        today_lesson = Lesson.objects.create(group=self.group_a, date=self.today, start_time=time(18), end_time=time(19))
        past_lesson = Lesson.objects.create(group=self.group_a, date=self.today - timedelta(days=3), start_time=time(18), end_time=time(19), status=LessonStatus.COMPLETED)
        foreign_pending = Lesson.objects.create(group=self.group_b, date=self.today, start_time=time(18), end_time=time(19))
        self.client.force_login(self.teacher_a_user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        pending = [l.pk for l in response.context["attendance_pending"]]
        self.assertIn(today_lesson.pk, pending)
        self.assertNotIn(foreign_pending.pk, pending)
        recent = [l.pk for l in response.context["recent_lessons"]]
        self.assertIn(past_lesson.pk, recent)
        self.assertContains(response, "Ожидают отметки посещаемости")
        self.assertNotContains(response, self.group_b.name)

    def test_teacher_dashboard_has_no_tjs(self):
        self.client.force_login(self.teacher_a_user)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "TJS")
