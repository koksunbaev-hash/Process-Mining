"""Связывание машин с двойниками из консоли.

В сеть тесты не ходят: каталог Ditto подменяется. Проверяется то, ради чего
команда и заведена, - что связь ставится по имени машины и что один двойник
не достаётся двум машинам сразу.
"""

from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from apps.bakery.models import ProductionStage, ProductionUnit

CATALOG = [
    ("digitalegiz:ESP32_Dala_Meter_001994", "Печь MIWE roll-in 1"),
    ("digitalegiz:ESP32_Dala_Meter_001990", "Печь MIWE roll-in 2"),
    ("digitalegiz:ESP32", "Миксер ARYSTAN H100 SPIRAL"),
    ("digitalegiz:ESP32_Orman_Meter_002001", "Льдогенератор Brema 1"),
]

LIVE = override_settings(DITTO_ENABLED=True, DITTO_BASE_URL="http://ditto.test")


@LIVE
class TwinIdsCommandTests(TestCase):
    def setUp(self):
        oven = ProductionStage.objects.create(code="oven", name="Печь", sequence=1)
        mixing = ProductionStage.objects.create(code="mixing", name="Замес", sequence=2)
        self.oven1 = ProductionUnit.objects.create(stage=oven, name="Печь 1", sequence=1)
        self.oven2 = ProductionUnit.objects.create(stage=oven, name="Печь 2", sequence=2)
        self.mixer = ProductionUnit.objects.create(stage=mixing, name="Миксер 1", sequence=1)

    def _run(self, *args):
        out = StringIO()
        with mock.patch("apps.bakery.management.commands.twin_ids.fetch_things", return_value=CATALOG):
            call_command("twin_ids", *args, stdout=out)
        return out.getvalue()

    def test_setting_a_pair_binds_the_machine(self):
        self._run("--set", "Печь 1=digitalegiz:ESP32_Dala_Meter_001994")
        self.oven1.refresh_from_db()
        self.assertEqual(self.oven1.twin_id, "digitalegiz:ESP32_Dala_Meter_001994")

    def test_one_twin_cannot_serve_two_machines(self):
        """Обе машины писали бы в одну серию, и панель разъезжалась бы молча."""
        self._run("--set", "Печь 1=digitalegiz:ESP32_Dala_Meter_001994")
        with self.assertRaises(CommandError):
            self._run("--set", "Печь 2=digitalegiz:ESP32_Dala_Meter_001994")
        self.oven2.refresh_from_db()
        self.assertEqual(self.oven2.twin_id, "")

    def test_rebinding_the_same_machine_is_allowed(self):
        self._run("--set", "Печь 1=digitalegiz:ESP32_Dala_Meter_001994")
        self._run("--set", "Печь 1=digitalegiz:ESP32_Dala_Meter_001990")
        self.oven1.refresh_from_db()
        self.assertEqual(self.oven1.twin_id, "digitalegiz:ESP32_Dala_Meter_001990")

    def test_clearing_unbinds(self):
        self._run("--set", "Печь 1=digitalegiz:ESP32_Dala_Meter_001994")
        self._run("--clear", "Печь 1")
        self.oven1.refresh_from_db()
        self.assertEqual(self.oven1.twin_id, "")

    def test_an_unknown_machine_is_refused_not_guessed(self):
        with self.assertRaises(CommandError):
            self._run("--set", "Печь 9=digitalegiz:ESP32")

    def test_the_listing_groups_the_catalog_by_kind(self):
        output = self._run()
        self.assertIn("Печь 1", output)
        self.assertIn("двойника нет", output)
        self.assertIn("Льдогенератор", output)
        self.assertIn("digitalegiz:ESP32_Dala_Meter_001994", output)

    def test_the_catalog_is_skipped_when_ditto_is_off(self):
        with override_settings(DITTO_ENABLED=False):
            output = self._run()
        self.assertIn("Каталог двойников не показан", output)
