"""Поток движений партий в общий InfluxDB.

В сеть тесты не ходят: транспорт подменяется, проверяется сборка точек и
дисциплина отправки. Дисциплина здесь важнее формата: выключенная
интеграция обязана молчать, демо-партии - не покидать стенд, а ошибка
записи - не ронять перемещение.
"""

import re
from unittest import mock

from django.test import TestCase, override_settings

from apps.bakery import influx
from apps.bakery.models import BatchStageHistory, ProductionStage, ProductionUnit

from .batch_workflow.factories import create_queued_batch, create_stage_list, create_user

LIVE = override_settings(
    INFLUX_ENABLED=True,
    INFLUX_URL="http://influx.invalid",
    INFLUX_ORG="opentwins",
    INFLUX_BUCKET="qms",
    INFLUX_TOKEN="test-token",
)


class LineProtocolTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.user = create_user()
        self.batch = create_queued_batch(user=self.user)
        self.batch.refresh_from_db()
        self.history = self.batch.stage_history.latest("created_at")

    def test_the_point_names_the_batch_the_way_the_shop_does(self):
        line = influx.history_point(self.history)
        self.assertTrue(line.startswith("qms_batch_event,stage=queue"))
        self.assertIn(f'batch="{self.batch.display_batch_label}"', line)
        self.assertIn(f'case_id="{self.batch.batch_number}"', line)
        self.assertIn("quantity=100", line)
        # Время - наносекундами, девятнадцать знаков.
        self.assertRegex(line.rsplit(" ", 1)[1], r"^\d{19}$")

    def test_tags_survive_spaces_and_commas(self):
        """«Печь 3» в теге обязана стать «Печь\\ 3»: пробел в line protocol
        отделяет теги от полей, и без экранирования точка рассыпается."""
        self.assertEqual(influx._tag("Печь 3"), "Печь\\ 3")
        self.assertEqual(influx._tag("a,b=c"), "a\\,b\\=c")
        self.assertEqual(influx._field_str('со "скобками"'), '"со \\"скобками\\""')

    def test_the_batch_number_is_a_field_not_a_tag(self):
        """Партий за год - тысячи, и каждая своя серия раздула бы базу.
        Номер партии живёт в полях, теги - только малочисленные значения."""
        line = influx.history_point(self.history)
        tags = line.split(" ")[0]
        self.assertNotIn(self.batch.batch_number, tags)


class TwinTagTests(TestCase):
    """Ключ, по которому движение партии сходится с киловаттами своей машины.

    Телеметрия счётчиков приходит в Influx от Telegraf с тегом `thingId` и
    про имя машины ничего не знает. Пока производственная точка помечена
    только именем, панель не может соединить два потока по машине - остаётся
    склеивать их наугад, приписывая последнюю партию цеха всем счётчикам
    сразу.
    """

    def setUp(self):
        create_stage_list()
        self.user = create_user()
        self.oven = ProductionUnit.objects.create(
            stage=ProductionStage.objects.get(code="queue"),
            name="Печь 3",
            sequence=3,
            twin_id="digitalegiz:ESP32_Dala_Meter_001994",
        )
        self.batch = create_queued_batch(user=self.user)
        self.batch.refresh_from_db()

    def _line(self):
        history = BatchStageHistory.objects.select_related(
            "batch__product", "batch__production_unit", "batch__order_item__order",
            "from_stage", "to_stage",
        ).filter(batch=self.batch).latest("created_at")
        return influx.history_point(history)

    @staticmethod
    def _parts(line):
        """Теги и поля точки. Делить строку по любому пробелу нельзя: пробел
        внутри «Печь\\ 3» экранирован и границей не является."""
        return re.split(r"(?<!\\) ", line)

    def test_the_point_carries_the_thing_id_of_its_machine(self):
        self.batch.production_unit = self.oven
        self.batch.save(update_fields=["production_unit"])
        tags = self._parts(self._line())[0]
        self.assertIn("thingId=digitalegiz:ESP32_Dala_Meter_001994", tags)
        # Имя машины остаётся: по нему читают панели, написанные до двойников.
        self.assertIn("unit=Печь\\ 3", tags)

    def test_a_machine_without_a_twin_says_nothing(self):
        """Пустое поле связи - это «двойника нет», а не пустой тег: тег без
        значения Influx не примет, и точка ушла бы в отказ целиком."""
        self.oven.twin_id = ""
        self.oven.save(update_fields=["twin_id"])
        self.batch.production_unit = self.oven
        self.batch.save(update_fields=["production_unit"])
        self.assertNotIn("thingId", self._line())

    def test_the_thing_id_is_a_tag_not_a_field(self):
        """Полем по нему не сгруппировать и не соединить - join в Flux сводит
        таблицы по колонкам группировки."""
        self.batch.production_unit = self.oven
        self.batch.save(update_fields=["production_unit"])
        tag_part, field_part = self._parts(self._line())[:2]
        self.assertIn("thingId=", tag_part)
        self.assertNotIn("thingId", field_part)


