# AgentContract Architecture v0.1

## Goal

AgentContract is a reliability control plane for long-horizon tool-using agents.

It does **not** replace the agent planner/model. It observes requirements and actions, maintains a durable execution contract, blocks or flags violations, records execution evidence, and gates completion claims.

## System boundary

```text
                    ┌──────────────────┐
User messages ─────→│ Requirement layer │
                    └────────┬─────────┘
                             ↓
                    ┌──────────────────┐
                    │ Constraint Ledger │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
Agent/tool request →│    SpecGuard      │──→ allow / block / warn / require evidence
                    └────────┬─────────┘
                             ↓
                        Tool runtime
                             ↓
                    ┌──────────────────┐
                    │ Trace / Evidence  │
                    └────────┬─────────┘
                             ↓
Agent claims ───────→┌──────────────────┐
                     │   EvidenceGate    │──→ verified / unverified / contradicted
                     └──────────────────┘
```

## Core packages

Planned package boundaries:

```text
src/agentcontract/
├── constraints/    # contract/constraint domain and ledger
├── trace/          # normalized events and provenance
├── guard/          # SpecGuard action/state verification
├── evidence/       # claims, evidence graph, completion verification
├── runtime/        # wrapper/orchestration integration
└── adapters/       # LLM/agent/tool-specific integrations
```

The core packages must remain vendor-neutral.

## Domain principles

### 1. Constraint provenance is mandatory

Every constraint must retain enough source information to answer:
- where did this requirement come from?
- was it explicitly supplied by the user, inferred by an agent, imposed by policy, or derived from the repository/environment?
- what superseded/revoked it?

### 2. Constraint state is versioned

A requirement can evolve through states such as:
- active;
- revoked;
- superseded;
- conflicted.

Historical records are not overwritten into oblivion.

### 3. Hard and soft constraints are different

At minimum the model must distinguish:
- hard prohibition/requirement;
- soft preference;
- assumption/inference.

A model inference must never silently acquire the authority of an explicit user requirement.

### 4. Unknown is not verified

Evidence evaluation must support at least:
- verified;
- contradicted;
- unverified/unknown.

Lack of evidence is not evidence of success.

### 5. Deterministic before probabilistic

If a constraint can be evaluated from:
- tool arguments;
- exit codes;
- filesystem state;
- diff;
- test output;
- structured API results;

then that deterministic path should be used before an LLM judge.

### 6. Evidence has provenance

A completion claim must be traceable to the concrete action/tool result/artifact/state that supports or contradicts it.

## MVP execution model

AgentContract v0.1 operates synchronously around tool calls:

```text
proposed action
    ↓
pre-action check
    ↓
ALLOW / WARN / BLOCK
    ↓
tool execution
    ↓
event/evidence recording
    ↓
post-action check
```

Task completion adds:

```text
agent final claims
    ↓
claim normalization
    ↓
evidence lookup / verification
    ↓
completion readiness
```

Durable distributed execution, retries, queues, and multi-agent coordination are intentionally deferred.

## Public API direction

The precise API is not frozen, but the design target is composable objects similar to:

```python
ledger = ConstraintLedger(...)
decision = spec_guard.evaluate(action, ledger=ledger, context=context)
result = evidence_gate.verify(claims, evidence=evidence_store)
```

Domain objects must serialize cleanly so that the state can later be persisted in SQLite/PostgreSQL or emitted as OTel-compatible events.

## Non-goals for v0.1

- building a general-purpose agent framework;
- implementing a full policy language;
- replacing existing tracing platforms;
- arbitrary MCP security gateway functionality;
- training/fine-tuning models;
- production distributed workflow execution.

## Quality bar

A component is not considered complete because the happy path works. Tests must include:
- state evolution;
- invalid transitions;
- conflicting/superseding constraints where applicable;
- serialization round trips;
- provenance preservation;
- failure/unknown cases.
