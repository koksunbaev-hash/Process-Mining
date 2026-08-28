"""Удаление с доски: ошибочная партия и ошибочный заказ.

Кнопка существует ради одного сценария - «создали не то, заметили сразу», - и
тесты охраняют её границы: кто может нажать, что она отказывается трогать и
какие хвосты убирает за собой. Самый важный тест здесь про склад: партию,
дошедшую до склада, не удаляет никто, и это не право, а физика остатков.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.audit.models import AuditLog
from apps.bakery.models import (
    BatchStageHistory,
    FinishedGoodsStock,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
)
from apps.bakery.services import delete_batch, delete_order_with_batches
from apps.bakery.tests.batch_workflow.factories import create_user
from apps.bakery.tests.batch_workflow.helpers import create_batch_at_stage
from apps.process_mining.models import ProcessEvent


class DeleteBatchServiceTests(TestCase):
    def setUp(self):
        self.manager = create_user("board-manager", UserProfile.Role.MANAGER)
        self.batch = create_batch_at_stage("mixing", self.manager)

    def test_deletes_the_batch_and_its_history(self):
        batch_id = self.batch.pk
        self.assertTrue(BatchStageHistory.objects.filter(batch_id=batch_id).exists())
        delete_batch(self.batch, self.manager)
        self.assertFalse(ProductionBatch.objects.filter(pk=batch_id).exists())
        self.assertFalse(BatchStageHistory.objects.filter(batch_id=batch_id).exists())

    def test_writes_the_audit_before_the_batch_is_gone(self):
        label = self.batch.display_batch_label
        delete_batch(self.batch, self.manager)
        entry = AuditLog.objects.filter(action="batch_deleted").latest("pk")
        self.assertEqual(entry.changes["batch"], label)

    def test_unsent_events_die_with_the_batch_sent_ones_stay(self):
        """SET_NULL без этой уборки отправил бы в аналитику строку-сироту."""
        pending = ProcessEvent.objects.filter(
            batch=self.batch, export_status=ProcessEvent.ExportStatus.PENDING
        )
        self.assertTrue(pending.exists())
        sent = pending.first()
        sent.pk = None
        sent.event_id = uuid.uuid4()
        sent.export_status = ProcessEvent.ExportStatus.SENT
        sent.save()

        pending_ids = list(pending.values_list("pk", flat=True))
        delete_batch(self.batch, self.manager)

        # Неотправленные события ПАРТИИ исчезли; отправленная копия осталась
        # следом - без привязки, но в журнале. События заказа не трогаем:
        # заказ жив, и его «подтверждён» по-прежнему должен уехать.
        self.assertFalse(ProcessEvent.objects.filter(pk__in=pending_ids).exists())
        survivor = ProcessEvent.objects.get(pk=sent.pk)
        self.assertEqual(survivor.export_status, ProcessEvent.ExportStatus.SENT)
        self.assertIsNone(survivor.batch_id)

    def test_a_stocked_batch_is_refused_by_name(self):
        FinishedGoodsStock.objects.create(
            product=self.batch.product,
            batch=self.batch,
            quantity=Decimal("10"),
            unit=self.batch.unit,
            expiration_date=timezone.now() + timedelta(hours=24),
            received_by=self.manager,
        )
        with self.assertRaises(ValidationError) as ctx:
            delete_batch(self.batch, self.manager)
        self.assertIn("склад", " ".join(ctx.exception.messages))
        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())


class DeleteOrderServiceTests(TestCase):
    def setUp(self):
        self.manager = create_user("board-manager", UserProfile.Role.MANAGER)
        self.batch = create_batch_at_stage("mixing", self.manager)
        self.order = self.batch.order_item.order

    def test_removes_order_items_and_batches_together(self):
        """Ради этого кнопка и появилась: страница заказа отказывает, едва
        партии созданы, и ошибочный заказ было не удалить вообще."""
        number, count = delete_order_with_batches(self.order, self.manager)
        self.assertEqual(count, 1)
        self.assertFalse(ProductionOrder.objects.filter(pk=self.order.pk).exists())
        self.assertFalse(ProductionOrderItem.objects.filter(order_id=self.order.pk).exists())
        self.assertFalse(ProductionBatch.objects.filter(pk=self.batch.pk).exists())

    def test_one_stocked_batch_blocks_the_whole_order(self):
        FinishedGoodsStock.objects.create(
            product=self.batch.product,
            batch=self.batch,
            quantity=Decimal("5"),
            unit=self.batch.unit,
            expiration_date=timezone.now() + timedelta(hours=24),
            received_by=self.manager,
        )
        with self.assertRaises(ValidationError):
            delete_order_with_batches(self.order, self.manager)
        self.assertTrue(ProductionOrder.objects.filter(pk=self.order.pk).exists())
        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())


class DeleteViewsTests(TestCase):
    def setUp(self):
        self.manager = create_user("board-manager", UserProfile.Role.MANAGER)
        self.worker = create_user("board-worker", UserProfile.Role.USER)
        self.batch = create_batch_at_stage("mixing", self.manager)

    def test_manager_deletes_from_the_board_and_returns_to_it(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("bakery:delete_batch", args=[self.batch.pk]),
            {"next": reverse("bakery:kanban")},
        )
        self.assertRedirects(response, reverse("bakery:kanban"))
        self.assertFalse(ProductionBatch.objects.filter(pk=self.batch.pk).exists())

    def test_a_worker_cannot_delete(self):
        self.client.force_login(self.worker)
        response = self.client.post(reverse("bakery:delete_batch", args=[self.batch.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())

    def test_get_does_nothing(self):
        """Удаление - только POST: ссылка из письма или предзагрузка браузера
        не должны уметь стирать партии."""
        self.client.force_login(self.manager)
        response = self.client.get(reverse("bakery:delete_batch", args=[self.batch.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())

    def test_order_route_deletes_the_group(self):
        self.client.force_login(self.manager)
        order = self.batch.order_item.order
        response = self.client.post(reverse("bakery:delete_order", args=[order.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProductionOrder.objects.filter(pk=order.pk).exists())

    def test_the_button_is_rendered_only_for_managers(self):
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse("bakery:kanban")), "kanban-card-delete")
        self.client.force_login(self.worker)
        self.assertNotContains(self.client.get(reverse("bakery:kanban")), "kanban-card-delete")

    def test_a_stocked_batch_survives_the_view_with_a_message(self):
        FinishedGoodsStock.objects.create(
            product=self.batch.product,
            batch=self.batch,
            quantity=Decimal("10"),
            unit=self.batch.unit,
            expiration_date=timezone.now() + timedelta(hours=24),
            received_by=self.manager,
        )
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("bakery:delete_batch", args=[self.batch.pk]), follow=True
        )
        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())
        self.assertContains(response, "склад")