class UnitStateTests(TestCase):
    """Что на машине сейчас - отдельной точкой, чтобы панель не считала это
    сама из истории переводов."""

    def setUp(self):
        create_stage_list()
        self.user = create_user()
        self.oven = ProductionUnit.objects.create(
            stage=ProductionStage.objects.get(code="queue"),
            name="Печь 3",
            sequence=3,
            twin_id="digitalegiz:ESP32_Dala_Meter_001994",
        )
        self.batch = create_queued_batch(user=self.user)
        self.batch.refresh_from_db()

    @staticmethod
    def _parts(line):
        return re.split(r"(?<!\\) ", line)

    def _point(self):
        self.oven.refresh_from_db()
        return influx.unit_state_point(self.oven)

    def test_a_free_machine_says_so_instead_of_yesterdays_bread(self):
        """В истории переводов события «партия ушла с печи» нет вовсе, и по
        ней освободившаяся машина показывает последнюю партию вечно."""
        line = self._point()
        self.assertIn('status="свободно"', line)
        self.assertIn('product=""', line)
        self.assertIn("quantity=0", line)

    def test_a_busy_machine_carries_its_order(self):
        self.batch.production_unit = self.oven
        self.batch.save(update_fields=["production_unit"])
        line = self._point()
        self.assertIn(f'order="№{self.batch.order_item.order.order_number}"', line)
        self.assertIn(f'product="{self.batch.product.name}"', line)

    def test_the_thing_id_is_there_for_the_join(self):
        tags = self._parts(self._point())[0]
        self.assertTrue(tags.startswith("qms_unit_state,"))
        self.assertIn("thingId=digitalegiz:ESP32_Dala_Meter_001994", tags)

    def test_the_quantity_unit_does_not_collide_with_the_machine_tag(self):
        """Тег `unit` - имя машины, поле `unit` было бы единицей измерения, и
        Influx их не различает."""
        tag_part, field_part = self._parts(self._point())[:2]
        self.assertIn("unit=Печь\\ 3", tag_part)
        self.assertIn("quantity_unit=", field_part)
        self.assertNotIn(",unit=", field_part)

    def test_quantity_stays_a_number_on_a_free_machine(self):
        """Тип поля Influx фиксирует первой записью навсегда."""
        free = self._point()
        self.batch.production_unit = self.oven
        self.batch.save(update_fields=["production_unit"])
        busy = self._point()
        for line in (free, busy):
            quantity = re.search(r"quantity=([^,]+)", line).group(1)
            self.assertNotIn('"', quantity)


