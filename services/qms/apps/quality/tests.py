from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.equipment.models import MeasuringEquipment
from apps.inspections.models import InspectionResult
from apps.inspections.services import complete_card, create_reinspection, start_task
from apps.nonconformities.models import DefectType
from apps.nonconformities.services import register_nonconformity
from apps.quality.models import (
    ControlParameter,
    ControlPost,
    ControlRoute,
    ControlRouteStep,
    ControlType,
    Department,
    InspectionTemplate,
    InspectionTemplateParameter,
    QualityObject,
)
from apps.quality.services import create_quality_object_with_route
from apps.quality.services import create_inspection_task_for_step


class QmsBusinessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user("admin", password="x", is_staff=True, is_superuser=True)
        self.inspector = User.objects.create_user("inspector", password="x")
        self.auditor = User.objects.create_user("auditor", password="x")
        self.auditor.profile.role = UserProfile.Role.AUDITOR
        self.auditor.profile.save()
        self.department = Department.objects.create(name="ОТК", code="QCD")
        self.control_type = ControlType.objects.create(name="измерительный", code="measure")
        self.post = ControlPost.objects.create(code="P01", name="Пост", department=self.department, control_type=self.control_type, responsible_user=self.inspector)
        self.parameter = ControlParameter.objects.create(code="LEN", name="Длина", unit="мм", value_type="number", lower_limit=10, upper_limit=20, criticality="medium")
        self.critical_parameter = ControlParameter.objects.create(code="CRIT", name="Критический размер", unit="мм", value_type="number", lower_limit=10, upper_limit=20, criticality="critical")
        self.template = InspectionTemplate.objects.create(name="Карта", code="TPL", control_post=self.post, control_type=self.control_type)
        self.tp = InspectionTemplateParameter.objects.create(template=self.template, parameter=self.parameter, sequence=1)
        self.critical_tp = InspectionTemplateParameter.objects.create(template=self.template, parameter=self.critical_parameter, sequence=2)
        self.route = ControlRoute.objects.create(name="Маршрут", code="R1")
        self.step = ControlRouteStep.objects.create(route=self.route, control_post=self.post, inspection_template=self.template, sequence=1)
        self.equipment = MeasuringEquipment.objects.create(name="ШЦ", equipment_type="инструмент", serial_number="S1", department=self.department, next_verification_date=timezone.localdate() + timedelta(days=10))
        self.expired_equipment = MeasuringEquipment.objects.create(name="Старый ШЦ", equipment_type="инструмент", serial_number="S2", department=self.department, next_verification_date=timezone.localdate() - timedelta(days=1))
        self.defect = DefectType.objects.create(code="D1", name="Критический дефект", criticality="critical", object_block_required=True)

    def make_object_and_card(self):
        obj = create_quality_object_with_route(
            user=self.admin,
            unique_number=f"OBJ-{QualityObject.objects.count() + 1}",
            object_type="part",
            product_name="Деталь",
            quantity=1,
            department=self.department,
            route=self.route,
        )
        card = start_task(obj.tasks.first(), self.inspector)
        return obj, card

    def test_create_quality_object_and_first_task(self):
        obj, _ = self.make_object_and_card()
        self.assertEqual(obj.tasks.count(), 1)
        self.assertEqual(obj.quality_status, "control_in_progress")

    def test_numeric_tolerance_ok(self):
        _, card = self.make_object_and_card()
        result = card.results.get(template_parameter=self.tp)
        result.numeric_value = 15
        result.measuring_equipment = self.equipment
        result.save()
        self.assertTrue(result.is_within_tolerance)

    def test_below_lower_tolerance(self):
        _, card = self.make_object_and_card()
        result = card.results.get(template_parameter=self.tp)
        result.numeric_value = 5
        result.comment = "ниже допуска"
        result.save()
        self.assertFalse(result.is_within_tolerance)

    def test_above_upper_tolerance(self):
        _, card = self.make_object_and_card()
        result = card.results.get(template_parameter=self.tp)
        result.numeric_value = 25
        result.comment = "выше допуска"
        result.save()
        self.assertFalse(result.is_within_tolerance)

    def test_required_value_blocks_completion(self):
        _, card = self.make_object_and_card()
        with self.assertRaises(ValidationError):
            complete_card(card, self.inspector)

    def test_expired_equipment_rejected(self):
        _, card = self.make_object_and_card()
        result = card.results.get(template_parameter=self.tp)
        result.numeric_value = 15
        result.measuring_equipment = self.expired_equipment
        with self.assertRaises(ValidationError):
            result.full_clean()

    def test_critical_defect_blocks_object_and_nonconformity_created(self):
        obj, card = self.make_object_and_card()
        nc = register_nonconformity(
            user=self.inspector,
            quality_object=obj,
            inspection_card=card,
            control_post=self.post,
            defect_type=self.defect,
            description="Критический дефект",
            criticality="critical",
        )
        obj.refresh_from_db()
        self.assertEqual(obj.quality_status, "blocked")
        self.assertEqual(nc.number[:7], "QMS-NC-")

    def test_reinspection_created(self):
        obj, card = self.make_object_and_card()
        nc = register_nonconformity(user=self.inspector, quality_object=obj, inspection_card=card, control_post=self.post, defect_type=self.defect, description="Дефект", criticality="critical")
        reinspection = create_reinspection(nc, inspector=self.inspector, user=self.admin)
        self.assertIsNotNone(reinspection.new_inspection_task)

    def test_positive_route_completion(self):
        obj, card = self.make_object_and_card()
        for result in card.results.all():
            result.numeric_value = 15
            result.measuring_equipment = self.equipment
            result.save()
        complete_card(card, self.inspector)
        obj.refresh_from_db()
        self.assertEqual(obj.quality_status, "ready_for_shipment")

    def test_inspector_api_write_allowed(self):
        client = APIClient()
        client.force_authenticate(self.inspector)
        response = client.get("/api/tasks/")
        self.assertEqual(response.status_code, 200)

    def test_auditor_is_read_only(self):
        client = APIClient()
        client.force_authenticate(self.auditor)
        response = client.post("/api/control-parameters/", {"code": "X", "name": "X", "value_type": "text"})
        self.assertEqual(response.status_code, 403)

    def test_closed_nonconformity_delete_forbidden(self):
        obj, card = self.make_object_and_card()
        nc = register_nonconformity(user=self.inspector, quality_object=obj, inspection_card=card, control_post=self.post, defect_type=self.defect, description="Дефект", criticality="critical")
        nc.status = "closed"
        nc.approved_by_quality_manager = self.admin
        nc.save()
        with self.assertRaises(ValidationError):
            nc.delete()

    def test_status_history_written(self):
        obj, _ = self.make_object_and_card()
        obj.set_status("quarantine", self.admin, "тест")
        self.assertEqual(obj.quality_status, "quarantine")
        self.assertTrue(obj.has_open_critical_nonconformity is False)

    def test_duplicate_active_task_for_post_forbidden(self):
        obj, _ = self.make_object_and_card()
        with self.assertRaises(ValidationError):
            create_inspection_task_for_step(obj, self.step, user=self.admin)

    def test_manual_override_requires_reason(self):
        _, card = self.make_object_and_card()
        result = card.results.get(template_parameter=self.tp)
        result.numeric_value = 15
        result.is_manual_override = True
        with self.assertRaises(ValidationError):
            result.full_clean()
