"""System prompt built from the department config (zero-shot, see #9)."""

from megatron.departments import DepartmentsConfig

INSTRUCTIONS = """\
You turn a support request into a ticket.
- Extract who reports the problem, where it happened, when it happened and what is wrong.
  Use null for who, where or when if the request does not say.
- Write a short summary (up to 10 words) and 3-6 short tags.
- Choose the department whose description fits the request best.
  Use "{fallback}" if the request is unclear or fits no other department.
- Write the ticket fields in the language of the request and set "language" to it (ru or en).
"""


def build_system_prompt(config: DepartmentsConfig) -> str:
    departments = "\n".join(f"- {d.id}: {d.description}" for d in config.departments)
    return INSTRUCTIONS.format(fallback=config.fallback.id) + "\nDepartments:\n" + departments
