# Этап 14 — Production Hardening + Business QA. Итоговый отчёт

**Проект:** Django CRM образовательного центра (Dushanbe)
**Дата:** 2026-08-16
**Среда проверки:** Docker Compose, web (Django 5.2.17, Python 3.12.14, gunicorn 3 workers) + db (PostgreSQL 16.14) + nginx 1.27-alpine.
**Команда прогона тестов:** `docker compose exec -T web python manage.py test --parallel` (PostgreSQL)

---

## 0. Итог

- **Тесты:** `Ran 257 tests` — **OK** (0 failures / 0 errors). База этого этапа — 251 тест, добавлено 6 новых регрессионных.
- `python manage.py check` — OK (0 silenced).
- `makemigrations --check --dry-run` — «No changes detected» (миграций-дрейфа нет, 0009 применена).
- **Статус:** CRM **READY** к передаче пользователю в Django-окружении; продакшен-развёртывание требует только инфраструктурных шагов (HTTPS/HSTS, реальные секреты, бэкапы — см. раздел 14 и 17).
- **Найден и исправлен 1 реальный дефект производительности** (N+1 на странице занятия, раздел 15); **не найдено** функциональных бизнес-багов, блокирующих использование.

---

## 1. Целостность полного бизнес-цикла

Проверено end-to-end через HTTP (тесты + ручная проверка шаблонов):

`Course → Group → Enrollment → Schedule → генерация Lessons → Attendance → Complete → Teacher Report → Payment`, а также `Student → Group → Payment`, `Teacher → Group → Lesson → Attendance`.

- Единственный источник правды — БД; страницы (dashboard, group/student/lesson/payment detail, calendar) строятся запросами к ней.
- Повторная генерация занятий идемпотентна (дубликаты не создаются).
- Все записи связаны через FK с `PROTECT`; случайное удаление родительских записей блокируется (раздел 12).

## 2. Полный рабочий процесс владельца (HTTP)

Покрыт `test_business_workflows.py::FullBusinessCycleTests` — полный цикл с проверкой redirect/redirect-URL, состояния БД и консистентности dashboard после каждого шага. Все шаги заканчиваются корректным redirect и видимыми данными в БД.

## 3. Расписание → Генерация занятий

- Preview (`preview_lessons`) и генерация (`generate_lessons`, `services.py`) с окном дат, идемпотентностью и детекцией конфликтов преподавателя.
- Конфликтующие слоты пропускаются, а не прерывают генерацию всего окна.
- Деактивированное расписание невозможно генерировать (проверка в сервисе и в view).
- UI: страница `schedule_generate.html` с предзаполненным окном из `start_date`/`end_date`, кнопками «Предпросмотр» и «Создать занятия», списком конфликтов.

## 4. Жизненный цикл занятия

Create / Edit / Cancel / Complete / Report / Reschedule — все операции аудируются (добавлены `LESSON_CREATE/EDIT`, `LESSON_CANCEL/COMPLETE`, `LESSON_REPORT`, `LESSON_RESCHEDULE`). Отмена/завершение идемпотентны (повторный POST не дублирует аудит). Завершить можно только SCHEDULED-занятие; отменённое занятие не редактируется (отчёт, перенос, посещаемость).

## 5. Жизненный цикл посещаемости

- Отметка/переотметка через `AttendanceBulkForm` (поля генерируются сервером по активным ученикам; поддельные student_id в POST игнорируются).
- Отменённое занятие — посещаемость неизменяема (и форма, и модель блокируют).
- Завершённое занятие — корректировать можно (**новый регрессионный тест**).
- Дубликат (lesson+student) невозможен: unique constraint + `get_or_create`.
- Ученик без активного зачисления не может получить отметку (проверка модели при создании).
- Summary считается по активным ученикам, история (включая завершивших обучение) сохраняется в present/absent/late (**новый тест на семантику**).

## 6. Целостность данных

Дубликатов нет: unique constraints в БД (`unique_lesson_group_date_time`, `unique_lesson_schedule_date`, `unique_attendance_per_lesson_student`, `unique_active_enrollment_per_student_group`, `payment_amount_positive`, `enrollment_status_matches_end_date`). Проверка `makemigrations --check` — чисто, схема БД соответствует моделям.

## 7. Платежи

Create / Edit / Cancel. Повторная отмена не дублирует аудит. Подделанные student/group в POST бесполезны (disabled-поля + проверка истории зачислений в `PaymentForm.clean` и `Payment.clean`). Прямой URL без зачисления → ошибка. Сумма > 0 на уровне БД (CheckConstraint) и модели.

