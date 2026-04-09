# Multi-Agent Governed Delivery System — Claude Code Master Brief

## What This Is
A governed multi-agent operating system for project delivery. It has
a fixed architecture of core agents that coordinate through structured
handoffs, shared state, and formal governance policies.

## Implementation Principles
1. **Start with data structures, not logic.** Build schemas, templates,
   and folder structures before any agent behavior.
2. **Build from the center out.** Master + Scribe first. Then intake
   and definition. Then capability discovery. Then execution. Then
   evaluation. Then spawning. Then training. Consultant panel can be
   built in parallel from Phase 3 onward.
3. **Every agent is a bounded service.** Each agent has a defined mission,
   explicit authority boundaries, typed inputs and outputs, and behavioral
   rules. No agent improvises beyond its definition.
4. **Handoffs are the communication protocol.** Agents do not call each
   other informally. Every transfer uses the handoff protocol.
5. **Shared state is the single source of truth.** No agent maintains
   private state that contradicts or shadows shared state.
6. **Test the governance, not just the logic.** Tests must verify that
   agents respect their authority boundaries, use proper handoffs, and
   cannot bypass governance rules.

## Build Order

| Phase | Build | Test |
|---|---|---|
| 0 | Schemas, templates, folder structure, policies | YAML validation, structure verification |
| 1 | Master + Scribe + handoff engine + state manager | Project initialization, basic handoff cycle |
| 2 | Inquirer + Product Manager + intake checklist | Full intake-to-product-plan pipeline |
| 3 | HR + capability registry | Capability matching and gap certification |
| 4 | Project Manager + task board | Full planning and execution tracking |
| 5 | Evaluator + metrics engine | Post-project evaluation |
| 6 | Spawner + spawn policy engine | Spawn request → draft package pipeline |
| 7 | Trainer (L0) | Evaluation → proposal pipeline |
| 8 | Consultant panel (5 consultants + synthesis) | Consultation → synthesis pipeline |

## Key Files to Create Per Agent
For each agent, create:
- `agents/{agent_id}/agent_definition.yaml` — The full specification
- `agents/{agent_id}/agent.py` — The implementation
- `agents/{agent_id}/system_prompt.md` — The prompt template
- `agents/{agent_id}/tests/` — Agent-specific tests

## Key Shared Files
- `core/shared_state_manager.py` — Read/write shared state
- `core/handoff_engine.py` — Create/validate/accept/reject handoffs
- `core/capability_registry.py` — Manage the roster
- `core/task_board.py` — Manage tasks
- `core/metrics_engine.py` — Calculate metrics
- `core/spawn_policy.py` — Enforce spawn rules

## Critical Governance Tests
Every test suite must include:
- [ ] Agent cannot write to fields it doesn't own
- [ ] Agent cannot skip handoff protocol
- [ ] Agent cannot spawn without gap certificate
- [ ] Agent cannot self-deploy spawned agents
- [ ] Trainer cannot apply changes at L0
- [ ] Spawned agents cannot spawn other agents
- [ ] All decisions are recorded in shared state
- [ ] All handoffs are logged
- [ ] All consultations are recorded with synthesis

## Success Criteria for Each Phase
A phase is complete when:
1. All specified files exist
2. All tests pass
3. Integration test with previous phases passes
4. Governance tests pass
5. The Scribe has recorded everything correctly