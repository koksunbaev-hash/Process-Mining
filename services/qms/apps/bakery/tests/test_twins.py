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
