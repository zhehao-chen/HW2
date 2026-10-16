# Assignment 2 report · A plan RepoMind cannot quietly abandon

Every number here that has a field in `reports/LAB_02.json` goes there too: the checker reads that file (format: `checks/FORMATS.md`, section 10.10). Give each number its run count. Mark any vendor figure you cite with its source and the date you read it.

## Part A · The plan artifact
Your `args` choice, `args_json` or one shape per tool with `oneOf`, and why, in two sentences. Your strict-mode count, in two sentences: optional fields and union types against the budgets of 24 and 16, and whether a strict request carrying the schema was accepted (or that your vendor has no strict mode).

**Args.** I chose `args_json`: each step's arguments are one JSON object encoded as a string, which the executor parses and checks against the named tool's `input_schema` before the call. One shape per tool with `oneOf` would spend at least two union types (the `oneOf` itself, and `search_repo`'s optional `max_results` made nullable) and put the four tools' argument lists into the plan schema, while `args_json` keeps the schema at one plain string field.

**Strict-mode count.** `agent/plan_schema.json` has 0 optional fields (budget 24) and 0 union types (budget 16): every field is required and none is nullable, with 8 object properties and 5 levels of nesting against OpenAI's 5,000 and 10 (limits as given in the assignment, read by the course on 30 September 2026). My vendor is OpenAI (`gpt-4o-mini`), which has a strict mode, and the planner's `submit_plan` tool is marked `"strict": true`, and requests carrying it were accepted: both planner calls in my first two development runs (14 October 2026) came back as `submit_plan` calls from `gpt-4o-mini-2024-07-18`.

## Part B · The validator and the boundary

| Plan | Valid | Failures (step, check) |
|---|---|---|
| `good_export_fix.json` | yes | none |
| `good_triage.json` | yes | none |
| `s18_specimen.json` | no | (2, 2), (3, 3), (5, 1); check 4 passes |

Your re-plan bound, `MAX_REPLANS`, and one line on why. How many of your planner's plans, in your measured runs, broke the schema or did not end with `post_comment` (your `schema` lines), out of how many plans.

**Re-plan bound.** `MAX_REPLANS = 2`, so a run makes at most three planner calls before it escalates: a model that writes one bad plan usually writes a good one when asked again, and one that fails three times in a row will not be fixed by a fourth call, only billed for it.

**Before the four checks.** Each plan is checked against `agent/plan_schema.json` with `harness.schema.errors`, then in code: every `args_json` parses to a JSON object, `"$fill"` is a whole value and never part of one, the comment's `body` is `"$fill"`, and the last step is `post_comment`. The two `$fill` rules come from my first two development runs: both plans wrote the body as `"label: bug\nfile: $fill"`, fixing a label before the issue was read, and one of them posted that text unfilled. A plan that breaks any of these writes a `schema` line and is re-planned against `MAX_REPLANS`.

**What the executor's fill call sees.** The issue, then the result of every step the current step lists in `depends_on`, then the step's `action`, its tool and its arguments with the `"$fill"` values marked; it is offered that step's tool alone. The issue is always included because every fill depends on it and a planner that never saw the issue may leave it out of `depends_on`. Values the plan fixes, such as the issue number, are taken from the plan, not from the model's call.

**Schema lines.** In my 54 measured planned runs, 7 of the 107 plans and revisions the planner and reviser wrote broke the schema or the plan rules, and were rejected before they ran.

## Part C · Revision at a checkpoint
The checkpoint's check, in one sentence, and your revision bound, `MAX_REVISIONS`.

**The check.** After the first search step, and after any search step a revision adds or changes, the search passes only if it returned at least one source file, a `.ts` or `.tsx` path under `src/`; a search with no results, or only documentation, changelog, test or translation files, fails, and the step is marked `failed` with the error code `no_matches` or `no_source`.

**The bound.** `MAX_REVISIONS = 3`, accepted and rejected alike: in development the reviser's first attempt was sometimes rejected (it wrote a fixed search query instead of `"$fill"`), so three leaves two usable revisions after a rejection, and a search that has failed four times will not be rescued by a fifth.

The check passes on any source file, relevant or not: in one development run on 4192 a search for `export` returned only `src/api/auth.ts` among its source files, the check passed, and the run went on with the wrong file. It catches a search that found no code, not one that found the wrong code.

## Part D · A second pass before posting
Your four external checks, one line each, and your bound, `MAX_ROUNDS`, in one line. For each mode, `off`, `self` and `external`, which of slide 41's three gates it passes: can a check find the error, does the critic know more than the agent, is there a limit and a log?

**The four external checks** (`verify` in `agent/critique.py`, code only, no model call):
1. *Parses*: the draft has a `label:` line with one of the four labels and a `file:` line with a path or `none`.
2. *Exists*: a path it names is a file under `fixtures/repo`.
3. *Seen*: that path is in the `paths` of one of this run's `tool_call` lines, so a search returned it or a step read it.
4. *Agrees*: a `question` names `none`, and every other label names a file.

A draft naming `none` skips checks 2 and 3. Each failed check gives a reason that names the file or label, and that reason is what the rewrite is given.

**The bound.** `MAX_ROUNDS = 2` in both modes: check, rewrite once with the reason, check the new draft, and hold it (no comment, the run ends escalated) if it still fails; one comment at most per run.

**Slide 41's three gates**, laid out as slide 42 lays out its three loops.

| | `off` | `self` | `external` |
|---|---|---|---|
| The loop | none: the draft is posted as written | the same model rereads its draft with the issue and the step results, accepts or asks for a rewrite, at most twice | `verify` checks the draft in code, a failure is rewritten with its reason, at most twice |
| Can a check find the error? | no: nothing checks | only as an opinion: no test tells a better label from a worse one | yes, for the errors its four checks cover: a malformed draft, a missing or unseen file, a label that contradicts its file; not a wrong file the run did see |
| Does the critic know more? | no critic | no: it is the author, with the same evidence | yes: the repository's files and this run's own trace |
| Is there a limit and a log? | no second pass to limit or log | yes: two rounds, a `critique` line each | yes: two rounds, a `critique` line each |
| Verdict | no reflection | fails the first two gates: critique, not verification, so it may help or hurt | passes all three for the errors it can see: verification |

In my development runs (one run per issue and mode, so examples, not results): `external` caught 4191's `question` with `file: README.md`, and the rewrite became `docs`, `README.md`, the right answer; it passed 4192's `bug`, `docs/API.md`, a file the run had seen but not the one at fault. `self` also rejected 4191's `question`, but asked for `bug`, and the rewrite was still wrong.

## Part E · Detectors and the diff
How your diff matches a traced call to a plan step.

**The looping run.** Questions 1 to 3, each with the turns or steps that fired, and how you answered question 2 without `depends_on`. Question 4, in one sentence.

**Slide 51's run.** Questions 1 to 3, each with the steps that fired. Question 4, in one sentence. The diff's label for every step of the plan.

**How a call matches a step** (`match_calls` in `agent/diff.py`). A `tool_call` line with a `plan_step` matches that step: my executor writes it on every call. A line without one, as in `fixtures/traces/`, matches the first step, in plan order, that no call has matched yet, whose `tool` is the call's `name`, and whose fixed arguments (every argument not written `"$fill"`) all equal the call's; when several fit, the one with the most fixed arguments wins. Each step takes one call at most, so a repeat of a matched call is `extra`. That is what separates slide 51's two `run_tests` calls: the first has no arguments and fits only step 1; the second carries `test: test_export_csv`, which step 5 fixes and step 1, already matched, does not. A step is `reordered` when its call comes before the call of a step earlier in the plan.

**The looping run.**
- Q1 fires: tool calls 1 and 3 (`search("export")` twice) and 2 and 4 (`read(ReportsPage.tsx)` twice).
- Q2 fires, on tool calls 1 and 2, judged from the trace: the plan has no `depends_on` and the results name no paths ("247 results"), so I counted a call as unused when the agent made the identical call again later. It fetched the same thing a second time rather than use what it had.
- Q3 fires on plan steps 3, 4, 5 and 6: nothing ran "identify the bug" (it has no tool), and the run hit its turn limit before edit, run_tests and open_pr. Calls 3 to 6 match no step: the repeats, and a search for `exportButton` that the plan, fixed on `export`, never named.
- Q4: The plan fit the task's shape, find, read, fix, verify, open a PR, but not its substance: it fixed the search term to the broad `export` (247 results) and gave "identify the bug" no tool and no expected result, so nothing told the run when a step had worked.

**Slide 51's run.**
- Q1 fires: tool calls 2 and 4, `search_repo("export")` twice.
- Q2 does not fire: every step but the last is in a later step's `depends_on`.
- Q3 fires on step 6, "confirm the button works": no `browse` call was made.
- Q4: The plan matched the task, but the run did not finish it: step 5 ran, so the expected-result check passes it, yet it returned "1 failing: test_export_csv" where the plan expected a pass, and the agent reported "fixed the export handler" anyway. My check asks whether a step ran without an error, not whether its result matched `expected_result`.
- The diff: steps 1 to 5 `executed`, step 6 `skipped`; `extra` is tool call 4, the repeated search.

## Part F · What the plan and the second pass bought
Three sweeps a configuration: a pilot, not a settled difference.

| Measure | Agent | Planned, off | Planned, self | Planned, external |
|---|---|---|---|---|
| Passes, of 18 | 8 | 4 | 3 | 6 |
| Per issue, 4201 to 4206, of 3 each | 2, 0, 3, 0, 3, 0 | 3, 0, 0, 0, 1, 0 | 3, 0, 0, 0, 0, 0 | 3, 0, 0, 0, 3, 0 |
| Spread: the lowest and highest sweep, of 6 | 2 to 3 | 1 to 2 | 1 to 1 | 2 to 2 |
| Tokens per run | 8,718 | 6,537 | 9,455 | 7,109 |
| Latency per run: median, and slowest | 7.6 s, 10.9 s | 8.4 s, 14.9 s | 9.5 s, 19.0 s | 7.6 s, 13.6 s |
| Plan overhead: the mean share of prompt tokens, and how it changes with run length | | 0.28 | 0.19 | 0.27 |
| Second-pass overhead: the mean share of prompt tokens | | | 0.32 | 0.07 |
| Runs with at least one exact repeat | 2 | 2 | 0 | 0 |
| `off_plan` lines | | 0 | 0 | 0 |
| Revisions per run: mean, and maximum | | 1.00, 3 | 0.72, 3 | 0.89, 3 |
| Second-pass rounds per run: mean, and maximum | | | 1.39, 2 | 1.28, 2 |
| Drafts changed; of those fixed, and broken | | | 7; 0, 0 | 6; 1, 0 |
| Drafts held at the bound | | | 8 | 0 |

18 finished runs per configuration, 3 per issue. How plan overhead changes with run length, over all 54 planned runs: the plan call alone takes 0.22 of a run's prompt tokens in runs of 4 model calls (8 runs), 0.14 at 6 calls (14 runs), 0.13 at 8 (8 runs) and 0.06 at 11 (2 runs); it is a fixed cost that longer runs dilute.

The script: `eval/summarize_lab02.py`, run as `python -m eval.summarize_lab02`. It reads `runs/` and the tracker, decides each run with `eval/check_triage.check`, prints this table and Part G's, and writes `results` and `context` into `reports/LAB_02.json`; `make check-02` reports that all four configurations match the tracker.

1. **What did the plan buy RepoMind, concretely?** Not success: the agent passed 8 of 18, the planned way 4 to 6. What it bought was a record and a boundary. Each of the 54 planned runs logged its plan before its first tool call (the checker counts all 66 planned and notes runs), and every tool call names the plan step it ran for, so each run has a diff of plan against trace. The schema check and code rules rejected 7 of 107 plans and revisions before they ran, at zero tool calls. The checkpoint wrote 47 `revision` lines, each a logged plan version, where the agent would have searched on unrecorded. There were 0 `off_plan` lines, and no planned run hit a turn limit, where 6 of the agent's 18 ended at its 12-call limit with nothing posted (4201 once, 4204 twice, 4206 three times). And it was cheaper: 6,537 tokens a run without a second pass, against the agent's 8,718.

2. **Where did it not pay?** Of slide 52's four cases, no issue is one step, and something did read every plan (the validator, the checkpoint, the diff). But the steps were known in advance: all 54 runs began with the same four-step plan (read the issue, search, read a file, post), which is Assignment 1's workflow with a model call in front. That rigidity cost passes where one search and one read were not enough. On 4203 the agent searched until it found `src/ingest/parser.ts` (3 of 3), while the planned runs read one file each and passed 0 of 9: six named `docs/API.md` and one `README.md`, and with `self` two were held and one named `src/api/uploads.ts`. The plan never cost more than the execution on average; the closest was 4204, where plan and revisions took 3,665 tokens a run against 4,167 for execution, because the checkpoint revised fruitless searches up to the bound.

3. **What did each second pass buy, and what did it cost?**
   - `external` changed 6 drafts and broke none: it held none, and it fixed one (4205, sweep 3: `question` naming `docs/ARCHITECTURE.md` became `question`, `none`). It also caught a label that contradicted its file on 4203, a directory that is not a file (`src/export/`) on 4202, and on 4206 a file the run never saw, three times; those rewrites passed `verify` and were still wrong. Cost: 0.07 of prompt tokens, 572 tokens a run over `off`, and no measurable time (median 7.6 s against 8.4 s).
   - `self` caught nothing that it then fixed (7 changed, 0 fixed) and held 8 drafts at the bound, posting nothing on 4202 and 4205 in any sweep. It turned at least one passing draft into a failure: on 4205, sweep 2, the first draft was `question`, `none`, right; the critic rejected it, the rewrite came back the same, and the second round rejected it again (now asking for `docs`), so the run posted nothing. The table's "broken" count is 0 only because that rewrite did not change the text. 4205 went 1 of 3 off, 0 of 3 with `self`, and 3 of 3 with `external`. Cost: 0.32 of prompt tokens, 2,918 tokens a run over `off`, and the slowest run of the four configurations (19.0 s).
   - 4206, whose title blames `src/export/csv.ts` (the answer is `src/ingest/dedupe.ts`): `off` posted `src/export/csv.ts` in all three sweeps, a file no search returned and no step read, taken from the issue's title. `self` accepted the same comment three times. `external` failed all three on "this run never saw src/export/csv.ts" and rewrote them to files the run had seen (`src/api/reports.ts` twice, `CHANGELOG.md` once): grounded, and still wrong. All three modes scored 0 of 3, and so did the agent, which hit its turn limit three times.
   - Slide 41's gates: `external` passes all three for the errors its checks can see (a failing check names the error, it knows the repository and the trace, two rounds each logged); `self` passes only the third, and these runs show what failing the first two looks like.

4. **Which failure did no detector catch?** Premature stopping, many times. A run that posted a wrong comment ended `completed`: every plan step executed, so the expected-result check and the diff saw nothing missing, and the second pass, if any, passed. That is 13 of `off`'s 14 failures, 11 of `external`'s 12, 6 of `self`'s 15 and 4 of the agent's 10. For example, all three 4203 runs with `external` searched, passed the checkpoint, read `docs/API.md`, passed `verify`, posted `bug`, `docs/API.md` and ended `completed`. I knew only from outside the run: the grounded check compared the posted comment with `fixtures/answers.yaml`, which nothing inside the run may read.

## Part G · Note-taking against compaction
Your `COMPACT_AT`, and what your progress file holds.

`COMPACT_AT = 600` tokens, counted with `estimate_tokens` (characters / 4): an issue is about 100 tokens, a 20-hit search about 400 and a file 300 to 700, so the history passes it once a file is read. A compaction keeps the most recent entry (`KEEP_RECENT = 1`) and summarizes the rest; a run that has not compacted by its questions compacts once first. The progress file, `runs/<run_id>.progress.json`, holds an `about` line ("What this run has already done, not what is left to do..."), `steps_done` (the step ids that have run, in order) and `paths` (every path a search returned or a step read, in order), and never a search term.

| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |
|---|---|---|---|---|
| notes-4203-s01-339d81 | 4203 | no | yes | 3 |
| notes-4203-s02-ca5b06 | 4203 | no | yes | 5 |
| notes-4204-s01-4b80e6 | 4204 | no | yes | 3 |
| notes-4204-s02-b8b2b7 | 4204 | no | yes | 6 |
| notes-4206-s01-88edb3 | 4206 | no | yes | 3 |
| notes-4206-s02-2d8edd | 4206 | no | yes | 4 |
| notes-4203-s01-c23f8f | 4203 | yes | yes | 6 |
| notes-4203-s02-2ed8ff | 4203 | yes | yes | 6 |
| notes-4204-s01-314074 | 4204 | yes | yes | 6 |
| notes-4204-s02-c2531d | 4204 | yes | yes | 6 |
| notes-4206-s01-0a46fd | 4206 | yes | yes | 6 |
| notes-4206-s02-413322 | 4206 | yes | yes | 6 |

1. **What did the progress file keep that compaction lost?** The early paths. With the file shown, every run answered 6 of 6 (36 of 36); without it, 24 of 36. Nine of the twelve wrong answers were a path the run had seen, answered no: the earliest search results, which went into the summary first. In 4203's first run without the file, all three seen paths (`src/i18n/en.json`, `.eslintrc.json`, `CHANGELOG.md`) were forgotten, so the summary kept none of them. The other three were false yeses for `src/util/pagination.ts`, a file never seen. The only run without the file to score 6 was the one that escalated after one compaction. Cost: the file's text in each executor and question call, about 700 to 780 prompt tokens a run (characters / 4, times the calls that showed it), some 6% of the 12,923 tokens a run with the file averaged. The runs without it averaged more, 14,340, but that difference comes from their searches, not from the file.

2. **Which context operations did RepoMind need?** My longest Part F run was the agent on 4202, sweep 3: 15,927 tokens over 12 model calls, its largest prompt 2,767 tokens.
   - Structured note-taking: not needed there, since nothing was compacted. It would have cost a file write per step and about 700 prompt tokens a run, and Part G shows it is the one that pays once compaction happens.
   - Sub-agent isolation: not needed; each subtask is one search or one read, a few hundred tokens. It would cost a model call per subtask, and whatever a sub-agent's summary leaves out.
   - Just-in-time retrieval: needed, and already in use. `search_repo` returns path-and-line pointers, and `read_file` fetches one file only when a step asks for it; the cost is the extra read call, which every planned run made once.
   - Compaction: not needed; a largest prompt of 2,767 tokens leaves nothing to compact. It would cost a summarizing call per compaction, and what Part G measured: 9 of 18 seen paths answered wrongly once the summary had replaced them.

## Assistance
Which AI tool, what it wrote, and what you checked.

Claude Code guide me with ideas on how to architecure the solution and help me to debug and check what I wrote. 
