# CommsOpt — Communication Optimization for MAS

## Goal

Minimize token expenditure in inter-agent communication while maintaining governance integrity and output quality.

## Workstreams

| # | Name | Summary |
|---|------|---------|
| 1 | Structured Wire Protocol | Agent payloads use codes + structured fields, not prose |
| 2 | Graph Memory (Graphify) | Agents query knowledge graph, not full files |
| 3 | Skill Bridge | Governed access to existing skills (notebooklm, research-extract, etc.) |
| 4 | Comms Metrics | Evaluator + Trainer measure and optimize communication efficiency |

## Build Order

```
Phase 0 (Baseline) → Phase 1 (Wire Protocol) → Phase 4 (Metrics) → Phase 2 (Graphify) → Phase 3 (Skill Bridge)
```

Rationale: measure first → biggest savings → measure improvement → add intelligence → add tools.

---

## Phase 0: Baseline Measurement

**Problem**: `token_usage` in handoffs is currently all zeros. Can't optimize what you can't measure.

**Changes**:

| File | Change |
|------|--------|
| `mas/core/prompt_assembler.py` | Add `count_tokens()` to `assemble()` return; return `(prompt_str, token_estimate)` tuple or add `last_token_count` attribute |
| `mas/core/message_bus.py` | Wrap `DirectCallBus.send()` to record actual LLM API token usage from Anthropic response metadata |
| `mas/core/metrics_engine.py` | Add `score_token_efficiency()` — tokens per handoff, per phase, per agent |
| `mas/core/shared_state_manager.py` | Add `communication` section to initial state schema for token tracking |
| `mas/core/access_control.py` | Add write rules for new `communication.*` fields |
| `mas/system_config.yaml` | Add `communication.token_tracking_enabled: true` |

**New files**:

| File | Purpose |
|------|---------|
| `mas/core/token_counter.py` | Utility: estimate tokens from string (tiktoken-compatible or char/4 heuristic) |
| `mas/tests/unit/test_token_counter.py` | Unit tests |

**Deliverable**: Run one full project lifecycle. Produce token usage report showing:
- Tokens per agent per invocation
- Tokens in prompt assembly (context injection size)
- Tokens in handoff payloads
- Tokens in consultation cycles (5 consultants × context)
- Total tokens per phase

**Success criteria**: Every handoff has non-zero `token_usage`. Report exists.

---

## Phase 1: Structured Wire Protocol

**Problem**: Handoff payloads currently use free-text `summary`, prose descriptions. Consultants write up to 500 words each. This is where most waste occurs.

**Current state** (already exists):
- `HandoffEngine.compact()` / `expand()` — compresses field names (`handoff_id→id`, `summary→s`)
- `ConsultationEngine.compact_request()` / `expand_request()` — same for consultations
- `_compact_projection()` in `prompt_assembler.py` — strips empty values, trims history

**Gap**: Compact format only compresses *keys*, not *values*. Agent outputs are still natural language prose.

**Design**:

```yaml
# BEFORE (current): agent writes prose
payload:
  summary: "I analyzed the specification and found 3 areas needing 
            clarification. The project goal is clear but scope boundaries 
            are ambiguous. I recommend asking about exclusions, timeline, 
            and quality expectations."
  artifacts_produced: ["clarified_spec_v1.yaml"]
  decisions_made: ["Proceed with 3-round clarification"]

# AFTER: structured wire format
payload:
  s: "spec_analysis:ok"
  f:  # findings (structured, not narrative)
    - {path: "scope.exclusions", st: "ambiguous", act: "clarify"}
    - {path: "timeline",         st: "missing",   act: "ask"}
    - {path: "quality",          st: "missing",   act: "ask"}
  art: ["clarified_spec_v1.yaml"]
  dec: [{id: "d-001", v: "3_round_clarification"}]
```