## 8. Зачисления

Создание (старт), завершение (status=ENDED + ended_at). Повторное завершение блокируется проверками модели. Некорректные даты (ended_at < started_at) отклоняются. Завершённое зачисление не блокирует историю посещаемости/платежей.

## 9. Ученики / преподаватели / курсы

CRUD, архив/восстановление, валидация телефона, статусы. Роль TEACHER видит только свой scope (списки, детали, календарь, занятия); финансовая информация скрыта в шаблонах для TEACHER.

## 10. AuditLog

- Все бизнес-действия пишут запись: платежи, посещаемость, зачисления, ученики, занятия, расписания (включая генерацию).
- Log append-only: `save()` модели AuditLog запрещает изменение существующих записей; UI не предоставляет удаления/редактирования.
- Прямой POST на удаление не существует (нет URL/view); прямой запрос на модификацию отбивается проверкой в `audit.py`.
- Отображение: страница аудита с пагинацией и select_related.

## 11. Dashboard

- Метрики считаются запросами к БД и совпадают с реальным состоянием (тест сверяет каждый блок с агрегатами БД).
- Для TEACHER — изоляция по своим группам, без финансовых данных.
- Период платежей на dashboard = текущий месяц (period = 1-е число месяца, учитываются только PAID) — зафиксировано как бизнес-правило тестами.

## 12. Целостность данных (ProtectedError, атомарность)

- `PROTECT`-FK защищают от каскадных удалений с потерями.
- **Атомарность генерации:** `generate_lessons` обёрнута в `transaction.atomic`; **новый тест** симулирует частичный отказ на 2-м занятии (monkeypatch `Lesson.save`) и подтверждает полный откат — в БД не остаётся «полу-созданных» занятий.

## 13. Поиск, фильтры, пагинация

Списки учеников/групп/курсов/занятий/платежей поддерживают поиск/фильтры по статусам, курсам, преподавателям, датам; пагинация сохраняет query-string. Для TEACHER фильтры корректно скрыты. Существующие тесты (search/filters, e2e) подтверждают поведение.

## 14. Производственная конфигурация — ПРОВЕРЕНО

Запуск с `DJANGO_DEBUG=False` (временный compose-override, затем восстановлен dev-режим):

| Проверка | Результат |
|---|---|
| `python manage.py check` при DEBUG=False | OK |
| gunicorn стартует, migrate+collectstatic выполняются | OK |
| `GET /health/` | 200 |
| `GET /` (защищённая) аноним | 302 → login |
| `GET /nonexistent-xyz/` | кастомный шаблон **404** (base.html + «404 — Страница не найдена») |
| `GET /static/css/crm.css` | 200 (28704 байт, nginx) |
| `/tmp` бэкап/restore (раздел 17) | OK |

Параметры настроек: `SECRET_KEY` обязателен из env при DEBUG=False; `ALLOWED_HOSTS` из env; `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` включаются автоматически; `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY`, `X_FRAME_OPTIONS=DENY`; HSTS opt-in (`DJANGO_SECURE_HSTS_SECONDS`); `SECURE_PROXY_SSL_HEADER` для https за nginx. В compose: `restart: unless-stopped`, healthcheck-и (db/web/nginx), gunicorn `--workers 3`, static/media volumes. Шаблоны 403/404/500 используют `base.html`.

**Перед реальным деплоем:** `DJANGO_DEBUG=False`, реальные `DJANGO_SECRET_KEY`/`POSTGRES_PASSWORD`, `DJANGO_ALLOWED_HOSTS`+`DJANGO_CSRF_TRUSTED_ORIGINS`, включить HSTS, поднять HTTPS (nginx + TLS).

## 15. Производительность — НАЙДЕН И ИСПРАВЛЕН ДЕФЕКТ (N+1)

### BUG-001 — N+1 на странице занятия (lesson_detail)

- **ROOT CAUSE:** в шаблоне (ветка для TEACHER) записи посещаемости запрашивались повторно `lesson.attendance_records.all` без `select_related("student")` → **1 запрос на каждую запись × ученика**. Плюс summary считался **7 отдельными запросами** (4× `records.filter(status=...).count()` + 2× `active_students()` + 1× `records.filter(student__in=...)`).
- **MINIMAL FIX** (`apps/education/views.py:lesson_detail`): записи грузятся один раз — `lesson.attendance_records.select_related("student").all()`, summary вычисляется в Python по загруженным данным (та же бизнес-семантика), в контекст передаётся `attendance_records`; шаблон использует контекстную переменную вместо повторного queryset.
- **REGRESSION TESTS:** `test_stage14_regressions.py::LessonDetailQueryStabilityTests` — для OWNER и TEACHER при росте данных (30 студентов + 30 записей) число запросов не растёт (< 5 прироста).

