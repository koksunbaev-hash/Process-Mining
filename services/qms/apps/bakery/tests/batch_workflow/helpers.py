from django.core.exceptions import PermissionDenied, ValidationError

from apps.bakery.models import ProductionBatch, ProductionStage
from apps.bakery.services import move_batch as service_move_batch
from apps.bakery.services import pause_batch, resume_batch

from .factories import create_queued_batch, create_stage_list, create_user


WORKFLOW = ["queue", "mixing", "forming", "proofing", "oven", "warehouse", "done"]


def stage(code):
    create_stage_list()
    return ProductionStage.objects.get(code=code)


def create_batch_at_stage(stage_code, user=None):
    user = user or create_user()
    batch = create_queued_batch(user=user)
    for code in WORKFLOW[1 : WORKFLOW.index(stage_code) + 1]:
        service_move_batch(batch, stage(code), user, f"to {code}")
        batch.refresh_from_db()
    return batch


def move_batch(batch, stage_code, user, comment=""):
    service_move_batch(batch, stage(stage_code), user, comment)
    batch.refresh_from_db()
    return batch


def complete_full_workflow(batch, user):
    for code in WORKFLOW[WORKFLOW.index(batch.current_stage.code) + 1 :]:
        move_batch(batch, code, user, f"to {code}")
        batch.refresh_from_db()
    return batch


def assert_move_rejected(testcase, batch, stage_code, user, exc=(ValidationError, PermissionDenied), comment=""):
    batch.refresh_from_db()
    old_stage = batch.current_stage_id
    old_history = batch.stage_history.count()
    with testcase.assertRaises(exc):
        move_batch(batch, stage_code, user, comment)
    batch.refresh_from_db()
    testcase.assertEqual(batch.current_stage_id, old_stage)
    testcase.assertEqual(batch.stage_history.count(), old_history)
