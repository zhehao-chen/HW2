"""Assignment 2, Part B: the validator. This file is yours.

Four checks you can run before anything executes (Lecture 2, slide 17). The checker
calls validate directly, on slide 18's specimen, on the good plans in
fixtures/plans/, and on plans of its own with one defect each, so keep this exact
signature:

    validate(plan) -> {"valid": bool, "failures": [{"step": id, "check": n}]}

    plan      a plan (checks/FORMATS.md, section 10.1)
    valid     True when nothing failed
    failures  one entry for each step and check that fails, in any order; "step"
              is the step's id, or None for check 4, which is about the whole plan

The checks, defined exactly in section 10.2:

    1  every referenced tool exists: a step's tool is in the plan's own list,
       plan["meta"]["tools"]
    2  no step depends on a later step: every id in depends_on is an earlier step's
       (a dependency on itself, or on a step that does not exist, fails too)
    3  every step has an observable outcome: a tool, and an expected_result
    4  the step count is within bounds: at least one, and at most max_steps in
       agent/bounds.yaml (agent.loop.load_bounds())

Building it is half the job. The other half is in ways/planned.py: a plan that
fails is rejected, re-planned up to your bound, then escalated. Never executed.
"""

from __future__ import annotations

from agent.loop import load_bounds



def validate(plan: dict) -> dict:
   failures = []
   tools = plan.get("meta",{}).get("tools",[])
   steps = plan.get("steps",[])

   max_steps = load_bounds().max_steps
   step_count = len(steps)
   if step_count == 0 or step_count > max_steps:
      failures.append({"step": None, "check": 4})

   earlier_ids = []
   for step in steps:
      step_id = step.get("id")
      tool = step.get("tool")
      expected = step.get("expected_result")
      depends_on = step.get("depends_on") or []

      if tool and tool not in tools:
         failures.append({"step": step_id,"check": 1})

      for dep in depends_on:
         if dep not in earlier_ids:
            failures.append({"step":step_id, "check": 2})
            break

      if not tool or not expected:
         failures.append({"step":step_id, "check": 3})

      earlier_ids.append(step_id)

   valid = len(failures) == 0

   return {"valid": valid, "failures": failures} 
