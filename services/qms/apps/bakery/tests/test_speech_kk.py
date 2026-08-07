"""Казахская речь до того, как её увидит разбор команды.

Модуль намеренно без Django, поэтому тесты — обычный unittest и бегут без базы.
Проверяется то, из-за чего команда на казахском не доезжала: номер партии,
произнесённый словами, и буква перед ним, произнесённая без алфавита.
"""

from __future__ import annotations

import unittest

from apps.bakery.speech_kk import fold, latin_batch_prefix, numbers_to_digits, prepare


class FoldTests(unittest.TestCase):
    def test_kazakh_letters_fold_to_their_russian_lookalikes(self):
        self.assertEqual(fold("бір"), "бир")
        self.assertEqual(fold("төрт"), "торт")
        self.assertEqual(fold("тоғыз"), "тогыз")
        self.assertEqual(fold("ҚЫРЫҚ"), "кырык")

    def test_russian_text_is_left_alone_apart_from_case(self):
        self.assertEqual(fold("Замес"), "замес")


class NumberTests(unittest.TestCase):
    def test_digits_read_one_by_one_join_up(self):
        """Как обычно называют код партии."""
        self.assertEqual(numbers_to_digits("бір бес төрт"), "154")

    def test_a_composed_number_is_summed(self):
        self.assertEqual(numbers_to_digits("жүз елу төрт"), "154")
        self.assertEqual(numbers_to_digits("екі жүз елу төрт"), "254")
        self.assertEqual(numbers_to_digits("мың бес жүз"), "1500")
        self.assertEqual(numbers_to_digits("он үш"), "13")

    def test_both_spellings_of_the_same_word_work(self):
        self.assertEqual(numbers_to_digits("бир бес торт"), "154")

    def test_a_single_word_is_still_a_number(self):
        self.assertEqual(numbers_to_digits("бір"), "1")

    def test_surrounding_words_survive_with_their_spacing(self):
        self.assertEqual(
            numbers_to_digits("партия бір бес төрт формовкаға"),
            "партия 154 формовкаға",
        )

    def test_text_without_numbers_is_returned_unchanged(self):
        self.assertEqual(numbers_to_digits("ештеңе жоқ"), "ештеңе жоқ")
        self.assertEqual(numbers_to_digits(""), "")

    def test_digits_already_written_as_digits_are_not_touched(self):
        self.assertEqual(numbers_to_digits("B-154 количество 20"), "B-154 количество 20")


class PrefixTests(unittest.TestCase):
    def test_a_spoken_cyrillic_letter_becomes_the_stored_latin_one(self):
        self.assertEqual(latin_batch_prefix("Б-102"), "B-102")
        self.assertEqual(latin_batch_prefix("б 154"), "B 154")
        self.assertEqual(latin_batch_prefix("д-7"), "D-7")

    def test_a_letter_inside_a_word_is_not_a_prefix(self):
        """Иначе «партия 5» превратилась бы в «партиB 5»."""
        self.assertEqual(latin_batch_prefix("көрдім 5"), "көрдім 5")
        self.assertEqual(latin_batch_prefix("заказ 13"), "заказ 13")

    def test_latin_is_left_as_it_is(self):
        self.assertEqual(latin_batch_prefix("B-154"), "B-154")


class PrepareTests(unittest.TestCase):
    def test_the_whole_kazakh_phrase(self):
        self.assertEqual(
            prepare("б бір бес төрт формовкаға"),
            "B 154 формовкаға",
        )

    def test_order_matters_number_first_then_the_letter(self):
        """«б бір» — буква становится префиксом только после того, как слово стало цифрой."""
        self.assertEqual(prepare("б бір"), "B 1")

    def test_a_russian_command_passes_through_untouched(self):
        phrase = "партия B-154 закончила замес, передать на формовку"
        self.assertEqual(prepare(phrase), phrase)

    def test_empty_input(self):
        self.assertEqual(prepare(""), "")
        self.assertEqual(prepare(None), "")


if __name__ == "__main__":
    unittest.main()
