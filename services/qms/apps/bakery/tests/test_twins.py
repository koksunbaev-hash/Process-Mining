"""Зеркало доски в двойниках OpenTwins: что и когда уходит в Ditto.

Сеть в тестах не нужна: проверяется содержимое payload и то, что перемещение
партии зовёт синхронизацию для обоих устройств - нового и покинутого. Сам
PUT - три строки urllib, его правильность видна на живом стенде.
"""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery import twins
from apps.bakery.models import (
    Customer,
    Product,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
    ProductionUnit,
)
from apps.bakery.services import assign_batch_to_unit, move_batch


@override_settings(DITTO_ENABLED=True, DITTO_BASE_URL="http://ditto.test")
class TwinSyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("twin-dispatcher", password="x")
        self.user.profile.role = UserProfile.Role.MANAGER
        self.user.profile.save(update_fields=["role"])

        for sequence, (code, name) in enumerate(
            [("queue", "Очередь"), ("mixing", "Замес"), ("forming", "Формовка"), ("done", "Готово")],
            start=1,
        ):
            ProductionStage.objects.create(code=code, name=name, sequence=sequence)
        self.mixing = ProductionStage.objects.get(code="mixing")
        self.mixer = ProductionUnit.objects.create(
            stage=self.mixing, name="Миксер 1", sequence=1, twin_id="digitalegiz:mixer-1"
        )
        self.customer = Customer.objects.create(name="Кафе")
        self.product = Product.objects.create(code="TWIN-BREAD", name="Хлеб", unit="шт")

        order = ProductionOrder.objects.create(
            customer=self.customer, required_date=timezone.now(), created_by=self.user
        )
        item = ProductionOrderItem.objects.create(
            order=order, product=self.product, quantity=Decimal("10"), unit="шт"
        )
        self.batch = ProductionBatch.objects.create(
            order_item=item,
            product=self.product,
            planned_quantity=Decimal("10"),
            unit="шт",
            current_stage=self.mixing,
            status=ProductionBatch.Status.IN_PROGRESS,
        )

    def test_payload_free_unit(self):
        payload = twins.unit_product_payload(self.mixer)
        self.assertEqual(payload["status"], "свободно")
        self.assertEqual(payload["product"], "—")
        self.assertEqual(payload["quantity"], "—")
        self.assertEqual(payload["stage"], "Замес")
        # Никаких вложенных объектов: интерфейс OpenTwins печатает каждое
        # свойство как есть, и словарь внутри превратился бы в кашу на экране.
        self.assertTrue(all(isinstance(value, str) for value in payload.values()))

    def test_payload_occupied_unit(self):
        self.batch.production_unit = self.mixer
        self.batch.save(update_fields=["production_unit"])
        payload = twins.unit_product_payload(self.mixer)
        self.assertEqual(payload["product"], "Хлеб")
        self.assertEqual(payload["quantity"], "10 шт")
        self.assertEqual(payload["status"], "в работе")
        self.assertEqual(payload["customer"], "Кафе")
        self.assertEqual(payload["stage"], "Замес")
        self.assertTrue(all(isinstance(value, str) for value in payload.values()))

    def test_assign_schedules_sync_for_unit(self):
        with mock.patch.object(twins, "schedule_sync") as scheduled:
            assign_batch_to_unit(self.batch, self.mixer, user=self.user)
        synced = {unit_id for call in scheduled.call_args_list for unit_id in call.args if unit_id}
        self.assertIn(self.mixer.pk, synced)

    def test_leaving_stage_syncs_released_unit(self):
        assign_batch_to_unit(self.batch, self.mixer, user=self.user)
        with mock.patch.object(twins, "schedule_sync") as scheduled:
            move_batch(self.batch, ProductionStage.objects.get(code="forming"), self.user)
        synced = {unit_id for call in scheduled.call_args_list for unit_id in call.args if unit_id}
        # Партия ушла с этапа - миксер освободился, и его двойник должен узнать.
        self.assertIn(self.mixer.pk, synced)

    def test_commit_starts_push_thread(self):
        with mock.patch.object(twins.threading, "Thread") as thread_cls:
            with self.captureOnCommitCallbacks(execute=True):
                assign_batch_to_unit(self.batch, self.mixer, user=self.user)
        targets = {call.kwargs.get("target") for call in thread_cls.call_args_list}
        self.assertIn(twins.push_units_by_id, targets)

    @override_settings(DITTO_ENABLED=False)
    def test_disabled_integration_stays_silent(self):
        with mock.patch.object(twins.threading, "Thread") as thread_cls:
            with self.captureOnCommitCallbacks(execute=True):
                assign_batch_to_unit(self.batch, self.mixer, user=self.user)
        thread_cls.assert_not_called()