**Key rule**: Wire format between agents = structured data. Human-facing output (CHECKPOINT.md, project_summary) = expanded natural language via `expand()`.

**Changes**:

| File | Change |
|------|--------|
| `mas/core/wire_protocol.py` | **NEW** — Schema definitions per message type. `WireEncoder.encode()` / `WireDecoder.decode()`. Status codes vocabulary. |
| `mas/core/handoff_engine.py` | Validate payloads against wire schema. Store compact by default. |
| `mas/core/consultation_engine.py` | Consultant responses use structured format: `{rl: "l", rec: "approve", kc: ["scope_risk"]}` not 500-word prose |
| `mas/core/prompt_assembler.py` | Inject wire-format context into prompts. Add instruction prefix: "Output in ACP wire format." |
| `mas/core/checkpoint_writer.py` | `expand()` wire format → human-readable Markdown (pattern already exists) |
| Each agent `.md` template | Add "Output Format" section specifying wire protocol for that agent's outputs |

**New files**:

| File | Purpose |
|------|---------|
| `mas/core/wire_protocol.py` | Wire protocol schemas, encoder, decoder, status codes |
| `mas/foundation/wire_protocol_spec.yaml` | Protocol specification (status codes, field schemas per message type) |
| `mas/tests/unit/test_wire_protocol.py` | Schema validation, encode/decode roundtrip |
| `mas/tests/governance/test_wire_validation.py` | Handoffs rejected if wire schema violated |

**Status code vocabulary** (examples):

```yaml
# Agent status codes (replace prose summaries)
status_codes:
  spec_analysis:ok        # Inquirer: spec analyzed, ready for questions
  spec_analysis:incomplete # Inquirer: spec missing critical fields
  clarification:complete   # Inquirer: all rounds done
  product_plan:ready       # PM: plan produced
  capability:match         # HR: found matching capability
  capability:gap           # HR: gap found, cert produced
  task:complete            # Execution: task done
  task:blocked             # Execution: task blocked
  task:failed              # Execution: task failed
  eval:report_ready        # Evaluator: report produced
  training:proposals_ready # Trainer: proposals produced
  consult:approve          # Consultant: recommends approval
  consult:caution          # Consultant: recommends with caveats
  consult:oppose           # Consultant: recommends against
```

**Expected savings**: 40-60% reduction in handoff payload tokens. Consultation cycle drops from ~2500 words (5×500) to ~500 tokens structured.

---

## Phase 4: Communication Efficiency Metrics

**Why before Phase 2**: Need the measurement loop working before adding complexity. Evaluator + Trainer should catch regressions immediately.

**Problem**: No metrics exist for communication efficiency. Training proposals don't cover token waste.

**Changes**:

| File | Change |
|------|--------|
| `mas/core/metrics_engine.py` | Add 4 new scoring functions (see below) |
| `mas/core/training_engine.py` | Add `communication_efficiency` proposal type. Add `PRIORITY_SCORES["communication_waste"] = 2`. Map new metrics to recommendations. |
| `mas/core/training_engine.py` | `_metric_to_proposal_type()` — add communication metrics mapping |
| `mas/core/training_engine.py` | `_recommend_for_metric()` — add comms-specific recommendations |
| `mas/foundation/shared_state_schema.yaml` | Add `communication` section definition |
| `mas/policies/evaluation_policy.yaml` | Add communication dimension to evaluation rubric |

**New metrics**:

```python
# In metrics_engine.py

def score_token_efficiency(self, handoff_history, phase_count):
    """Tokens per phase. Lower = better. Score relative to baseline."""

def score_payload_density(self, handoff_history):
    """Ratio of structured fields to prose in payloads. Higher = better."""

def score_context_injection_efficiency(self, prompt_token_counts):
    """Injected context tokens vs total prompt tokens. Lower ratio = better."""

def score_consultation_overhead(self, consultation_data):
    """Total consultation tokens vs decision complexity. Lower = better."""
```

