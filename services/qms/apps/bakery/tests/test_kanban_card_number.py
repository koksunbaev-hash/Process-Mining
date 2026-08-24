"""Номер партии на доске опознаёт партию только вместе с её днём.

Нумерация начинается заново каждый производственный день, а на доске лежит
не один день: партии, не дошедшие до «Готово», остаются на ней и назавтра.
Значит «01» на доске встречается столько раз, сколько дней на ней лежит, и
само по себе число партию не называет.

Отсюда требование: день стоит на карточке рядом с номером всегда - и в
разметке, и в подсказке. Уберут его как «лишний» - и смена начнёт возить
не ту партию, причём молча.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse

from .batch_workflow.factories import create_queued_batch, create_stage_list, create_user


class KanbanCardNumberTests(TestCase):
    def setUp(self):
        create_stage_list()
        self.user = create_user()
        self.client.force_login(self.user)

    def board(self):
        return self.client.get(reverse("bakery:kanban"))

    def test_the_day_stands_next_to_the_number(self):
        batch = create_queued_batch(user=self.user)
        batch.refresh_from_db()
        self.assertIsNotNone(batch.daily_card_number, "партии не досталось видимого номера")

        response = self.board()
        self.assertContains(response, batch.display_batch_number)
        # Ровно тот день, к которому отнесён номер, а не «сегодня».
        self.assertContains(response, batch.display_batch_date.strftime("%d.%m"))

    def test_the_tooltip_names_the_batch_the_way_the_shop_does(self):
        """В подсказке был только технический номер - тот, которым партию не
        зовёт никто. Видимый номер с днём там нужнее."""
        batch = create_queued_batch(user=self.user)
        batch.refresh_from_db()
        response = self.board()
        self.assertContains(response, f"Партия {batch.display_batch_label}")
        self.assertContains(response, batch.batch_number)

    def test_two_days_share_a_number_and_the_board_still_tells_them_apart(self):
        """Тот самый случай со стенда: «01» за вчера и «01» за сегодня лежат
        рядом. Число одно, а карточки - разные, и различает их день."""
        today = create_queued_batch(user=self.user)
        yesterday = create_queued_batch(user=self.user, quantity=50)
        yesterday.card_number_date = today.card_number_date - timedelta(days=1)
        yesterday.daily_card_number = today.daily_card_number
        yesterday.save(update_fields=["card_number_date", "daily_card_number"])

        self.assertEqual(today.display_batch_number, yesterday.display_batch_number)
        self.assertNotEqual(today.display_batch_label, yesterday.display_batch_label)

        response = self.board()
        for batch in (today, yesterday):
            self.assertContains(response, batch.display_batch_date.strftime("%d.%m"))

    def test_the_number_is_never_shown_bare(self):
        """Разметка, в которой номер стоит без дня, - это возврат к ошибке.
        Проверяем сам шаблон: <b>номер</b> обязан идти вместе с <i>днём</i>.
        """
        create_queued_batch(user=self.user)
        html = self.board().content.decode()
        chip_start = html.index('class="kanban-card__id"')
        chip = html[chip_start:chip_start + 400]
        self.assertIn("<b>", chip)
        self.assertIn("<i>", chip, "день пропал из плашки номера")
        self.assertLess(chip.index("<b>"), chip.index("<i>"), "день оказался раньше номера")


class DailyNumberUniquenessTests(TestCase):
    """Номер уникален внутри дня, но не между днями - и это осознанно.

    Сквозная нумерация избавила бы от совпадений, но номер перестал бы быть
    двузначным, а его называют вслух и пишут мелом на тележке.
    """

    def setUp(self):
        create_stage_list()
        self.user = create_user()

    def test_within_one_day_numbers_do_not_repeat(self):
        batches = [create_queued_batch(user=self.user) for _ in range(3)]
        for batch in batches:
            batch.refresh_from_db()
        same_day = [b for b in batches if b.card_number_date == batches[0].card_number_date]
        numbers = [b.daily_card_number for b in same_day]
        self.assertEqual(len(numbers), len(set(numbers)), f"номер повторился внутри дня: {numbers}")

    def test_across_days_the_count_starts_over(self):
        """Иначе номер быстро перестал бы помещаться на тележку."""
        batch = create_queued_batch(user=self.user)
        batch.refresh_from_db()

        other_day = create_queued_batch(user=self.user, quantity=10)
        other_day.card_number_date = batch.card_number_date - timedelta(days=1)
        other_day.daily_card_number = batch.daily_card_number
        other_day.save(update_fields=["card_number_date", "daily_card_number"])

        self.assertEqual(other_day.display_batch_number, batch.display_batch_number)
        self.assertNotEqual(other_day.display_batch_label, batch.display_batch_label)
