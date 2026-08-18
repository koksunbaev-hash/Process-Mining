"""Место на устройстве: одно устройство - одна партия.

Этап отвечает на вопрос «что с партией делают», устройство - «на чём именно».
Колонка «Печь» с пятью карточками раньше читалась как «пять печей заняты»
независимо от того, сколько печей в цеху.
"""

from decimal import Decimal
import importlib

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import (
    Customer,
    Product,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
    ProductionUnit,
)
from apps.bakery.services import assign_batch_to_unit, confirm_order, free_units_for_stage, move_batch
from apps.bakery.units import DEFAULT_UNITS, ensure_default_units
from apps.bakery.voice_process_mining import extract_unit, parse_voice_command


class ProductionUnitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("unit-dispatcher", password="x")
        self.user.profile.role = UserProfile.Role.MANAGER
        self.user.profile.save(update_fields=["role"])
        self.client.force_login(self.user)

        for sequence, (code, name) in enumerate(
            [("queue", "Очередь"), ("mixing", "Замес"), ("forming", "Формовка"),
             ("proofing", "Расстойка"), ("oven", "Печь"), ("warehouse", "Склад"), ("done", "Готово")],
            start=1,
        ):
            ProductionStage.objects.create(code=code, name=name, sequence=sequence)
        ensure_default_units()

        self.mixing = ProductionStage.objects.get(code="mixing")
        self.oven = ProductionStage.objects.get(code="oven")
        self.customer = Customer.objects.create(name="Кафе")
        self.product = Product.objects.create(code="UNIT-BREAD", name="Хлеб", unit="шт")

    def make_batch(self, quantity="10"):
        order = ProductionOrder.objects.create(
            customer=self.customer,
            required_date=timezone.now(),
            created_by=self.user,
        )
        ProductionOrderItem.objects.create(
            order=order, product=self.product, quantity=Decimal(quantity), unit="шт"
        )
        return confirm_order(order, user=self.user)[0]

    # ---- количество ------------------------------------------------------
    def test_the_shop_floor_equipment_is_seeded_exactly_once(self):
        self.assertEqual(
            list(ProductionUnit.objects.filter(stage=self.oven).values_list("name", flat=True)),
            ["Печь 1", "Печь 2", "Печь 3", "Печь 4", "Печь 5"],
        )
        self.assertEqual(ProductionUnit.objects.filter(stage=self.mixing).count(), 3)
        self.assertEqual(ProductionUnit.objects.filter(stage__code="forming").count(), 2)
        self.assertEqual(ProductionUnit.objects.filter(stage__code="proofing").count(), 3)
        # Повторный запуск ничего не удваивает: seed_bakery зовут на живой базе.
        self.assertEqual(ensure_default_units(), 0)

    def test_stages_without_equipment_have_none(self):
        """У очереди и склада устройств нет - там партия просто лежит."""
        self.assertFalse(ProductionUnit.objects.filter(stage__code__in=["queue", "warehouse", "done"]).exists())

    # ---- одно устройство - одна партия -----------------------------------
    def test_a_device_takes_one_batch_and_refuses_the_second(self):
        first, second = self.make_batch(), self.make_batch()
        first = move_batch(first, self.mixing, self.user, "в замес")
        second = move_batch(second, self.mixing, self.user, "в замес")
        mixer = ProductionUnit.objects.get(name="Миксер 1")

        assign_batch_to_unit(first, mixer, self.user)
        with self.assertRaises(ValidationError) as refusal:
            assign_batch_to_unit(second, mixer, self.user)

        self.assertIn("занято", " ".join(refusal.exception.messages))
        second.refresh_from_db()
        self.assertIsNone(second.production_unit)

    def test_the_waiting_batch_takes_the_device_once_it_is_free(self):
        first, second = self.make_batch(), self.make_batch()
        first = move_batch(first, self.mixing, self.user, "в замес")
        second = move_batch(second, self.mixing, self.user, "в замес")
        mixer = ProductionUnit.objects.get(name="Миксер 1")
        assign_batch_to_unit(first, mixer, self.user)

        # Первая уехала дальше - место освободилось само, без отдельного действия.
        move_batch(first, ProductionStage.objects.get(code="forming"), self.user, "дальше")
        first.refresh_from_db()
        self.assertIsNone(first.production_unit)
        self.assertIn(mixer, free_units_for_stage(self.mixing))

        assign_batch_to_unit(second, mixer, self.user)
        second.refresh_from_db()
        self.assertEqual(second.production_unit, mixer)

    def test_a_device_belongs_to_its_stage(self):
        batch = move_batch(self.make_batch(), self.mixing, self.user, "в замес")
        with self.assertRaises(ValidationError):
            assign_batch_to_unit(batch, ProductionUnit.objects.get(name="Печь 1"), self.user)

    def test_a_device_in_repair_takes_nothing(self):
        batch = move_batch(self.make_batch(), self.mixing, self.user, "в замес")
        mixer = ProductionUnit.objects.get(name="Миксер 1")
        mixer.status = ProductionUnit.Status.REPAIR
        mixer.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            assign_batch_to_unit(batch, mixer, self.user)

    def test_leaving_the_stage_releases_the_device(self):
        batch = move_batch(self.make_batch(), self.mixing, self.user, "в замес")
        assign_batch_to_unit(batch, ProductionUnit.objects.get(name="Миксер 2"), self.user)

        move_batch(batch, ProductionStage.objects.get(code="forming"), self.user, "дальше")

        batch.refresh_from_db()
        self.assertIsNone(batch.production_unit)

    # ---- доска -----------------------------------------------------------
    def test_the_board_shows_a_lane_per_device_and_a_pool_for_the_rest(self):
        batch = move_batch(self.make_batch(), self.oven, self.user, "в печь", allow_skip=True)

        board = self.client.get(reverse("bakery:kanban"))
        self.assertContains(board, "Не распределено")
        for number in range(1, 6):
            self.assertContains(board, f"Печь {number}")
        # Пока партию не поставили - она ждёт в общей дорожке, а все пять печей
        # свободны. Загрузка этапа читается без пересчёта дорожек глазами.
        oven_column = next(c for c in board.context["columns"] if c["stage"] == self.oven)
        self.assertEqual(oven_column["busy"], 0)
        self.assertEqual(oven_column["capacity"], 5)
        self.assertEqual([card.pk for card in oven_column["lanes"][0]["cards"]], [batch.pk])

    def test_dropping_a_card_on_a_device_lane_puts_it_there(self):
        batch = move_batch(self.make_batch(), self.oven, self.user, "в печь", allow_skip=True)
        oven_2 = ProductionUnit.objects.get(name="Печь 2")

        response = self.client.post(
            reverse("bakery:move_batch", args=[batch.pk]),
            {"stage": self.oven.pk, "from_stage": self.oven.pk, "unit": oven_2.pk, "comment": "перенос"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertJSONEqual(response.content, {"ok": True, "error": ""})
        batch.refresh_from_db()
        self.assertEqual(batch.production_unit, oven_2)

    def test_dropping_a_card_on_an_occupied_device_is_refused(self):
        first = move_batch(self.make_batch(), self.oven, self.user, "в печь", allow_skip=True)
        second = move_batch(self.make_batch(), self.oven, self.user, "в печь", allow_skip=True)
        oven_1 = ProductionUnit.objects.get(name="Печь 1")
        assign_batch_to_unit(first, oven_1, self.user)

        response = self.client.post(
            reverse("bakery:move_batch", args=[second.pk]),
            {"stage": self.oven.pk, "from_stage": self.oven.pk, "unit": oven_1.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertFalse(response.json()["ok"])
        second.refresh_from_db()
        self.assertIsNone(second.production_unit)

    def test_an_empty_unit_field_sends_the_card_back_to_the_pool(self):
        batch = move_batch(self.make_batch(), self.oven, self.user, "в печь", allow_skip=True)
        assign_batch_to_unit(batch, ProductionUnit.objects.get(name="Печь 3"), self.user)

        self.client.post(
            reverse("bakery:move_batch", args=[batch.pk]),
            {"stage": self.oven.pk, "from_stage": self.oven.pk, "unit": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        batch.refresh_from_db()
        self.assertIsNone(batch.production_unit)

    def test_moving_on_from_the_board_leaves_the_device_behind(self):
        batch = move_batch(self.make_batch(), self.mixing, self.user, "в замес")
        assign_batch_to_unit(batch, ProductionUnit.objects.get(name="Миксер 3"), self.user)

        self.client.post(
            reverse("bakery:move_batch", args=[batch.pk]),
            {"stage": ProductionStage.objects.get(code="forming").pk, "from_stage": self.mixing.pk},
        )

        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")
        self.assertIsNone(batch.production_unit)


class VoiceUnitTests(TestCase):
    """Голос - основной способ работы в цеху, и устройство он должен слышать."""

    def setUp(self):
        for sequence, (code, name) in enumerate(
            [("queue", "Очередь"), ("mixing", "Замес"), ("forming", "Формовка"),
             ("proofing", "Расстойка"), ("oven", "Печь"), ("warehouse", "Склад"), ("done", "Готово")],
            start=1,
        ):
            ProductionStage.objects.create(code=code, name=name, sequence=sequence)
        ensure_default_units()

    def test_a_named_device_is_heard_in_any_case_form(self):
        for phrase in ("поставь на печь 2", "в печку 2", "на печи 2", "печь № 2"):
            self.assertEqual(extract_unit(phrase)[0], "Печь 2", phrase)

    def test_every_kind_of_device_is_heard(self):
        self.assertEqual(extract_unit("на миксер 3")[0], "Миксер 3")
        self.assertEqual(extract_unit("в шкаф 1")[0], "Шкаф 1")
        self.assertEqual(extract_unit("в расстоечный шкаф 2")[0], "Шкаф 2")
        self.assertEqual(extract_unit("на формовщик 2")[0], "Формовщик 2")

    def test_the_stage_alone_is_not_a_device(self):
        """«На печь» - это этап. Устройство без номера не названо."""
        self.assertEqual(extract_unit("отправь на печь")[0], "")

    def test_the_device_number_is_not_mistaken_for_the_batch(self):
        """«Партия 3 на печь 2» - две цифры подряд, и спутать их нельзя."""
        parsed = parse_voice_command("партия 3 на печь 2")
        self.assertEqual(parsed["unit"], "Печь 2")
        self.assertEqual(parsed["batch_number"], "3")
        self.assertEqual(parsed["to_stage"], "oven")

    def test_the_device_is_heard_even_when_named_first(self):
        parsed = parse_voice_command("печь 2 партия 3")
        self.assertEqual(parsed["unit"], "Печь 2")
        self.assertEqual(parsed["batch_number"], "3")

    def test_a_missing_device_leaves_the_command_a_plain_move(self):
        parsed = parse_voice_command("партия 3 на расстойку")
        self.assertEqual(parsed["unit"], "")
        self.assertEqual(parsed["to_stage"], "proofing")


class DefaultUnitsSpecTests(TestCase):
    def test_the_seed_migration_and_the_module_agree(self):
        """Две копии списка не должны разъезжаться.

        Миграция не ходит в код приложения - иначе правка units.py молча меняла
        бы уже применённую миграцию. Цена этого - вторая копия, и её сверяет
        этот тест: иначе свежая база получила бы не то оборудование, что
        обновлённая.
        """
        migration = importlib.import_module("apps.bakery.migrations.0011_seed_production_units")
        self.assertEqual(migration.UNITS, DEFAULT_UNITS)
