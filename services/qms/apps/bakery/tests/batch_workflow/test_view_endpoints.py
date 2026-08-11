from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile

from .factories import create_user
from .helpers import create_batch_at_stage, stage


class BatchViewEndpointTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.batch = create_batch_at_stage("mixing", self.user)
        self.client.force_login(self.user)

    def test_batch_detail_opens(self):
        self.assertEqual(self.client.get(reverse("bakery:batch_detail", args=[self.batch.pk])).status_code, 200)

    def test_move_view_post_moves_batch(self):
        response = self.client.post(reverse("bakery:move_batch", args=[self.batch.pk]), {"stage": stage("forming").pk, "comment": "form"})
        self.assertEqual(response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "forming")

    def test_move_view_rejects_invalid_transition(self):
        response = self.client.post(reverse("bakery:move_batch", args=[self.batch.pk]), {"stage": stage("oven").pk})
        self.assertEqual(response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "mixing")

    def test_move_view_on_last_stage_answers_instead_of_crashing(self):
        # No stage in the post and none after "done", so the view used to read
        # .sequence off None while building the move_batch arguments.
        batch = create_batch_at_stage("done", self.user)
        response = self.client.post(reverse("bakery:move_batch", args=[batch.pk]))
        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "done")

    def test_move_view_ajax_reports_a_refused_move(self):
        response = self.client.post(
            reverse("bakery:move_batch", args=[self.batch.pk]),
            {"stage": stage("oven").pk},
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["ok"], False)
        self.assertTrue(response.json()["error"])
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "mixing")

    def test_move_view_ajax_reports_a_successful_move(self):
        response = self.client.post(
            reverse("bakery:move_batch", args=[self.batch.pk]),
            {"stage": stage("forming").pk, "comment": "form"},
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertIs(response.json()["ok"], True)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "forming")

    def test_pause_view_sets_paused(self):
        self.client.post(reverse("bakery:batch_action", args=[self.batch.pk, "pause"]), {"comment": "pause"})
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "paused")

    def test_resume_view_sets_in_progress(self):
        self.client.post(reverse("bakery:batch_action", args=[self.batch.pk, "pause"]), {"comment": "pause"})
        self.client.post(reverse("bakery:batch_action", args=[self.batch.pk, "resume"]), {"comment": "resume"})
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "in_progress")

    def test_prev_view_requires_comment(self):
        batch = create_batch_at_stage("forming", self.user)
        self.client.post(reverse("bakery:batch_action", args=[batch.pk, "prev"]), {"comment": ""})
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "forming")

    def test_prev_view_with_comment_returns(self):
        batch = create_batch_at_stage("forming", self.user)
        self.client.post(reverse("bakery:batch_action", args=[batch.pk, "prev"]), {"comment": "return"})
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_employee_moves_a_batch_from_the_board(self):
        # Было наоборот: аудитор нажимал и партия оставалась на месте. Роли
        # аудитора нет, а доска - главный экран сотрудника, поэтому проверяем,
        # что перенос с неё проходит.
        worker = create_user("view-worker", UserProfile.Role.USER)
        self.client.force_login(worker)
        self.client.post(reverse("bakery:move_batch", args=[self.batch.pk]), {"stage": stage("forming").pk})
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_stage.code, "forming")

    def test_a_refused_move_reads_as_a_sentence(self):
        # ValidationError.__str__ is repr(list(self)), so the board would have
        # shown ['Переход возможен только на соседний этап.'] verbatim.
        response = self.client.post(
            reverse("bakery:move_batch", args=[self.batch.pk]),
            {"stage": stage("oven").pk},
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        error = response.json()["error"]
        self.assertTrue(error)
        self.assertNotIn("[", error)
        self.assertNotIn("'", error)
