"""Номер партии за день: два знака, даже когда заказов больше сотни.

Номер называют вслух и пишут мелом на тележке, поэтому он двузначный. За день
заказов обычно меньше сотни, но упереться в 99 всё же можно - тогда номер
получает букву.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.bakery.models import (
    ProductionOrder,
    format_daily_number,
    parse_daily_number,
)

from .batch_workflow.factories import create_user


class FormatTests(TestCase):
    def test_up_to_ninety_nine_it_is_plain_digits(self):
        self.assertEqual(format_daily_number(1), "01")
        self.assertEqual(format_daily_number(9), "09")
        self.assertEqual(format_daily_number(42), "42")
        self.assertEqual(format_daily_number(99), "99")

    def test_past_the_hundred_a_letter_takes_over(self):
        """Так это и произносят: сотый - «а один», сто девятый - «б один»."""
        self.assertEqual(format_daily_number(100), "А1")
        self.assertEqual(format_daily_number(101), "А2")
        self.assertEqual(format_daily_number(108), "А9")
        self.assertEqual(format_daily_number(109), "Б1")
        self.assertEqual(format_daily_number(110), "Б2")

    def test_it_stays_two_characters(self):
        """Ради этого всё и затевалось: три цифры на тележке не помещаются."""
        for value in range(1, 325):
            with self.subTest(value=value):
                self.assertEqual(len(format_daily_number(value)), 2)

    def test_every_number_is_its_own(self):
        """Два заказа с одним номером в один день - худшее, что тут может
        случиться: партии перепутают в цеху, а не на экране."""
        seen = [format_daily_number(value) for value in range(1, 325)]
        self.assertEqual(len(seen), len(set(seen)))

    def test_beyond_the_alphabet_it_shows_the_raw_number(self):
        """Больше трёхсот партий за день не бывало ни разу. Если случится -
        длинный номер честнее, чем начать алфавит заново и выдать двойника."""
        self.assertEqual(format_daily_number(1000), "1000")

    def test_no_number_means_no_label(self):
        self.assertEqual(format_daily_number(None), "")


class ParseTests(TestCase):
    """Обратный разбор: смена говорит «а один», в базе лежит 100."""

    def test_letters_come_back_as_numbers(self):
        self.assertEqual(parse_daily_number("А1"), 100)
        self.assertEqual(parse_daily_number("Б1"), 109)

    def test_case_and_spaces_do_not_matter(self):
        self.assertEqual(parse_daily_number("а1"), 100)
        self.assertEqual(parse_daily_number(" А 1 "), 100)

    def test_latin_lookalikes_are_accepted(self):
        """«A» латинская и «А» русская неотличимы на вид, а приходят обе."""
        self.assertEqual(parse_daily_number("A1"), 100)

    def test_plain_digits_still_work(self):
        self.assertEqual(parse_daily_number("99"), 99)
        self.assertEqual(parse_daily_number("7"), 7)

    def test_nonsense_is_refused(self):
        """Лучше переспросить, чем перевести не ту партию."""
        for text in ["", None, "мусор", "А0", "Ъ1", "АА", "1А"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_daily_number(text))

    def test_it_survives_the_round_trip(self):
        for value in range(1, 325):
            with self.subTest(value=value):
                self.assertEqual(parse_daily_number(format_daily_number(value)), value)


class OrderLabelTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def make_order(self, number):
        from apps.bakery.models import Customer

        customer, _ = Customer.objects.get_or_create(name="Клиент для номеров")
        day = timezone.now() + timedelta(days=1)
        return ProductionOrder.objects.create(
            customer=customer,
            required_date=day,
            batch_number_date=timezone.localtime(day).date(),
            daily_batch_number=number,
        )

    def test_the_order_shows_the_letter_form(self):
        self.assertEqual(self.make_order(100).display_batch_number, "А1")

    def test_an_ordinary_order_is_unchanged(self):
        """Обычный день не должен измениться ни на знак."""
        self.assertEqual(self.make_order(7).display_batch_number, "07")

    def test_an_order_without_a_number_says_so(self):
        from apps.bakery.models import Customer

        customer, _ = Customer.objects.get_or_create(name="Клиент без номера")
        order = ProductionOrder.objects.create(
            customer=customer, required_date=timezone.now() + timedelta(days=1)
        )
        self.assertEqual(order.display_batch_number, "—")
