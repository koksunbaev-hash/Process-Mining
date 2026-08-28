"""Удаление карточек с доски.

Кнопка нужна для одного случая - карточки, которой не должно было возникнуть.
Поэтому тесты стерегут не столько удаление, сколько его границы: кто может,
что именно исчезает и что при этом обязано уцелеть.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.bakery.models import ProductionBatch, ProductionOrder
from .batch_workflow.factories import create_queued_batch, create_stage_list, create_user

User = get_user_model()

#: Доску рисуют два теста, а манифест статики в тестовой среде не собран:
#: ManifestStaticFilesStorage требует собранных файлов и падает на первом же
#: {% static %}. Проверяется здесь разметка, а не отпечатки имён файлов.
PLAIN_STATIC = override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})


class BoardDeleteTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.dispatcher = create_user()
        self.batch = create_queued_batch(user=self.dispatcher)
        self.batch.refresh_from_db()
        self.order = self.batch.order_item.order
        self.client.force_login(self.dispatcher)

    def _delete(self, batch=None):
        return self.client.post(
            reverse("bakery:delete_batch", args=[(batch or self.batch).pk]),
            {"next": reverse("bakery:kanban")},
        )

    def test_the_card_and_its_emptied_order_both_go(self):
        """Заказ без партий - след ошибки ввода, а не заказ."""
        self._delete()
        self.assertFalse(ProductionBatch.objects.filter(pk=self.batch.pk).exists())
        self.assertFalse(ProductionOrder.objects.filter(pk=self.order.pk).exists())

    def test_an_order_with_other_batches_survives(self):
        """Заказ на пять позиций, из которых ошибочна одна, теряет только её."""
        second = ProductionBatch.objects.create(
            order_item=self.batch.order_item,
            product=self.batch.product,
            recipe=self.batch.recipe,
            planned_quantity=self.batch.planned_quantity,
            unit=self.batch.unit,
            current_stage=self.batch.current_stage,
            status=self.batch.status,
            assigned_to=self.dispatcher,
        )
        self._delete()
        self.assertTrue(ProductionOrder.objects.filter(pk=self.order.pk).exists())
        self.assertTrue(ProductionBatch.objects.filter(pk=second.pk).exists())

    def test_a_get_request_deletes_nothing(self):
        """Иначе карточку сносил бы переход по ссылке - из истории браузера,
        из предзагрузки, из чужого письма."""
        response = self.client.get(reverse("bakery:delete_batch", args=[self.batch.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())

    def test_a_baker_cannot_delete(self):
        baker = create_user(username="пекарь", role="user")
        self.client.force_login(baker)
        self._delete()
        self.assertTrue(ProductionBatch.objects.filter(pk=self.batch.pk).exists())

    def test_deleting_the_same_card_twice_says_so_instead_of_crashing(self):
        """Двое смотрят на одну доску: второй нажмёт на карточку, которой уже
        нет."""
        pk = self.batch.pk
        self._delete()
        response = self.client.post(
            reverse("bakery:delete_batch", args=[pk]), {"next": reverse("bakery:kanban")}
        )
        self.assertEqual(response.status_code, 404)

    @PLAIN_STATIC
    def test_the_button_is_hidden_from_those_who_cannot_use_it(self):
        baker = create_user(username="пекарь2", role="user")
        self.client.force_login(baker)
        board = self.client.get(reverse("bakery:kanban"))
        self.assertNotContains(board, "kanban-card-delete")

    @PLAIN_STATIC
    def test_the_button_is_on_the_board_for_a_dispatcher(self):
        board = self.client.get(reverse("bakery:kanban"))
        self.assertContains(board, "kanban-card-delete")
