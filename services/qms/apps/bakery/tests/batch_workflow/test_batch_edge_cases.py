from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.bakery.models import ProductionBatch, ProductionStage

from .factories import create_manual_batch, create_stage_list, create_user
from .helpers import assert_move_rejected, create_batch_at_stage, move_batch, stage


class BatchEdgeCaseTests(TestCase):
    def setUp(self):
        self.user = create_user()
        create_stage_list()

    def test_missing_current_stage_fails_model_save(self):
        batch = create_manual_batch(user=self.user)
        batch.current_stage = None
        with self.assertRaises(Exception):
            batch.save()

    def test_inactive_next_stage_is_not_returned_by_next_endpoint_helper(self):
        from apps.bakery.services import next_stage_for
        batch = create_batch_at_stage("queue", self.user)
        mixing = stage("mixing")
        mixing.is_active = False
        mixing.save(update_fields=["is_active"])
        self.assertNotEqual(next_stage_for(batch).code, "mixing")

    def test_duplicate_stage_sequence_rejected(self):
        with self.assertRaises(IntegrityError):
            ProductionStage.objects.create(code="duplicate-sequence", name="Duplicate", sequence=1)

    def test_large_quantity_is_supported(self):
        batch = create_manual_batch(user=self.user, quantity=Decimal("999999.999"))
        self.assertEqual(batch.planned_quantity, Decimal("999999.999"))

    def test_fractional_quantity_is_supported(self):
        batch = create_manual_batch(user=self.user, quantity=Decimal("12.500"))
        self.assertEqual(batch.planned_quantity, Decimal("12.500"))

    def test_actual_quantity_can_be_more_than_planned(self):
        batch = create_manual_batch(user=self.user)
        batch.actual_quantity = Decimal("120.000")
        batch.full_clean()
        self.assertEqual(batch.actual_quantity, Decimal("120.000"))

    def test_actual_quantity_can_be_less_than_planned(self):
        batch = create_manual_batch(user=self.user)
        batch.actual_quantity = Decimal("80.000")
        batch.full_clean()
        self.assertEqual(batch.actual_quantity, Decimal("80.000"))

    def test_negative_actual_quantity_rejected(self):
        batch = create_manual_batch(user=self.user)
        batch.actual_quantity = Decimal("-1.000")
        with self.assertRaises(ValidationError):
            batch.full_clean()

    def test_long_comment_is_saved(self):
        batch = create_batch_at_stage("mixing", self.user)
        comment = "x" * 5000
        move_batch(batch, "forming", self.user, comment)
        self.assertEqual(batch.stage_history.order_by("-created_at").first().comment, comment)

    def test_empty_comment_allowed_on_forward_transition(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_empty_comment_forbidden_on_backward_transition(self):
        assert_move_rejected(self, create_batch_at_stage("forming", self.user), "mixing", self.user, ValidationError)

    def test_planned_dates_are_timezone_aware(self):
        batch = create_manual_batch(user=self.user, planned_finish=timezone.now())
        self.assertTrue(timezone.is_aware(batch.planned_finish))
