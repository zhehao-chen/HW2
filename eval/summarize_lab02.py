"""Assignment 2's results script: builds Part F's table and Part G's context entries
from runs/ and the tracker, and writes them into reports/LAB_02.json.

    python -m eval.summarize_lab02            # print the tables, and write the JSON
    python -m eval.summarize_lab02 --dry-run  # print only

Part F (checks/FORMATS.md, section 10.10, "results"): every finished run of this lab
(run_start.lab == "02") on the six evaluation issues, from a real backend, grouped
into agent, planned_off, planned_self and planned_external. A run passes by
Assignment 1's grounded check (eval/check_triage.check), read from the comments
that carry its run_id.

Part G ("context"): every finished --way notes run on 4203, 4204 and 4206. Each
question's truth comes from the trace, never from the model: a path was seen when a
tool_call line above the question has it in its paths.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml

from eval.check_triage import check
from harness import ROOT
from harness.backends import REAL_BACKENDS
from harness.formats import UNFINISHED, normalize_path, parse_triage_comment
from harness.trace import read_trace
from harness.tracker import Tracker

LAB = "02"
CONFIGS = ("agent", "planned_off", "planned_self", "planned_external")
NOTES_ISSUES = (4203, 4204, 4206)


# -- reading runs -------------------------------------------------------------------

def configuration(start: dict) -> str | None:
    if start.get("way") == "agent":
        return "agent"
    if start.get("way") == "planned":
        return "planned_" + (start.get("critique") or "off")
    return None


def finished_runs() -> list[dict]:
    """Every finished run of this lab on a real backend, with its records."""
    runs = []
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        records = read_trace(path)
        if not records or records[0].get("type") != "run_start" or records[-1].get("type") != "run_end":
            continue
        start = records[0]
        if start.get("lab") != LAB or start.get("backend") not in REAL_BACKENDS:
            continue
        if any(r.get("type") == "end" and r.get("terminal_reason") in UNFINISHED for r in records):
            continue
        runs.append({"run_id": start["run_id"], "way": start.get("way"), "issue": start["issue"],
                     "sweep": start["sweep"], "critique": start.get("critique") or "off",
                     "notes": start.get("notes") or "off", "records": records})
    return runs


# -- Part F ---------------------------------------------------------------------------

def model_calls(run: dict) -> list[dict]:
    return [r for r in run["records"] if r.get("type") == "model_call"]


def prompt_share(run: dict, purposes: tuple) -> float:
    calls = model_calls(run)
    total = sum(c["usage"]["prompt_tokens"] for c in calls)
    if total == 0:
        return 0.0
    part = sum(c["usage"]["prompt_tokens"] for c in calls if c.get("purpose") in purposes)
    return part / total


def has_exact_repeat(run: dict) -> bool:
    seen = set()
    for r in run["records"]:
        if r.get("type") == "tool_call":
            key = json.dumps([r.get("name"), r.get("input") or {}], sort_keys=True)
            if key in seen:
                return True
            seen.add(key)
    return False


def draft_is_right(body: str | None, answer: dict) -> bool:
    label, file = parse_triage_comment(body or "")
    return label == answer["label"] and file == normalize_path(answer["file"])


def mean(values: list) -> float | None:
    return sum(values) / len(values) if values else None


def nearest_rank_median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-len(ordered) // 2) - 1)]


def summarize(config: str, runs: list[dict], answers: dict, tracker: Tracker) -> dict:
    planned = config != "agent"
    second = config in ("planned_self", "planned_external")
    per_issue = {str(i): 0 for i in sorted(answers)}
    per_sweep = defaultdict(int)
    tokens, latency, plan_shares, critique_shares, revisions, rounds = [], [], [], [], [], []
    changed = fixed = broken = held = 0

    for run in runs:
        answer = answers[run["issue"]]
        ok = check(tracker, run["run_id"], run["issue"], answer)
        run["passed"] = ok
        per_issue[str(run["issue"])] += ok
        per_sweep[run["sweep"]] += ok

        calls = model_calls(run)
        tokens.append(sum(c["usage"]["prompt_tokens"] + c["usage"]["output_tokens"] for c in calls))
        latency.append(run["records"][-1].get("elapsed_s") or 0.0)
        plan_shares.append(prompt_share(run, ("plan", "revise")))
        critique_shares.append(prompt_share(run, ("critique",)))
        revisions.append(sum(1 for r in run["records"] if r.get("type") == "revision"))

        lines = [r for r in run["records"] if r.get("type") == "critique"]
        rounds.append(len(lines))
        if any(line.get("changed") for line in lines):
            changed += 1
            first_right = draft_is_right(lines[0].get("draft"), answer)
            fixed += (not first_right) and ok
            broken += first_right and not ok
        if lines and lines[-1].get("result") == "fail" and not tracker.comments(run_id=run["run_id"]):
            held += 1

    sweeps = sorted(per_sweep) if runs else []
    return {
        "runs": len(runs),
        "passes": sum(per_issue.values()),
        "per_issue": per_issue,
        "sweep_min": min((per_sweep[s] for s in sweeps), default=None),
        "sweep_max": max((per_sweep[s] for s in sweeps), default=None),
        "mean_tokens": mean(tokens),
        "p50_latency_s": nearest_rank_median(latency),
        "max_latency_s": max(latency, default=None),
        "plan_overhead_share": mean(plan_shares) if planned else None,
        "critique_overhead_share": mean(critique_shares) if second else None,
        "runs_with_repeat": sum(has_exact_repeat(run) for run in runs),
        "off_plan": sum(1 for run in runs for r in run["records"] if r.get("type") == "off_plan") if planned else None,
        "revisions_mean": mean(revisions) if planned else None,
        "revisions_max": max(revisions, default=None) if planned else None,
        "rounds_mean": mean(rounds) if second else None,
        "rounds_max": max(rounds, default=None) if second else None,
        "drafts_changed": changed if second else None,
        "drafts_fixed": fixed if second else None,
        "drafts_broken": broken if second else None,
        "drafts_held": held if second else None,
    }


def plan_share_by_length(runs: list[dict]) -> dict:
    """The plan call's share of prompt tokens alone, grouped by the run's number of model calls."""
    groups = defaultdict(list)
    for run in runs:
        calls = model_calls(run)
        groups[len(calls)].append(prompt_share(run, ("plan",)))
    return {n: (len(shares), mean(shares)) for n, shares in sorted(groups.items())}


def schema_lines(runs: list[dict]) -> tuple[int, int]:
    """Plans that broke the schema or the post_comment rule (schema lines), out of all plans written."""
    broke = plans = 0
    for run in runs:
        for r in run["records"]:
            if r.get("type") == "schema":
                broke += 1
            if r.get("type") == "model_call" and r.get("purpose") in ("plan", "revise"):
                plans += 1
    return broke, plans


# -- Part G ---------------------------------------------------------------------------

def context_entry(run: dict) -> dict:
    seen = set()
    compacted = False
    asked = False
    questions = []
    for r in run["records"]:
        if r.get("type") == "tool_call":
            for path in r.get("paths") or []:
                seen.add(path)
        elif r.get("type") == "compaction" and not asked:
            compacted = True
        elif r.get("type") == "question":
            asked = True
            truth = "yes" if r["path"] in seen else "no"
            questions.append({"path": r["path"], "truth": truth, "answer": r["answer"]})
    return {
        "run_id": run["run_id"],
        "issue": run["issue"],
        "notes_shown": run["notes"] == "on",
        "compacted": compacted,
        "questions": questions,
        "right": sum(1 for q in questions if q["answer"] == q["truth"]),
    }


def notes_tokens(run: dict) -> int:
    """How many prompt tokens the progress file added: its characters / 4, times the calls that showed it."""
    progress = ROOT / "runs" / f"{run['run_id']}.progress.json"
    if run["notes"] != "on" or not progress.exists():
        return 0
    shown_calls = sum(1 for c in model_calls(run) if c.get("purpose") in ("execute", None))
    return shown_calls * (len(progress.read_text()) // 4)


# -- output ---------------------------------------------------------------------------

def fmt(value, digits=2) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print the tables, do not write reports/LAB_02.json")
    args = parser.parse_args()

    answers = {int(k): v for k, v in yaml.safe_load((ROOT / "fixtures/answers.yaml").read_text())["eval"].items()}
    tracker = Tracker(ROOT)
    runs = finished_runs()

    by_config = {config: [] for config in CONFIGS}
    for run in runs:
        config = configuration(run)
        if config in by_config and run["issue"] in answers:
            by_config[config].append(run)
    results = {config: summarize(config, by_config[config], answers, tracker) for config in CONFIGS}

    notes_runs = [run for run in runs if run["way"] == "notes" and run["issue"] in NOTES_ISSUES]
    context = [context_entry(run) for run in notes_runs]

    # Part F's table
    print("Part F")
    print("| Measure | Agent | Planned, off | Planned, self | Planned, external |")
    print("|---|---|---|---|---|")
    rows = [
        ("Passes, of 18", lambda r: fmt(r["passes"])),
        ("Per issue, 4201 to 4206, of 3 each", lambda r: " ".join(str(r["per_issue"][str(i)]) for i in sorted(answers))),
        ("Spread: lowest and highest sweep, of 6", lambda r: f"{fmt(r['sweep_min'])} to {fmt(r['sweep_max'])}"),
        ("Tokens per run", lambda r: fmt(r["mean_tokens"], 0)),
        ("Latency per run: median, slowest (s)", lambda r: f"{fmt(r['p50_latency_s'], 1)}, {fmt(r['max_latency_s'], 1)}"),
        ("Plan overhead: mean share of prompt tokens", lambda r: fmt(r["plan_overhead_share"])),
        ("Second-pass overhead: mean share", lambda r: fmt(r["critique_overhead_share"])),
        ("Runs with at least one exact repeat", lambda r: fmt(r["runs_with_repeat"])),
        ("off_plan lines", lambda r: fmt(r["off_plan"])),
        ("Revisions per run: mean, max", lambda r: "" if r["revisions_mean"] is None
            else f"{fmt(r['revisions_mean'])}, {r['revisions_max']}"),
        ("Second-pass rounds per run: mean, max", lambda r: "" if r["rounds_mean"] is None
            else f"{fmt(r['rounds_mean'])}, {r['rounds_max']}"),
        ("Drafts changed; fixed, broken", lambda r: "" if r["drafts_changed"] is None
            else f"{r['drafts_changed']}; {r['drafts_fixed']}, {r['drafts_broken']}"),
        ("Drafts held at the bound", lambda r: fmt(r["drafts_held"])),
    ]
    for label, cell in rows:
        print(f"| {label} | " + " | ".join(cell(results[c]) for c in CONFIGS) + " |")
    for config in CONFIGS:
        print(f"  {config}: {results[config]['runs']} finished runs (complete at 18, 3 per issue)")

    planned_runs = [run for c in CONFIGS[1:] for run in by_config[c]]
    print("\nThe plan call's share of prompt tokens, by the run's number of model calls (runs, mean share):")
    for n, (count, share) in plan_share_by_length(planned_runs).items():
        print(f"  {n:2d} calls: {count:2d} runs, {fmt(share)}")
    broke, plans = schema_lines(planned_runs)
    print(f"\nschema lines in the planned runs: {broke} of {plans} plans and revisions")

    # Part G's table
    print("\nPart G")
    print("| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |")
    print("|---|---|---|---|---|")
    for entry, run in zip(context, notes_runs):
        print(f"| {entry['run_id']} | {entry['issue']} | {'yes' if entry['notes_shown'] else 'no'} | "
              f"{'yes' if entry['compacted'] else 'no'} | {entry['right']} |")
        if run["notes"] == "on":
            print(f"    progress file: about {notes_tokens(run)} prompt tokens over the run")
    print(f"  {len(context)} notes runs (complete at 12: 2 per issue per --notes setting)")

    if not args.dry_run:
        path = ROOT / "reports" / "LAB_02.json"
        report = json.loads(path.read_text())
        report["results"] = results
        report["context"] = context
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nwrote results and context into {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
