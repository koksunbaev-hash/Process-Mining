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

from apps.bakery.services import numbers_busy_on_board

from .batch_workflow.factories import create_queued_batch, create_stage_list, create_user


def move_to_previous_day(batch, days=1, status=None):
    """Отправить партию во вчера - вместе с её заказом.

    Дневной номер висит и на партии, и на заказе: заказ помнит номер своей
    первой карточки. Перенести одну партию - значит оставить заказ в
    сегодняшнем дне и получить в тесте состояние, которого в жизни нет.
    """
    batch.card_number_date = batch.card_number_date - timedelta(days=days)
    fields = ["card_number_date"]
    if status is not None:
        batch.status = status
        fields.append("status")
    batch.save(update_fields=fields)
    order = batch.order_item.order
    order.batch_number_date = batch.card_number_date
    order.save(update_fields=["batch_number_date"])
    return batch


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


class NumberFreeOnBoardTests(TestCase):
    """Компромисс: счёт дневной, но занятые доской числа пропускаются.

    Партия, не закрытая вчера, лежит на доске и сегодня и честно держит
    своё число - оно написано мелом на её тележке. Сегодняшняя нумерация
    его обходит, и двух одинаковых чисел на доске не оказывается.
    """

    def setUp(self):
        create_stage_list()
        self.user = create_user()

    def test_an_ordinary_day_starts_at_one_as_before(self):
        """Вчера всё закрыто - ничего не меняется, счёт идёт с 01."""
        old = create_queued_batch(user=self.user)
        old.refresh_from_db()
        move_to_previous_day(old, status="completed")

        fresh = create_queued_batch(user=self.user, quantity=20)
        fresh.refresh_from_db()
        self.assertEqual(fresh.daily_card_number, 1)

    def test_a_carried_over_batch_keeps_its_number_and_today_steps_over_it(self):
        leftover = create_queued_batch(user=self.user)
        leftover.refresh_from_db()
        kept = leftover.daily_card_number
        move_to_previous_day(leftover, status="in_progress")

        today = create_queued_batch(user=self.user, quantity=20)
        today.refresh_from_db()

        leftover.refresh_from_db()
        self.assertEqual(leftover.daily_card_number, kept, "у вчерашней партии отобрали её число")
        self.assertNotEqual(today.daily_card_number, kept, "сегодняшняя заняла занятое число")

    def test_no_two_active_cards_on_the_board_share_a_number(self):
        """Главное свойство всей затеи, проверенное на смеси дней."""
        batches = []
        for index in range(4):
            batch = create_queued_batch(user=self.user, quantity=10 + index)
            batch.refresh_from_db()
            if index < 2:
                move_to_previous_day(batch, days=index + 1)
            batches.append(batch)

        newcomer = create_queued_batch(user=self.user, quantity=99)
        newcomer.refresh_from_db()
        batches.append(newcomer)

        active = [b for b in batches if b.status not in ("completed", "cancelled")]
        numbers = [b.daily_card_number for b in active]
        self.assertEqual(len(numbers), len(set(numbers)), f"на доске повторился номер: {numbers}")

    def test_a_closed_batch_gives_its_number_back(self):
        """Ушла с доски - число снова свободно, иначе счёт убежал бы вверх."""
        done = create_queued_batch(user=self.user)
        done.refresh_from_db()
        freed = done.daily_card_number
        move_to_previous_day(done, status="completed")

        busy = numbers_busy_on_board()
        self.assertNotIn(freed, busy)
