Import map: locations that import `core.*` modules

This file was generated from a repository search for the patterns `from core.` and `import core.` and lists the primary callers found. Use this as a reference when planning module moves (wrappers remain to preserve compatibility).

Summary: 181 matches found across mas/ (tests + core modules). Below are the top-level `core.*` modules and the files that import them (unique paths).

core.config
- mas/core/cli.py
- mas/core/capability_registry.py
- mas/core/metrics_engine.py
- mas/core/task_board.py

core.shared_state_manager
- mas/core/cli.py
- mas/core/metrics_engine.py
- mas/core/handoff_engine.py
- mas/core/shared_state_manager.py
- mas/tests/unit/test_graph_memory.py
- mas/tests/unit/test_checkpoint_writer.py
- mas/tests/unit/test_handoff_engine.py
- mas/tests/unit/test_shared_state_manager.py
- mas/tests/governance/test_immutable_fields.py
- mas/tests/governance/test_access_control.py
- mas/tests/governance/test_wire_validation.py
- mas/tests/governance/test_append_only.py
- mas/tests/integration/test_capability_query.py
- mas/tests/integration/test_checkpoint_resume_e2e.py
- mas/tests/integration/test_comms_metrics_flow.py
- mas/tests/integration/test_consultation_flow.py
- mas/tests/integration/test_evaluation_flow.py
- mas/tests/integration/test_intake_to_product_plan.py
- mas/tests/integration/test_full_lifecycle.py
- mas/tests/integration/test_master_scribe_initialization.py
- mas/tests/integration/test_product_plan_to_execution.py
- mas/tests/integration/test_resume_flow.py
- mas/tests/integration/test_spawn_flow.py
- mas/tests/integration/test_training_flow.py

core.handoff_engine
- mas/core/cli.py
- mas/core/handoff_engine.py
- mas/core/shared_state_manager.py
- mas/tests/unit/test_graph_memory.py
- mas/tests/unit/test_checkpoint_writer.py
- mas/tests/unit/test_handoff_engine.py
- mas/tests/unit/test_compact_format.py
- mas/tests/governance/test_wire_validation.py
- mas/tests/integration/test_capability_query.py
- mas/tests/integration/test_checkpoint_resume_e2e.py
- mas/tests/integration/test_comms_metrics_flow.py
- mas/tests/integration/test_consultation_flow.py
- mas/tests/integration/test_evaluation_flow.py
- mas/tests/integration/test_full_lifecycle.py
- mas/tests/integration/test_master_scribe_initialization.py
- mas/tests/integration/test_product_plan_to_execution.py
- mas/tests/integration/test_resume_flow.py
- mas/tests/integration/test_spawn_flow.py
- mas/tests/integration/test_training_flow.py

core.wire_protocol
- mas/core/checkpoint_writer.py
- mas/core/handoff_engine.py
- mas/core/wire_protocol.py
- mas/tests/unit/test_wire_protocol.py
- mas/tests/governance/test_wire_validation.py
- mas/tests/integration/test_comms_metrics_flow.py

core.checkpoint_writer
- mas/core/checkpoint_writer.py
- mas/core/handoff_engine.py
- mas/core/shared_state_manager.py
- mas/tests/unit/test_graph_memory.py
- mas/tests/unit/test_checkpoint_writer.py
- mas/tests/governance/test_wire_validation.py
- mas/tests/integration/test_checkpoint_resume_e2e.py
- mas/tests/integration/test_resume_flow.py

core.graph_memory
- mas/core/metrics_engine.py
- mas/core/handoff_engine.py
- mas/core/prompt_assembler.py
- mas/core/graph_memory.py
- mas/tests/unit/test_graph_memory_cli.py
- mas/tests/unit/test_graph_memory.py
- mas/tests/prompts/test_prompt_assembler.py

core.metrics_engine
- mas/core/metrics_engine.py
- mas/core/training_engine.py
- mas/tests/unit/test_metrics_engine.py
- mas/tests/integration/test_comms_metrics_flow.py
- mas/tests/integration/test_evaluation_flow.py
- mas/tests/integration/test_full_lifecycle.py

core.utils.token_counter (implementation)
- mas/core/metrics_engine.py
- mas/core/message_bus.py
- mas/core/graph_memory.py
- mas/core/prompt_assembler.py
- mas/core/skill_bridge.py
- mas/core/token_counter.py  (wrapper)
- mas/tests/unit/test_token_counter.py

core.token_counter (wrapper)
- mas/core/token_counter.py
- mas/tests/unit/test_token_counter.py

core.log_helpers
- mas/core/log_helpers.py
- mas/tests/unit/test_log_helpers.py

core.db_init / core.utils.db_init
- mas/core/db_init.py

core.task_board
- mas/core/task_board.py
- mas/tests/unit/test_task_board.py
- mas/tests/integration/test_evaluation_flow.py
- mas/tests/integration/test_product_plan_to_execution.py

core.message_bus
- mas/core/message_bus.py
- mas/tests/unit/test_message_bus.py

core.prompt_assembler
- mas/core/prompt_assembler.py
- mas/tests/prompts/test_prompt_assembler.py
- mas/tests/unit/test_compact_format.py

core.skill_bridge
- mas/core/skill_bridge.py
- mas/tests/unit/test_skill_bridge.py

core.training_engine
- mas/core/training_engine.py
- mas/tests/unit/test_training_engine.py
- mas/tests/integration/test_comms_metrics_flow.py
- mas/tests/integration/test_training_flow.py
- mas/tests/integration/test_full_lifecycle.py

core.capability_registry
- mas/core/capability_registry.py
- mas/tests/unit/test_capability_registry.py
- mas/tests/integration/test_capability_query.py
- mas/tests/integration/test_product_plan_to_execution.py
- mas/tests/integration/test_spawn_flow.py

core.consultation_engine
- mas/tests/unit/test_consultation_engine.py
- mas/tests/unit/test_compact_format.py
- mas/tests/integration/test_consultation_flow.py
- mas/tests/integration/test_full_lifecycle.py

core.spawn_policy
- mas/tests/unit/test_spawn_policy.py
- mas/tests/integration/test_full_lifecycle.py
- mas/tests/integration/test_spawn_flow.py

core.intake_checker
- mas/core/intake_checker.py
- mas/tests/unit/test_intake_checker.py
- mas/tests/integration/test_intake_to_product_plan.py
- mas/tests/integration/test_full_lifecycle.py

core.audit_logger
- mas/core/handoff_engine.py
- mas/core/shared_state_manager.py

core.access_control
- mas/core/shared_state_manager.py
- mas/tests/governance/test_access_control.py

core.handoff_helpers
- mas/tests/unit/test_handoff_helpers.py

core.context_compressor
- mas/tests/unit/test_context_compressor.py

Notes
- This is a concise mapping focused on the modules with the most references. The raw search returned 181 matches; keep the wrappers in place while you migrate modules in small batches.
- If you want a machine-readable CSV or the full raw grep output file, say so and I will add it.
