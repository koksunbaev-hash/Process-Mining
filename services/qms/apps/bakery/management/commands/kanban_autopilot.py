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

Команда одноразовая и идемпотентная, как `clear_done_board`: ставится в cron
и вызывается раз в полчаса. Пропущенный запуск не беда - следующий продолжит
с того же места. Двух прогонов за день не заведётся: на день создаётся ровно
один, и повторный вызов это проверяет.

    python manage.py kanban_autopilot             # один такт
    python manage.py kanban_autopilot --dry-run   # посмотреть, не трогая
    python manage.py kanban_autopilot --stop      # остановить и убрать всё демо
"""

import os
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bakery.kanban_demo import (
    create_demo_run,
    demo_status,
    demo_user,
    reset_demo,
    start_demo,
    stop_demo,
    tick_demo,
)
from apps.bakery.models import KanbanDemoRun

#: Сколько партий заводить в каждый день недели. Числа сняты с настоящего
#: журнала этой установки за 25 августа - 10 сентября: в среднем за сутки
#: понедельник 17, вторник 25, среда 26, четверг 13, пятница 12. Суббот и
#: воскресений в журнале нет вовсе - цех по ним не работает, и демо тоже молчит.
BATCHES_BY_WEEKDAY = {0: 17, 1: 25, 2: 26, 3: 13, 4: 12}

#: Граница смены по местному времени цеха (TIME_ZONE = Asia/Qyzylorda).
#: Настоящие партии заводятся с 9 до 17 - демо держится тех же часов, иначе
#: на карте появится производство в три часа ночи.
SHIFT_START_HOUR = 9
SHIFT_END_HOUR = 17

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

        status = tick_demo(run, user)
        moved = ", ".join(item["batch_number"] for item in status["changed_batches"][:6])
        self.stdout.write(
            f"прогон {run.pk}: {status['completed_batches']}/{status['total_batches']} "
            f"({status['progress_percent']}%), сдвинуто {len(status['changed_batches'])}"
            + (f": {moved}" if moved else "")
        )
        for error in status["errors"][:3]:
            self.stderr.write(f"  {error['batch']}: {error['error']}")

    # ------------------------------------------------------------------

    def run_for_today(self, user, now, volume, dry_run):
        """Прогон на сегодня: идущий продолжаем, нового за день не заводим дважды."""
        active = (
            KanbanDemoRun.objects.filter(is_active=True)
            .exclude(status__in=[KanbanDemoRun.Status.COMPLETED, KanbanDemoRun.Status.STOPPED])
            .order_by("-created_at")
            .first()
        )
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
            # Волнами: партии двигаются группами, как настоящая смена. По одной
            # доска ползла бы слишком ровно, а FAST пролетел бы день за час.
            mode=KanbanDemoRun.Mode.WAVE,
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
            result = reset_demo(run, user)
            self.stdout.write(
                f"Убран прогон {run.pk}: партий {result['deleted_batches']}, заказов {result['deleted_orders']}."
            )
