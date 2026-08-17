"""Разбор казахской речи с цеха.

Тексты здесь - настоящие расшифровки со стенда, не выдуманные. Их и стоит
пополнять, когда с производства придёт очередная запись: смена говорит не так,
как пишут в примерах.
"""

from __future__ import annotations

from django.test import TestCase

from apps.bakery import speech_kk
from apps.bakery.voice_process_mining import resolve_target_stage, split_commands


class NumbersTests(TestCase):
    """Номер партии приходит словами - модель пишет то, что услышала."""

    def test_kazakh_numbers_become_digits(self):
        self.assertEqual(speech_kk.prepare("үш жүз отыз тоғыз"), "339")
        self.assertEqual(speech_kk.prepare("мың бір жүз жиырма"), "1120")

    def test_mixed_speech_keeps_the_russian_part(self):
        """Числа по-казахски, этап по-русски - так и говорят на линии."""
        self.assertEqual(
            speech_kk.prepare("үш жүз қырық сегіз на формовку"), "348 на формовку"
        )


class StageBySoundTests(TestCase):
    """Распознаватель пишет услышанное, и «расстойка» приходит по-разному."""

    def test_distortions_still_find_the_stage(self):
        for said in ("растойка", "ростойкова", "на растой", "формовкаға", "складқа", "печкаға"):
            with self.subTest(said=said):
                self.assertTrue(speech_kk.stage_by_sound(said))

    def test_the_right_stage_not_just_any(self):
        self.assertEqual(speech_kk.stage_by_sound("ростойкова"), "proofing")
        self.assertEqual(speech_kk.stage_by_sound("формовкаға"), "forming")
        self.assertEqual(speech_kk.stage_by_sound("складқа"), "warehouse")

    def test_it_refuses_rather_than_guesses(self):
        """Переспросить дешевле, чем перевести партию не туда. Эти слова со
        стенда: «қысқақты» не похоже ни на один этап, «триста сорок» - число."""
        for said in ("қысқақты", "триста сорок", "проблема", "мың бір жүз жиырма"):
            with self.subTest(said=said):
                self.assertEqual(speech_kk.stage_by_sound(said), "")

    def test_exact_match_still_wins(self):
        self.assertEqual(resolve_target_stage("1120 расстойкаға"), "proofing")


class SplitTests(TestCase):
    """Одно нажатие кнопки - сколько угодно команд."""

    def test_two_commands_in_one_breath(self):
        self.assertEqual(
            split_commands("339 на формовку 348 на формовку"),
            ["339 на формовку", "348 на формовку"],
        )

    def test_one_command_stays_whole(self):
        self.assertEqual(split_commands("1120 расстойкаға"), ["1120 расстойкаға"])

    def test_two_batches_one_destination_is_not_split(self):
        """«339 и 348 на формовку» - один приказ на две партии, а не два
        приказа. У второго куска нет своего этапа, и угадывать мы не станем."""
        self.assertEqual(
            split_commands("339 и 348 на формовку"), ["339 и 348 на формовку"]
        )

    def test_nothing_to_split(self):
        self.assertEqual(split_commands(""), [])
        self.assertEqual(split_commands("на формовку"), ["на формовку"])
