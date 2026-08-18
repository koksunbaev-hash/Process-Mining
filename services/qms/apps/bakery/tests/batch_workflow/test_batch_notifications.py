from django.test import TestCase

from apps.bakery.services import pause_batch, resume_batch
from apps.notifications.models import Notification

from .factories import create_user
from .helpers import WORKFLOW, create_batch_at_stage, move_batch


class BatchNotificationTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_queue_notification_created_on_confirm(self):
        batch = create_batch_at_stage("queue", self.user)
        self.assertTrue(Notification.objects.filter(recipient=self.user, notification_type="batch_queued", message__icontains=batch.display_batch_label).exists())

    def test_queue_notification_does_not_name_the_technical_number(self):
        """Уведомление называет партию так же, как карточка на доске.

        Технический B-1000 остаётся идентификатором кейса в process mining, но
        человеку он ничего не говорит: в цеху эту партию зовут двузначным
        номером дня, и уведомление должно совпадать с тем, что видно на доске.
        """
        batch = create_batch_at_stage("queue", self.user)
        message = Notification.objects.filter(notification_type="batch_queued").latest("id").message
        self.assertIn(batch.display_batch_number, message)
        self.assertNotIn(batch.batch_number, message)

    def test_notification_has_unread_default(self):
        create_batch_at_stage("queue", self.user)
        self.assertFalse(Notification.objects.latest("id").is_read)

    def test_notification_has_related_url(self):
        create_batch_at_stage("queue", self.user)
        self.assertIn("/bakery/batches/", Notification.objects.latest("id").related_url)

    def test_pause_does_not_create_stage_notification(self):
        batch = create_batch_at_stage("mixing", self.user)
        before = Notification.objects.count()
        pause_batch(batch, self.user, "pause")
        self.assertEqual(Notification.objects.count(), before)

    def test_resume_does_not_create_stage_notification(self):
        batch = create_batch_at_stage("mixing", self.user)
        pause_batch(batch, self.user, "pause")
        before = Notification.objects.count()
        resume_batch(batch, self.user, "resume")
        self.assertEqual(Notification.objects.count(), before)


def make_notification_transition_test(from_code, to_code):
    def test(self):
        batch = create_batch_at_stage(from_code, self.user)
        before = Notification.objects.filter(notification_type="stage_changed").count()
        move_batch(batch, to_code, self.user, to_code)
        self.assertEqual(Notification.objects.filter(notification_type="stage_changed").count(), before + 1)
        self.assertIn(batch.display_batch_label, Notification.objects.latest("id").message)
    return test


for from_code, to_code in zip(WORKFLOW[:-1], WORKFLOW[1:]):
    setattr(BatchNotificationTests, f"test_notification_for_{from_code}_to_{to_code}", make_notification_transition_test(from_code, to_code))
