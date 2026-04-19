"""
Graph Memory
Stores project knowledge as a graph of episodes for efficient context retrieval.

Instead of injecting full shared state into every agent prompt (~2000 tokens),
agents query the graph for relevant facts (~300 tokens). This is Phase 4 of
the CommsOpt plan, gated on context_injection_efficiency being the top cost driver.

Architecture:
  - GraphStore: in-memory networkx graph, persisted to SQLite (agent_graph tables)
  - GraphMemory: public interface — query(), get_related(), write_episode()
  - EpisodeWriter: called by handoff_engine after each handoff to record events
  - prompt_assembler integration: injects graph context instead of full state

Entity types:
  project, agent, decision, artifact, capability, evaluation, finding, proposal

Relationship types:
  owns, produced, decided, references, depends_on, handoff_to, evaluated_by,
  spawned_from, related_to

Usage as library:
    from core.engine.graph_memory import GraphMemory
    gm = GraphMemory("proj-20260410-001-session-scheduler")
    gm.write_episode("handoff", {"from": "master_orchestrator", "to": "scribe_agent", ...})
    results = gm.query("scribe_agent", context="intake phase artifacts")

Usage as CLI:
    uv run python mas/core/engine/graph_memory.py stats --project-id proj-001
    uv run python mas/core/engine/graph_memory.py query --project-id proj-001 --agent scribe_agent --context "artifacts"
    uv run python mas/core/engine/graph_memory.py episodes --project-id proj-001
"""

from __future__ import annotations

import sys
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False

try:
    from core.utils.token_counter import TokenCounter as _TokenCounter
    _tc = _TokenCounter()
except ImportError:
    _tc = None  # type: ignore

ROOT = Path(__file__).parent.parent.parent   # mas/

# Module-level DB path — promoted so tests can monkeypatch it.
# Falls back gracefully when core.db is not importable (e.g. isolated unit tests).
try:
    from core.db import _get_connection as _db_get_connection, init_db as _db_init_db, DB_PATH as _DB_PATH
    _DB_AVAILABLE = True
except ImportError:
    _db_get_connection = None  # type: ignore
    _db_init_db = None  # type: ignore
    _DB_PATH = None  # type: ignore
    _DB_AVAILABLE = False

# Special sentinel: the cross-project global graph stored in SQLite
GLOBAL_PROJECT_ID = "__global__"

# ---------------------------------------------------------------------------
# Constants — entity and relationship vocabulary
# ---------------------------------------------------------------------------

ENTITY_TYPES = frozenset({
    "project",
    "agent",
    "decision",
    "artifact",
    "capability",
    "evaluation",
    "finding",
    "proposal",
    "phase",
    "handoff",
})

RELATIONSHIP_TYPES = frozenset({
    "owns",
    "produced",
    "decided",
    "references",
    "depends_on",
    "handoff_to",
    "evaluated_by",
    "spawned_from",
    "related_to",
    "completed",
    "raised",
})

# Max tokens to inject from graph results (Phase 4 target: ~300 tokens)
MAX_INJECT_TOKENS = 300
MAX_QUERY_RESULTS = 10


# ---------------------------------------------------------------------------
# GraphStore — networkx backend
# ---------------------------------------------------------------------------