class InlineThread:
    """Поток, работающий на месте: сигнал шлёт точку из фонового потока, и
    настоящий Thread обгонял бы проверки теста."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@LIVE
class DisciplineTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.user = create_user()
        patcher = mock.patch.object(influx.threading, "Thread", InlineThread)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_transition_sends_exactly_its_own_point(self):
        with mock.patch.object(influx, "write_lines", return_value=True) as sent:
            with self.captureOnCommitCallbacks(execute=True):
                batch = create_queued_batch(user=self.user)
            batch.refresh_from_db()
        self.assertTrue(sent.called)
        lines = sent.call_args[0][0]
        self.assertEqual(len(lines), 1)
        self.assertIn(f'case_id="{batch.batch_number}"', lines[0])

    def test_demo_batches_never_leave_the_stand(self):
        """Общая витрина показывает завод, а не репетицию."""
        with mock.patch.object(influx, "write_lines", return_value=True) as sent:
            with self.captureOnCommitCallbacks(execute=True):
                batch = create_queued_batch(user=self.user)
                batch.refresh_from_db()
                batch.is_demo = True
                batch.save(update_fields=["is_demo"])
                BatchStageHistory.objects.create(
                    batch=batch, to_stage=batch.current_stage, comment="демо-переход"
                )
        for call in sent.call_args_list:
            for line in call[0][0]:
                self.assertNotIn("демо", line)

    def test_disabled_integration_stays_silent(self):
        with override_settings(INFLUX_ENABLED=False):
            with mock.patch.object(influx, "write_lines") as sent:
                with self.captureOnCommitCallbacks(execute=True):
                    create_queued_batch(user=self.user)
            sent.assert_not_called()

    def test_leaving_a_machine_rewrites_the_machine_it_left(self):
        """Иначе покинутая печь осталась бы занятой навсегда: партия уехала, а
        её состояние переписать некому."""
        oven = ProductionUnit.objects.create(
            stage=ProductionStage.objects.get(code="queue"), name="Печь 3", sequence=3
        )
        with self.captureOnCommitCallbacks(execute=True):
            batch = create_queued_batch(user=self.user)
        batch.refresh_from_db()
        with mock.patch.object(influx, "push_unit_states_by_id") as pushed:
            with self.captureOnCommitCallbacks(execute=True):
                batch.production_unit = oven
                batch.save(update_fields=["production_unit"])
            with self.captureOnCommitCallbacks(execute=True):
                batch.production_unit = None
                batch.save(update_fields=["production_unit"])
        touched = {unit_id for call in pushed.call_args_list for unit_id in call.args[0]}
        self.assertIn(oven.pk, touched)

    def test_a_network_error_is_a_log_line_not_a_broken_move(self):
        """Ради этого всё и устроено как у Ditto: витрина отстанет на точку,
        а перемещение партии не заметит ничего."""
        import urllib.error

        def refuse(request, timeout):
            raise urllib.error.URLError("нет сети")

        with mock.patch.object(influx.urllib.request, "urlopen", side_effect=refuse):
            ok = influx.write_lines(["qms_batch_event,stage=queue x=1 1"])
        self.assertFalse(ok)


@LIVE
class SyncCommandTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.user = create_user()

    def test_the_backfill_sends_history_and_skips_demo(self):
        from django.core.management import call_command
        from io import StringIO

        with self.captureOnCommitCallbacks(execute=True):
            with mock.patch.object(influx, "write_lines", return_value=True):
                real = create_queued_batch(user=self.user)
                demo = create_queued_batch(user=self.user, quantity=10)
        demo.refresh_from_db()
        demo.is_demo = True
        demo.save(update_fields=["is_demo"])
        real.refresh_from_db()

        sent_lines = []
        with mock.patch(
            "apps.bakery.management.commands.sync_influx.write_lines",
            side_effect=lambda lines: sent_lines.extend(lines) or True,
        ):
            out = StringIO()
            call_command("sync_influx", stdout=out)

        joined = "\n".join(sent_lines)
        self.assertIn(real.batch_number, joined)
        self.assertNotIn(demo.batch_number, joined)
        self.assertIn("отправлено", out.getvalue())
