import json

import pytest

from megatron.inputs import Request, load_requests
from megatron.testset import (
    TRACKER_KEY,
    TRACKER_LINK,
    GoldTicket,
    clean_text,
    draft_gold,
    find_identifiers,
    label_counts,
    label_to_id,
    load_gold,
    pick_gold,
    sample,
    split,
    to_requests,
    write_gold,
)
from megatron.testset_cli import main


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("VPN is down\\n\\nsince 9:00", "VPN is down\n\nsince 9:00"),
        ("line one<br>line two", "line one\nline two"),
        ("&nbsp;\n\n### Client ID 1042\n\n**Printer** jams", "Client ID 1042\n\nPrinter jams"),
        ("call [[phone]](tel:[phone]) or \\[phone]", "call [phone] or [phone]"),
        ("see [image] [image]", "see"),
        ("{#answer_long_text_17-label}Mail does not sync", "Mail does not sync"),
        ("number \\+7 and a\\_b", "number +7 and a_b"),
        ("a\r\nb   c\n\n\n\nd", "a\nb c\n\nd"),
    ],
)
def test_clean_text_removes_export_noise(raw, clean):
    assert clean_text(raw) == clean


def test_clean_text_strips_tracker_keys_and_links():
    raw = "IT-768: VPN drops, like https://tracker.example.com/IT-631 and HELP-12"
    assert clean_text(raw, [TRACKER_LINK, TRACKER_KEY]) == "VPN drops, like and"


def test_tracker_keys_keep_other_codes():
    # Order ids without a dash, phone numbers and lowercase codes are request content.
    raw = "order 104233, phone +7 999 123-45-67, code abc-12"
    assert clean_text(raw, [TRACKER_LINK, TRACKER_KEY]) == raw


@pytest.mark.parametrize(
    ("label", "department_id"),
    [
        ("Technical Support", "technical_support"),
        ("Sales and Pre-Sales", "sales_and_pre_sales"),
        ("TIER2", "tier2"),
    ],
)
def test_label_to_id(label, department_id):
    assert label_to_id(label) == department_id


@pytest.mark.parametrize("label", ["Поддержка", "1st line"])
def test_label_to_id_rejects_labels_without_a_valid_id(label):
    with pytest.raises(ValueError, match="no valid department id"):
        label_to_id(label)


def test_to_requests_joins_columns_and_skips_bad_rows():
    rows = [
        {"subject": "VPN down", "body": "Since morning", "queue": "IT Support", "answer": "x"},
        {"subject": "", "body": "Printer jams", "queue": "IT Support"},
        {"subject": "VPN down", "body": "Since morning", "queue": "IT Support"},  # repeated
        {"subject": "", "body": "  ", "queue": "IT Support"},  # empty text
        {"subject": "Invoice", "body": "Wrong amount", "queue": ""},  # no label
    ]
    requests = to_requests(rows, ["subject", "body"], "queue")
    assert requests == [
        Request(text="VPN down\n\nSince morning", id=1, expected="it_support"),
        Request(text="Printer jams", id=2, expected="it_support"),
    ]


def test_to_requests_takes_the_id_column():
    rows = [{"key": "T-1", "text": "Printer jams", "line": "L1"}]
    assert to_requests(rows, ["text"], "line", id_field="key")[0].id == "T-1"


def requests_with(**counts: int) -> list[Request]:
    return [
        Request(text=f"{label} {i}", id=f"{label}-{i}", expected=label)
        for label, count in counts.items()
        for i in range(count)
    ]


def test_sample_caps_each_label_and_is_reproducible():
    requests = requests_with(big=40, small=3)
    picked = sample(requests, per_label=10, seed=1)
    assert label_counts(picked) == {"big": 10, "small": 3}
    assert picked == sample(requests, per_label=10, seed=1)
    assert picked != sample(requests, per_label=10, seed=2)


def test_split_keeps_proportions_and_a_test_request_per_label():
    dev, test = split(requests_with(a=20, b=10, c=1), dev_share=0.3, seed=1)
    assert label_counts(dev) == {"a": 6, "b": 3}
    assert label_counts(test) == {"a": 14, "b": 7, "c": 1}
    assert not {r.id for r in dev} & {r.id for r in test}


def test_pick_gold_takes_labels_in_turn():
    gold = pick_gold(requests_with(a=20, b=2, c=1), size=7, seed=1)
    assert label_counts(gold) == {"a": 4, "b": 2, "c": 1}


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


def test_draft_gold_does_not_take_dates_for_identifiers():
    request = Request(
        text="Since 17.08.2026 at 16:36 account 104233 is locked", id=5, expected="it"
    )
    draft = draft_gold(request)
    assert draft.when == "17.08.2026, 16:36"
    assert draft.identifiers == ["104233"]
    assert (draft.who, draft.where, draft.what, draft.checked) == (None, None, None, False)


def test_gold_round_trip_keeps_multiline_text(tmp_path):
    path = tmp_path / "gold.yaml"
    tickets = [GoldTicket(id=1, expected="it", text="VPN down\n\nsince 9:00", what="VPN down")]
    write_gold(path, tickets)
    assert "text: |-\n" in path.read_text(encoding="utf-8")
    assert load_gold(path) == tickets


def test_cli_builds_dev_test_and_gold_draft(tmp_path, capsys):
    source = tmp_path / "export.jsonl"
    rows = [
        {"key": f"IT-{i}", "text": f"IT-{i}: request {i}", "line": "L1" if i % 3 else "L2"}
        for i in range(30)
    ]
    source.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = tmp_path / "set"
    args = [str(source), "--text", "text", "--label", "line", "--id", "key"]
    args += ["--strip-tracker-keys", "--gold", "5", "--out", str(out)]

    assert main(args) == 0
    dev, test = load_requests(out / "dev.jsonl"), load_requests(out / "test.jsonl")
    assert (len(dev), len(test)) == (9, 21)
    assert all("IT-" not in r.text for r in dev + test)
    gold = load_gold(out / "gold.yaml")
    assert len(gold) == 5
    assert {g.id for g in gold} <= {r.id for r in test}

    # A rerun leaves the hand-checked gold file alone.
    write_gold(out / "gold.yaml", [gold[0].model_copy(update={"checked": True})])
    assert main(args) == 0
    assert "left as is" in capsys.readouterr().out
    assert len(load_gold(out / "gold.yaml")) == 1


def test_cli_filters_rows(tmp_path):
    source = tmp_path / "tickets.csv"
    source.write_text(
        "subject,body,queue,language\n"
        "VPN down,since morning,IT Support,en\n"
        "VPN gestört,seit heute,IT Support,de\n",
        encoding="utf-8",
    )
    out = tmp_path / "set"
    args = [str(source), "--text", "subject,body", "--label", "queue"]
    assert main([*args, "--filter", "language=en", "--dev", "0", "--out", str(out)]) == 0
    assert [r.text for r in load_requests(out / "test.jsonl")] == ["VPN down\n\nsince morning"]
