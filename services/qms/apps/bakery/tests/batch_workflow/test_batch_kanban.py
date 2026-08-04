from django.test import TestCase
from django.urls import reverse

from apps.bakery.models import BatchStageHistory, ProductionBatch
from apps.bakery.services import pause_batch

from .factories import create_problem, create_user
from .helpers import WORKFLOW, create_batch_at_stage, stage


class BatchKanbanTests(TestCase):
    def setUp(self):
        self.user = create_user()


def make_kanban_stage_test(code):
    def test(self):
        batch = create_batch_at_stage(code, self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, batch.batch_number)
        self.assertEqual(ProductionBatch.objects.filter(pk=batch.pk, current_stage__code=code).count(), 1)
    return test


for code in WORKFLOW:
    setattr(BatchKanbanTests, f"test_batch_visible_in_{code}_column", make_kanban_stage_test(code))


class BatchKanbanFilterTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.batch = create_batch_at_stage("mixing", self.user)
        self.client.force_login(self.user)

    def test_search_by_batch_number(self):
        response = self.client.get(reverse("bakery:kanban"), {"q": self.batch.batch_number})
        self.assertContains(response, self.batch.batch_number)

    def test_filter_by_product(self):
        response = self.client.get(reverse("bakery:kanban"), {"product": self.batch.product_id})
        self.assertContains(response, self.batch.batch_number)

    def test_filter_by_assigned_status(self):
        response = self.client.get(reverse("bakery:kanban"), {"status": self.batch.status})
        self.assertContains(response, self.batch.batch_number)

    def test_filter_by_priority(self):
        response = self.client.get(reverse("bakery:kanban"), {"priority": self.batch.order_item.order.priority})
        self.assertContains(response, self.batch.batch_number)

    def test_column_search(self):
        response = self.client.get(reverse("bakery:kanban"), {"stage_q_mixing": self.batch.batch_number})
        self.assertContains(response, self.batch.batch_number)

    def test_paused_batch_visible_with_status(self):
        pause_batch(self.batch, self.user, "pause")
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, "paused")

    def test_problem_batch_visible_with_status(self):
        create_problem(self.batch)
        self.batch.status = "problem"
        self.batch.save(update_fields=["status", "updated_at"])
        response = self.client.get(reverse("bakery:kanban"))
        self.assertContains(response, "problem")

    def test_batch_list_page_contains_batch(self):
        response = self.client.get(reverse("bakery:batches"))
        self.assertContains(response, self.batch.batch_number)


class KanbanCardActionsTests(TestCase):
    """The "Дальше →" button posts without naming a stage, so on a card in the
    last column it asked the view to move a batch that has nowhere left to go."""

    def setUp(self):
        self.user = create_user()
        self.client.force_login(self.user)

    def board(self):
        return self.client.get(reverse("bakery:kanban")).content.decode()

    def test_card_in_a_middle_column_offers_the_next_stage(self):
        create_batch_at_stage("mixing", self.user)
        self.assertEqual(self.board().count("Дальше"), 1)

    def test_card_in_the_last_column_does_not(self):
        batch = create_batch_at_stage("done", self.user)
        html = self.board()
        self.assertIn(batch.batch_number, html)
        self.assertNotIn("Дальше", html)

    def test_only_the_last_column_loses_the_button(self):
        for code in ("queue", "mixing", "oven"):
            create_batch_at_stage(code, create_user(username=f"op-{code}"))
        create_batch_at_stage("done", create_user(username="op-done"))
        self.assertEqual(self.board().count("Дальше"), 3)


class KanbanReturnUrlTests(TestCase):
    """kanban_partial serves the same template for script refreshes, so a card
    rendered there must still send you back to the page, not to the fragment."""

    def setUp(self):
        self.user = create_user()
        self.client.force_login(self.user)
        create_batch_at_stage("mixing", self.user)

    def test_the_page_points_cards_at_the_board(self):
        html = self.client.get(reverse("bakery:kanban")).content.decode()
        self.assertIn('name="next" value="/bakery/board/"', html)

    def test_the_refresh_fragment_points_cards_at_the_board_too(self):
        html = self.client.get(reverse("bakery:kanban_partial")).content.decode()
        self.assertIn('name="next" value="/bakery/board/"', html)
        self.assertNotIn("board/partial", html)

    def test_filters_survive_the_round_trip(self):
        html = self.client.get(reverse("bakery:kanban_partial"), {"demo": "all"}).content.decode()
        self.assertIn('name="next" value="/bakery/board/?demo=all"', html)


class KanbanTouchFallbackTests(TestCase):
    """HTML5 drag and drop fires nothing from touch, so on a phone or tablet the
    card buttons are the only way to move a batch - in either direction."""

    def setUp(self):
        self.user = create_user()
        self.client.force_login(self.user)

    def board(self):
        return self.client.get(reverse("bakery:kanban")).content.decode()

    def test_first_column_offers_no_way_back(self):
        create_batch_at_stage("queue", self.user)
        self.assertNotIn("Назад", self.board())

    def test_middle_column_offers_both_directions(self):
        create_batch_at_stage("mixing", self.user)
        html = self.board()
        self.assertIn("Назад", html)
        self.assertIn("Дальше", html)

    def test_last_column_offers_only_the_way_back(self):
        create_batch_at_stage("done", self.user)
        html = self.board()
        self.assertIn("Назад", html)
        self.assertNotIn("Дальше", html)

    def test_the_back_button_moves_the_batch(self):
        batch = create_batch_at_stage("forming", self.user)
        html = self.board()
        # The form carries a comment, because move_batch demands one for a
        # backward step - the same one drag and drop has always sent.
        self.assertIn("Возврат на Kanban-доске", html)
        self.client.post(
            reverse("bakery:move_batch", args=[batch.pk]),
            {"stage": stage("mixing").pk, "comment": "Возврат на Kanban-доске"},
        )
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")


class KanbanFreeDragTests(TestCase):
    """Dragging a card names a column, not a step, so it may cross several."""

    def setUp(self):
        self.user = create_user()
        self.client.force_login(self.user)

    def drag(self, batch, stage_code, comment="Перенос на Kanban-доске"):
        return self.client.post(
            reverse("bakery:move_batch", args=[batch.pk]),
            {"stage": stage(stage_code).pk, "comment": comment},
            headers={"x-requested-with": "XMLHttpRequest"},
        )

    def test_a_card_may_be_dragged_across_several_columns(self):
        batch = create_batch_at_stage("mixing", self.user)
        response = self.drag(batch, "warehouse")
        self.assertIs(response.json()["ok"], True)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "warehouse")

    def test_a_dragged_jump_records_what_it_stepped_over(self):
        batch = create_batch_at_stage("mixing", self.user)
        self.drag(batch, "oven")
        history = BatchStageHistory.objects.filter(batch=batch, to_stage__code="oven").latest("created_at")
        self.assertIn("Формовка", history.comment)
        self.assertIn("Расстойка", history.comment)

    def test_a_card_may_be_dragged_backwards(self):
        batch = create_batch_at_stage("oven", self.user)
        self.assertIs(self.drag(batch, "mixing").json()["ok"], True)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_a_jump_with_no_comment_is_still_refused(self):
        batch = create_batch_at_stage("mixing", self.user)
        response = self.drag(batch, "warehouse", comment="")
        self.assertIs(response.json()["ok"], False)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")
