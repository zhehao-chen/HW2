"""Assignment 2, Part E: the diff of the plan against what ran. This file is yours.

"The one people skip" (Lecture 2, slide 54). The checker calls it on slide 51's run
in fixtures/traces/s49/, so keep this exact signature (checks/FORMATS.md, section
10.2):

    diff(plan, trace) -> {"steps": {step_id: label}, "extra": [step numbers]}

    steps   every plan step, labelled
              executed   it ran, in plan order
              skipped    it never ran
              reordered  it ran, out of plan order
    extra   the step numbers of tool_call lines that match no plan step

How a call matches a step is yours to decide: by its tool, and by any arguments
the plan fixes (an argument written "$fill" is fixed by nothing). Say how in your
report. Mind slide 51's run: it calls run_tests twice, and only one of those calls
can belong to each run_tests step.
"""

from __future__ import annotations

import json

FILL = "$fill"


def step_args(step: dict) -> dict:
    """A step's arguments: fixtures use args (a dict), our plans use args_json (a string)."""
    if isinstance(step.get("args"), dict):
        return step["args"]
    try:
        args = json.loads(step.get("args_json") or "{}")
    except json.JSONDecodeError:
        return {}
    return args if isinstance(args, dict) else {}


def fixed_args(step: dict) -> dict:
    """The arguments the plan fixes: every one not written "$fill"."""
    fixed = {}
    for key, value in step_args(step).items():
        if value != FILL:
            fixed[key] = value
    return fixed


def fits(step: dict, call: dict) -> bool:
    """Does the call fit this step: the same tool, and every argument the plan fixes equal."""
    if step.get("tool") is None or step.get("tool") != call.get("name"):
        return False
    call_input = call.get("input") or {}
    for key, value in fixed_args(step).items():
        if call_input.get(key) != value:
            return False
    return True


def match_calls(plan: dict, trace: list[dict]) -> tuple[dict, list]:
    """Match each tool_call line to a plan step. Returns ({step id: its call}, [calls that match no step]).

    A line with a plan_step (our executor writes one on every call) matches that step.
    A line without one (the transcribed runs in fixtures/traces/) matches, in order, a step not yet
    matched with the same tool and the same fixed arguments; if several fit, the one with the most fixed arguments, then the earliest.
    Each step takes one call at most: a repeated call is extra.
    """
    steps = plan.get("steps", [])
    ids = [step.get("id") for step in steps]
    matched = {}
    extra = []

    for record in trace:
        if record.get("type") != "tool_call":
            continue

        if record.get("plan_step") is not None:
            step_id = record["plan_step"]
            if step_id in ids and step_id not in matched:
                matched[step_id] = record
            elif step_id not in ids:
                extra.append(record.get("step"))
            # the same step run again (a retry after a revision): keep the latest
            else:
                matched[step_id] = record
            continue

        best = None
        for step in steps:
            if step.get("id") in matched or not fits(step, record):
                continue
            if best is None or len(fixed_args(step)) > len(fixed_args(best)):
                best = step
        if best is None:
            extra.append(record.get("step"))
        else:
            matched[best.get("id")] = record

    return matched, extra


def diff(plan: dict, trace: list[dict]) -> dict:
    matched, extra = match_calls(plan, trace)

    # each call's position in the trace, to judge the order
    position = {}
    index = 0
    for record in trace:
        if record.get("type") == "tool_call":
            position[id(record)] = index
            index += 1

    labels = {}
    latest = -1                                      # the latest position among the steps executed so far, in plan order
    for step in plan.get("steps", []):
        call = matched.get(step.get("id"))
        if call is None:
            labels[step.get("id")] = "skipped"
            continue
        here = position[id(call)]
        if here < latest:
            labels[step.get("id")] = "reordered"     # it ran before a step that comes earlier in the plan
        else:
            labels[step.get("id")] = "executed"
            latest = here

    return {"steps": labels, "extra": extra}
