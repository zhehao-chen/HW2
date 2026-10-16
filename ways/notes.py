"""Way 6, notes: the planned way with a progress file and a compaction. This file is yours.

Assignment 2, Part G. Your planned way with the second pass off, plus two things,
so that Part F's configurations stay as they were (checks/FORMATS.md, section 10):

    python run.py --way notes --notes off --issues 4203,4204,4206 --runs 2
    python run.py --way notes --notes on --issues 4203,4204,4206 --runs 2

  1. A progress file, ctx.progress_path (runs/<run_id>.progress.json): JSON outside
     the conversation, written after every step, holding at least
       "steps_done"  the ids of the steps that have run, in order
       "paths"       every path a search returned or a read read, in order
     and never a search term: terms come from the issue's text. Say in the file what
     it records (an "about" line, or labelled keys): a bare list of paths can be read
     as a to-do list. With ctx.notes == "on", every executor call and the questions'
     call after its first write show the model the file's text, exactly as written
     (not the planner, not the reviser). With "off", it is still written, and never
     shown.
  2. A history and a compaction: every model call sees the run's history so far,
     its step results oldest first. Once that history passes COMPACT_AT tokens, the
     oldest entries become a model-written summary and the recent ones stay as
     they were. Write ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=...)
     each time. It runs whatever ctx.notes says. A low threshold is a test setting
     here, not advice.

Then, at the end of the run, however it ended (comment posted, escalated, halted),
one model call asks six closed questions, each "Has this run seen `<path>`: did a
search return it, or did you read it?", and returns six answers, yes or no: about
the three earliest paths the run saw (its tool_call lines returned them; all of
them, if it saw fewer), and paths it did not see for the rest. If the run has not
compacted yet, compact its history once first. Write each answer as
ctx.trace.event("question", path=..., answer=...), the six together.

Part G's 12 runs are the ones on issues 4203, 4204 and 4206; a notes run on a
development issue is development, and reports/LAB_02.json's context leaves it out.
"""

from __future__ import annotations

import json
import re
from harness.scripted import estimate_tokens

from ways.planned import Executor, get_valid_plan, MAX_REPLANS

COMPACT_AT = 600    # tokens: an issue is about 100, a 20-hit search about 400, a file 300 to 700, so a run compacts once it reads a file
KEEP_RECENT = 1     # a compaction keeps only the latest entry: the issue and the search go into the summary, so the earliest paths are the first lost
QUESTIONS = 6

# Files to fill the six questions with paths the run did not see: real repository files, unrelated to 4203, 4204 and 4206.
# Taken in order, skipping any this run happened to see
UNSEEN_CANDIDATES = [
    "src/util/money.ts",
    "src/util/pagination.ts",
    "src/util/retry.ts",
    "src/logger.ts",
    "src/components/UploadForm.tsx",
    "src/config.ts",
    "src/util/strings.ts",
    "docs/CONFIG.md",
]


