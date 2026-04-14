# MAS Core Restructure Plan

Status: initial staging complete — alias packages added (`core.engine`, `core.utils`, `core.policy`).

Goal
----
Cleanly group MAS core Python modules into logical subpackages to improve discoverability and make future maintenance easier. Keep changes incremental and non-breaking.

High-level grouping (proposed)
- `core.engine` — engines and managers: handoff_engine, shared_state_manager, task_board, metrics_engine, consultation_engine, training_engine, graph_memory, context_compressor, skill_bridge, message_bus, prompt_assembler
- `core.utils`  — utilities: access_control, audit_logger, checkpoint_writer, config, log_helpers, token_counter, wire_protocol, db_init
- `core.policy` — policy/registry: capability_registry, spawn_policy
- `core.cli`    — CLI entrypoint remains at `core/cli.py`

Observed import patterns (examples)
- `core.shared_state_manager` is widely imported by: `core/cli.py`, many tests (`mas/tests/**`), `core/handoff_engine.py`, `core/checkpoint_writer.py`.
- `core.handoff_engine` used by: CLI, tests, `core/graph_memory.py`, `core/checkpoint_writer.py`.
- `core.checkpoint_writer` used by: tests, `core/shared_state_manager.py`, `core/checkpoint_writer.py` (self refs), resume/restore flows.
- `core.wire_protocol` used by: `core/checkpoint_writer.py`, governance tests, comms/tests.
- `core.metrics_engine`, `core.task_board`, `core.training_engine` appear in integration and unit tests and reference `core.config` for project paths.

Strategy (non-breaking, incremental)
1. Alias packages (done): add `core.engine`, `core.utils`, `core.policy` that re-export current top-level modules. This allows code to start importing from the new namespace immediately.
2. Mapping: scan the repo for importers and pick a small subset of callers to change first (tests are useful smoke tests).
3. Move modules in small batches:
   - Option A (recommended): create the physical subpackage (`mas/core/engine/`), copy the module into it, update internal imports to relative imports, then leave a thin top-level wrapper that imports and re-exports public names from the new location. Run tests and fix any cycles.
   - Option B: move the file and simultaneously update all importers to the new path; requires a coordinated update across tests and callers.
4. After moving each batch, run unit and integration tests, fix import cycles by converting imports to local/relative imports, and remove top-level wrappers once all callers are migrated.
5. Update documentation (`mas/CLAUDE.md`, `mas/foundation/folder_structure.yaml`) and add `mas/core/README.md` (done).

Next immediate steps
- Produce a full mapping CSV of top-level modules → importer files (I can generate this file next).
- Choose the first safe batch to move (e.g., `core.utils` modules: `config`, `log_helpers`, `token_counter`, `wire_protocol`) and perform the copy + wrapper approach.

If you approve, I'll generate the full mapping of importers and then move the first batch (utilities), updating wrappers and tests as I go.
