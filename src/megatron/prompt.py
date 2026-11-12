"""System prompt built from the department config (zero-shot, see #9)."""

from megatron.departments import DepartmentsConfig

# Bumped on every change of the instructions; results record it, so runs can be compared (#9).
PROMPT_VERSION = "v4"  # v4: systems vocabulary (#34)

INSTRUCTIONS = """\
You turn a support request into a ticket.
- "who": the person, client, account or organisation the request is about or that reports
  it, with its ID if the request gives one ("client 1042", "hospital IT department"). Not
  the support team the message is addressed to.
- "where": the product, system, service, channel or place of the problem in a few words,
  using the words of the request and its names ("VPN gateway", "CRM -> messenger"); no URLs.
- "when": when it happened, as stated (dates, times, "since this morning").
- Use null for who, where or when if the request does not say.
- "what": what is wrong or what is asked, in one sentence (up to 20 words) that names the
  affected product or system, so it can be read on its own.
- Copy codes from the request into "identifiers" exactly as written, without labels such as
  "ID": phone numbers, message, order or ticket IDs, account names, logins. Names, places,
  URLs and words describing the problem do not go there. Use [] if the request has no such
  codes; never make one up.
- Write a short summary (up to 10 words) and 3-6 short tags.
- In "candidates", put the department whose description fits the request best first, then
  up to {more} others that could also handle it, best fit first. List only departments
  that really fit. Use "{fallback}" alone if the request is unclear or fits no other
  department; never list it together with another department.
- Write the ticket fields in the language of the request and set "language" to it ({languages}).
  If the request is in another language, write the fields in {default_language}.
"""


SYSTEMS_INSTRUCTION = """\
- "systems": the ids of the systems below that the request is about: where the problem is,
  and both ends of an integration ("A -> B"). Recognise them by meaning and by any of their
  spellings, including other cases and transliterations. Use [] if none of them is meant.
"""


def build_system_prompt(config: DepartmentsConfig) -> str:
    instructions = INSTRUCTIONS.format(
        fallback=config.fallback.id,
        more=len(config.routing.rank_match) - 1,
        languages=", ".join(config.languages),
        default_language=config.languages[0],
    )
    departments = "\n".join(f"- {d.id}: {d.description}" for d in config.departments)
    if not config.systems:  # without a vocabulary the prompt is v3's
        return instructions + "\nDepartments:\n" + departments
    systems = "\n".join(f"- {x.id}: {x.name} ({', '.join(x.spellings)})" for x in config.systems)
    return (
        instructions
        + SYSTEMS_INSTRUCTION
        + "\nDepartments:\n"
        + departments
        + "\n\nSystems:\n"
        + systems
    )
