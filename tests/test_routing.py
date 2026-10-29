import pytest

from megatron.departments import DepartmentsConfig
from megatron.routing import route, score_candidates
from megatron.ticket import Ticket

TICKET = {
    "who": None,
    "where": None,
    "when": None,
    "what": "VPN drops every few minutes",
    "identifiers": [],
    "summary": "VPN drops",
    "tags": ["vpn"],
    "language": "en",
}


def ticket(*candidates: str) -> Ticket:
    return Ticket.model_validate(TICKET | {"candidates": list(candidates)})


def with_load(departments: DepartmentsConfig, **open_tickets: int) -> DepartmentsConfig:
    """The config with each named department's open tickets set (capacity stays)."""
    raw = departments.model_dump()
    for d in raw["departments"]:
        d["open_tickets"] = open_tickets.get(d["id"], d["open_tickets"])
    return DepartmentsConfig.model_validate(raw)


def test_score_is_weighted_match_and_free_capacity(departments):
    # w_match 0.7, w_load 0.3, rank_match 1.0 / 0.6; network 5/8 busy, software 3/12.
    scores = score_candidates(ticket("network", "software"), departments)
    assert scores == pytest.approx({"network": 0.7 + 0.3 * 3 / 8, "software": 0.42 + 0.3 * 0.75})
    assert list(scores) == ["network", "software"]


def test_best_fit_wins_at_normal_load(departments):
    routed = route(ticket("network", "software"), departments)
    assert routed.department == "network"
    assert routed.candidates == ["network", "software"]


def test_overloaded_best_fit_loses_to_free_second(departments):
    config = with_load(departments, network=8, software=0)
    assert route(ticket("network", "software"), config).department == "software"


def test_department_not_listed_never_wins(departments):
    # hardware and software are full, security is empty but was not a candidate.
    config = with_load(departments, hardware=10, software=12, security=0)
    assert route(ticket("hardware", "software"), config).department == "hardware"


def test_without_load_the_best_fit_wins(queues):
    routed = route(ticket("billing", "technical_support"), queues)
    assert routed.department == "billing"
    assert score_candidates(ticket("billing", "technical_support"), queues) == pytest.approx(
        {"billing": 0.7, "technical_support": 0.42}
    )


def test_tie_goes_to_the_better_fit(departments):
    raw = departments.model_dump()
    raw["routing"] = {"w_match": 0.0, "w_load": 1.0, "rank_match": [1.0, 0.5]}
    config = with_load(DepartmentsConfig.model_validate(raw), hardware=0, network=0)
    assert route(ticket("network", "hardware"), config).department == "network"


def test_weights_come_from_config(departments):
    raw = departments.model_dump()
    raw["routing"]["w_load"] = 0.0
    config = with_load(DepartmentsConfig.model_validate(raw), network=8, software=0)
    assert route(ticket("network", "software"), config).department == "network"