class NotesExecutor(Executor):
    """The planned way's executor, with a progress file, a history and its compaction, and six questions."""

    def __init__(self, ctx, plan: dict):
        super().__init__(ctx, plan)               # Executor's own setup first
        self.steps_done = []                      # ids of the steps that have run, in order
        self.paths = []                           # paths a search returned or a step read, in order, without repeats
        self.history = []                          # [{"step", "tool", "args", "result"}, or {"summary"}]
        self.compacted = False
        self.asked = False                         # whether the six questions were asked (once a run)

    # ---------- The progress file ----------

    def after_step(self, step: dict, result) -> None:
        """After every step that ran: update the history, compact if due, and write the progress file."""
        self.steps_done.append(step["id"])              # this step's id

        latest = self.step_results[-1]            # the result Executor.run_step just recorded
        for path in latest["paths"]:                         # the paths this step returned
            if path not in self.paths:
                self.paths.append(path)

        # The history lives in the conversation, so it may hold search terms; the progress file may not
        self.history.append({
            "step": step["id"],
            "tool": step["tool"],
            "args": latest["args"],
            "result": result.content,
        })
        self.maybe_compact()

        self.write_progress()

    def write_progress(self) -> None:
        progress = {
            "about": ("What this run has already done, not what is left to do: steps_done lists "
                      "the plan steps that have run, in order; paths lists every file a search "
                      "returned or a step read, in order. A path here has been seen."),
            "steps_done": self.steps_done,
            "paths": self.paths,
        }
        self.ctx.progress_path.write_text(json.dumps(progress, indent=2))

    # ---------- The history and its compaction ----------

    def history_tokens(self) -> int:
        return estimate_tokens(self.history)

    def maybe_compact(self, force: bool = False) -> None:
        """Compact the history once it passes COMPACT_AT. force=True compacts whatever its size (before the questions)."""
        tokens = self.history_tokens()
        if not force and tokens <= COMPACT_AT:
            return

        older = self.history[:-KEEP_RECENT]          # all but the latest KEEP_RECENT entries
        recent = self.history[-KEEP_RECENT:]         # the latest KEEP_RECENT entries, kept as they are
        if not older and force:
            older, recent = self.history, []         # forced, but too short to split: compact it all, so every run compacts before its questions
        elif not older:
            return                                   # nothing to compact

        summary = self.summarize(older)
        self.history = [{"summary": summary}] + recent
        self.compacted = True
        self.ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=tokens,
                             entries_summarized=len(older))

    def summarize(self, entries: list[dict]) -> str:
        """One model call that summarizes the older entries."""
        self.model_step += 1
        response = self.ctx.client.create(
            system=self.ctx.prompt("compact.md"),
            messages=[{"role": "user", "content": "The steps to summarize:\n\n"
                       + (self.entries_text(entries) or "(no step has run yet)")}],
        )
        self.ctx.trace.model_call(self.model_step, response, purpose=None)   # a compaction is none of plan, revise, execute or critique
        return response.text

    def entries_text(self, entries: list[dict]) -> str:
        """History entries as text for the model, oldest first."""
        lines = []
        for entry in entries:
            if "summary" in entry:
                lines.append("Summary of earlier steps:\n" + entry["summary"])
            else:
                lines.append(f"Step {entry['step']}, {entry['tool']} {json.dumps(entry['args'])}:\n{entry['result']}")
        return "\n\n".join(lines)

    def history_text(self) -> str:
        return self.entries_text(self.history)

    def build_messages(self, step: dict, args: dict) -> list[dict]:
        """Every executor call sees the history, and with --notes on the progress file's text as written."""
        messages = super().build_messages(step, args)       # the messages Executor builds
        extra = "The run's history so far, oldest first:\n" + (self.history_text() or "(nothing yet)")
        if self.ctx.notes == "on" and self.ctx.progress_path.exists():
            extra += "\n\nThe run's progress file:\n" + self.ctx.progress_path.read_text()   # exactly as written
        messages[0]["content"] = extra + "\n\n" + messages[0]["content"]
        return messages

    # ---------- The six questions ----------

    def run_step(self, step: dict) -> bool:
        if step["tool"] == "post_comment" and not self.asked:
            self.ask_questions()                     # before the comment is drafted
        return super().run_step(step)

    def escalate(self, detail: str) -> None:
        if not self.asked:
            self.ask_questions()                     # ending early: ask first, then end
        super().escalate(detail)

    def question_paths(self) -> list[str]:
        """The three earliest paths the run saw (all of them, if fewer), then unseen ones to make six."""
        seen = self.paths[:3]
        unseen = []
        for path in UNSEEN_CANDIDATES:
            if path not in self.paths and len(seen) + len(unseen) < QUESTIONS:
                unseen.append(path)
        return seen + unseen

    def ask_questions(self) -> None:
        self.asked = True
        if not self.compacted:
            self.maybe_compact(force=True)           # not compacted yet: compact once first

        paths = self.question_paths()
        lines = []
        for number, path in enumerate(paths, start=1):
            lines.append(f"{number}. Has this run seen {path}: did a search return it, or did you read it?")

        # Keep rewrite, draft and comment out of this message: the checker's scripted model answers them with a comment
        content = "The run's history so far, oldest first:\n" + (self.history_text() or "(nothing yet)")
        if self.ctx.notes == "on" and self.ctx.progress_path.exists():
            content += "\n\nThe run's progress file:\n" + self.ctx.progress_path.read_text()   # exactly as written
        content += ("\n\nAnswer each question with yes or no, one line each, as '1: yes'.\n"
                    + "\n".join(lines))

        self.model_step += 1
        response = self.ctx.client.create(
            system=self.ctx.prompt("questions.md"),
            messages=[{"role": "user", "content": content}],
        )                                            # no tools: the model answers in text
        self.ctx.trace.model_call(self.model_step, response, purpose=None)   # Part G's questions have purpose None

        answers = self.parse_answers(response.text, len(paths))
        for path, answer in zip(paths, answers):
            self.ctx.trace.event("question", path=path, answer=answer)

    def parse_answers(self, text: str, count: int) -> list[str]:
        """Read count yes or no answers from the reply: one per "1: yes" line; a reply of one bare yes or no answers them all; anything unread is no."""
        answers = ["no"] * count
        found = False
        for line in text.splitlines():
            match = re.match(r"\s*(\d+)\s*[:.)\-]\s*(yes|no)\b", line, re.IGNORECASE)
            if match:
                number = int(match.group(1))
                if 1 <= number <= count:
                    answers[number - 1] = match.group(2).lower()
                    found = True
        if not found:
            words = re.findall(r"\b(yes|no)\b", text, re.IGNORECASE)
            if len(words) == 1:
                answers = [words[0].lower()] * count
        return answers

    # Part G runs with the second pass off
    def before_comment(self, draft: str) -> str | None:
        return draft


def run(ctx) -> None:
    plan = get_valid_plan(ctx)
    if plan is None:
        # a run with no valid plan still compacts and asks, through an executor with no steps
        NotesExecutor(ctx, {"steps": []}).escalate(f"no valid plan after {MAX_REPLANS + 1} attempts")
        return

    ctx.trace.plan(1, plan)
    executor = NotesExecutor(ctx, plan)
    executor.run()