**Trainer extensions**:

```python
# New proposal types
PRIORITY_SCORES["communication_waste"] = 2
PRIORITY_SCORES["context_bloat"] = 2

# Example generated proposal:
# "Agent 'product_manager_agent' averaged 1200 tokens per handoff payload.
#  Wire protocol compliance: 40%. Recommend enforcing structured output format."
```

**Success criteria**: After running a project, evaluation report includes communication metrics. Trainer produces at least 1 comms-related proposal.

---

## Phase 2: Graph Memory with Graphify

**Problem**: Agents get context via full state injection (`prompt_assembler.py` dumps YAML into prompts). Cross-project memory = reading entire files. Scales poorly.

**Reference**: https://graphify.net/graphify-claude-code-integration.html

**Architecture**:

```
mas/core/memory/
├── __init__.py
├── graph_store.py        # Graphify integration wrapper
├── memory_manager.py     # Query interface for agents
├── episode_writer.py     # Writes project events as graph episodes
└── schema.py             # Entity + relationship type definitions
```

**Entity types**:

```yaml
entities:
  project:     {id, name, status, phase, created_at}
  agent:       {id, name, tier, capabilities}
  decision:    {id, type, rationale, outcome}
  artifact:    {id, type, path, phase}
  capability:  {id, name, tags}
  evaluation:  {id, project_id, overall_score}
  finding:     {id, metric, score, description}
  proposal:    {id, type, priority, status}

relationships:
  produced_by:     artifact → agent
  decided_by:      decision → agent
  depends_on:      task → task
  evaluated_in:    agent → evaluation
  improved_from:   proposal → finding
  blocked_by:      task → blocker
  used_in:         capability → project
  spawned_by:      agent → project
```

**How agents query** (replaces full-file reads):

```python
# memory_manager.py
class MemoryManager:
    async def query(self, question: str, entity_types: list = None, 
                    limit: int = 5) -> list[dict]:
        """Semantic search over knowledge graph. Returns relevant facts only."""
    
    async def get_related(self, entity_id: str, relationship: str, 
                          depth: int = 1) -> list[dict]:
        """Graph traversal. E.g. get all findings related to an agent."""
    
    async def write_episode(self, episode_type: str, body: str, 
                            source: str, timestamp: datetime) -> None:
        """Record a project event as a graph episode."""
```

**Integration points**:

| Agent | Uses Memory For |
|-------|----------------|
| `scribe_agent` | Writes episodes after every handoff recording |
| `hr_agent` | Queries for capability matches (replaces flat roster scan) |
| `trainer_agent` | Queries for cross-project patterns |
| `evaluator_agent` | Queries for historical benchmarks (after 3+ projects) |
| `master_orchestrator` | Queries for prior decision context |

**Changes**:

| File | Change |
|------|--------|
| `mas/core/prompt_assembler.py` | Add `memory_context` injection: query graph for relevant facts, inject only results (not full state) |
| `mas/core/handoff_engine.py` | After `create()`, call `episode_writer.write_episode()` |
| `mas/core/capability_registry.py` | Add graph-backed search alongside existing tag matching |
| `mas/system_config.yaml` | Add `memory.provider: graphify`, `memory.fallback: filesystem` |
| `pyproject.toml` | Add graphify dependency |

**Fallback**: If Graphify is not available, fall back to current file-based reads. `MemoryManager` checks config and routes accordingly.

**Expected savings**: Prompt context drops from ~2000 tokens of YAML dump to ~300 tokens of targeted query results.

---

## Phase 3: Skill Bridge (Governed External Tool Access)

**Problem**: Agents are isolated. Existing skills in `skills/` (notebooklm, research-extract, research-sync, frontend-design, skill-builder) can't be used by MAS agents.

**Key constraint**: NOT all agents get tool access. Explicit authorization only.

**Architecture**:

