"""Демо-партии на доске - сами, каждый рабочий день.

Зачем. Доску показывают партнёрам, а заказчик данные не вносит: колонки стоят
пустыми. Команда ведёт демонстрационный поток параллельно настоящему -
заводские партии и демо-партии идут по доске рядом.

Демо от настоящего отделено на уровне строк: у заказа, позиции, партии и
складской записи есть `is_demo` и ссылка на `KanbanDemoRun`. Отсюда три
свойства, ради которых это вообще можно держать на боевом стенде:

* отчёты демо не видят - в `views.py` шесть выборок с `.exclude(is_demo=True)`;
* в аналитику демо не уезжает - `choose_pending_events()` его отбрасывает,
  потому что из журнала событие уже не отозвать, а партию с доски удалить можно;
* удаляется по одному прогону - `reset_demo()` сносит ровно свой.

Двигает партии команда сама, а не через `tick_demo`. Тот берёт семь самых
продвинутых партий и двигает их разом на этап вперёд - для запуска демо
вручную это то, что нужно, но на доске, идущей весь день, выглядит неправдой:
головная группа пролетает до «Готово» за несколько тактов, пока остальные стоят
в очереди, и переходы случаются пачками в одну секунду. Здесь у каждой партии
своя выдержка на каждом этапе, а в работу они уходят по одной.

Команда одноразовая и идемпотентная, как `clear_done_board`: ставится в cron
и вызывается раз в несколько минут. Пропущенный запуск не беда - следующий
продолжит с того же места.

    python manage.py kanban_autopilot             # один такт
    python manage.py kanban_autopilot --dry-run   # посмотреть, не трогая
    python manage.py kanban_autopilot --stop      # остановить и убрать всё демо
"""

import hashlib
import os
import random
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bakery.kanban_demo import (
    create_demo_run,
    demo_status,
    demo_user,
    reset_demo,
    start_demo,
    stop_demo,
)
from apps.bakery.models import BatchStageHistory, KanbanDemoRun
from apps.bakery.services import (
    assign_batch_to_unit,
    free_units_for_stage,
    move_batch,
    next_stage_for,
)

#: Сколько партий заводить в каждый день недели. Числа сняты с настоящего
#: журнала этой установки за 25 августа - 10 сентября: в среднем за сутки
#: понедельник 17, вторник 25, среда 26, четверг 13, пятница 12. Суббот и
#: воскресений в журнале нет вовсе - цех по ним не работает, и демо тоже молчит.
BATCHES_BY_WEEKDAY = {0: 17, 1: 25, 2: 26, 3: 13, 4: 12}

#: Сколько партия стоит на этапе, минут. Медианы из того же журнала: переход
#: «Распределение на устройство -> следующий этап» занимал 27, 27, 28 и 33
#: минуты. Итого партия проходит доску примерно за два с половиной часа - при
#: настоящем среднем 2 часа 11 минут.
DWELL_MINUTES = {"mixing": 25, "forming": 25, "proofing": 27, "oven": 28, "warehouse": 33}
DEFAULT_DWELL_MINUTES = 25

#: Граница смены по местному времени цеха (TIME_ZONE = Asia/Qyzylorda).
#: Настоящие партии заводятся с 9 до 17 - демо держится тех же часов, иначе
#: на доске появится производство в три часа ночи.
SHIFT_START_HOUR = 9
SHIFT_END_HOUR = 17

#: Какую долю смены занимает запуск партий в работу. Не всю: партия идёт по
#: доске ещё два с половиной часа после запуска, и выпускать последнюю в 16:50
#: значило бы гарантированно не довести её до «Готово».
RELEASE_WINDOW_SHARE = 0.6

#: Больше переходов за один такт не бывает - при любых обстоятельствах.
#: Выдержка на этапе сама по себе рассыпает переходы по времени, но только пока
#: такты идут подряд. После ночи, простоя или перезапуска контейнера у всех
#: партий, что стояли на этапах, выдержка оказывается просрочена одновременно,
#: и без этого предела они сдвинулись бы в одну секунду. В обычный день
#: переходов около двух-трёх за пять минут, так что предел не мешает, а только
#: страхует.
MAX_MOVES_PER_TICK = 4

#: Завершённые прогоны старше этого срока убираются: доска не должна зарастать,
#: а «Готово» и так подметается каждое утро `clear_done_board`.
KEEP_DAYS = 3


