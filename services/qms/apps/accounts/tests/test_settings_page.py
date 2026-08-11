from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.bakery.models import ProductionStage
from apps.bakery.tests.batch_workflow.factories import (
    create_manual_batch,
    create_stage_list,
    create_user,
)


class SettingsPageTests(TestCase):
    def setUp(self):
        self.stages = create_stage_list()
        self.url = reverse("accounts:settings")

    def login(self, username, role):
        user = create_user(username, role, password="pass12345")
        self.client.login(username=username, password="pass12345")
        return user

    # -- кто что видит на самой странице ------------------------------------

    def test_operator_gets_the_personal_half_only(self):
        self.login("operator", UserProfile.Role.USER)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Личные данные")
        self.assertNotContains(response, "Этапы производства")
        self.assertFalse(response.context["may_configure"])

    def test_technologist_gets_catalogues_and_stages(self):
        self.login("tech", UserProfile.Role.MANAGER)
        response = self.client.get(self.url)
        self.assertTrue(response.context["may_configure"])
        self.assertContains(response, "Этапы производства")
        self.assertEqual(len(response.context["catalog"]), 3)
        self.assertEqual(len(response.context["stages"]), len(self.stages))

    # -- личные данные -------------------------------------------------------

    def test_profile_is_saved_across_both_models(self):
        user = self.login("operator2", UserProfile.Role.USER)
        self.client.post(self.url, {
            "action": "profile",
            "first_name": "Асхат",
            "last_name": "Ермеков",
            "email": "a@example.kz",
            "phone": "+7 701 000 00 00",
        })
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Асхат")
        self.assertEqual(user.email, "a@example.kz")
        self.assertEqual(user.profile.phone, "+7 701 000 00 00")

    def test_password_change_keeps_the_session_alive(self):
        self.login("operator3", UserProfile.Role.USER)
        response = self.client.post(self.url, {
            "action": "password",
            "old_password": "pass12345",
            "new_password1": "Zerde-2026-xyz",
            "new_password2": "Zerde-2026-xyz",
        }, follow=True)
        self.assertContains(response, "Пароль изменён")
        # Без update_session_auth_hash здесь была бы форма входа.
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_password_change_reports_a_mismatch(self):
        self.login("operator4", UserProfile.Role.USER)
        response = self.client.post(self.url, {
            "action": "password",
            "old_password": "pass12345",
            "new_password1": "Zerde-2026-xyz",
            "new_password2": "Zerde-2026-abc",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["password_form"].errors)

    # -- этапы ---------------------------------------------------------------

    def test_technologist_renames_a_stage(self):
        self.login("tech2", UserProfile.Role.MANAGER)
        data = self.stage_form()
        data[f"stage_name_{self.stages['oven'].pk}"] = "Печь №2"
        data["action"] = "stages"
        self.client.post(self.url, data)
        self.stages["oven"].refresh_from_db()
        self.assertEqual(self.stages["oven"].name, "Печь №2")

    def test_moving_a_stage_swaps_the_sequences(self):
        self.login("tech3", UserProfile.Role.MANAGER)
        mixing, forming = self.stages["mixing"], self.stages["forming"]
        before = (mixing.sequence, forming.sequence)
        data = self.stage_form()
        data["move"] = f"down:{mixing.pk}"
        self.client.post(self.url, data)
        mixing.refresh_from_db()
        forming.refresh_from_db()
        # Порядок уникален: прямой обмен упал бы на ограничении базы.
        self.assertEqual((mixing.sequence, forming.sequence), (before[1], before[0]))

    def test_the_topmost_stage_cannot_go_up(self):
        self.login("tech4", UserProfile.Role.MANAGER)
        first = ProductionStage.objects.order_by("sequence").first()
        data = self.stage_form()
        data["move"] = f"up:{first.pk}"
        response = self.client.post(self.url, data, follow=True)
        self.assertContains(response, "уже крайний")
        first.refresh_from_db()
        self.assertEqual(first.sequence, 1)

    def test_a_stage_holding_batches_cannot_be_switched_off(self):
        """Выключенный этап пропадает с доски вместе со стоящими на нём партиями."""
        self.login("tech5", UserProfile.Role.MANAGER)
        create_manual_batch(stage_code="mixing")
        data = self.stage_form()
        data.pop(f"stage_active_{self.stages['mixing'].pk}")
        data["action"] = "stages"
        response = self.client.post(self.url, data, follow=True)
        self.assertContains(response, "нельзя выключить")
        self.stages["mixing"].refresh_from_db()
        self.assertTrue(self.stages["mixing"].is_active)

    def test_an_empty_stage_switches_off(self):
        self.login("tech6", UserProfile.Role.MANAGER)
        data = self.stage_form()
        data.pop(f"stage_active_{self.stages['warehouse'].pk}")
        data["action"] = "stages"
        self.client.post(self.url, data)
        self.stages["warehouse"].refresh_from_db()
        self.assertFalse(self.stages["warehouse"].is_active)

    def test_operator_cannot_touch_the_stages(self):
        self.login("operator5", UserProfile.Role.USER)
        data = self.stage_form()
        data[f"stage_name_{self.stages['oven'].pk}"] = "Взломано"
        data["action"] = "stages"
        response = self.client.post(self.url, data, follow=True)
        self.assertContains(response, "доступна менеджеру")
        self.stages["oven"].refresh_from_db()
        self.assertEqual(self.stages["oven"].name, "Печь")

    def stage_form(self):
        """Форма этапов такая, какой её отправляет браузер: все поля разом."""
        data = {}
        for stage in ProductionStage.objects.all():
            data[f"stage_name_{stage.pk}"] = stage.name
            if stage.is_active:
                data[f"stage_active_{stage.pk}"] = "on"
        return data