```
mas/core/
├── skill_bridge.py       # Governed interface to skills/
└── skill_registry.py     # Which agents can use which skills
```

**Authorization matrix** (in `system_config.yaml`):

```yaml
skill_access:
  # agent_id → list of allowed skill names
  master_orchestrator: []          # No direct skill use — delegates
  product_manager_agent:
    - research-extract             # Can extract research for product decisions
  project_manager_agent: []        # No skill access
  hr_agent: []                     # No skill access
  evaluator_agent: []              # No skill access  
  trainer_agent:
    - research-extract             # Can research improvement patterns
  inquirer_agent:
    - notebooklm                   # Can query NotebookLM for domain context
  scribe_agent: []                 # No skill access
  spawner_agent:
    - skill-builder                # Can use skill-builder to create agent packages
  domain_expert:
    - notebooklm                   # Can query NotebookLM for domain knowledge
    - research-extract             # Can extract domain research
  # Consultants: no skill access by default
  risk_advisor: []
  quality_advisor: []
  devils_advocate: []
  efficiency_advisor: []
```

**Governance rules**:
1. Every skill invocation logged in audit
2. Master must pre-approve skill use per project (in delegation plan)
3. Skill results go through Scribe (recorded as artifacts)
4. Token cost of skill invocation tracked in `communication` section
5. Unauthorized skill access = governance violation (blocked + logged)

**Implementation**:

```python
# skill_bridge.py
class SkillBridge:
    def __init__(self, config: dict, audit_logger):
        self.skill_access = config["skill_access"]
        self.logger = audit_logger
    
    def invoke(self, agent_id: str, skill_name: str, 
               query: str, project_id: str) -> SkillResult:
        """Invoke a skill on behalf of an agent. Checks authorization."""
        if not self._is_authorized(agent_id, skill_name):
            self.logger.log_violation(agent_id, f"skill:{skill_name}", 
                                      project_id, "unauthorized_skill_access")
            raise GovernanceViolation(f"{agent_id} not authorized for {skill_name}")
        
        # Load and invoke the skill
        result = self._execute_skill(skill_name, query)
        
        # Log invocation
        self.logger.log("skill_invoked", agent_id=agent_id, 
                       skill=skill_name, project_id=project_id,
                       tokens_used=result.token_count)
        return result
```

**Changes**:

| File | Change |
|------|--------|
| `mas/core/skill_bridge.py` | **NEW** — Skill invocation with authorization |
| `mas/core/skill_registry.py` | **NEW** — Discovers available skills from `skills/` directory |
| `mas/core/access_control.py` | Add `skill_access` checking functions |
| `mas/core/audit_logger.py` | Add `log_skill_invocation()` method |
| `mas/system_config.yaml` | Add `skill_access` matrix |
| `mas/core/message_bus.py` | Add `SKILL_REQUEST` / `SKILL_RESULT` message types |
| Agent templates that get skill access | Add "Available Skills" section with usage instructions |

**New files**:

| File | Purpose |
|------|---------|
| `mas/core/skill_bridge.py` | Governed skill invocation |
| `mas/core/skill_registry.py` | Skill discovery and metadata |
| `mas/tests/unit/test_skill_bridge.py` | Unit tests |
| `mas/tests/governance/test_skill_authorization.py` | Unauthorized access blocked |

---

## Success Criteria (overall project)

| Metric | Baseline (Phase 0) | Target |
|--------|-------------------|--------|
| Tokens per handoff payload | TBD (measure) | -50% |
| Tokens per consultation cycle | TBD (measure) | -60% |
| Prompt context injection size | TBD (measure) | -30% |
| Total tokens per project lifecycle | TBD (measure) | -40% |
| Wire protocol compliance rate | 0% | >90% |
| Communication efficiency score (new metric) | N/A | >75/100 |

---

## Expert Questions to Resolve During Build

