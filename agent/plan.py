"""Assignment 2, Parts A and C: the planner and the reviser. This file is yours.

The contract (checks/FORMATS.md, section 10). The checker calls both functions
directly, with a scripted model that keeps a copy of every request, so keep these
exact signatures. You may add keyword arguments with defaults; the checker passes
only these.

    make_plan(client, issue_number, tool_schemas, trace=None) -> dict
    revise_plan(client, plan, step_results, trace=None) -> dict

    client        harness.client.ModelClient: client.create(system=, messages=, tools=)
    issue_number  the issue to triage, an int
    tool_schemas  the tool definitions, as ctx.tools.schemas gives them
    plan          the active plan, its steps' statuses brought up to date
    step_results  one entry per step that has run (section 10.3)
    trace         a harness.trace.TraceWriter, or None. When you get one, trace your
                  model call: trace.model_call(0, response, purpose="plan") in
                  make_plan, purpose="revise" in revise_plan
    returns       a plan (section 10.1): {"meta": {...}, "steps": [...]}

make_plan writes the plan and stops (Lecture 2, slide 15). Its request carries the
task, the issue number and the tool list, and nothing from the issue: not its body,
not its title. The checker looks for each issue's sentinel string in every request.
The usual way to get the plan back as data: offer the model one tool whose
input_schema is agent/plan_schema.json, and read the plan from its call. Mark an
argument that waits on an earlier step's result "$fill"; the executor fills it in.

revise_plan repairs before it replaces: it never changes a step whose status is
done; it may change a step that failed, to retry it, and any step not yet run. A
step whose step result says "done" comes back unchanged, every field but status,
whatever the model wrote. Its request carries structured step results only (status, counts, paths,
error codes): never the issue's text, and never a step result's `args`, which the
executor may have filled in from the issue.

Keep your prompts in prompts/.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANNER_PROMPT = "prompts/planner.md"
PLAN_SCHEMA = json.loads((ROOT / "agent" / "plan_schema.json").read_text())


def make_plan(client, issue_number, tool_schemas, trace=None):
    system = (ROOT / PLANNER_PROMPT).read_text()

    # 1. The tool list: tool_schemas written out as text for the model (name, description, arguments)
    lines = []
    for t in tool_schemas:
        name = t["name"]
        description = t.get("description","")
        arguments = json.dumps(t["input_schema"].get("properties", {}))
        lines.append(f"- {name}: {description} Arguments: {arguments}")
    tool_list = "\n".join(lines)

    # 2. The user message: the issue number and the tool list. Never the issue's title or body
    message = (
        f'Plan the triage of issue #{issue_number}.\n'
        "\n"
        "Tools:\n"
        f"{tool_list}"
    )

    # 3. Offer one tool only: the one that submits the plan
    plan_tool = {
        "name": "submit_plan",
        "description": "Submit the triage plan: the steps, in the order they run.",
        "input_schema": PLAN_SCHEMA,   # must equal plan_schema.json exactly: the checker compares with ==
        "strict": True,
    }

    response = client.create(system=system,
                             messages=[{"role": "user", "content": message}],
                             tools=[plan_tool])
    if trace is not None:
        trace.model_call(0, response, purpose="plan")

    # 4. Take the plan from the submit_plan call in response.tool_calls
    #    If there is none (the model answered in prose), return an empty plan, which Part B rejects
    plan = {"steps":[]}
    for call in response.tool_calls:
        if call.name == "submit_plan":
            plan = dict(call.input)
            break

    # 5. The code adds meta; the model never writes it
    plan["meta"] = {
        "model": response.model,
        "prompt": PLANNER_PROMPT,
        "tools": [t["name"] for t in tool_schemas],   
    }
    return plan


REVISER_PROMPT = "prompts/reviser.md"


def revise_plan(client, plan: dict, step_results: list[dict], trace=None) -> dict:
    system = (ROOT / REVISER_PROMPT).read_text()

    # 1. Keep the structured fields only, and drop args: they may hold search terms taken from the issue
    safe_results = []
    for result in step_results:
        safe_results.append({
            "id": result["id"],
            "tool": result["tool"],
            "status": result["status"],
            "count": result.get("count"),
            "paths": result.get("paths", []),
            "error_code": result.get("error_code"),
        })

    # 2. The user message: the current plan's steps (without meta) and the results above
    message = (
        "The current plan:\n"
        f"{json.dumps(plan['steps'], indent=1)}\n"
        "\n"
        "What each step that has run returned:\n"
        f"{json.dumps(safe_results, indent=1)}"
    )

    plan_tool = {
        "name": "submit_plan",
        "description": "Submit the revised plan: every step, in the order they run.",
        "input_schema": PLAN_SCHEMA,
        "strict": True,
    }
    response = client.create(system=system,
                             messages=[{"role": "user", "content": message}],
                             tools=[plan_tool])
    if trace is not None:
        trace.model_call(0, response, purpose="revise")

    new_plan = {"steps": []}
    for call in response.tool_calls:
        if call.name == "submit_plan":
            new_plan = dict(call.input)
            break

    # 3. Protect done steps in code: whatever the model wrote, put them back as they were
    new_steps = new_plan.get("steps")
    if isinstance(new_steps, list):          # a malformed reply is left for the schema check to reject
        missing = []
        for old_step in plan["steps"]:
            if old_step.get("status") != "done":
                continue
            found = False
            for index, step in enumerate(new_steps):
                if isinstance(step, dict) and step.get("id") == old_step["id"]:
                    new_steps[index] = dict(old_step)      # the model changed it: restore it
                    found = True
                    break
            if not found:
                missing.append(dict(old_step))             # the model dropped it: note it, and put it back

        # done steps always come first, so dropped ones go back at the front, in their original order
        new_plan["steps"] = missing + new_steps

    new_plan["meta"] = {
        "model": response.model,
        "prompt": REVISER_PROMPT,
        "tools": plan["meta"]["tools"],      # the original plan's tool list
    }
    return new_plan

