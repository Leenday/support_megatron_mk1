"""Triage-time measurement (#43): the plan, the order, the report and the page's server."""

import json
import threading
import time
import urllib.request
from collections import Counter
from http.server import ThreadingHTTPServer

import pytest

from megatron import triage_cli
from megatron.evaluation import Result
from megatron.inputs import Request
from megatron.ticket import RoutedTicket
from megatron.triage import (
    Answer,
    Fields,
    Mode,
    PlanItem,
    build_plan,
    changed_fields,
    render,
    report,
    sequence,
    write_plan,
)

TICKET = {
    "who": "Anna",
    "where": "room 305",
    "systems": [],
    "when": None,
    "what": "Printer jam",
    "identifiers": [],
    "summary": "Printer jam",
    "tags": [],
    "candidates": ["hardware"],
    "language": "en",
    "department": "hardware",
}


def requests_and_results(n_hardware: int, n_network: int) -> tuple[list[Request], list[Result]]:
    labels = ["hardware"] * n_hardware + ["network"] * n_network
    requests = [Request(id=i, text=f"r{i}", expected=label) for i, label in enumerate(labels)]
    results = [
        Result(id=r.id, request=r.text, ticket=RoutedTicket.model_validate(TICKET), seconds=1.5)
        for r in requests
    ]
    return requests, results


def item(id_: str, half: str, expected: str = "hardware") -> PlanItem:
    return PlanItem(
        id=id_,
        text="t",
        expected=expected,
        half=half,
        service=Fields(department="hardware", who="Anna", what="Printer jam"),
        model_seconds=1.5,
    )


def test_plan_keeps_label_shares_balances_halves_and_skips_excluded():
    requests, results = requests_and_results(30, 10)
    plan = build_plan(requests, results, size=20, seed=1, exclude={"0", "1"})
    assert len(plan) == 20
    assert Counter(p.expected for p in plan) == {"hardware": 15, "network": 5}
    assert not {"0", "1"} & {p.id for p in plan}
    assert Counter(p.half for p in plan) == {"A": 10, "B": 10}
    assert plan[0].service.department == "hardware"
    assert plan[0].model_seconds == 1.5


def test_plan_needs_enough_answered_requests():
    requests, results = requests_and_results(3, 0)
    with pytest.raises(ValueError, match="only 3"):
        build_plan(requests, results, size=5, seed=1)


def test_sequence_alternates_blocks_and_swaps_halves():
    plan = [item(f"a{i}", "A") for i in range(10)] + [item(f"b{i}", "B") for i in range(10)]
    first = sequence(plan, swap=False)
    modes = [m for _, m in first]
    assert modes == [Mode.MANUAL] * 5 + [Mode.SERVICE] * 5 + [Mode.MANUAL] * 5 + [Mode.SERVICE] * 5
    assert {p.half for p, m in first if m is Mode.MANUAL} == {"A"}
    second = sequence(plan, swap=True)
    assert second[0][1] is Mode.SERVICE
    assert {p.half for p, m in second if m is Mode.MANUAL} == {"B"}
    assert sorted(p.id for p, _ in second) == sorted(p.id for p in plan)  # each request once


def answer(id_: str, mode: Mode, seconds: float, department: str = "hardware", **fields) -> Answer:
    base = {"who": "Anna", "what": "Printer jam"} if mode is Mode.SERVICE else {}
    return Answer(
        id=id_,
        participant="p1",
        mode=mode,
        seconds=seconds,
        fields=Fields(department=department, **(base | fields)),
        model_seconds=1.5,
    )


def test_changed_fields_compares_with_the_service_ticket():
    p = item("x", "B")
    assert changed_fields(answer("x", Mode.SERVICE, 10), p) == []
    edited = answer("x", Mode.SERVICE, 10, department="network", when="since morning")
    assert changed_fields(edited, p) == ["department", "when"]


def test_report_adds_model_time_to_the_check_and_scores_departments():
    plan = [item(f"a{i}", "A") for i in range(4)] + [item(f"b{i}", "B") for i in range(4)]
    answers = [answer(f"a{i}", Mode.MANUAL, s) for i, s in enumerate([60, 80, 100, 120])]
    answers[0] = answer("a0", Mode.MANUAL, 60, department="network")  # one wrong by hand
    answers += [answer(f"b{i}", Mode.SERVICE, s) for i, s in enumerate([20, 30, 40, 50])]
    answers[-1] = answer("b3", Mode.SERVICE, 50, when="since morning")  # one edited
    r = report(answers, plan, rounds=200)
    assert r.manual.median == 90
    assert r.manual.department_accuracy == 0.75
    assert r.service.median == 35 + 1.5
    assert r.check_median == 35
    assert r.reduction.value == pytest.approx(1 - 36.5 / 90)
    assert r.reduction.low <= r.reduction.value <= r.reduction.high
    assert r.kept_department == 1.0
    assert r.untouched == 0.75
    assert "Median time reduction" in render("ru", r)


def test_report_needs_both_modes():
    with pytest.raises(ValueError, match="both modes"):
        report([answer("a0", Mode.MANUAL, 60)], [item("a0", "A")])


def test_page_serves_the_next_request_and_records_answers(tmp_path, monkeypatch):
    """The server shows requests in the plan's order and appends one answer per request."""
    monkeypatch.chdir(tmp_path)
    set_dir = tmp_path / "ru"
    plan = [item("a0", "A"), item("b0", "B")]
    write_plan(triage_cli.out_dir(set_dir) / "plan.jsonl", plan)
    config = tmp_path / "departments.yaml"
    config.write_text(
        "departments:\n"
        "  - {id: hardware, name_ru: Оборудование, name_en: Hardware, description: d,"
        " tags: [printer], language: ru, fallback: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEPARTMENTS_PATH", str(config))
    servers: list[ThreadingHTTPServer] = []
    real = triage_cli.ThreadingHTTPServer

    def start(address, handler):
        server = real((address[0], 0), handler)
        servers.append(server)
        return server

    monkeypatch.setattr(triage_cli, "ThreadingHTTPServer", start)
    thread = threading.Thread(
        target=triage_cli.main, args=(["serve", str(set_dir), "--participant", "p1"],), daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not servers:
        assert thread.is_alive(), "the server did not start"
        assert time.monotonic() < deadline
        time.sleep(0.01)
    base = f"http://127.0.0.1:{servers[0].server_address[1]}"
    try:
        state = json.load(urllib.request.urlopen(base + "/api/next"))
        assert state["item"] == {"id": "a0", "mode": "manual", "text": "t", "fields": None}
        assert state["departments"][0]["name"] == "Оборудование"
        body = {"id": "a0", "mode": "manual", "seconds": 42.0, "fields": {"department": "hardware"}}
        post = urllib.request.Request(
            base + "/api/answer", json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        urllib.request.urlopen(post)
        state = json.load(urllib.request.urlopen(base + "/api/next"))
        assert state["done"] == 1
        assert state["item"]["mode"] == "service"
        assert state["item"]["fields"]["department"] == "hardware"
        saved = (triage_cli.out_dir(set_dir) / "answers-p1.jsonl").read_text().splitlines()
        assert json.loads(saved[0])["seconds"] == 42.0
        assert json.loads(saved[0])["model_seconds"] == 1.5
    finally:
        servers[0].shutdown()