1. **Wire protocol strictness**: Should agents that produce non-compliant output get a governance violation, or just a warning logged? → Recommend: warning for first 2 projects, then violation.

2. **Graphify cold start**: First project has no memory. What's the minimum seed data? → Recommend: seed with agent roster + policy summaries.

3. **Skill invocation budget**: Should there be a per-project token budget for skill invocations? → Recommend: no hard limit v1, track and review.

4. **Consultation wire format adoption**: Can consultants produce useful structured output, or does their value come from prose reasoning? → Recommend: hybrid — structured `risk_level` + `recommendation` + `key_concerns` (already in schema) but allow optional `reasoning` field (max 100 words, not 500).

5. **Graph memory vs state injection**: Should graph memory *replace* or *supplement* `_compact_projection()` in prompt assembly? → Recommend: supplement first. Graph for cross-project memory, projection for current-project state.

6. **Wire protocol versioning**: How to handle protocol evolution? → Recommend: version field in wire messages. Decoder handles all known versions.

7. **Skill result caching**: Should skill results be cached to avoid re-invocation? → Recommend: yes, cache in graph memory with TTL.

8. **Token counting accuracy**: Use tiktoken (accurate but adds dependency) or char/4 heuristic (fast but approximate)? → Recommend: char/4 for v1, add tiktoken optional.

9. **Backward compatibility**: Existing 590 tests assume current format. How to migrate? → Recommend: wire protocol is opt-in initially. `compact()` produces wire format, `expand()` produces legacy format. Tests use `expand()`.

10. **Graphify authentication**: How does the MAS authenticate with Graphify? → Recommend: API key in `.env`, loaded via `python-dotenv` (already a dependency).

11. **Memory write permissions**: Which agents can write to graph memory? → Recommend: only `scribe_agent` and `system` write. All agents read.

12. **Skill invocation during consultation**: Can consultants invoke skills? → Recommend: only `domain_expert` (see authorization matrix above).

13. **Wire protocol for human-facing phases**: Inquirer talks to humans. Should intake Q&A use wire format? → Recommend: No. Inquirer input/output stays natural language. Wire format only for agent-to-agent.

---

## File Impact Summary

### New files (12)

| File | Phase |
|------|-------|
| `mas/core/token_counter.py` | 0 |
| `mas/core/wire_protocol.py` | 1 |
| `mas/foundation/wire_protocol_spec.yaml` | 1 |
| `mas/core/memory/__init__.py` | 2 |
| `mas/core/memory/graph_store.py` | 2 |
| `mas/core/memory/memory_manager.py` | 2 |
| `mas/core/memory/episode_writer.py` | 2 |
| `mas/core/memory/schema.py` | 2 |
| `mas/core/skill_bridge.py` | 3 |
| `mas/core/skill_registry.py` | 3 |
| `mas/tests/unit/test_token_counter.py` | 0 |
| `mas/tests/unit/test_wire_protocol.py` | 1 |
| `mas/tests/governance/test_wire_validation.py` | 1 |
| `mas/tests/governance/test_skill_authorization.py` | 3 |
| `mas/tests/unit/test_skill_bridge.py` | 3 |

### Modified files (13)

| File | Phases |
|------|--------|
| `mas/core/prompt_assembler.py` | 0, 1, 2 |
| `mas/core/message_bus.py` | 0, 3 |
| `mas/core/metrics_engine.py` | 0, 4 |
| `mas/core/handoff_engine.py` | 1, 2 |
| `mas/core/consultation_engine.py` | 1 |
| `mas/core/checkpoint_writer.py` | 1 |
| `mas/core/training_engine.py` | 4 |
| `mas/core/shared_state_manager.py` | 0 |
| `mas/core/access_control.py` | 0, 3 |
| `mas/core/capability_registry.py` | 2 |
| `mas/core/audit_logger.py` | 3 |
| `mas/system_config.yaml` | 0, 2, 3 |
| `pyproject.toml` | 2 |