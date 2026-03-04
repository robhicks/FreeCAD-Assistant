# SPDX-License-Identifier: LGPL-2.1-or-later

try:
    from freecad_assistant_core import PlanStep, Plan, parse_response, extract_code_block
    _BACKEND = "rust"
except ImportError:
    from assistant.plan_parser import PlanStep, Plan, parse_response, extract_code_block
    _BACKEND = "python"
