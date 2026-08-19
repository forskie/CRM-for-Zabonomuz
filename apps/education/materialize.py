"""Authoritative Schedule -> Lesson occurrence reconciliation."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from .models import Lesson, LessonStatus, OverrideType, Schedule, ScheduleOverride, Teacher


def override_for_date(schedule: Schedule, target_date: date) -> Optional[ScheduleOverride]:
    return ScheduleOverride.objects.filter(schedule=schedule, date=target_date).select_related("substitute_teacher").first()


def effective_teacher(schedule: Schedule, target_date: date) -> Teacher:
    override = override_for_date(schedule, target_date)
    if override and override.override_type == OverrideType.SUBSTITUTE and override.substitute_teacher_id:
        return override.substitute_teacher
    return schedule.group.teacher


@transaction.atomic
def reconcile_occurrence(schedule: Schedule, occurrence_date: date) -> Optional[Lesson]:
    """Create or reconcile one occurrence idempotently; completed history is stable."""
    schedule = Schedule.objects.select_for_update().select_related("group__teacher").get(pk=schedule.pk)
    override = override_for_date(schedule, occurrence_date)
    lesson = Lesson.objects.select_for_update().filter(schedule=schedule, occurrence_date=occurrence_date).first()
    if lesson is None:
        lesson = Lesson.objects.select_for_update().filter(
            schedule=schedule, occurrence_date__isnull=True, date=occurrence_date
        ).first()
    if lesson and lesson.status == LessonStatus.COMPLETED:
        return lesson

    effective_date = occurrence_date
    start_time = schedule.start_time
    end_time = schedule.end_time
    status = LessonStatus.SCHEDULED
    teacher = schedule.group.teacher
    source = "NORMAL"
    if override:
        source = "OVERRIDE"
        if override.override_type == OverrideType.CANCELLED:
            status = LessonStatus.CANCELLED
        elif override.override_type == OverrideType.RESCHEDULED:
            if not (override.new_date and override.new_start_time and override.new_end_time):
                return lesson
            effective_date = override.new_date
            start_time = override.new_start_time
            end_time = override.new_end_time
        elif override.override_type == OverrideType.SUBSTITUTE and override.substitute_teacher_id:
            teacher = override.substitute_teacher

    candidate = lesson or Lesson(group=schedule.group, schedule=schedule)
    candidate.group = schedule.group
    candidate.schedule = schedule
    candidate.occurrence_date = occurrence_date
    candidate.date = effective_date
    candidate.start_time = start_time
    candidate.end_time = end_time
    candidate.status = status
    candidate.teacher = teacher
    candidate.source = source
    try:
        candidate.full_clean()
        # A savepoint keeps the outer reconciliation transaction usable if a
        # concurrent worker wins the uniqueness race.
        with transaction.atomic():
            candidate.save()
    except (ValidationError, IntegrityError):
        return None
    return candidate


def get_or_create_lesson(schedule: Schedule, target_date: date) -> Optional[Lesson]:
    return reconcile_occurrence(schedule, target_date)


@transaction.atomic
def materialize_range(group, date_from: date, date_to: date) -> list[Lesson]:
    schedules = Schedule.objects.filter(group=group, is_active=True).exclude(
        Q(start_date__isnull=True) | Q(end_date__isnull=True)
    ).select_related("group__teacher")
    lessons: list[Lesson] = []
    for schedule in schedules:
        effective_from = max(date_from, schedule.start_date)
        effective_to = min(date_to, schedule.end_date)
        if effective_from > effective_to:
            continue
        for occurrence_date in _scheduled_dates(schedule, effective_from, effective_to):
            lesson = reconcile_occurrence(schedule, occurrence_date)
            if lesson is not None:
                lessons.append(lesson)
    return lessons


def _scheduled_dates(schedule: Schedule, date_from: date, date_to: date) -> list[date]:
    offset = (schedule.weekday - date_from.weekday()) % 7
    current = date_from + timedelta(days=offset)
    dates = []
    while current <= date_to:
        dates.append(current)
        current += timedelta(days=7)
    return dates
