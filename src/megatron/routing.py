"""Routing: the department for a ticket by profile match and current load (#10).

score = w_match * match + w_load * (1 - load)

`match` comes from the model's ranked candidates (`routing.rank_match` in the config). Only
the candidates are scored: a department the model did not list never gets the ticket,
however free it is (and the fallback is never among several candidates, see
`keep_fallback_alone`). Without load in the config the score is the match alone, so the
best fit wins; with load, a busy best fit can lose to a free second candidate.
"""

from megatron.departments import DepartmentsConfig
from megatron.ticket import RoutedTicket, Ticket


def score_candidates(ticket: Ticket, config: DepartmentsConfig) -> dict[str, float]:
    """Score of each candidate, in the model's order (best fit first)."""
    weights = config.routing
    scores = {}
    # Fewer candidates than ranks is normal: the model lists only those that fit.
    for department_id, match in zip(ticket.candidates, weights.rank_match, strict=False):
        load = config.get(department_id).load
        score = weights.w_match * match
        if load is not None:
            score += weights.w_load * (1 - load)
        scores[department_id] = score
    return scores


def route(ticket: Ticket, config: DepartmentsConfig) -> RoutedTicket:
    scores = score_candidates(ticket, config)
    # max() keeps the first of equal scores, so a tie goes to the better fit.
    department = max(scores, key=lambda d: scores[d])
    return RoutedTicket.model_validate(ticket.model_dump() | {"department": department})
