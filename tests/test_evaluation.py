import json

import ollama
import pytest

from megatron import eval_cli
from megatron.evaluation import (
    Counts,
    Result,
    accuracy,
    bootstrap,
    field_counts,
    load_results,
    macro_f1,
    majority_baseline,
    model_report,
    render,
    tfidf_baseline,
    token_f1,
)
from megatron.inputs import Request
from megatron.llm import OllamaExtractor
from megatron.prompt import PROMPT_VERSION
from megatron.settings import Settings
from megatron.testset import GoldTicket, write_gold
from megatron.ticket import RoutedTicket

TICKET = {
    "who": "Anna Petrova, accounting",
    "where": "room 305",
    "when": "since this morning",
    "what": "The printer shows a paper jam error and does not print",
    "identifiers": ["PRN-305"],
    "summary": "Printer paper jam",
    "tags": ["printer"],
    "candidates": ["hardware", "software"],
    "language": "en",
}
GOLD = GoldTicket(
    id=1,
    expected="hardware",
    checked=True,
    text="...",
    who="Anna Petrova",
    where="room 305, 3rd floor",
    when=None,
    what="Printer does not print: paper jam error",
    identifiers=["PRN-305", "+7 999 123-45-67"],
)


def ticket(**changes) -> RoutedTicket:
    return RoutedTicket.model_validate(TICKET | {"department": "hardware"} | changes)


@pytest.mark.parametrize(
    ("gold", "given", "score"),
    [
        ("printer jam", "printer jam", 1.0),
        ("Printers jammed", "printer is jammed", pytest.approx(0.8)),
        ("сообщения не отправляются", "сообщение не отправилось", 1.0),  # stems match
        ("printer", "network", 0.0),
        ("printer", None, 0.0),
    ],
)
def test_token_f1(gold, given, score):
    assert token_f1(gold, given) == score


def test_field_counts():
    counts = field_counts(GOLD, ticket())
    assert counts["who"] == Counts(tp=1)
    assert counts["where"] == Counts(tp=1)
    assert counts["when"] == Counts(fp=1)  # given, but the request does not say when
    assert counts["what"] == Counts(tp=1)
    assert counts["identifiers"] == Counts(tp=1, fn=1)


def test_wrong_value_is_a_false_positive_and_a_false_negative():
    assert field_counts(GOLD, ticket(where="VPN gateway"))["where"] == Counts(fp=1, fn=1)


def test_empty_answer_is_no_answer():
    assert field_counts(GOLD, ticket(who="  "))["who"] == Counts(fn=1)


def test_failure_counts_as_an_empty_ticket():
    counts = field_counts(GOLD, None)
    assert [counts[f] for f in ("who", "where", "when", "what")] == [
        Counts(fn=1),
        Counts(fn=1),
        Counts(),
        Counts(fn=1),
    ]
    assert counts["identifiers"] == Counts(fn=2)


def test_identifiers_compared_as_normalized_sets():
    gold = GOLD.model_copy(update={"identifiers": ["ORD-1042"]})
    assert field_counts(gold, ticket(identifiers=["ord-1042.", "ORD-1042"]))["identifiers"] == (
        Counts(tp=1)
    )


def test_counts_scores_are_undefined_without_positives():
    assert (Counts().precision, Counts().recall, Counts().f1) == (None, None, None)
    counts = Counts(tp=2, fp=1, fn=3)
    assert (counts.precision, counts.recall) == (pytest.approx(2 / 3), pytest.approx(2 / 5))
    assert counts.f1 == pytest.approx(0.5)


def test_accuracy_and_macro_f1():
    pairs = [("a", "a"), ("a", "a"), ("a", "b"), ("b", "b"), ("c", None)]
    assert accuracy(pairs) == pytest.approx(0.6)
    # F1: a = 0.8, b = 2/3, c = 0 (a failure is never right)
    assert macro_f1(pairs) == pytest.approx((0.8 + 2 / 3 + 0) / 3)


def test_bootstrap_range_holds_the_value_and_is_reproducible():
    items = [1.0] * 30 + [0.0] * 10
    score = bootstrap(items, lambda s: sum(s) / len(s), rounds=500, seed=1)
    assert score is not None
    assert score.low <= score.value == 0.75 <= score.high
    assert score.high - score.low < 0.4
    assert score == bootstrap(items, lambda s: sum(s) / len(s), rounds=500, seed=1)
    assert str(score).startswith("0.75 (")


def test_bootstrap_of_an_undefined_score_is_none():
    assert bootstrap([Counts()], lambda s: s[0].f1, rounds=10, seed=1) is None


def request(text: str, label: str) -> Request:
    return Request(text=text, expected=label)


TRAIN = [
    request("printer jam paper", "hardware"),
    request("printer toner empty", "hardware"),
    request("monitor flickers", "hardware"),
    request("vpn disconnects", "network"),
    request("wifi slow network", "network"),
]
TEST = [request("printer paper stuck", "hardware"), request("vpn wifi down", "network")]


def test_majority_baseline():
    assert majority_baseline(TRAIN, TEST) == ["hardware", "hardware"]


def test_tfidf_baseline_learns_from_train():
    assert tfidf_baseline(TRAIN, TEST) == ["hardware", "network"]


def test_tfidf_baseline_with_one_label_is_the_majority():
    assert tfidf_baseline(TRAIN[:2], TEST) == ["hardware", "hardware"]


def results() -> list[Result]:
    return [
        Result(id=1, request="a", expected="hardware", ticket=ticket(), seconds=2.0, attempts=1),
        Result(
            id=2,
            request="b",
            expected="software",
            ticket=ticket(),
            seconds=4.0,
            attempts=2,
            dropped_identifiers=["user123"],
        ),
        Result(id=3, request="c", expected="network", error="no valid ticket", seconds=9.0),
    ]


