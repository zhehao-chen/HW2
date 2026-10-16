"""Way 5, planned: RepoMind with a plan it cannot quietly abandon. This file is yours.

Assignment 2, Parts B, C and D. Like every way, run(ctx) -> None (see ways/__init__.py):

    python run.py --way planned --set dev
    python run.py --way planned --critique self --set dev      # or external; off is the default

The run, in order (checks/FORMATS.md, section 10):

  1. Plan: agent.plan.make_plan(ctx.client, ctx.issue_number, ctx.tools.schemas,
     trace=ctx.trace). The planner never sees the issue.
  2. Check, then validate. First the plan against agent/plan_schema.json, with
     harness.schema.errors (a vendor may accept "strict" and not enforce it), and
     that its last step is post_comment (a plan without one passes the four checks
     and posts nothing); a plan that breaks either writes
     ctx.trace.event("schema", errors=...). Then agent.validator.validate(plan). A
     plan that fails any of these is rejected and re-planned, at most MAX_REPLANS
     times; then the run escalates: ctx.trace.end("escalated", detail), no tool
     call, nothing posted.
  3. Log: ctx.trace.plan(1, plan), before the first tool call.
  4. Execute the steps in order, each tool call through ctx.call_tool, naming the
     plan step it runs for: ctx.call_tool(n, tool, args, plan_step=step["id"]). Where a step
     has arguments marked "$fill", one model call fills them in: offer it that
     step's tool alone, and trace it with ctx.trace.model_call(n,
     response, purpose="execute"). Act on the tool calls a response holds,
     whatever its stop_reason says. The executor may run, retry or halt a step; it
     may not add, drop or reorder one. A call that is not the current step's tool
     never runs: refuse it and write ctx.trace.event("off_plan", step=..., tool=...).
  5. Part C: revise only at one checkpoint, after a search step: the first search
     step, and any search step a revision added or changed, until MAX_REVISIONS is
     spent; and only when the check there fails (a check in code, not in a prompt,
     such as "the search returned at least one source file, not only documentation
     or translations"): revise_plan, which never changes a step that is done but may
     change a failed one to retry it, then check the new version against the schema
     and validate it, write
     ctx.trace.event("revision", checkpoint=..., version=..., valid=...), and log a
     valid one with ctx.trace.plan(version, plan). A revision that fails the
     validator never runs, and counts against the bound.
  6. Part D: before post_comment, the second pass, in the mode ctx.critique names
     (off, self or external), at most MAX_ROUNDS rounds. A round checks the
     current draft (agent.critique.verify, or agent.critique.self_critique) and
     writes ctx.trace.event("critique", round=..., mode=..., result="pass" or
     "fail", reason=..., changed=..., draft=...). A draft that fails, with a round
     left, is rewritten by one model call given the reason, traced with
     purpose="critique", and the next round checks the new draft. A draft still
     failing in the last round is held: not posted, and the run ends escalated.
     Nothing is posted until the last round, and a run posts one comment at most.

The comment is Assignment 1's: two lines, label: and file: (section 1). A run that
finishes its plan can leave its ending to the runner, which writes completed.

Part G's ways/notes.py extends this way without changing it, so build this one with
hooks it can override: for example an executor class whose methods run after every
step, build what each model call sees, and run before the comment.

The checker reads MAX_REPLANS, MAX_REVISIONS and MAX_ROUNDS from this module, and
runs this way against scripted models (harness/scripted.py). You can run them too,
free:

    python run.py --way planned --backend harness.scripted:AlwaysInvalidPlanner --set dev
    python run.py --way planned --backend harness.scripted:OffPlanExecutor --set dev
    python run.py --way planned --critique external --backend harness.scripted:DraftNamesUnseenFile --set dev
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.critique import self_critique, verify
from agent.plan import make_plan, revise_plan
from agent.validator import validate
from harness.formats import normalize_path, result_paths
from harness.schema import errors

MAX_REPLANS = 2     # Part B: re-plans after a rejected plan before you escalate; say why in your report
MAX_REVISIONS = 3      # Part C: rejected revisions count too, so 3 leaves two good ones after a rejection; past that only tokens
MAX_ROUNDS = 2         # Part D: check, rewrite once with the reason, check again; the same in both modes

PLAN_SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "agent" / "plan_schema.json").read_text())

FILL = "$fill"


def schema_problems(plan: dict) -> list[str]:
    """What a plan must pass before the validator: the schema, args_json as a JSON object, "$fill" used rightly, and a last step that is post_comment."""
    # 1. The schema check, on the plan without meta (the code adds meta; it is not in the schema)
    body = {}
    for key, value in plan.items():
        if key != "meta":
            body[key] = value
    problems = errors(body, PLAN_SCHEMA)
    if problems:
        return problems              # the wrong shape: the other checks cannot run

    steps = plan["steps"]            # the schema has made sure steps exists and is a list

    # 2. Every step's args_json must parse to a JSON object
    for step in steps:
        try:
            args = json.loads(step["args_json"])
        except json.JSONDecodeError:
            args = None
        if not isinstance(args, dict):                     # anything but an object is a problem
            problems.append(f"step {step['id']}: args_json is not a JSON object")
            continue

        # "$fill" must be a whole value: inside a longer string ("file: $fill") the executor cannot see it, and posts it as written
        for key, value in args.items():
            if isinstance(value, str) and FILL in value and value != FILL:
                problems.append(f"step {step['id']}: {key} has {FILL} inside a longer value; it must be the whole value")

        # A search term, a file path and a comment's body are only known once the issue is read, and neither the planner
        # nor the reviser sees it, so the plan must leave them "$fill" (a revision once fixed an example from the prompt as its query)
        must_fill = {"search_repo": "query", "read_file": "path", "post_comment": "body"}
        key = must_fill.get(step["tool"])
        if key is not None and args.get(key) != FILL:
            problems.append(f"step {step['id']}: {step['tool']}'s {key} must be {FILL}")

    # 3. The last step must be post_comment (a plan with no steps is left to the validator's check 4)
    if len(steps) > 0 and steps[-1]["tool"] != "post_comment":
        problems.append("the last step is not post_comment")

    return problems


def get_valid_plan(ctx) -> dict | None:
    """Plan, and re-plan a rejected plan at most MAX_REPLANS times. Returns a plan that passed, or None."""
    for attempt in range(MAX_REPLANS + 1):
        plan = make_plan(ctx.client, ctx.issue_number, ctx.tools.schemas, trace=ctx.trace)

        problems = schema_problems(plan)
        if problems:
            ctx.trace.event("schema", errors=problems, attempt=attempt)
            continue                 # rejected: plan again

        result = validate(plan)                # the four checks
        if not result["valid"]:
            ctx.trace.event("rejected", failures=result["failures"], attempt=attempt)
            continue

        return plan

    return None


class Executor:
    """Runs the plan step by step. Part G's ways/notes.py extends this class."""

    def __init__(self, ctx, plan: dict):
        self.ctx = ctx
        self.plan = plan
        self.model_step = 0          # the executor's own model call count; 0 before its first call
        self.results = {}            # {step id: the text its tool returned}
        self.system = ctx.prompt("executor.md")

        self.version = 1             # the active plan's version
        self.revisions = 0           # revision attempts so far, accepted and rejected alike
        self.step_results = []       # in FORMATS section 10.3's shape, for the reviser
        self.to_check = set()        # ids of the search steps the checkpoint checks after they run

        for step in plan["steps"]:   # at first, only the first search step
            if step["tool"] == "search_repo":
                self.to_check.add(step["id"])
                break

    def run(self) -> bool:
        """Run the steps, with the checkpoint after a search. True when every step is done; False when the run stopped (and escalated)."""
        while True:
            step = self.next_step()
            if step is None:
                return True                        # every step is done

            if not self.run_step(step):
                return False

            if step["id"] in self.to_check:
                self.to_check.discard(step["id"])
                last = self.step_results[-1]
                if not self.search_found_source(last["paths"]):
                    step["status"] = "failed"      # the search ran, but found no source file
                    last["status"] = "failed"
                    if len(last["paths"]) == 0:
                        last["error_code"] = "no_matches"
                    else:
                        last["error_code"] = "no_source"
                    if not self.revise():
                        self.escalate(f"step {step['id']}: no source file found, and {MAX_REVISIONS} revisions spent")
                        return False

    def next_step(self) -> dict | None:
        """The plan's first step that is not done."""
        for step in self.plan["steps"]:
            if step["status"] != "done":
                return step
        return None

    def run_step(self, step: dict) -> bool:
        args = json.loads(step["args_json"])                            # the step's arguments, as a dict

        if self.needs_fill(args):
            filled = self.fill(step, args)
            if filled is not None and not self.path_was_found(step, filled):
                # the model made up a path no search returned: list the paths it may choose from, and fill once more
                note = ("You chose " + json.dumps(filled.get("path")) + ", which no search returned. "
                        "Choose one of these paths, exactly as written:\n" + "\n".join(self.search_paths()))
                filled = self.fill(step, args, note=note)
                if filled is not None and not self.path_was_found(step, filled):
                    filled = None
            args = filled
            if args is None:                     # no fill: no tool call, an argument left out, or a made-up path twice
                step["status"] = "failed"
                self.escalate(f"step {step['id']}: could not fill the arguments for {step['tool']}")
                return False

        # Part D: the second pass before posting. None means the draft was held and the run has escalated
        if step["tool"] == "post_comment":
            final_draft = self.before_comment(args["body"])
            if final_draft is None:
                step["status"] = "failed"
                return False
            args["body"] = final_draft

        # Search results come in path order, 10 by default, and CHANGELOG, README and docs often fill them.
        # Ask for 20 (the tool's cap) when the plan leaves max_results out; a value the plan fixes stays
        if step["tool"] == "search_repo" and "max_results" not in args:
            args["max_results"] = 20

        result = self.ctx.call_tool(self.model_step, step["tool"], args, plan_step=step["id"])

        # record a structured result (FORMATS section 10.3) for the reviser
        paths = result_paths(step["tool"], args, result.content, result.is_error)
        if step["tool"] == "search_repo":
            count = len(paths)
        else:
            count = None
        if result.is_error:
            status, error_code = "failed", "tool_error"
        else:
            status, error_code = "done", None
        self.step_results.append({
            "id": step["id"],
            "tool": step["tool"],
            "status": status,
            "count": count,
            "paths": paths,
            "error_code": error_code,
            "args": args,              # kept, but revise_plan never sends it to the model
        })

        if result.is_error:
            step["status"] = "failed"
            self.escalate(f"step {step['id']} ({step['tool']}) failed")
            return False

        step["status"] = "done"
        self.results[step["id"]] = result.content
        self.after_step(step, result)
        return True

    def needs_fill(self, args: dict) -> bool:
        for value in args.values():
            if value == FILL:                             # an argument marked to be filled
                return True
        return False

    def search_paths(self) -> list[str]:
        """Every path a search in this run returned, in order, without repeats."""
        paths = []
        for result in self.step_results:
            if result["tool"] == "search_repo":
                for path in result["paths"]:
                    if path not in paths:
                        paths.append(path)
        return paths

    def path_was_found(self, step: dict, filled: dict) -> bool:
        """A read_file path must be one a search returned; other tools are not checked."""
        if step["tool"] != "read_file":
            return True
        return normalize_path(str(filled.get("path"))) in self.search_paths()

    def fill(self, step: dict, args: dict, note: str | None = None) -> dict | None:
        """One model call, offered this step's tool alone, to fill the step's arguments. note is added when it fills again."""
        tool_schema = None
        for schema in self.ctx.tools.schemas:
            if schema["name"] == step["tool"]:                             # this step's tool
                tool_schema = schema

        messages = self.build_messages(step, args)
        if note is not None:
            messages[-1]["content"] += "\n\n" + note

        self.model_step += 1
        response = self.ctx.client.create(
            system=self.system,
            messages=messages,
            tools=[tool_schema],                 # this tool alone
        )
        self.ctx.trace.model_call(self.model_step, response, purpose="execute")

        for call in response.tool_calls:         # act on the tool calls, whatever stop_reason says
            if call.name != step["tool"]:
                # the boundary: not this step's tool, so refuse it; it never runs
                self.ctx.trace.event("off_plan", step=step["id"], tool=call.name, input=call.input)
                continue

            filled = {}
            for key, value in args.items():
                if value == FILL:
                    if key not in call.input:
                        return None              # an argument left out: no fill
                    filled[key] = call.input[key]           # the model's value
                else:
                    filled[key] = value           # the plan's fixed value
            return filled

        return None                              # no tool call

    def issue_text(self) -> str:
        """The read_issue step's result: the issue itself."""
        for step in self.plan["steps"]:
            if step["tool"] == "read_issue" and step["id"] in self.results:
                return self.results[step["id"]]
        return "(the issue has not been read)"

    def build_messages(self, step: dict, args: dict) -> list[dict]:
        """What a fill call sees: the issue, and the results of the steps this one depends on. Part G overrides it."""
        parts = []
        parts.append("The issue:\n" + self.issue_text())

        for dep_id in step["depends_on"]:
            dep_step = None
            for step2 in self.plan["steps"]:
                if step2["id"] == dep_id:
                    dep_step = step2
                    break    # the step whose id is dep_id
            if dep_step["tool"] == "read_issue":
                continue                         # the issue is already above
            result_text = self.results.get(dep_id, "(no result)")
            # with the arguments of its latest run: a read_file result is only the file's text, so without them the model does not know which file it read
            dep_args = {}
            for result in self.step_results:
                if result["id"] == dep_id:
                    dep_args = result["args"]
            parts.append(f"Result of step {dep_id} ({dep_step['tool']} {json.dumps(dep_args)}):\n{result_text}")

        # when a failed step runs again, show what was tried, so the model does not fill the same values
        earlier = []
        for result in self.step_results:
            if result["id"] == step["id"] and result["status"] == "failed":
                found = "no results" if not result["paths"] else "only " + ", ".join(result["paths"])
                earlier.append(f"- {json.dumps(result['args'])}: {found}")
        if earlier:
            parts.append("Earlier attempts at this step did not find source code; try something different:\n"
                         + "\n".join(earlier))

        parts.append(
            f"Now run step {step['id']}: {step['action']}.\n"
            f"Call {step['tool']} once. These are its arguments; replace every {FILL} with a real value:\n"
            f"{json.dumps(args)}"
        )
        return [{"role": "user", "content": "\n\n".join(parts)}]

    # ---------- Part C: the checkpoint and the revision ----------

    def search_found_source(self, paths: list[str]) -> bool:
        """The checkpoint's check: the search returned at least one .ts or .tsx file under src/."""
        for path in paths:
            if path.startswith("src/") and (path.endswith(".ts") or path.endswith(".tsx")):
                return True
        return False

    def revise(self) -> bool:
        """Revise the plan until a revision passes or MAX_REVISIONS is spent. True when one passed."""
        while self.revisions < MAX_REVISIONS:
            self.revisions += 1
            version = self.version + 1
            new_plan = revise_plan(self.ctx.client, self.plan, self.step_results, trace=self.ctx.trace)

            problems = schema_problems(new_plan)
            if problems:
                self.ctx.trace.event("schema", errors=problems, version=version)
                valid = False
            else:
                valid = validate(new_plan)["valid"]
            self.ctx.trace.event("revision", checkpoint="after_search", version=version, valid=valid)

            if valid:
                self.mark_changed_searches(new_plan)
                self.plan = new_plan
                self.version = version
                self.ctx.trace.plan(version, new_plan)
                return True
        return False

    def mark_changed_searches(self, new_plan: dict) -> None:
        """A search step a revision added or changed is checked again after it runs."""
        for step in new_plan["steps"]:
            if step["tool"] != "search_repo":
                continue
            old = None
            for candidate in self.plan["steps"]:
                if candidate["id"] == step["id"]:
                    old = candidate
            # new, or any field changed (including failed back to pending, a retry)
            if old is None or old != step:
                self.to_check.add(step["id"])

    # ---------- Part D: the second pass before posting ----------

    def before_comment(self, draft: str) -> str | None:
        """Check the draft in the mode ctx.critique names, for at most MAX_ROUNDS rounds. Returns the draft to post, or None when it is held."""
        mode = self.ctx.critique
        if mode == "off":
            return draft                           # no second pass: no critique call, no critique line

        for round_number in range(1, MAX_ROUNDS + 1):
            passed, reason = self.check_draft(draft, mode)

            new_draft = draft
            if not passed and round_number < MAX_ROUNDS:
                new_draft = self.rewrite_draft(draft, reason)     # a round is left: rewrite once, with the reason

            self.ctx.trace.event("critique", round=round_number, mode=mode,
                                 result="pass" if passed else "fail", reason=reason,
                                 changed=new_draft != draft, draft=draft)
            if passed:
                return draft
            draft = new_draft

        # still failing in the last round: hold it
        self.escalate(f"the draft still failed the {mode} check after {MAX_ROUNDS} rounds")
        return None

    def check_draft(self, draft: str, mode: str) -> tuple[bool, str | None]:
        """One check. Returns (passed, the reason it failed)."""
        if mode == "external":
            outcome = verify(draft, self.ctx)            # checks in code, no model call
            if outcome["passed"]:
                return True, None
            return False, "; ".join(outcome["reasons"])

        self.model_step += 1                             # self: the same model rereads the draft
        verdict = self_critique(self.ctx.client, draft, self.build_evidence(),
                                trace=self.ctx.trace, step=self.model_step)
        if verdict["decision"] == "accept":
            return True, None
        return False, verdict["reason"]

    def build_evidence(self) -> dict:
        """What a self critique sees: the issue, and each step's latest arguments and result (what the draft's author saw)."""
        latest_args = {}
        for result in self.step_results:
            latest_args[result["id"]] = result["args"]   # a step run more than once keeps its latest

        steps = []
        for step in self.plan["steps"]:
            if step["tool"] in ("read_issue", "post_comment"):
                continue                                 # the issue goes first; the comment is the draft itself
            if step["id"] in self.results:
                steps.append({"tool": step["tool"], "args": latest_args.get(step["id"], {}),
                              "result": self.results[step["id"]]})
        return {"issue": self.issue_text(), "steps": steps}

    def rewrite_draft(self, draft: str, reason: str | None) -> str:
        """One model call that rewrites the draft with the reason. No tools: the model answers with the new draft."""
        evidence = self.build_evidence()
        parts = ["The issue:\n" + evidence["issue"]]
        for item in evidence["steps"]:
            parts.append(f"{item['tool']} {json.dumps(item['args'])}:\n{str(item['result'])[:4000]}")
        parts.append("Files this run saw (a search returned them or a step read them):\n"
                     + "\n".join(self.seen_paths()))
        parts.append("The draft comment:\n" + draft)
        parts.append("Why it must be rewritten:\n" + str(reason))
        parts.append("Rewrite the draft comment. Reply with the new comment only.")

        self.model_step += 1
        response = self.ctx.client.create(
            system=self.ctx.prompt("rewrite.md"),
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
        )
        self.ctx.trace.model_call(self.model_step, response, purpose="critique")

        new_draft = response.text.strip().strip("`").strip()
        if not new_draft:
            return draft                                 # an empty answer keeps the draft
        return new_draft

    def seen_paths(self) -> list[str]:
        """The paths this run has seen: those a search returned or a step read."""
        paths = []
        for result in self.step_results:
            for path in result["paths"]:
                if path not in paths:
                    paths.append(path)
        return paths

    # ---------- Hooks for ways/notes.py to override ----------
    def escalate(self, detail: str) -> None:
        """Hand the issue to a person. Part G overrides it to ask its questions first."""
        self.ctx.trace.end("escalated", detail)

    def after_step(self, step: dict, result) -> None:
        """After every step that ran. Part G writes its progress file here."""
        pass


def run(ctx) -> None:
    plan = get_valid_plan(ctx)
    if plan is None:
        ctx.trace.end("escalated", f"no valid plan after {MAX_REPLANS + 1} attempts")
        return

    ctx.trace.plan(1, plan)                  # before the first tool call

    executor = Executor(ctx, plan)
    executor.run()
