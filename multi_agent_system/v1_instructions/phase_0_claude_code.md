# Phase 0 — Foundation Layer — Claude Code Instructions

## Objective
Create the foundation directory structure, all schema files, all template
files, and all policy files. Nothing executes yet. This phase produces
the structural skeleton that all agents will operate within.

## What to build

### 1. Create the directory structure
Create every directory shown in `folder_structure.yaml` at the system root.
The `projects/` directory starts empty (projects are created dynamically).

### 2. Create schema files
- `foundation/memory_types.yaml` — Copy exactly from specification
- `foundation/shared_state_schema.yaml` — Copy exactly from specification  
- `foundation/handoff_protocol.yaml` — Copy exactly from specification
- `foundation/folder_structure.yaml` — Copy exactly from specification

### 3. Create template files in `templates/`
Each template should be a valid YAML file with all required fields
shown as empty/placeholder values with inline comments explaining
what goes in each field.

### 4. Create policy files in `policies/`
- `spawn_policy.yaml` — See Phase 6 specification
- `governance_policy.yaml` — See governance rules throughout this document
- `handoff_protocol.yaml` — Reference copy of the handoff spec
- `trust_tier_policy.yaml` — See trust tier definitions
- `evaluation_policy.yaml` — See Phase 5 specification
- `training_policy.yaml` — See Phase 7 specification

### 5. Create a system configuration file
```yaml
# system_config.yaml
system:
  name: "Governed Multi-Agent Delivery System"
  version: "0.1.0"
  created_at: "{timestamp}"
  governance_mode: "strict"  # strict | permissive
  
  defaults:
    trainer_authority_level: "L0_advisory"
    spawn_mode: "draft_only"
    max_spawns_per_project: 3
    max_spawns_per_phase: 1
    recursive_spawn_allowed: false
    
  paths:
    roster: "roster/"
    policies: "policies/"
    templates: "templates/"
    projects: "projects/"
    foundation: "foundation/"