@override_settings(
    DITTO_ENABLED=True, DITTO_BASE_URL="http://ditto.test", DITTO_PRODUCT_STYLE="value"
)
class ValueStyleTests(TwinSyncTests):
    """Контракт публичного контура основного стенда (dt.digitalegiz.kz).

    Каждое поле отсюда автоматически становится полем в InfluxDB, а Influx
    фиксирует тип поля первой записью навсегда. Поэтому проверяются не только
    значения, но и типы: количество однажды строкой - и числом оно уже не
    станет никогда.
    """

    # Плоские тесты родителя здесь не о чем: payload другой. Переопределяем.
    def test_payload_free_unit(self):
        payload = twins.unit_product_value(self.mixer)
        self.assertEqual(payload["status"], "свободно")
        self.assertEqual(payload["product"], "")
        self.assertEqual(payload["quantity"], 0)
        self.assertEqual(payload["unit"], "")
        self.assertEqual(payload["started_at"], "")

    def test_payload_occupied_unit(self):
        self.batch.production_unit = self.mixer
        self.batch.save(update_fields=["production_unit"])
        payload = twins.unit_product_value(self.mixer)
        self.assertEqual(payload["product"], "Хлеб")
        self.assertEqual(payload["quantity"], 10.0)
        self.assertEqual(payload["unit"], "шт")
        self.assertEqual(payload["customer"], "Кафе")

    def test_quantity_is_a_number_in_both_states(self):
        """Правило Influx: тип не должен зависеть от того, занята ли машина."""
        free = twins.unit_product_value(self.mixer)
        self.batch.production_unit = self.mixer
        self.batch.save(update_fields=["production_unit"])
        busy = twins.unit_product_value(self.mixer)
        self.assertIsInstance(free["quantity"], (int, float))
        self.assertIsInstance(busy["quantity"], (int, float))

    def test_both_states_carry_the_same_keys(self):
        """Набор полей всегда полный: пустота - это "" и 0, не пропуск ключа."""
        free = set(twins.unit_product_value(self.mixer))
        self.batch.production_unit = self.mixer
        self.batch.save(update_fields=["production_unit"])
        busy = set(twins.unit_product_value(self.mixer))
        self.assertEqual(free, busy)

    def test_dates_are_iso_not_human(self):
        self.batch.production_unit = self.mixer
        self.batch.actual_start = timezone.now()
        self.batch.save(update_fields=["production_unit", "actual_start"])
        payload = twins.unit_product_value(self.mixer)
        self.assertIn("T", payload["updated_at"])
        self.assertIn("T", payload["started_at"])
        self.assertNotIn(".2026 ", payload["updated_at"])

    def test_put_goes_to_the_value_path(self):
        """Конвейер основного стенда подписан на properties/value - плоский
        путь ушёл бы мимо него молча."""
        with mock.patch.object(twins, "_put") as put:
            twins.put_feature_properties("digitalegiz:mixer-1", {"product": "Хлеб"})
        put.assert_called_once()
        url = put.call_args[0][0]
        self.assertTrue(url.endswith("/features/product/properties/value"))

    def test_missing_feature_is_created_wrapped_in_value(self):
        import urllib.error

        calls = []

        def fake_put(url, payload):
            calls.append((url, payload))
            if len(calls) == 1:
                raise urllib.error.HTTPError(url, 404, "no feature", {}, None)

        with mock.patch.object(twins, "_put", side_effect=fake_put):
            ok = twins.put_feature_properties("digitalegiz:mixer-1", {"product": "Хлеб"})
        self.assertTrue(ok)
        self.assertTrue(calls[1][0].endswith("/features/product"))
        self.assertEqual(calls[1][1], {"properties": {"value": {"product": "Хлеб"}}})

    def test_unit_payload_picks_the_style(self):
        payload = twins.unit_payload(self.mixer)
        self.assertEqual(payload["quantity"], 0)  # число, значит value-стиль


