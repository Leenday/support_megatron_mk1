"""System prompt built from the department config (zero-shot, see #9)."""

from megatron.departments import DepartmentsConfig

INSTRUCTIONS = """\
You turn a support request into a ticket.
- Extract who reports the problem, where it happened, when it happened and what is wrong.
  Use null for who, where or when if the request does not say.
- Copy codes from the request into "identifiers" exactly as written: phone numbers, message,
  order or ticket IDs, account names, logins. Names, places and words describing the problem
  do not go there. Use [] if the request has no such codes; never make one up.
- Write a short summary (up to 10 words) and 3-6 short tags.
- In "candidates", put the department whose description fits the request best first, then
  up to {more} others that could also handle it, best fit first. List only departments
  that really fit. Use "{fallback}" alone if the request is unclear or fits no other
  department; never list it together with another department.
- Write the ticket fields in the language of the request and set "language" to it ({languages}).
  If the request is in another language, write the fields in {default_language}.
"""


def build_system_prompt(config: DepartmentsConfig) -> str:
    instructions = INSTRUCTIONS.format(
        fallback=config.fallback.id,
        more=len(config.routing.rank_match) - 1,
        languages=", ".join(config.languages),
        default_language=config.languages[0],
    )
    departments = "\n".join(f"- {d.id}: {d.description}" for d in config.departments)
    return instructions + "\nDepartments:\n" + departments
