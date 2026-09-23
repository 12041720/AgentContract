# AgentContract Agent Protocol

This file is the repository-wide contract for every agent working on AgentContract.

## Roles

### Main agent
The main agent owns project direction, architecture, task decomposition, acceptance criteria, and review.

The main agent is the only role allowed to:
- change the authoritative task status in `.agent/STATE.md`;
- mark a task accepted/rejected;
- redefine architecture or task scope;
- create the next active task.

### Execution agent
An execution agent implements exactly one active task.

An execution agent must:
1. Read this file.
2. Read `.agent/STATE.md`.
3. Read the active task file under `.agent/tasks/`.
4. Stay inside the task's stated scope.
5. Run the required tests/checks.
6. Record a concise handoff in the task file's **Executor Report** section.
7. Stop after the requested task is implemented; do not silently start the next task.

An execution agent must not:
- mark its own task accepted;
- change project architecture without explicit task instructions;
- rewrite `.agent/STATE.md` except when the task explicitly delegates that responsibility;
- weaken tests or acceptance criteria merely to make a task pass.

## Persistent workflow

The repository itself is the shared memory.

```text
Main agent writes task
        ↓
.agent/STATE.md points to active task
        ↓
Execution agent reads task and implements it
        ↓
Execution agent writes Executor Report + commit/PR
        ↓
Main agent reviews code, tests, and diff
        ↓
Main agent writes review verdict
        ↓
STATE + TASKS updated
        ↓
Next task activated
```

A new chat/session must be able to reconstruct the current project state only from repository files.

## Source-of-truth files

- `.agent/STATE.md` — current project state and active task.
- `.agent/TASKS.md` — ordered roadmap and task statuses.
- `.agent/tasks/TASK-XXX.md` — complete executable task specification and handoff.
- `.agent/REVIEW_LOG.md` — append-only main-agent review history.
- `docs/ARCHITECTURE.md` — current architecture and design boundaries.

If chat instructions and these files conflict, stop and surface the conflict to the user/main agent instead of guessing.

## Engineering rules

- Development baseline is the user's installed local Python: **Python 3.12.9**.
- Do not install or download alternate Python versions solely to satisfy compatibility checks.
- Run the required test suite on the local development interpreter. Compatibility matrices are not required unless the user explicitly asks for them.
- If a tool such as uv previously downloaded an extra interpreter only for compatibility testing, remove that managed interpreter after confirming it is not the user's system Python.
- Prefer standard library plus Pydantic for domain models.
- Keep the core independent of any specific LLM vendor.
- Deterministic verification should be preferred over LLM judgement whenever possible.
- Every externally visible behavior added by an execution task needs tests.
- Constraints and evidence must retain provenance.
- Never silently convert uncertain evidence into verified evidence.
- No production claim is considered verified merely because an LLM says so.

## Handoff format

At the end of a task, update only the task file's **Executor Report** section with:

- implementation summary;
- files changed;
- tests/checks run and results;
- known limitations;
- commit SHA or PR URL if available;
- questions/blockers for main-agent review.

The main agent will fill the **Main Agent Review** section.
