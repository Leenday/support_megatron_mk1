"""Rules for identifiers and dates (src/megatron/rules.py, #35)."""

import pytest

from megatron.rules import apply_rules, find_identifiers, looks_like_identifier
from megatron.ticket import Ticket


def ticket(identifiers=(), when=None) -> Ticket:
    return Ticket(
        who=None,
        where=None,
        when=when,
        what="Не работает",
        identifiers=list(identifiers),
        summary="Не работает",
        tags=["сбой"],
        candidates=["general"],
        language="ru",
    )


def test_find_identifiers():
    text = "User jsmith, order ORD-1042 and 104233, phone +7 999 123-45-67, mail a.b@example.com"
    assert find_identifiers(text) == [
        "ORD-1042",
        "104233",
        "+7 999 123-45-67",
        "a.b@example.com",
    ]


def test_find_identifiers_keeps_placeholders():
    assert find_identifiers("call [phone] about <acc_num>") == ["[phone]", "<acc_num>"]


@pytest.mark.parametrize(
    "value",
    [
        "INC-20417",
        "12345",
        "+7 999 123-45-67",
        "a.b@example.com",
        "a.smirnova",
        "ivan_petrov",
        "portal.example.ru",
        "<acc_num>",
        "[phone]",
    ],
)
def test_looks_like_identifier(value):
    assert looks_like_identifier(value)


@pytest.mark.parametrize("value", ["asdfgh", "VPN", "Wi-Fi", "e-mail", "бухгалтерия", "a. b", ""])
def test_plain_words_are_not_identifiers(value):
    assert not looks_like_identifier(value)


def test_review_example_drops_the_word_and_keeps_the_number():
    """Iteration 1 review: "asdfgh" from "asdfgh 12345" became an identifier."""
    fixed, log = apply_rules(ticket(["asdfgh", "12345"]), "asdfgh 12345")
    assert fixed.identifiers == ["12345"]
    assert log.shape_dropped == ["asdfgh"]
    assert log.added_identifiers == []


def test_login_is_kept():
    fixed, log = apply_rules(ticket(["a.smirnova"]), "Не могу войти под a.smirnova")
    assert fixed.identifiers == ["a.smirnova"]
    assert log.shape_dropped == []


def test_missed_codes_are_added_after_the_models_own():
    text = "Заявка INC-20417: клиент 104233 звонил с +7 999 123-45-67"
    fixed, log = apply_rules(ticket(["INC-20417"]), text, add=True)
    assert fixed.identifiers == ["INC-20417", "104233", "+7 999 123-45-67"]
    assert log.added_identifiers == ["104233", "+7 999 123-45-67"]


def test_a_code_overlapping_the_models_is_not_added():
    fixed, log = apply_rules(ticket(["20417"]), "Заявка INC-20417 висит", add=True)
    assert fixed.identifiers == ["20417"]
    assert log.added_identifiers == []


def test_dates_and_years_are_not_identifiers():
    text = "С 12.03.2025 в 10:30 не работает, с 2024 года такое бывает"
    fixed, log = apply_rules(ticket(when="12.03.2025"), text, add=True)
    assert fixed.identifiers == []
    assert log.added_identifiers == []


def test_empty_when_gets_the_explicit_date():
    fixed, log = apply_rules(ticket(), "Вчера в 10:30 упал сервер", add=True)
    assert fixed.when == "Вчера, 10:30"
    assert log.when_from_rule == "Вчера, 10:30"


def test_the_models_when_is_kept():
    fixed, log = apply_rules(ticket(when="вчера утром"), "Вчера в 10:30 упал сервер", add=True)
    assert fixed.when == "вчера утром"
    assert log.when_from_rule is None


def test_nothing_to_change_returns_the_same_ticket():
    original = ticket(["12345"], when="вчера")
    fixed, log = apply_rules(original, "вчера заказ 12345", add=True)
    assert fixed is original
    assert log == log.__class__()


def test_rules_are_idempotent():
    text = "asdfgh 12345, звонок вчера"
    once, _ = apply_rules(ticket(["asdfgh"]), text, add=True)
    twice, log = apply_rules(once, text, add=True)
    assert twice == once
    assert not (log.shape_dropped or log.added_identifiers or log.when_from_rule)


def test_additions_are_off_by_default():
    """Measured on the gold results, they cost more precision than they add recall (#35)."""
    text = "asdfgh: заказ 104233, вчера в 10:30"
    fixed, log = apply_rules(ticket(["asdfgh"]), text)
    assert (fixed.identifiers, fixed.when) == ([], None)
    assert log == log.__class__(shape_dropped=["asdfgh"])
