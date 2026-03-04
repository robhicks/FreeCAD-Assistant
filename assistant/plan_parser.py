# SPDX-License-Identifier: LGPL-2.1-or-later

import re


class PlanStep:
    """A single step in an execution plan."""

    __slots__ = ("number", "description", "status", "code", "result", "retries")

    def __init__(self, number, description):
        self.number = number
        self.description = description
        self.status = "pending"  # pending, running, done, failed
        self.code = None
        self.result = None  # (success, stdout, stderr)
        self.retries = 0


class Plan:
    """A multi-step execution plan parsed from LLM output."""

    __slots__ = ("steps", "raw_text")

    def __init__(self, steps, raw_text):
        self.steps = steps
        self.raw_text = raw_text


_PLAN_RE = re.compile(
    r"<<<PLAN>>>\s*(.*?)\s*<<<END_PLAN>>>", re.DOTALL
)
_STEP_RE = re.compile(
    r"STEP\s+(\d+)\s*:\s*(.+)", re.IGNORECASE
)
_CODE_BLOCK_RE = re.compile(
    r"```python\s*\n(.*?)```", re.DOTALL
)


def parse_response(text):
    """Parse LLM response for plan markers.

    Returns (Plan, preamble) if a plan is found, or (None, text) if not.
    """
    m = _PLAN_RE.search(text)
    if not m:
        return None, text

    preamble = text[: m.start()].strip()
    plan_body = m.group(1)

    steps = []
    for step_match in _STEP_RE.finditer(plan_body):
        number = int(step_match.group(1))
        description = step_match.group(2).strip()
        steps.append(PlanStep(number, description))

    if not steps:
        return None, text

    plan = Plan(steps, plan_body)
    return plan, preamble


def extract_code_block(text):
    """Extract the first ```python code block from text. Returns code or None."""
    m = _CODE_BLOCK_RE.search(text)
    if m:
        return m.group(1).rstrip("\n")
    return None