Прочие страницы уже оптимизированы: dashboard/calendar/lesson_list/group_list/student_detail/payments/audit используют `select_related`/`annotate`; на списки действует `QueryCountStabilityTests` (small vs large). Новых N+1 не обнаружено.

## 16. UI/UX

Тёмная/светлая тема (localStorage + prefers-color-scheme), адаптивность, sidebar, кастомная Grunge-стилистика (crm.css). Действия ролевые: TEACHER — только «Завершить занятие», «Заполнить отчёт», посещаемость — только просмотр; OWNER/ADMIN — полный набор кнопок. Пустые состояния, бейджи статусов, errorlist'ы форм, пагинация. Поток «Расписание → Генерация» очевиден (кнопки на странице группы + Preview/Submit на schedule_generate).

## 17. Стратегия резервного копирования

**Статус: NOT IMPLEMENTED** (в docker-compose нет автоматического бэкапа — нет volume для дампов, нет job/cron).

Проверена возможность ручного бэкапа и восстановления (не деструктивно, в тестовую БД):
- `pg_dump` (PostgreSQL 16.14) доступен; дамп рабочей БД — ~59 КБ.
- Восстановление в новую БД `education_crm_restore_test`: успех, 20 таблиц, счётчики записей совпали с источником; тестовая БД удалена.

Рекомендация (не внедрялась по правилам этапа — «не внедрять новую сложную инфраструктуру»): ежедневный `pg_dump` через cron на хосте или service в docker-compose, хранение вне контейнера; команда для ручного бэкапа:
`docker compose exec db pg_dump -U education_crm education_crm --no-owner > backup_$(date +%F).sql`

## 18. Контроль объёма

Новых бизнес-модулей не добавлено. Добавлены только: регрессионные тесты, исправление N+1 (существующая страница), документ отчёта. AI/Telegram/WhatsApp/online-payments/бухгалтерия/salary/B2C/pipeline — не реализовывались.

## 19. Регрессионные тесты

Полный прогон: **Ran 257 tests — OK** (PostgreSQL, Docker).

Новые тесты этапа (6 шт., `apps/education/tests/test_stage14_regressions.py`):
- `LessonDetailQueryStabilityTests` × 2 — N+1 регрессия для OWNER и TEACHER (раздел 15).
- `LessonDetailSummaryTests.test_summary_with_historical_students` — семантика summary с историческими учениками (раздел 5).
- `CompletedLessonAttendanceTests` × 2 — завершённое занятие корректируется; отменённое никогда не создаёт записи.
- `GenerateLessonsAtomicityTests.test_partial_failure_rolls_back_whole_generation` — атомарность генерации (раздел 12).

## 20. Финальный статус

| Критерий | Статус |
|---|---|
| Полный бизнес-цикл | ✅ READY |
| Безопасность ролей и изоляция TEACHER | ✅ READY |
| AuditLog полный и append-only | ✅ READY |
| Целостность данных (constraints, ProtectedError, атомарность) | ✅ READY |
| Производительность (нет N+1) | ✅ READY (исправлен BUG-001) |
| Производственная конфигурация (DEBUG=False) | ✅ READY (шаги развёртывания в разделе 14) |
| UI/UX | ✅ READY |
| **Бэкапы** | ⚠️ NOT IMPLEMENTED (ручной pg_dump/restore проверен) |

## 21. Найденные баги

| ID | Описание | Статус |
|---|---|---|
| BUG-001 | N+1 на lesson_detail (TEACHER) + 7 лишних запросов summary | Исправлен + регрессионный тест |

Функциональных/бизнес-багов, влияющих на работу, в ходе аудита не обнаружено; поведение зафиксировано тестами (251 существующих + 6 новых).

## 22. Отчёт

Файл `STAGE14_REPORT.md` (этот документ). Изменённые файлы сессии:
- `apps/education/views.py` — lesson_detail (summary + `attendance_records` в контексте);
- `templates/education/lesson_detail.html` — ветка TEACHER использует контекстные записи;
- `apps/education/tests/test_stage14_regressions.py` — 6 новых регрессионных тестов.
