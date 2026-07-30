from django.test import TestCase
from django.utils import timezone

from .factories import create_user
from .helpers import create_batch_at_stage, move_batch


class StageTimingTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_actual_start_is_timezone_aware(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.assertTrue(timezone.is_aware(batch.actual_start))

    def test_history_finished_at_is_timezone_aware(self):
        row = create_batch_at_stage("mixing", self.user).stage_history.first()
        self.assertTrue(timezone.is_aware(row.finished_at))

    def test_queue_duration_is_not_negative(self):
        self.assertGreaterEqual(create_batch_at_stage("queue", self.user).stage_duration.total_seconds(), 0)

    def test_mixing_duration_is_not_negative(self):
        self.assertGreaterEqual(create_batch_at_stage("mixing", self.user).stage_duration.total_seconds(), 0)

    def test_forming_duration_is_not_negative(self):
        self.assertGreaterEqual(create_batch_at_stage("forming", self.user).stage_duration.total_seconds(), 0)

    def test_proofing_duration_is_not_negative(self):
        self.assertGreaterEqual(create_batch_at_stage("proofing", self.user).stage_duration.total_seconds(), 0)

    def test_oven_duration_is_not_negative(self):
        self.assertGreaterEqual(create_batch_at_stage("oven", self.user).stage_duration.total_seconds(), 0)

    def test_warehouse_duration_is_not_negative(self):
        self.assertGreaterEqual(create_batch_at_stage("warehouse", self.user).stage_duration.total_seconds(), 0)

    def test_same_moment_transition_allows_zero_or_positive_duration(self):
        batch = create_batch_at_stage("mixing", self.user)
        move_batch(batch, "forming", self.user, "same moment")
        self.assertGreaterEqual(batch.stage_history.order_by("-created_at").first().duration_minutes, 0)

    def test_planned_finish_equal_now_is_comparable(self):
        batch = create_batch_at_stage("mixing", self.user)
        batch.planned_finish = timezone.now()
        batch.save(update_fields=["planned_finish", "updated_at"])
        self.assertLessEqual(batch.planned_finish, timezone.now())
