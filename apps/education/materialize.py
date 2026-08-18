"""Lazy materialization of Lesson records from Schedule rules + overrides.

On read, each schedule occurrence is turned into a real Lesson row if one
doesn't already exist.  Overrides (CANCELLED / RESCHEDULED / SUBSTITUTE)
are respected.  No cron, no Celery — just in-time DB writes behind a
transaction so concurrent readers never see partial state.
"""

from __future__ import annotations

from datetime import date, time
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.db.models import Q

from .models import (
    Lesson,
    LessonStatus,
    OverrideType,
    Schedule,
    ScheduleOverride,
    Teacher,
)


def _existing_lesson(schedule: Schedule, target_date: date) -> Optional[Lesson]:
    """Return existing Lesson for this schedule+date, or None."""
    try:
        return Lesson.objects.get(schedule=schedule, date=target_date)
    except Lesson.DoesNotExist:
        return None


def _create_lesson_from_schedule(
    schedule: Schedule,
    target_date: date,
    *,
    start_time: time | None = None,
    end_time: time | None = None,
    source: str = "NORMAL",
) -> Lesson:
    lesson = Lesson(
        group=schedule.group,
        schedule=schedule,
        date=target_date,
        start_time=start_time or schedule.start_time,
        end_time=end_time or schedule.end_time,
        status=LessonStatus.SCHEDULED,
        source=source,
    )
    lesson.save()
    return lesson


@transaction.atomic
def get_or_create_lesson(schedule: Schedule, target_date: date) -> Optional[Lesson]:
    """Materialize (or retrieve) a Lesson for one schedule occurrence.

    Returns None for CANCELLED dates.  For RESCHEDULED dates that fall
    within the same query window the caller should re-query the new date.
    """

    existing = _existing_lesson(schedule, target_date)
    if existing:
        return existing

    override = (
        ScheduleOverride.objects.filter(schedule=schedule, date=target_date)
        .select_related("substitute_teacher")
        .first()
    )

    if override:
        if override.override_type == OverrideType.CANCELLED:
            return None

        if override.override_type == OverrideType.RESCHEDULED:
            if override.new_date:
                return _create_lesson_from_schedule(
                    schedule,
                    override.new_date,
                    start_time=override.new_start_time,
                    end_time=override.new_end_time,
                    source="OVERRIDE",
                )
            return None

        if override.override_type == OverrideType.SUBSTITUTE:
            return _create_lesson_from_schedule(
                schedule,
                target_date,
                source="OVERRIDE",
            )

    return _create_lesson_from_schedule(schedule, target_date)


def effective_teacher(schedule: Schedule, target_date: date) -> Teacher:
    """Return the teacher who should teach on this date (handles SUBSTITUTE)."""
    override = ScheduleOverride.objects.filter(
        schedule=schedule, date=target_date, override_type=OverrideType.SUBSTITUTE
    ).select_related("substitute_teacher").first()
    if override and override.substitute_teacher_id:
        return override.substitute_teacher
    return schedule.group.teacher


def override_for_date(schedule: Schedule, target_date: date) -> Optional[ScheduleOverride]:
    """Return the ScheduleOverride for a schedule+date, or None."""
    return ScheduleOverride.objects.filter(schedule=schedule, date=target_date).select_related("substitute_teacher").first()


@transaction.atomic
def materialize_range(
    group,
    date_from: date,
    date_to: date,
) -> list[Lesson]:
    """Eagerly materialize ALL lessons for a group's active schedules in a date range.

    Only creates lessons for schedules that have both start_date and end_date
    set (bounded period).  Returns all lessons (including previously-existing
    ones) in the range.
    """
    schedules = Schedule.objects.filter(group=group, is_active=True).exclude(
        Q(start_date__isnull=True) | Q(end_date__isnull=True)
    )
    all_lessons: list[Lesson] = []

    for schedule in schedules:
        effective_from = max(date_from, schedule.start_date) if schedule.start_date else date_from
        effective_to = min(date_to, schedule.end_date) if schedule.end_date else date_to
        if effective_from > effective_to:
            continue
        for d in _scheduled_dates(schedule, effective_from, effective_to):
            lesson = get_or_create_lesson(schedule, d)
            if lesson is not None:
                all_lessons.append(lesson)

    return all_lessons


def _scheduled_dates(schedule: Schedule, date_from: date, date_to: date) -> list[date]:
    """All dates in [date_from, date_to] falling on the schedule's weekday."""
    from datetime import timedelta

    offset = (schedule.weekday - date_from.weekday()) % 7
    current = date_from + timedelta(days=offset)
    dates = []
    while current <= date_to:
        dates.append(current)
        current += timedelta(days=7)
    return dates
