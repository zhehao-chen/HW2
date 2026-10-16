"""Assignment 2, Part E: three detectors, and Lecture 2's ladder. This file is yours.

Three of the four plan failures have a detector of a few lines over a trace
(Lecture 2, slides 45 to 49); the validator is the fourth. The checker calls these
on fixtures/traces/, so keep these exact signatures (checks/FORMATS.md, section
10.2):

    repeat_check(trace) -> list[list]
        Circular reasoning. Exact repeats: two tool_call lines with the same tool
        and the same arguments. Returns each group of repeats as the step numbers
        of its tool_call lines, e.g. [[1, 3], [2, 4]].

    orphan_check(plan) -> list
        Hallucinated steps. The ids of steps, other than the last, whose result no
        later step uses: no later step lists them in depends_on.

    expected_result_check(plan, trace) -> list
        Premature stopping, in part. The ids of plan steps that did not run and
        return their result. It catches skipped steps, not a plan too short.

    ladder(plan, trace) -> {"q1": {"fired": bool, "ids": [...]}, "q2": ..., "q3": ...}
        Lecture 2's questions 1 to 3 (slide 50), in order: did any two steps do
        the same thing; is any step's result never used; did every planned step
        execute. "ids" says what fired: groups of step numbers for q1, step ids
        (or, from a trace, step numbers) for q2 and q3. Question 4 needs
        judgment, so it goes in your report, not here.

    plan    a plan (section 10.1)
    trace   a list of trace lines, as harness.trace.read_trace returns them

A plan with no depends_on cannot answer question 2 from the plan. Answer it from
the trace, and say how in your report.
"""

from __future__ import annotations

import json

from agent.diff import match_calls


def tool_calls(trace: list[dict]) -> list[dict]:
    """Every tool_call line in the trace, in order."""
    calls = []
    for record in trace:
        if record.get("type") == "tool_call":
            calls.append(record)
    return calls


def repeat_check(trace: list[dict]) -> list[list]:
    """Exact repeats: the same tool and the same arguments (compared as JSON with sorted keys). Each group is returned as its step numbers."""
    groups = {}                                      # {(tool, arguments): [step numbers]}
    for call in tool_calls(trace):
        key = (call.get("name"), json.dumps(call.get("input") or {}, sort_keys=True))
        if key not in groups:
            groups[key] = []
        groups[key].append(call.get("step"))

    repeats = []
    for steps in groups.values():
        if len(steps) >= 2:
            repeats.append(steps)
    return repeats


def orphan_check(plan: dict) -> list:
    """Hallucinated steps: every step but the last that no later step lists in depends_on."""
    steps = plan.get("steps", [])
    orphans = []
    for index, step in enumerate(steps[:-1]):
        used = False
        for later in steps[index + 1:]:
            if step.get("id") in (later.get("depends_on") or []):
                used = True
                break
        if not used:
            orphans.append(step.get("id"))
    return orphans


def expected_result_check(plan: dict, trace: list[dict]) -> list:
    """Plan steps that did not run and return their result: no call matched them, or the call that did was an error."""
    matched, _extra = match_calls(plan, trace)
    missing = []
    for step in plan.get("steps", []):
        call = matched.get(step.get("id"))
        if call is None or call.get("is_error"):
            missing.append(step.get("id"))
    return missing


def unused_from_trace(trace: list[dict]) -> list:
    """Question 2 from the trace, for a plan with no depends_on: a call the run later repeated exactly
    had a result it did not use (it fetched it again). Returns the step numbers of every repeat but the last."""
    unused = []
    for group in repeat_check(trace):
        for step in group[:-1]:
            unused.append(step)
    return sorted(unused)


def ladder(plan: dict, trace: list[dict]) -> dict:
    """Lecture 2's questions 1 to 3 (slide 50). Question 4 needs judgment, so it is in the report."""
    repeats = repeat_check(trace)

    has_depends_on = True
    for step in plan.get("steps", []):
        if "depends_on" not in step:
            has_depends_on = False
    if has_depends_on:
        unused = orphan_check(plan)                  # plan step ids
    else:
        unused = unused_from_trace(trace)            # no depends_on: judged from the trace, as tool_call step numbers

    missing = expected_result_check(plan, trace)

    return {
        "q1": {"fired": len(repeats) > 0, "ids": repeats},
        "q2": {"fired": len(unused) > 0, "ids": unused},
        "q3": {"fired": len(missing) > 0, "ids": missing},
    }


if __name__ == "__main__":
    from pathlib import Path

    from agent.diff import diff
    from harness.trace import read_trace

    for name in ("looping", "s49"):
        folder = Path(__file__).resolve().parent.parent / "fixtures" / "traces" / name
        run_plan = json.loads((folder / "plan.json").read_text())
        run_trace = read_trace(folder / "trace.jsonl")
        print(name, "ladder:", json.dumps(ladder(run_plan, run_trace)))
        print(name, "diff:  ", json.dumps(diff(run_plan, run_trace)))