def test_model_report():
    report = model_report("m", results(), [GOLD], rounds=50, seed=1)
    assert report.requests == 3
    assert report.accuracy is not None
    assert report.accuracy.value == pytest.approx(1 / 3)
    assert report.in_candidates == pytest.approx(2 / 3)  # software is the 2nd candidate
    assert report.valid is not None
    assert report.valid.value == pytest.approx(2 / 3)
    assert report.first_try == pytest.approx(1 / 3)
    assert (report.dropped, report.tickets_with_dropped) == (1, 1)
    assert (report.seconds_median, report.seconds_p90) == (4.0, 4.0)
    assert report.gold == 1
    assert report.fields["identifiers"] == Counts(tp=1, fn=1)
    when = report.field_f1["when"]  # given once, never expected
    assert when is not None and when.value == 0.0


def test_model_report_uses_only_checked_gold():
    unchecked = GOLD.model_copy(update={"checked": False})
    report = model_report("m", results(), [unchecked], rounds=10, seed=1)
    assert (report.gold, report.field_f1) == (0, {})


def test_render_lists_baselines_and_models():
    report = model_report("gpt", results(), [GOLD], rounds=20, seed=1)
    text = render("en", [report])
    assert "## en: department (test part)" in text
    assert "| gpt | 3 | 0.33 (" in text
    assert "| gpt | 1 | " in text  # one gold request
    assert "1 in 1 of 3 tickets" in text


class FakeClient:
    def __init__(self, *answers: dict | str) -> None:
        self.answers = [a if isinstance(a, str) else json.dumps(a) for a in answers]

    def chat(self, **kwargs) -> ollama.ChatResponse:
        return ollama.ChatResponse(
            message=ollama.Message(role="assistant", content=self.answers.pop(0))
        )


def write_set(path, requests: list[dict], gold: list[GoldTicket]) -> None:
    path.mkdir()
    for name in ("dev", "test"):
        lines = "".join(json.dumps(r) + "\n" for r in requests)
        (path / f"{name}.jsonl").write_text(lines, encoding="utf-8")
    write_gold(path / "gold.yaml", gold)


def test_cli_runs_backend_resumes_and_reports(
    tmp_path, monkeypatch, capsys, departments, departments_path
):
    answer = TICKET | {"candidates": ["hardware"], "when": None}
    extractor = OllamaExtractor(
        departments,
        Settings(_env_file=None, ollama_model="tiny:1b"),
        client=FakeClient(answer, "bad", "bad", "bad", answer),
    )
    monkeypatch.setattr(eval_cli, "build_extractor", lambda config, settings: extractor)
    monkeypatch.setenv("DEPARTMENTS_PATH", str(departments_path))
    requests = [
        {"id": 1, "text": "printer jam PRN-305", "expected": "hardware"},
        {"id": 2, "text": "vpn drops", "expected": "network"},
        {"id": 3, "text": "toner empty", "expected": "hardware"},
    ]
    write_set(tmp_path / "set", requests, [GOLD])
    out = tmp_path / "eval"
    args = [str(tmp_path / "set"), "--out", str(out), "--rounds", "20"]

    assert eval_cli.main([*args, "--run", "--limit", "2"]) == 0
    path = out / "tiny-1b.jsonl"
    first = load_results(path)
    assert [r.id for r in first] == [1, 2]
    assert first[0].ticket is not None and first[0].attempts == 1
    assert first[0].ticket.when is None  # a null field of the ticket survives the round trip
    assert first[1].error  # three invalid answers

    # The rerun only asks for the request that is missing.
    assert eval_cli.main([*args, "--run"]) == 0
    assert [r.id for r in load_results(path)] == [1, 2, 3]
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "| majority class (3 train) |" in report
    assert "| TF-IDF + logreg (3 train) |" in report
    assert "| tiny-1b | 3 | 0.67 (" in report
    assert "| tiny-1b | 1 | " in report  # fields on one gold request
    assert "2 done, 1 to go" in capsys.readouterr().out


def test_cli_rejects_labels_missing_from_the_config(tmp_path, monkeypatch, departments_path):
    monkeypatch.setenv("DEPARTMENTS_PATH", str(departments_path))
    write_set(tmp_path / "set", [{"id": 1, "text": "x", "expected": "billing"}], [])
    assert eval_cli.main([str(tmp_path / "set"), "--run", "--out", str(tmp_path / "e")]) == 2


def test_cli_dev_part_uses_dev_gold_and_no_baselines(
    tmp_path, monkeypatch, departments, departments_path
):
    extractor = OllamaExtractor(
        departments,
        Settings(_env_file=None, ollama_model="tiny:1b"),
        client=FakeClient(TICKET | {"candidates": ["hardware"]}),
    )
    monkeypatch.setattr(eval_cli, "build_extractor", lambda config, settings: extractor)
    monkeypatch.setenv("DEPARTMENTS_PATH", str(departments_path))
    write_set(tmp_path / "set", [{"id": 1, "text": "printer PRN-305", "expected": "hardware"}], [])
    write_gold(tmp_path / "set" / "gold-dev.yaml", [GOLD])
    out = tmp_path / "eval"
    args = [str(tmp_path / "set"), "--part", "dev", "--run", "--name", "prompt-v9"]
    assert eval_cli.main([*args, "--out", str(out), "--rounds", "10"]) == 0

    [result] = load_results(out / "prompt-v9.jsonl")
    assert (result.model, result.prompt) == ("tiny:1b", PROMPT_VERSION)
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "## set-dev: department" in report
    assert "majority" not in report
    assert "| prompt-v9 | 1 | " in report  # fields scored on gold-dev.yaml
