"""Машина на слух: искажённые названия устройств из настоящих записей.

Каждая фраза здесь - расшифровка со стенда, не выдумка. Модель слышит
неплохо, но мнёт казахские падежные числительные («үшке» приходит как
«ішке») и рвёт слова («миксер екіге» - как «мик сергей»). Разбор обязан
вытянуть то, что вытягивается однозначно, и переспросить там, где между
двумя машинами ничья: увезти партию не в ту печь хуже, чем переспросить.
"""

from django.test import TestCase

from apps.bakery import speech_kk
from apps.bakery.models import ProductionStage, ProductionUnit
from apps.bakery.voice_process_mining import extract_unit


def hear(text):
    unit, stage, _, problem = extract_unit(speech_kk.prepare(text))
    return unit


class UnitHearingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        stages = {}
        for seq, (code, name) in enumerate(
            [("mixing", "Замес"), ("forming", "Формовка"), ("proofing", "Расстойка"), ("oven", "Печь")],
            start=1,
        ):
            stages[code] = ProductionStage.objects.create(code=code, name=name, sequence=seq)
        for name, stage, seq in [
            ("Миксер 1", "mixing", 1), ("Миксер 2", "mixing", 2), ("Миксер 3", "mixing", 3),
            ("Формовщик 1", "forming", 1), ("Формовщик 2", "forming", 2),
            ("Шкаф 1", "proofing", 1), ("Шкаф 2", "proofing", 2), ("Шкаф 3", "proofing", 3),
            ("Печь 1", "oven", 1), ("Печь 2", "oven", 2), ("Печь 3", "oven", 3),
            ("Печь 4", "oven", 4), ("Печь 5", "oven", 5),
        ]:
            ProductionUnit.objects.create(name=name, stage=stages[stage], sequence=seq)

    def test_mangled_kazakh_datives_still_name_the_machine(self):
        """«үшке» приходит как «ішке»/«ішкі» - на слух это одна и та же тройка."""
        self.assertEqual(hear("печ ішке"), "Печь 3")
        self.assertEqual(hear("екі шкаф ішкі"), "Шкаф 3")
        self.assertEqual(hear("он бір миксер егілген"), "Миксер 2")

    def test_known_mishearings_of_oven(self):
        """«печь» модель пишет как «пейдж», а «на печь три» - как «на пять три».
        Второе особенно коварно: числительные склеились бы в 53, и печь
        пропала бы вместе с номером."""
        self.assertEqual(hear("он сегіз пейдж төртке"), "Печь 4")
        self.assertEqual(hear("ноль один на пять четыре"), "Печь 4")
        self.assertEqual(hear("газ первый на пять три"), "Печь 3")

    def test_a_tie_between_machines_is_a_question_not_a_guess(self):
        """«мик сергей» одинаково далеко от первого и второго миксера,
        «формовщики где» - от первого и второго формовщика. Выбор наугад
        означал бы партию не в той машине - честнее переспросить."""
        self.assertEqual(hear("он жеті мик сергей"), "")
        self.assertEqual(hear("бес формовщики где"), "")
        self.assertEqual(hear("он жеті миксер пішкен"), "")

    def test_clean_commands_are_untouched(self):
        self.assertEqual(hear("жиырма үш миксер үшке"), "Миксер 3")
        self.assertEqual(hear("екі шкаф үшке"), "Шкаф 3")
        self.assertEqual(hear("пять наформовщик два"), "Формовщик 2")

    def test_stage_words_do_not_become_machines(self):
        """«на формовку», «складқа», «замеске» - этапы, не устройства.
        Раздача машин по созвучию с этапом увозила бы партии сама."""
        for said in ["339 на формовку", "сегіз складқа", "он жеті замеске", "1120 расстойкаға"]:
            with self.subTest(said=said):
                self.assertEqual(hear(said), "")

    def test_na_pyat_repair_needs_a_number_after(self):
        """«пять» чинится в «печь» только перед числом: «на пять минут»
        остаётся пятью минутами."""
        self.assertEqual(speech_kk.prepare("останови на пять минут"), "останови на 5 минут")
        self.assertEqual(speech_kk.prepare("ноль один на пять три"), "01 на печь 3")