class GraphStore:
    """
    In-memory directed graph backed by networkx (or a dict fallback).
    Persisted to SQLite (mas/data/episodic.db — agent_graph + agent_graph_edges tables).
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._g = self._create_graph()
        self._load()

    def _create_graph(self):
        if _NX_AVAILABLE:
            return nx.DiGraph()
        return None  # fallback mode: plain dict

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def add_node(self, node_id: str, entity_type: str, **attrs) -> None:
        """Add or update a node."""
        if entity_type not in ENTITY_TYPES:
            entity_type = "related_to"  # safe fallback

        if _NX_AVAILABLE and self._g is not None:
            self._g.add_node(node_id, entity_type=entity_type, **attrs)
        else:
            # fallback: store in _nodes dict
            if not hasattr(self, "_nodes"):
                self._nodes: dict = {}
            self._nodes[node_id] = {"entity_type": entity_type, **attrs}

    def get_node(self, node_id: str) -> dict | None:
        if _NX_AVAILABLE and self._g is not None:
            if self._g.has_node(node_id):
                return dict(self._g.nodes[node_id])
            return None
        return getattr(self, "_nodes", {}).get(node_id)

    def has_node(self, node_id: str) -> bool:
        if _NX_AVAILABLE and self._g is not None:
            return self._g.has_node(node_id)
        return node_id in getattr(self, "_nodes", {})

    def node_count(self) -> int:
        if _NX_AVAILABLE and self._g is not None:
            return self._g.number_of_nodes()
        return len(getattr(self, "_nodes", {}))

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def add_edge(self, source: str, target: str, rel_type: str, **attrs) -> None:
        """Add a directed edge between two nodes."""
        if rel_type not in RELATIONSHIP_TYPES:
            rel_type = "related_to"

        if _NX_AVAILABLE and self._g is not None:
            self._g.add_edge(source, target, rel_type=rel_type, **attrs)
        else:
            if not hasattr(self, "_edges"):
                self._edges: list = []
            self._edges.append({
                "source": source, "target": target, "rel_type": rel_type, **attrs
            })

    def edge_count(self) -> int:
        if _NX_AVAILABLE and self._g is not None:
            return self._g.number_of_edges()
        return len(getattr(self, "_edges", []))

    def neighbors(self, node_id: str, depth: int = 1) -> list[dict]:
        """Return neighbors up to `depth` hops from node_id."""
        if not self.has_node(node_id):
            return []

        if _NX_AVAILABLE and self._g is not None:
            try:
                ego = nx.ego_graph(self._g, node_id, radius=depth)
                return [
                    {"node_id": n, **dict(ego.nodes[n])}
                    for n in ego.nodes
                    if n != node_id
                ]
            except Exception:
                return []

        # Fallback: 1-hop only from edges
        result = []
        for e in getattr(self, "_edges", []):
            if e["source"] == node_id:
                n = self.get_node(e["target"]) or {}
                result.append({"node_id": e["target"], **n})
            elif e["target"] == node_id:
                n = self.get_node(e["source"]) or {}
                result.append({"node_id": e["source"], **n})
        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist graph to SQLite (agent_graph + agent_graph_edges tables)."""
        self._save_to_sqlite(self._to_dict())

    def _save_to_sqlite(self, data: dict) -> None:
        """Upsert all nodes and edges into the agent_graph SQLite tables."""
        import json
        if not _DB_AVAILABLE or _DB_PATH is None:
            return
        try:
            _db_init_db(_DB_PATH)
            with _db_get_connection(_DB_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_graph (
                        id TEXT PRIMARY KEY,
                        type TEXT,
                        label TEXT,
                        meta TEXT
                    )""")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_graph_edges (
                        id TEXT PRIMARY KEY,
                        source TEXT,
                        target TEXT,
                        relation TEXT,
                        meta TEXT
                    )""")
                pid = self.project_id  # injected into every row for filtering
                for node in data.get("nodes", []):
                    nid = node.get("id")
                    if not nid:
                        continue
                    meta = {k: v for k, v in node.items()
                            if k not in ("id", "entity_type")}
                    meta.setdefault("project_id", pid)
                    conn.execute(
                        "INSERT OR REPLACE INTO agent_graph(id, type, label, meta) "
                        "VALUES (?, ?, ?, ?)",
                        (nid,
                         node.get("entity_type", ""),
                         node.get("label", nid),
                         json.dumps(meta)),
                    )
                for edge in data.get("edges", []):
                    src = edge.get("source")
                    tgt = edge.get("target")
                    if not src or not tgt:
                        continue
                    edge_id = f"{src}__{edge.get('rel_type', 'related_to')}__{tgt}__{pid}"
                    meta = {k: v for k, v in edge.items()
                            if k not in ("source", "target", "rel_type")}
                    meta.setdefault("project_id", pid)
                    conn.execute(
                        "INSERT OR REPLACE INTO agent_graph_edges"
                        "(id, source, target, relation, meta) VALUES (?, ?, ?, ?, ?)",
                        (edge_id, src, tgt,
                         edge.get("rel_type", "related_to"),
                         json.dumps(meta)),
                    )
        except Exception:
            pass  # DB write failure is non-fatal; in-memory graph remains valid

    def _load(self) -> None:
        """Load from SQLite (agent_graph + agent_graph_edges tables)."""
        self._load_from_sqlite()

    def _load_from_sqlite(self) -> bool:
        """Load nodes and edges from SQLite. Returns True if data was found."""
        import json
        if not _DB_AVAILABLE or _DB_PATH is None:
            return False
        try:
            with _db_get_connection(_DB_PATH) as conn:
                # Check tables exist
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                if "agent_graph" not in tables:
                    return False

                # For project-scoped graphs, filter by project_id in meta
                # For the global graph, load everything
                if self.project_id == GLOBAL_PROJECT_ID:
                    node_rows = conn.execute(
                        "SELECT id, type, label, meta FROM agent_graph"
                    ).fetchall()
                    edge_rows = conn.execute(
                        "SELECT source, target, relation, meta FROM agent_graph_edges"
                    ).fetchall()
                else:
                    node_rows = conn.execute(
                        "SELECT id, type, label, meta FROM agent_graph "
                        "WHERE meta LIKE ?",
                        (f'%"project_id": "{self.project_id}"%',),
                    ).fetchall()
                    edge_rows = conn.execute(
                        "SELECT source, target, relation, meta "
                        "FROM agent_graph_edges "
                        "WHERE meta LIKE ?",
                        (f'%"project_id": "{self.project_id}"%',),
                    ).fetchall()

                if not node_rows and not edge_rows:
                    return False

                for row in node_rows:
                    meta = json.loads(row["meta"] or "{}")
                    self.add_node(row["id"], row["type"] or "related_to",
                                  label=row["label"], **meta)
                for row in edge_rows:
                    meta = json.loads(row["meta"] or "{}")
                    self.add_edge(row["source"], row["target"],
                                  row["relation"] or "related_to", **meta)
                return True
        except Exception:
            return False

    def _to_dict(self) -> dict:
        if _NX_AVAILABLE and self._g is not None:
            nodes = [
                {"id": n, **dict(self._g.nodes[n])}
                for n in self._g.nodes
            ]
            edges = [
                {"source": u, "target": v, **dict(self._g.edges[u, v])}
                for u, v in self._g.edges
            ]
        else:
            nodes = [{"id": k, **v} for k, v in getattr(self, "_nodes", {}).items()]
            edges = list(getattr(self, "_edges", []))

        return {
            "project_id": self.project_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "nodes": nodes,
            "edges": edges,
        }

    def _from_dict(self, data: dict) -> None:
        for node in data.get("nodes", []):
            nid = node.pop("id", None)
            if nid:
                etype = node.pop("entity_type", "related_to")
                self.add_node(nid, etype, **node)
        for edge in data.get("edges", []):
            src = edge.pop("source", None)
            tgt = edge.pop("target", None)
            rel = edge.pop("rel_type", "related_to")
            if src and tgt:
                self.add_edge(src, tgt, rel, **edge)


