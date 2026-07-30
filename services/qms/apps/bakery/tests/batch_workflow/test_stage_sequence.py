from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.bakery.models import BatchStageHistory, FinishedGoodsStock

from .factories import create_user
from .helpers import WORKFLOW, assert_move_rejected, create_batch_at_stage, move_batch


ALLOWED = [
    ("queue", "mixing"),
    ("mixing", "forming"),
    ("forming", "proofing"),
    ("proofing", "oven"),
    ("oven", "warehouse"),
    ("warehouse", "done"),
]

FORBIDDEN = [
    ("queue", "forming"), ("queue", "proofing"), ("queue", "oven"), ("queue", "warehouse"), ("queue", "done"),
    ("mixing", "proofing"), ("mixing", "oven"), ("mixing", "warehouse"), ("mixing", "done"),
    ("forming", "oven"), ("forming", "warehouse"), ("forming", "done"),
    ("proofing", "warehouse"), ("proofing", "done"),
    ("oven", "done"),
]


class StageSequenceTests(TestCase):
    def setUp(self):
        self.user = create_user()


def make_allowed_test(from_code, to_code):
    def test(self):
        batch = create_batch_at_stage(from_code, self.user)
        move_batch(batch, to_code, self.user, "ok")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, to_code)
        self.assertEqual(batch.stage_history.order_by("-created_at").first().to_stage.code, to_code)
    return test


def make_forbidden_test(from_code, to_code):
    def test(self):
        batch = create_batch_at_stage(from_code, self.user)
        assert_move_rejected(self, batch, to_code, self.user, ValidationError)
        self.assertFalse(FinishedGoodsStock.objects.filter(batch=batch).exists())
    return test


for from_code, to_code in ALLOWED:
    setattr(StageSequenceTests, f"test_allows_{from_code}_to_{to_code}", make_allowed_test(from_code, to_code))

for from_code, to_code in FORBIDDEN:
    setattr(StageSequenceTests, f"test_rejects_{from_code}_to_{to_code}", make_forbidden_test(from_code, to_code))


class FullSequenceTests(TestCase):
    def test_full_route_has_expected_order(self):
        user = create_user()
        batch = create_batch_at_stage("queue", user)
        for code in WORKFLOW[1:]:
            move_batch(batch, code, user, code)
            batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "done")
        self.assertEqual(list(BatchStageHistory.objects.filter(batch=batch).order_by("created_at").values_list("to_stage__code", flat=True))[1:], WORKFLOW[1:])
