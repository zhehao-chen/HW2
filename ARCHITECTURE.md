# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 40 to 42):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table below is RepoMind as Assignment 1 left it. In Assignment 2, the Harness
row comes to cite the validator and the boundary, and any other row your work
changes changes with it.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | The configured model, called only through the metered client | `harness/client.py:116` | present |
| Harness | Assignment 1's loop and bounds; the planned way checks each plan against the schema and plan rules, then the validator's four checks, re-plans a rejected one up to `MAX_REPLANS` and escalates; the executor runs only the active plan's step and refuses any other tool | `agent/loop.py:38`, `agent/validator.py:35`, `ways/planned.py:85`, `ways/planned.py:127`, `ways/planned.py:303` | present |
| Tools | Four tools behind one registry (read_file arrived with Assignment 2's starter); post_comment stamps the run_id | `tools/__init__.py:52`, `harness/tracker.py:60` | present |
| Memory & State | The plan's step statuses within a run; the notes way's progress file outside the conversation, and its compaction of the history | `ways/notes.py:97`, `ways/notes.py:112` | partial: nothing survives a run |
| Control & Policy | The executor refuses off-plan calls; a draft that fails the second pass is held, not posted, and the run escalates to a person | `ways/planned.py:303`, `ways/planned.py:412` | partial: no approval gate yet |
| Observability | Trace lines per call, plus each plan version, revision, critique round and refusal; the detectors and the diff read them | `ways/planned.py:515`, `agent/detectors.py:103`, `agent/diff.py:101` | partial: traces, no alerts |
| Evaluation | The grounded check reads the tracker, never the agent; the Assignment 2 results script builds Part F's table from the traces | `eval/check_triage.py:7`, `eval/summarize_lab02.py:111` | partial: offline only |

**Empty layers: 0 of 7**, and four are partial. Assignment 1 left Memory & State
and Control & Policy empty; Assignment 2's progress file and plan boundary fill
them in part, in code rather than in a prompt.