# ---------------------------------------------------------------------------
# GraphMemory — public interface
# ---------------------------------------------------------------------------

class GraphMemory:
    """
    Public interface for graph-based context retrieval.

    Provides query(), get_related(), and write_episode() — the three operations
    used by prompt_assembler and handoff_engine.
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.store = GraphStore(project_id)
        # Global overlay — omitted when we ARE the global graph to avoid recursion
        self._global_store: GraphStore | None = (
            None if project_id == GLOBAL_PROJECT_ID
            else GraphStore(GLOBAL_PROJECT_ID)
        )

    # ------------------------------------------------------------------
    # query() — retrieve relevant facts for a prompt injection
    # ------------------------------------------------------------------

    def query(self, agent_id: str, context: str = "", max_tokens: int = MAX_INJECT_TOKENS) -> dict:
        local_facts = self._collect_facts(self.store, agent_id, context)
        for f in local_facts:
            f["scope"] = "local"

        global_facts: list[dict] = []
        if self._global_store is not None:
            global_facts = self._collect_facts(self._global_store, agent_id, context)
            for f in global_facts:
                f["scope"] = "global"

        seen: set[str] = set()
        merged: list[dict] = []
        for f in local_facts + global_facts:
            key = f["summary"]
            if key not in seen:
                seen.add(key)
                merged.append(f)

        result_lines = [f"[{f['type']}] {f['summary']}" for f in merged]
        bounded = self._bound_to_tokens(result_lines, max_tokens)
        bounded_facts = merged[:len(bounded)]

        token_estimate = _tc.count("\n".join(bounded)) if _tc else len("\n".join(bounded)) // 4

        return {
            "agent_id": agent_id,
            "context_used": context,
            "facts": bounded_facts,
            "token_estimate": token_estimate,
        }

    def _collect_facts(self, store: "GraphStore", agent_id: str, context: str) -> list[dict]:
        facts: list[dict] = []

        if store.has_node(agent_id):
            neighbors = store.neighbors(agent_id, depth=2)
            for n in neighbors[:MAX_QUERY_RESULTS]:
                ntype = n.get("entity_type", "unknown")
                label = n.get("label") or n.get("node_id", "")
                facts.append({"type": ntype, "summary": label})

        if context:
            keywords = set(context.lower().split())
            if _NX_AVAILABLE and store._g is not None:
                for node_id, attrs in store._g.nodes(data=True):
                    label = str(attrs.get("label", "")).lower()
                    if any(kw in label for kw in keywords):
                        facts.append({
                            "type": attrs.get("entity_type", "unknown"),
                            "summary": attrs.get("label", node_id),
                        })
            else:
                for nid, attrs in getattr(store, "_nodes", {}).items():
                    label = str(attrs.get("label", "")).lower()
                    if any(kw in label for kw in keywords):
                        facts.append({
                            "type": attrs.get("entity_type", "unknown"),
                            "summary": attrs.get("label", nid),
                        })

        return facts

    # ------------------------------------------------------------------
    # get_related() — neighborhood lookup
    # ------------------------------------------------------------------

    def get_related(self, node_id: str, rel_type: str | None = None, depth: int = 1) -> list[dict]:
        neighbors = self.store.neighbors(node_id, depth=depth)
        if rel_type is None:
            return neighbors

        if not _NX_AVAILABLE or self.store._g is None:
            return neighbors

        filtered = []
        for n in neighbors:
            nid = n.get("node_id", "")
            for u, v, data in self.store._g.edges(data=True):
                if data.get("rel_type") == rel_type and {u, v} == {node_id, nid}:
                    filtered.append(n)
                    break
        return filtered

    # ------------------------------------------------------------------
    # write_episode() — record a project event as a graph node + edges
    # ------------------------------------------------------------------

    def write_episode(self, episode_type: str, data: dict, mirror_to_global: bool = True) -> str:
        ts = datetime.now(timezone.utc).isoformat()
        episode_id = f"ep-{episode_type}-{ts[:19].replace(':', '').replace('T', '-') }"

        handlers = {
            "handoff": self._episode_handoff,
            "decision": self._episode_decision,
            "artifact": self._episode_artifact,
            "phase": self._episode_phase,
            "finding": self._episode_finding,
            "proposal": self._episode_proposal,
        }

        handler = handlers.get(episode_type, self._episode_generic)
        handler(episode_id, data, ts)

        try:
            self.store.save()
        except Exception:
            pass

        if mirror_to_global and self._global_store is not None:
            try:
                self._mirror_to_global(episode_type, data, ts)
                self._global_store.save()
            except Exception:
                pass

        return episode_id

    def _mirror_to_global(self, episode_type: str, data: dict, ts: str) -> None:
        g = self._global_store
        pid = self.project_id

        def _ensure_agent(aid: str) -> None:
            if not g.has_node(aid):
                g.add_node(aid, "agent", label=aid)
            if _NX_AVAILABLE and g._g is not None:
                if aid in g._g:
                    existing = g._g.nodes[aid].get("projects", "")
                    projects = set(existing.split(",")) if existing else set()
                    projects.add(pid)
                    g._g.nodes[aid]["projects"] = ",".join(sorted(projects))

        def _ensure_project() -> None:
            if not g.has_node(pid):
                g.add_node(pid, "project", label=pid)

        def _ensure_phase(phase: str) -> None:
            node_id = f"{pid}:{phase}"
            if not g.has_node(node_id):
                g.add_node(node_id, "phase", label=f"{pid}:{phase}", project=pid)
            _ensure_project()
            if not any(
                True for u, v, _ in (g._g.edges(data=True) if _NX_AVAILABLE and g._g else [])
                if u == pid and v == node_id
            ):
                g.add_edge(pid, node_id, "completed", timestamp=ts)

        if episode_type == "handoff":
            from_agent = data.get("from_agent", "")
            to_agent = data.get("to_agent", "")
            phase = data.get("phase", "")
            if from_agent:
                _ensure_agent(from_agent)
            if to_agent:
                _ensure_agent(to_agent)
            if from_agent and to_agent:
                g.add_edge(from_agent, to_agent, "handoff_to",
                           project=pid, phase=phase, timestamp=ts)
            if phase:
                _ensure_phase(phase)

        elif episode_type == "phase":
            phase = data.get("phase", "")
            if phase:
                _ensure_phase(phase)

        elif episode_type == "artifact":
            created_by = data.get("created_by", "")
            name = data.get("name", "")
            if created_by:
                _ensure_agent(created_by)
            if name:
                artifact_id = f"{pid}:artifact:{name[:40]}"
                if not g.has_node(artifact_id):
                    g.add_node(artifact_id, "artifact",
                               label=f"artifact:{name[:40]}", project=pid)
                if created_by:
                    g.add_edge(created_by, artifact_id, "produced",
                               project=pid, timestamp=ts)

        elif episode_type == "decision":
            made_by = data.get("made_by", "")
            label = data.get("label", data.get("decision", ""))
            if made_by:
                _ensure_agent(made_by)
            _ensure_project()
            if label:
                dec_id = f"{pid}:decision:{label[:40]}"
                if not g.has_node(dec_id):
                    g.add_node(dec_id, "decision",
                               label=f"decision:{label[:40]}", project=pid)
                if made_by:
                    g.add_edge(made_by, dec_id, "decided",
                               project=pid, timestamp=ts)

        elif episode_type == "finding":
            agent = data.get("agent", "")
            label = data.get("label", data.get("description", ""))
            if agent:
                _ensure_agent(agent)
            _ensure_project()
            if label:
                find_id = f"{pid}:finding:{label[:40]}"
                if not g.has_node(find_id):
                    g.add_node(find_id, "finding",
                               label=f"finding:{label[:40]}", project=pid)
                if agent:
                    g.add_edge(agent, find_id, "found",
                               project=pid, timestamp=ts)

    def _episode_handoff(self, eid: str, data: dict, ts: str) -> None:
        from_agent = data.get("from_agent", "unknown")
        to_agent = data.get("to_agent", "unknown")
        phase = data.get("phase", "unknown")
        task = data.get("task_description", "")[:60]

        self._ensure_agent_node(from_agent)
        self._ensure_agent_node(to_agent)
        self._ensure_phase_node(phase)

        self.store.add_node(eid, "handoff",
                            label=f"handoff:{from_agent}→{to_agent}:{phase}",
                            task=task, timestamp=ts)
        self.store.add_edge(from_agent, eid, "handoff_to", timestamp=ts)
        self.store.add_edge(eid, to_agent, "handoff_to", timestamp=ts)
        self.store.add_edge(eid, phase, "completed", timestamp=ts)

    def _episode_decision(self, eid: str, data: dict, ts: str) -> None:
        made_by = data.get("made_by", "unknown")
        desc = data.get("description", "")[:80]
        decision_id = data.get("decision_id", eid)

        self._ensure_agent_node(made_by)
        self.store.add_node(decision_id, "decision",
                            label=f"decision:{desc}", timestamp=ts)
        self.store.add_edge(made_by, decision_id, "decided", timestamp=ts)

    def _episode_artifact(self, eid: str, data: dict, ts: str) -> None:
        created_by = data.get("created_by", "unknown")
        name = data.get("name", "")[:60]
        artifact_id = data.get("artifact_id", eid)

        self._ensure_agent_node(created_by)
        self.store.add_node(artifact_id, "artifact",
                            label=f"artifact:{name}", timestamp=ts)
        self.store.add_edge(created_by, artifact_id, "produced", timestamp=ts)

    def _episode_phase(self, eid: str, data: dict, ts: str) -> None:
        phase_name = data.get("phase", "unknown")
        project_id = data.get("project_id", self.project_id)

        self._ensure_project_node(project_id)
        self._ensure_phase_node(phase_name)
        self.store.add_edge(project_id, phase_name, "completed", timestamp=ts)

    def _episode_finding(self, eid: str, data: dict, ts: str) -> None:
        desc = data.get("description", "")[:80]
        related_to = data.get("related_to", "")

        self.store.add_node(eid, "finding", label=f"finding:{desc}", timestamp=ts)
        if related_to and self.store.has_node(related_to):
            self.store.add_edge(eid, related_to, "related_to", timestamp=ts)

    def _episode_proposal(self, eid: str, data: dict, ts: str) -> None:
        proposal_id = data.get("proposal_id", eid)
        desc = data.get("description", "")[:80]
        target = data.get("target_agent", "system")

        self._ensure_agent_node(target)
        self.store.add_node(proposal_id, "proposal",
                            label=f"proposal:{desc}", timestamp=ts)
        self.store.add_edge("trainer_agent", proposal_id, "raised", timestamp=ts)
        self.store.add_edge(proposal_id, target, "related_to", timestamp=ts)

    def _episode_generic(self, eid: str, data: dict, ts: str) -> None:
        label = data.get("label") or data.get("description") or eid
        self.store.add_node(eid, "related_to", label=str(label)[:80], timestamp=ts)

    def _ensure_agent_node(self, agent_id: str) -> None:
        if not self.store.has_node(agent_id):
            self.store.add_node(agent_id, "agent", label=agent_id)

    def _ensure_phase_node(self, phase: str) -> None:
        if not self.store.has_node(phase):
            self.store.add_node(phase, "phase", label=phase)

    def _ensure_project_node(self, project_id: str) -> None:
        if not self.store.has_node(project_id):
            self.store.add_node(project_id, "project", label=project_id)

    def _bound_to_tokens(self, lines: list[str], max_tokens: int) -> list[str]:
        result = []
        total = 0
        for line in lines:
            cost = _tc.count(line) if _tc else len(line) // 4
            if total + cost > max_tokens:
                break
            result.append(line)
            total += cost
        return result

    def stats(self) -> dict:
        return {
            "project_id": self.project_id,
            "node_count": self.store.node_count(),
            "edge_count": self.store.edge_count(),
            "storage": "sqlite",
            "networkx_available": _NX_AVAILABLE,
        }


class EpisodeWriter:
    """
    Thin adapter between handoff_engine and GraphMemory.
    Called after each handoff_engine.create() to record the event.
    """

    def __init__(self, project_id: str):
        self._gm = GraphMemory(project_id)

    def record_handoff(self, handoff: dict) -> str:
        return self._gm.write_episode("handoff", {
            "from_agent": handoff.get("from_agent", ""),
            "to_agent": handoff.get("to_agent", ""),
            "phase": handoff.get("phase", ""),
            "task_description": handoff.get("task_description", ""),
        })

    def record_phase_transition(self, phase: str, project_id: str) -> str:
        return self._gm.write_episode("phase", {
            "phase": phase,
            "project_id": project_id,
        })

    @classmethod
    def replay_from_state(cls, project_id: str, shared_state: dict) -> int:
        writer = cls(project_id)
        gm = writer._gm
        count = 0

        wf = shared_state.get("workflow", {})
        artifacts_section = shared_state.get("artifacts", {})
        pd = shared_state.get("project_definition", {})
        ci = shared_state.get("core_identity", {})

        gm._ensure_project_node(project_id)
        count += 1

        for h in wf.get("handoff_history", []):
            from_agent = h.get("from_agent", "")
            to_agent = h.get("to_agent", "")
            phase = h.get("phase", "")
            task = h.get("task_description", "")
            ts = h.get("timestamp", datetime.now(timezone.utc).isoformat())
            if from_agent and to_agent:
                gm.write_episode("handoff", {
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "phase": phase,
                    "task_description": task,
                }, mirror_to_global=True)
                count += 1

        for phase in wf.get("completed_phases", []):
            gm.write_episode("phase", {
                "phase": phase,
                "project_id": project_id,
            }, mirror_to_global=True)
            count += 1

        for doc in artifacts_section.get("documents", []):
            if isinstance(doc, str):
                name, created_by = doc, ""
            else:
                name = doc.get("name", "")
                created_by = doc.get("created_by", "")
            if name:
                gm.write_episode("artifact", {
                    "name": name,
                    "created_by": created_by or "scribe_agent",
                }, mirror_to_global=True)
                count += 1

        goal = pd.get("project_goal", "") or pd.get("clarified_specification", {})
        if isinstance(goal, str) and goal:
            gm.write_episode("decision", {
                "made_by": "master_orchestrator",
                "description": goal[:80],
                "decision_id": f"{project_id}:goal",
            }, mirror_to_global=True)
            count += 1

        return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Graph Memory CLI",
        epilog="uv run python mas/core/graph_memory.py stats --project-id proj-001",
    )
    sub = parser.add_subparsers(dest="command")

    s = sub.add_parser("stats", help="Show graph statistics for a project")
    s.add_argument("--project-id", required=True)

    q = sub.add_parser("query", help="Query graph for agent context")
    q.add_argument("--project-id", required=True)
    q.add_argument("--agent", required=True)
    q.add_argument("--context", default="")

    ep = sub.add_parser("episodes", help="List recent episodes (nodes)")
    ep.add_argument("--project-id", required=True)
    ep.add_argument("--limit", type=int, default=20)

    gs = sub.add_parser("global-stats", help="Show cross-project global graph statistics")

    gq = sub.add_parser("global-query", help="Query the global graph for an agent")
    gq.add_argument("--agent", required=True)
    gq.add_argument("--context", default="")

    rp = sub.add_parser("replay", help="Back-populate graph memory from a project's shared_state.yaml")
    rp.add_argument("--project-id", required=True)

    ns = parser.parse_args()

    if ns.command == "stats":
        gm = GraphMemory(ns.project_id)
        s = gm.stats()
        print(json.dumps(s, indent=2))
        return 0

    if ns.command == "query":
        gm = GraphMemory(ns.project_id)
        result = gm.query(ns.agent, ns.context)
        print(json.dumps(result, indent=2))
        return 0

    if ns.command == "episodes":
        gm = GraphMemory(ns.project_id)
        store = gm.store
        if _NX_AVAILABLE and store._g is not None:
            nodes = list(store._g.nodes(data=True))[-ns.limit:]
        else:
            nodes = list(getattr(store, "_nodes", {}).items())[-ns.limit:]
        for nid, attrs in nodes:
            print(f"  {nid}: {attrs.get('entity_type', '?')} — {attrs.get('label', '')}")
        return 0

    if ns.command == "global-stats":
        store = GraphStore(GLOBAL_PROJECT_ID)
        out = {
            "storage": "sqlite",
            "node_count": store.node_count(),
            "edge_count": store.edge_count(),
            "networkx_available": _NX_AVAILABLE,
        }
        print(json.dumps(out, indent=2))
        return 0

    if ns.command == "global-query":
        gm = GraphMemory(GLOBAL_PROJECT_ID)
        result = gm.query(ns.agent, ns.context)
        print(json.dumps(result, indent=2))
        return 0

    if ns.command == "replay":
        state_path = ROOT / "projects" / ns.project_id / "shared_state.yaml"
        if not state_path.exists():
            print(f"ERROR: {state_path} not found", file=sys.stderr)
            return 1
        with state_path.open(encoding="utf-8") as f:
            state = yaml.safe_load(f) or {}
        n = EpisodeWriter.replay_from_state(ns.project_id, state)
        print(json.dumps({"project_id": ns.project_id, "episodes_written": n}, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
