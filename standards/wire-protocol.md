# Wire Protocol Standard

**Type:** Normative
**Applies to:** All inter-agent handoff payloads and responses
**Source of truth:** `mas/foundation/wire_protocol_spec.yaml`

---

## Format

All agent-to-agent outputs use MAS wire protocol v1.0:

```json
{
  "_v": "1.0",
  "s": "task:complete",
  "art": ["path/to/artifact.yaml"],
  "dec": [
    {
      "id": "d-001",
      "v": "decision value",
      "rat": "why this decision was made",
      "alt": ["alternative A", "alternative B"],
      "rel": "d-000"
    }
  ],
  "rsn": "Optional reasoning — max 100 words"
}
```

---

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `_v` | Yes | Protocol version — always `"1.0"` |
| `s` | Yes | Status code (see vocabulary below) |
| `art` | No | List of artifact paths on disk |
| `dec` | No | List of decisions made |
| `rsn` | No | Optional reasoning — max 100 words |

Omit empty lists and null values.

---

## Status Code Vocabulary

| Code | Meaning |
|------|---------|
| `task:complete` | Task finished successfully |
| `task:delegated` | Task delegated to another agent |
| `task:blocked` | Task cannot proceed; escalation needed |
| `eval:pass` | Evaluation passed |
| `eval:fail` | Evaluation failed |
| `consult:approve` | Consultant approves |
| `consult:flag` | Consultant flags a risk |
| `scribe:recorded` | Scribe recorded the artifact/phase |
| `hr:plan_ready` | HR deployment plan is ready |
| `spawn:approved` | Spawn approved |
| `spawn:denied` | Spawn denied |

---

## Decision Quality Fields

To score above 70 on `decision_quality`, each `dec` entry should include:

| Field | Description | Scoring impact |
|-------|-------------|----------------|
| `id` | Decision identifier | Required |
| `v` | Decision value / outcome | Required |
| `rat` | Rationale — why this decision was made | +20 pts |
| `alt` | Alternatives considered — list of strings | +20 pts |
| `rel` | Related decision id or context | +20 pts |

---

## Orchestration Extension Keys

Used when `mas run` drives the project loop:

```json
{
  "_v": "1.0",
  "s": "task:complete",
  "next_action": "delegate",
  "next_agent": "inquirer_agent",
  "consultation_trigger": {
    "decision_type": "architecture",
    "question": "Should we spawn a specialist agent for X?",
    "consultants": ["domain_expert", "risk_advisor"],
    "context": {"gap": "no agent covers X"}
  }
}
```

| Key | Values | Meaning |
|-----|--------|---------|
| `next_action` | `delegate`, `advance_phase`, `consult`, `escalate`, `wait` | What the loop should do next |
| `next_agent` | agent_id | Who to delegate to (when `next_action == "delegate"`) |
| `next_agents` | [agent_id, ...] | Parallel dispatch (when HR marks `parallel: true`) |
