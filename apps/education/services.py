"""Recurring schedule → Lesson generation.

A Schedule is a weekly rule (weekday + time window). generate_lessons() turns
an explicit date window into concrete Lesson records, one per occurrence.

Idempotency contract: a date that already has a Lesson linked to this schedule
is never re-created. Teacher conflicts (overlapping lessons) are detected with
Lesson.full_clean() and skipped, not aborted, so a wide window can still be
generated if a single slot is already occupied.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Lesson, LessonStatus


class LessonGenerationResult:
    def __init__(self, created=0, skipped=0, conflicts=0, total=0):
        self.created = created
        self.skipped = skipped
        self.conflicts = conflicts
        self.total = total

    def __str__(self) -> str:
        return f"created={self.created} skipped={self.skipped} conflicts={self.conflicts}"


def scheduled_dates(schedule, date_from, date_to):
    """All dates in [date_from, date_to] falling on the schedule's weekday."""
    offset = (schedule.weekday - date_from.weekday()) % 7
    current = date_from + timedelta(days=offset)
    dates = []
    while current <= date_to:
        dates.append(current)
        current += timedelta(days=7)
    return dates


def _existing_dates(schedule, date_from, date_to):
    return set(
        Lesson.objects.filter(schedule=schedule, date__range=(date_from, date_to)).values_list("date", flat=True)
    )


def _probe_lesson(schedule, lesson_date):
    return Lesson(
        group=schedule.group,
        schedule=schedule,
        date=lesson_date,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        status=LessonStatus.SCHEDULED,
    )


def _would_conflict(schedule, lesson_date) -> bool:
    try:
        _probe_lesson(schedule, lesson_date).full_clean()
    except ValidationError:
        return True
    return False


def _validate_window(schedule, date_from, date_to) -> None:
    if date_from > date_to:
        raise ValidationError("Дата окончания не может быть раньше даты начала.")
    if not schedule.is_active:
        raise ValidationError("Нельзя генерировать занятия по неактивному расписанию.")


def preview_lessons(schedule, date_from, date_to) -> LessonGenerationResult:
    """Count what generate_lessons() would do without writing anything."""
    _validate_window(schedule, date_from, date_to)
    existing = _existing_dates(schedule, date_from, date_to)
    result = LessonGenerationResult()
    for lesson_date in scheduled_dates(schedule, date_from, date_to):
        result.total += 1
        if lesson_date in existing:
            result.skipped += 1
        elif _would_conflict(schedule, lesson_date):
            result.conflicts += 1
        else:
            result.created += 1
    return result


@transaction.atomic
def generate_lessons(schedule, date_from, date_to) -> LessonGenerationResult:
    """Create one Lesson per schedule occurrence in the window (idempotent)."""
    result = preview_lessons(schedule, date_from, date_to)
    if result.created:
        existing = _existing_dates(schedule, date_from, date_to)
        for lesson_date in scheduled_dates(schedule, date_from, date_to):
            if lesson_date in existing or _would_conflict(schedule, lesson_date):
                continue
            _probe_lesson(schedule, lesson_date).save()
    return result
