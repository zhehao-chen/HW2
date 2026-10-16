"""Assignment 2, Part D: the second pass before posting. This file is yours.

Two ways to read a drafted comment before it is posted (Lecture 2, slides 31 to 34).
The checker runs your planned way in each mode against scripted models, so keep
these exact signatures (checks/FORMATS.md, section 10.2). You may add keyword
arguments with defaults; the checker passes only these.

    verify(draft, ctx) -> {"passed": bool, "reasons": [str, ...]}

        The external mode: checks in code, against the repository and this run's
        own record. Four checks:
          1. the draft parses: a `label:` line with a known label, and a `file:`
             line with a path or none (section 1; harness.formats.parse_triage_comment);
          2. a path it names exists in the repository (ctx.root / "fixtures" / "repo");
          3. this run saw that path: a search_repo result or a read_file call in this
             run's trace returned it. Each tool_call line's `paths` field lists the
             files it returned; read the trace so far with
             harness.trace.read_trace(ctx.trace.path);
          4. the label and the file agree: a question names none, and every other
             label names a file.
        "reasons" says why each failed check failed; it is empty when all pass.
        verify reads only what the run itself can see: never the answer key, and
        never Assignment 1's grounded check in eval/. The checker flags a second
        pass that does.

    self_critique(client, draft, evidence, trace=None) -> {"decision": "accept" | "revise", "reason": str | None}

        The self mode: one model call that rereads the draft, given the issue and
        what the run's steps returned (`evidence`, a dict of your design), and
        accepts it or asks for a revision with a reason. Given a trace, trace the
        call: trace.model_call(n, response, purpose="critique").

    draft   the comment your executor drafted, the text post_comment would post
    ctx     the run's harness.runner.WayContext
    client  harness.client.ModelClient

The loop that uses them, its rewrite call and MAX_ROUNDS live in ways/planned.py.
Keep your prompts in prompts/.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.formats import LABELS, parse_triage_comment
from harness.trace import read_trace

ROOT = Path(__file__).resolve().parent.parent
CRITIC_PROMPT = "prompts/critic.md"
RESULT_LIMIT = 4000          # the most characters of each step's result the model is shown (a file can be long)

# The verdict comes back through a tool. Its "decision" enum holds "accept", which is how the checker's scripted models recognise a self critique
VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Accept the draft comment, or ask for it to be revised and say why.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["accept", "revise"]},
            "reason": {"type": ["string", "null"]},
        },
        "required": ["decision", "reason"],
        "additionalProperties": False,
    },
    "strict": True,
}


def verify(draft: str, ctx) -> dict:
    reasons = []
    label, file = parse_triage_comment(draft)        # e.g. ("bug", "src/a.ts"); a missing line is None

    # 1. Parses: a known label, and a file line
    if label not in LABELS or file is None:
        reasons.append("the draft does not parse: its first two lines must be "
                       "'label: <bug | feature | question | docs>' and 'file: <path or none>'")
        return {"passed": False, "reasons": reasons}  # unparsable: the other three checks cannot run

    if file != "none":
        # 2. Exists
        repo_path = ctx.root / "fixtures" / "repo" / file
        if not repo_path.is_file():
            reasons.append(f"the file {file} does not exist in the repository")

        # 3. Seen: some tool_call line of this run has it in its paths (a search returned it, or a step read it)
        seen = set()
        for record in read_trace(ctx.trace.path):
            if record.get("type") == "tool_call":
                for path in record.get("paths") or []:
                    seen.add(path)
        if file not in seen:
            reasons.append(f"this run never saw {file}: no search returned it and no step read it")

    # 4. Agrees: a question names none, and every other label names a file
    if label == "question" and file != "none":
        reasons.append(f"a question names no file, but the draft names {file}")
    if label != "question" and file == "none":
        reasons.append(f"a {label} must name the file to change, but the draft names none")

    return {"passed": len(reasons) == 0, "reasons": reasons}


def self_critique(client, draft: str, evidence: dict, trace=None, step: int = 0) -> dict:
    """evidence: {"issue": the issue's text, "steps": [{"tool", "args", "result"}, ...]},
    which is what the model that wrote the draft could see, and nothing new."""
    system = (ROOT / CRITIC_PROMPT).read_text()

    step_lines = []
    for item in evidence.get("steps", []):
        result = str(item.get("result", ""))
        if len(result) > RESULT_LIMIT:
            result = result[:RESULT_LIMIT] + "\n... (cut)"
        step_lines.append(f"{item.get('tool')} {json.dumps(item.get('args', {}))}:\n{result}")

    message = (
        "The issue:\n" + str(evidence.get("issue", "")) + "\n\n"
        "What the run found:\n" + "\n\n".join(step_lines) + "\n\n"
        "The draft comment:\n" + draft
    )

    response = client.create(system=system,
                             messages=[{"role": "user", "content": message}],
                             tools=[VERDICT_TOOL])
    if trace is not None:
        trace.model_call(step, response, purpose="critique")

    for call in response.tool_calls:
        if call.name == "submit_verdict":
            decision = call.input.get("decision")
            reason = call.input.get("reason")
            if decision == "accept":
                return {"decision": "accept", "reason": None}
            if decision == "revise":
                return {"decision": "revise", "reason": reason or "the critic asked for a revision"}

    # No verdict: accept, rather than rewrite a draft that may be right on the strength of a check that did not answer
    return {"decision": "accept", "reason": None}