@override_settings(DITTO_ENABLED=True, DITTO_BASE_URL="http://ditto.test")
class FlatStyleStaysDefaultTests(TestCase):
    """Локальный стенд ничего не должен заметить: по умолчанию всё как было."""

    def test_default_style_is_flat(self):
        from django.conf import settings as django_settings

        self.assertEqual(django_settings.DITTO_PRODUCT_STYLE, "flat")

    def test_put_goes_to_the_flat_path(self):
        with mock.patch.object(twins, "_put") as put:
            twins.put_feature_properties("digitalegiz:mixer-1", {"product": "Хлеб"})
        url = put.call_args[0][0]
        self.assertTrue(url.endswith("/features/product/properties"))


@override_settings(
    DITTO_ENABLED=True, DITTO_BASE_URL="http://ditto.test", DITTO_PRODUCT_STYLE="both"
)
class BothStyleTests(TestCase):
    """Данные конвейеру, витрина глазам - два запроса, строгий порядок.

    Основной стенд принимает строгий JSON в properties/value, но карточка в
    интерфейсе тогда показывает один ком. Режим both дописывает те же поля
    плоско merge-патчем - карточка снова построчная, а value не тронут, и
    конвейер не видит лишнего события на своём пути.
    """

    def setUp(self):
        stage = ProductionStage.objects.create(code="mixing", name="Замес", sequence=1)
        self.mixer = ProductionUnit.objects.create(
            stage=stage, name="Миксер 1", sequence=1, twin_id="digitalegiz:mixer-1"
        )

    def test_value_goes_first_then_the_flat_showcase(self):
        calls = []
        with mock.patch.object(
            twins, "_send", side_effect=lambda url, payload, method="PUT", content_type="application/json": calls.append((method, url, payload, content_type))
        ):
            ok = twins.push_unit(self.mixer)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)

        method, url, payload, ctype = calls[0]
        self.assertEqual(method, "PUT")
        self.assertTrue(url.endswith("/features/product/properties/value"))
        self.assertEqual(payload["quantity"], 0)  # строгий, типизированный

        method, url, payload, ctype = calls[1]
        self.assertEqual(method, "PATCH")
        self.assertTrue(url.endswith("/features/product/properties"))
        self.assertEqual(ctype, "application/merge-patch+json")
        self.assertEqual(payload["quantity"], "—")  # человеческий, для карточки
        # Merge-патч не смеет нести value - иначе он перетёр бы данные конвейера.
        self.assertNotIn("value", payload)

    def test_a_failed_showcase_does_not_fail_the_data(self):
        """Витрина - украшение. Упала - в лог, а не в отказ доставки."""
        import urllib.error

        def send(url, payload, method="PUT", content_type="application/json"):
            if method == "PATCH":
                raise urllib.error.HTTPError(url, 500, "boom", {}, None)

        with mock.patch.object(twins, "_send", side_effect=send):
            ok = twins.push_unit(self.mixer)
        self.assertTrue(ok)

    def test_flat_and_value_styles_still_send_one_request(self):
        for style in ("flat", "value"):
            with override_settings(DITTO_PRODUCT_STYLE=style):
                with mock.patch.object(twins, "_send") as send:
                    twins.push_unit(self.mixer)
                self.assertEqual(send.call_count, 1, style)
