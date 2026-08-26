"""Справочник привязки машин к двойникам - то, чем живёт 3D-сцена.

Сцена в Grafana собрана на объектах, каждый из которых должен знать свой
`thingId`. Раньше эту таблицу передавали словами, и любая правка двойника в
админке расходилась со сценой молча. Здесь проверяется, что API отдаёт её
целиком и честно показывает машины, у которых двойника ещё нет.
"""

from django.test import TestCase
from django.urls import reverse

from apps.bakery.models import ProductionStage, ProductionUnit

from .batch_workflow.factories import create_stage_list, create_user


class ProductionUnitApiTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.user = create_user()
        self.client.force_login(self.user)
        oven = ProductionStage.objects.get(code="oven")
        self.bound = ProductionUnit.objects.create(
            stage=oven, name="Печь 1", sequence=1, twin_id="digitalegiz:oven-1"
        )
        self.unbound = ProductionUnit.objects.create(stage=oven, name="Печь 2", sequence=2)
        self.url = reverse("production-unit-list")

    def test_every_machine_comes_with_its_thing_id(self):
        rows = {row["name"]: row for row in self.client.get(self.url).json()}
        self.assertEqual(rows["Печь 1"]["twin_id"], "digitalegiz:oven-1")
        self.assertEqual(rows["Печь 1"]["stage_code"], "oven")
        self.assertEqual(rows["Печь 2"]["twin_id"], "")

    def test_the_row_carries_what_the_twin_carries(self):
        """Тот же payload, что уезжает в фичу product: сцену можно сверить с
        источником, не имея доступа к Ditto."""
        row = self.client.get(self.url).json()[0]
        self.assertEqual(row["product"]["status"], "свободно")
        self.assertEqual(row["product"]["stage"], "Печь")

    def test_the_list_shows_machines_still_waiting_for_a_twin(self):
        rows = self.client.get(self.url, {"bound": "0"}).json()
        self.assertEqual([row["name"] for row in rows], ["Печь 2"])
        rows = self.client.get(self.url, {"bound": "1"}).json()
        self.assertEqual([row["name"] for row in rows], ["Печь 1"])

    def test_the_whole_shop_fits_in_one_answer(self):
        """Сцене нужен цех целиком, а не первая страница из двадцати пяти."""
        payload = self.client.get(self.url).json()
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)

    def test_the_binding_is_set_in_the_admin_not_over_the_api(self):
        response = self.client.post(self.url, {"name": "Печь 3", "stage": self.bound.stage_id})
        self.assertEqual(response.status_code, 405)

    def test_a_stranger_gets_nothing(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)