def env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def env_float(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def planned_batches(day, volume):
    base = BATCHES_BY_WEEKDAY.get(day.weekday())
    if not base:
        return 0
    # Ровное число каждую среду выдало бы генератор с первого взгляда: в
    # настоящих данных разброс за сутки от 7 до 40.
    return max(1, int(round(base * volume * random.uniform(0.7, 1.3))))


def dwell_for(batch_number, stage_code):
    """Сколько эта партия стоит на этом этапе.

    Считается детерминированно от пары (партия, этап), а не случайно: команду
    будит cron, каждый раз это новый процесс, и случайное значение означало бы,
    что партия то «пора двигать», то «ещё рано». От хеша же она получает свою
    выдержку раз и навсегда - и соседние партии на одном этапе стоят
    по-разному, как в цеху.
    """
    base = DWELL_MINUTES.get(stage_code, DEFAULT_DWELL_MINUTES)
    digest = hashlib.sha256(f"{batch_number}|{stage_code}".encode("utf-8")).digest()
    return timedelta(minutes=base * (0.6 + digest[0] / 255 * 0.8))


def waiting_since(batch):
    """Когда партия встала на нынешний этап."""
    last = BatchStageHistory.objects.filter(batch=batch).order_by("-created_at").first()
    return last.created_at if last else batch.created_at


def releases_due(run, now):
    """Сколько партий уже должно было уйти из очереди в работу.

    Запуск размазан по смене: иначе два десятка партий снимаются с очереди
    разом и дальше идут одной толпой, а это первое, что видно на доске.

    Отсчёт идёт от старта прогона, а не от начала смены. От смены считать
    нельзя: прогон, заведённый в середине дня - после простоя, перезапуска или
    в первый день - оказался бы «отставшим на четыре часа», и догонял бы
    расписание, выпустив всю очередь разом. Ровно то, чего эта функция и
    должна не допускать.
    """
    started = run.started_at or run.created_at
    elapsed = max(0.0, (now - started).total_seconds() / 60)
    window = (SHIFT_END_HOUR - SHIFT_START_HOUR) * 60 * RELEASE_WINDOW_SHARE
    step = max(window / max(run.total_batches, 1), 1.0)
    return int(elapsed / step) + 1


class Command(BaseCommand):
    help = "Ведёт демонстрационный поток партий на канбан-доске: один такт за вызов."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Показать, что было бы сделано.")
        parser.add_argument("--stop", action="store_true", help="Остановить поток и удалить все демо-прогоны.")
        parser.add_argument("--user", default="", help="От чьего имени двигать партии.")
        parser.add_argument("--force", action="store_true", help="Работать вне смены и в выходной.")

    def handle(self, *args, **options):
        if os.environ.get("KANBAN_AUTOPILOT_ENABLED", "0") != "1" and not options["stop"]:
            self.stdout.write("KANBAN_AUTOPILOT_ENABLED != 1 — выключено, ничего не делаю.")
            return

        user = demo_user(options["user"] or None)
        if not user:
            self.stderr.write("Не найден администратор или менеджер — некому вести демо.")
            return

        if options["stop"]:
            self.retire(user, keep_days=0, dry_run=options["dry_run"], everything=True)
            return

        now = timezone.localtime()
        volume = env_float("KANBAN_AUTOPILOT_VOLUME", 1.0)

        # Уборка идёт всегда, даже в выходной: завершённый в пятницу прогон
        # незачем держать на доске до понедельника.
        self.retire(user, keep_days=env_int("KANBAN_AUTOPILOT_KEEP_DAYS", KEEP_DAYS), dry_run=options["dry_run"])

        if not options["force"]:
            if now.weekday() not in BATCHES_BY_WEEKDAY:
                self.stdout.write(f"{now:%a %d.%m} — выходной, партии не завожу.")
                return
            if not (SHIFT_START_HOUR <= now.hour < SHIFT_END_HOUR):
                self.stdout.write(f"{now:%H:%M} — вне смены ({SHIFT_START_HOUR}:00–{SHIFT_END_HOUR}:00).")
                return

        run = self.run_for_today(user, now, volume, dry_run=options["dry_run"])
        if not run:
            return
        if options["dry_run"]:
            status = demo_status(run)
            self.stdout.write(f"dry-run: такт по прогону {run.pk}, готово {status['completed_batches']}/{status['total_batches']}")
            return

        moved, errors = self.advance(run, user, now)
        status = demo_status(run)
        self.stdout.write(
            f"прогон {run.pk}: {status['completed_batches']}/{status['total_batches']} "
            f"({status['progress_percent']}%), сдвинуто {len(moved)}"
            + (": " + ", ".join(moved) if moved else "")
        )
        for line in errors[:3]:
            self.stderr.write("  " + line)

    # ------------------------------------------------------------------

    def advance(self, run, user, now):
        """Продвинуть тех, чьё время на этапе вышло. Из очереди - по одной."""
        batches = list(
            run.batches.exclude(current_stage__code="done")
            .select_related("current_stage", "order_item__order", "product")
            .order_by("id")  # очередь: кто раньше заведён, тот раньше и пойдёт
        )
        started = run.total_batches - sum(1 for batch in batches if batch.current_stage.code == "queue")
        # Из очереди - не больше одной за такт, даже если расписание отстало:
        # отставание нагоняется по одной партии каждые пять минут, а не залпом.
        allowance = min(1, releases_due(run, now) - started)

        moved, errors = [], []
        for batch in batches:
            if len(moved) >= MAX_MOVES_PER_TICK:
                break
            code = batch.current_stage.code
            if code == "queue":
                if allowance <= 0:
                    continue
            elif now - waiting_since(batch) < dwell_for(batch.batch_number, code):
                continue

            target = next_stage_for(batch)
            if not target:
                continue
            try:
                move_batch(batch, target, user, f"DEMO: переход на этап {target.name}")
                batch.refresh_from_db()
                # Партия не должна висеть в «Не распределено»: на доске это
                # выглядит как затор, которого нет. Свободного устройства нет -
                # значит и в демо она ждёт, ровно как ждала бы в цеху.
                free = free_units_for_stage(batch.current_stage)
                if free:
                    assign_batch_to_unit(batch, free[0], user)
            except (PermissionDenied, ValidationError) as exc:
                errors.append(f"{batch.batch_number}: {exc}")
                continue
            except Exception as exc:  # доска не должна вставать из-за одной партии
                errors.append(f"{batch.batch_number}: {exc}")
                continue

            if code == "queue":
                allowance -= 1
            moved.append(batch.batch_number)

        if errors:
            run.last_error = "; ".join(errors[:3])
            run.save(update_fields=["last_error", "updated_at"])
        return moved, errors

    def run_for_today(self, user, now, volume, dry_run):
        """Прогон на сегодня: идущий продолжаем, нового за день не заводим дважды."""
        active = (
            KanbanDemoRun.objects.filter(is_active=True)
            .exclude(status__in=[KanbanDemoRun.Status.COMPLETED, KanbanDemoRun.Status.STOPPED])
            .order_by("-created_at")
            .first()
        )
        if active and timezone.localtime(active.started_at or active.created_at).date() < now.date():
            # Вчерашний прогон не доехал до «Готово» - так бывает, если он начался
            # поздно или смена кончилась раньше последней партии. Тянуть его
            # дальше нельзя: create_demo_run держит один активный прогон, и пока
            # вчерашний идёт, сегодняшняя очередь не появится вовсе. Доску
            # каждое утро и так начинают заново - в 7:55 clear_done_board
            # подметает «Готово», - демо живёт в том же ритме.
            if dry_run:
                self.stdout.write(f"dry-run: убрал бы вчерашний прогон {active.pk} и завёл сегодняшний.")
                return None
            number = active.pk
            stop_demo(active, user)
            result = reset_demo(active, user)
            self.stdout.write(f"Вчерашний прогон {number} убран: партий {result['deleted_batches']}.")
            active = None

        if active:
            if active.status != KanbanDemoRun.Status.RUNNING and not dry_run:
                start_demo(active, user)
            return active

        if KanbanDemoRun.objects.filter(created_at__date=now.date()).exists():
            self.stdout.write("Сегодняшний прогон уже отработал — новый не завожу.")
            return None

        count = planned_batches(now.date(), volume)
        if dry_run:
            self.stdout.write(f"dry-run: завёл бы прогон на {count} партий.")
            return None

        run = create_demo_run(
            user=user,
            count=count,
            name=f"Демо-поток {now:%d.%m.%Y}",
            mode=KanbanDemoRun.Mode.SEQUENTIAL,
            client_request_id=f"autopilot-{now:%Y-%m-%d}",
        )
        start_demo(run, user)
        self.stdout.write(self.style.SUCCESS(f"Заведён прогон {run.pk} на {count} партий."))
        return run

    def retire(self, user, keep_days, dry_run, everything=False):
        """Убрать отработавшие прогоны, чтобы доска не зарастала."""
        queryset = KanbanDemoRun.objects.all()
        if not everything:
            edge = timezone.now() - timedelta(days=keep_days)
            queryset = queryset.filter(
                status__in=[KanbanDemoRun.Status.COMPLETED, KanbanDemoRun.Status.STOPPED],
                updated_at__lt=edge,
            )
        for run in list(queryset):
            if dry_run:
                self.stdout.write(f"dry-run: убрал бы прогон {run.pk} ({run.name}).")
                continue
            if everything and run.status == KanbanDemoRun.Status.RUNNING:
                stop_demo(run, user)
            # Номер запоминается до вызова: reset_demo удаляет сам прогон,
            # и Django обнуляет pk у объекта в памяти — в лог уходило бы None.
            number = run.pk
            result = reset_demo(run, user)
            self.stdout.write(
                f"Убран прогон {number}: партий {result['deleted_batches']}, заказов {result['deleted_orders']}."
            )
