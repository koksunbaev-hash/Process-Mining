"""Ручные правки прогноза: клетку можно исправить, а исправление - снять.

Хранится не прогноз, а несогласие с ним, поэтому проверяется ровно это:
правка ложится поверх расчёта, итоги считаются по исправленному, пустое
значение возвращает расчёт, а обнулённая вручную строка не исчезает с листа
вместе с возможностью передумать.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import (
    BatchStageHistory,
    Customer,
    ForecastOverride,
    Product,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
)
from apps.bakery.views import build_forecast


class ForecastOverrideTests(TestCase):
    def setUp(self):
        self.manager = get_user_model().objects.create_user("forecast-manager", password="x")
        self.manager.profile.role = UserProfile.Role.MANAGER
        self.manager.profile.save(update_fields=["role"])
        self.client.force_login(self.manager)

        for sequence, (code, name) in enumerate(
            [("queue", "Очередь"), ("mixing", "Замес"), ("done", "Готово")], start=1
        ):
            ProductionStage.objects.create(code=code, name=name, sequence=sequence)
        self.mixing = ProductionStage.objects.get(code="mixing")
        self.done = ProductionStage.objects.get(code="done")

        self.customer = Customer.objects.create(name="Кафе")
        self.product = Product.objects.create(code="FCST-BREAD", name="Хлеб", unit="шт")

        # Одна запись факта выпуска неделю назад от целевого дня: прогноз на
        # завтра строится по тому же дню недели, и одного наблюдения хватает.
        self.start = timezone.localdate() + timedelta(days=1)
        order = ProductionOrder.objects.create(
            customer=self.customer, required_date=timezone.now(), created_by=self.manager
        )
        item = ProductionOrderItem.objects.create(
            order=order, product=self.product, quantity=Decimal("100"), unit="шт"
        )
        batch = ProductionBatch.objects.create(
            order_item=item,
            product=self.product,
            planned_quantity=Decimal("100"),
            unit="шт",
            current_stage=self.done,
            status=ProductionBatch.Status.COMPLETED,
        )
        now = timezone.now()
        record = BatchStageHistory.objects.create(
            batch=batch, from_stage=self.mixing, to_stage=self.done, started_at=now, finished_at=now
        )
        BatchStageHistory.objects.filter(pk=record.pk).update(
            created_at=now - timedelta(days=(timezone.localdate() - (self.start - timedelta(weeks=1))).days)
        )

    def post_override(self, quantity, date=None):
        return self.client.post(
            reverse("bakery:forecast_override"),
            {
                "product": self.product.pk,
                "date": (date or self.start).isoformat(),
                "quantity": quantity,
                "from": self.start.isoformat(),
                "weeks": 4,
            },
        )

    def cell(self, data=None):
        data = data or build_forecast(self.start, 4)
        row = next(r for r in data["rows"] if r["product_id"] == self.product.pk)
        return row, row["points"][0]

    def test_computed_forecast_before_any_edits(self):
        row, cell = self.cell()
        self.assertEqual(cell["quantity"], Decimal("100"))
        self.assertFalse(cell["overridden"])

    def test_override_replaces_computed_value_and_totals(self):
        response = self.post_override("150")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["cell"]["overridden"])

        data = build_forecast(self.start, 4)
        row, cell = self.cell(data)
        self.assertEqual(cell["quantity"], Decimal("150"))
        self.assertEqual(cell["computed"], Decimal("100"))
        self.assertEqual(row["total"], Decimal("150"))
        self.assertEqual(data["grand_total"], Decimal("150"))
        self.assertEqual(data["daily"][0], Decimal("150"))

    def test_empty_quantity_returns_the_cell_to_the_computed_value(self):
        self.post_override("150")
        response = self.post_override("")
        self.assertTrue(response.json()["ok"])
        self.assertFalse(ForecastOverride.objects.exists())
        _, cell = self.cell()
        self.assertEqual(cell["quantity"], Decimal("100"))
        self.assertFalse(cell["overridden"])

    def test_zeroed_row_stays_on_the_sheet(self):
        """Иначе вместе со строкой исчезла бы и возможность вернуть её."""
        self.post_override("0")
        data = build_forecast(self.start, 4)
        row, cell = self.cell(data)
        self.assertEqual(row["total"], Decimal("0"))
        self.assertTrue(cell["overridden"])

    def test_comma_decimal_and_negative_are_handled(self):
        self.assertTrue(self.post_override("12,5").json()["ok"])
        self.assertEqual(ForecastOverride.objects.get().quantity, Decimal("12.5"))
        response = self.post_override("-5")
        self.assertEqual(response.status_code, 400)

    def test_plain_user_cannot_edit(self):
        user = get_user_model().objects.create_user("forecast-viewer", password="x")
        user.profile.role = UserProfile.Role.USER
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)
        response = self.post_override("150")
        # 302, а не 403: адрес приписан к разделу «Прогноз», и посредник
        # заворачивает чужую роль на доску - так же, как на любом другом
        # действии не своего раздела. Проверка во вью осталась на месте, просто
        # до неё дело не доходит. Важно здесь другое - что запись не создана.
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ForecastOverride.objects.exists())

    def test_page_renders_with_override_mark(self):
        self.post_override("150")
        response = self.client.get(reverse("bakery:forecast"), {"from": self.start.isoformat(), "weeks": 4})
        self.assertContains(response, "is-override")
        self.assertContains(response, "исправлено вручную")
