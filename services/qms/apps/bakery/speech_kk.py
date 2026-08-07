"""Kazakh speech, in the narrow sense this system needs.

The shop floor does not speak Kazakh to the system - it speaks commands. Stage
names arrive as Russian roots with Kazakh endings ("замеске", "формовкаға"),
which the existing substring matching already handles: "замес" is inside
"замеске". What it does not handle is the part that matters most, the batch
number, because Kazakh digits come back as words.

Nothing here imports Django. It is text in, text out, so it can be tested and
reasoned about without a database or a request.
"""

from __future__ import annotations

import re

# Whisper's spelling of Kazakh wobbles between the specific letters and their
# nearest Russian neighbours - "бір" and "бир", "төрт" and "торт" - and which
# one comes back depends on the audio, not on the speaker. Folding both to the
# same form means every table below needs one spelling instead of two.
_FOLD = str.maketrans({
    "ә": "а", "ғ": "г", "қ": "к", "ң": "н",
    "ө": "о", "ұ": "у", "ү": "у", "һ": "х", "і": "и",
})


def fold(value: str) -> str:
    """Kazakh-specific letters down to their Russian lookalikes, lowercased."""
    return (value or "").lower().translate(_FOLD)


# Keys are folded, so "төрт" and "торт" both find 4.
#
# Russian is here for the same reason Kazakh is: the model writes numbers the
# way they were said. Whisper answered "341" and hid this; NeMo answers "триста
# сорок три", which is what the operator actually pronounced. The same shift
# happens whenever the recogniser changes, so both languages live in one table
# and the algorithm below does not care which one it is reading.
_UNITS = {
    "нол": 0, "бир": 1, "еки": 2, "уш": 3, "торт": 4,
    "бес": 5, "алты": 6, "жети": 7, "сегиз": 8, "тогыз": 9,
    "ноль": 0, "нуль": 0, "один": 1, "одна": 1, "одну": 1, "два": 2, "две": 2,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9,
}

# Everything that simply adds up. Russian hundreds are irregular words rather
# than "three" plus "hundred", so they belong here and not among the multipliers.
_TENS = {
    "он": 10, "жиырма": 20, "отыз": 30, "кырык": 40, "елу": 50,
    "алпыс": 60, "жетпис": 70, "сексен": 80, "токсан": 90,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
    "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}

# Multipliers: "үш жүз" is three hundreds, "две тысячи" is two thousands.
_SCALES = {
    "жуз": 100, "мын": 1000,
    "тысяча": 1000, "тысячи": 1000, "тысяч": 1000,
}

_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES)

# Latin B and D are what the batch numbers are stored with, but a person saying
# them out loud produces Cyrillic in the transcript. Confined to these two
# letters on purpose: a general Cyrillic-to-Latin fold would also rewrite words.
_PREFIX_LETTERS = {"б": "B", "д": "D"}


def _run_to_number(words: list[str]) -> str:
    """One run of number words to digits.

    Two ways of saying the same batch, both heard on the floor:

        "бир бес торт"        digit by digit  -> 154
        "жуз елу торт"        as a number     -> 154

    Telling them apart by shape is a guess, but a defensible one: a run made
    only of single digits is somebody reading a code, while anything with a ten
    or a hundred in it is somebody saying a quantity. The guess is only ever
    wrong in the direction of a batch number that does not exist, which
    resolve_batch() already rejects rather than acting on.
    """
    if len(words) > 1 and all(word in _UNITS for word in words):
        return "".join(str(_UNITS[word]) for word in words)

    total = 0
    current = 0
    for word in words:
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word in _SCALES:
            scale = _SCALES[word]
            if current == 0:
                current = 1
            if scale == 1000:
                total += current * 1000
                current = 0
            else:
                current *= scale
    return str(total + current)


def numbers_to_digits(text: str) -> str:
    """Rewrite spelled-out Kazakh numbers as digits, leaving everything else.

    Runs are collapsed as a whole: "партия бир бес торт формовкага" becomes
    "партия 154 формовкага", which is what the batch pattern is looking for.
    """
    if not text:
        return text

    tokens = re.split(r"(\W+)", text)
    out: list[str] = []
    run: list[str] = []
    # The separator after the last number word. Whether it belongs inside the
    # run or after it is only known once the next word arrives, so it waits.
    pending: str | None = None

    def flush() -> None:
        nonlocal pending
        if run:
            out.append(_run_to_number(run))
            run.clear()
        if pending is not None:
            out.append(pending)
            pending = None

    for index, token in enumerate(tokens):
        if index % 2:  # separator
            if run and not token.strip():
                pending = token
            else:
                flush()
                out.append(token)
            continue

        if fold(token) in _NUMBER_WORDS:
            # A space between two number words is inside the run: the digits
            # join up, the space does not survive.
            pending = None
            run.append(fold(token))
        else:
            flush()
            out.append(token)

    flush()
    return "".join(out)


def latin_batch_prefix(text: str) -> str:
    """"б 154", "Б-154" -> "B-154".

    Speech does not carry the alphabet a code is written in. The batch numbers
    in the database are Latin, so a spoken Cyrillic letter in front of digits is
    rewritten - and only there, immediately before a number.
    """
    def replace(match: re.Match) -> str:
        letter = _PREFIX_LETTERS[match.group(1).lower()]
        return f"{letter}{match.group(2)}{match.group(3)}"

    return re.sub(r"(?<![а-яёәғқңөұүһі])([бдБД])([-\s]?)(\d)", replace, text)


# The letter of a batch code, said out loud rather than spelled. Whisper writes
# it as a word, and a word is not a prefix until it is one letter again.
_SPOKEN_LETTERS = {
    "бэ": "б", "бе": "б", "би": "б",
    "дэ": "д", "де": "д", "ди": "д",
}


def spoken_letter_prefix(text: str) -> str:
    """"бэ 154" -> "б 154", so the rule below can make it "B-154"."""
    def replace(match: re.Match) -> str:
        return f"{_SPOKEN_LETTERS[fold(match.group(1))]}{match.group(2)}{match.group(3)}"

    return re.sub(
        r"\b(бэ|бе|би|дэ|де|ди)([-\s]+)(\d)",
        replace,
        text,
        flags=re.IGNORECASE,
    )


def prepare(text: str) -> str:
    """Everything the Kazakh path needs, in the order it has to happen.

    Numbers first: "б бир бес торт" has to become "б 154" before the letter in
    front of it can be recognised as a batch prefix. A letter said as a word
    ("бэ") becomes a letter in between.
    """
    return latin_batch_prefix(spoken_letter_prefix(numbers_to_digits(text or "")))
