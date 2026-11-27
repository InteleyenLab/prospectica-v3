"""Rehidratador post-cierre: reconstruye actores y memoria sin requerir subproceso OASIS activo."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class SwarmRehydrator:
    """Rehidrata perfiles, acciones históricas, analytics_bundle y SQLite aunque `env_status == stopped`."""

    def __init__(self, simulation_id: str, sim_dir: Path):
        self.simulation_id = simulation_id
        self.sim_dir = Path(sim_dir)

    def load_profiles(self) -> List[Dict[str, Any]]:
        enriched = self.sim_dir / "profiles_enriched.json"
        if enriched.exists():
            try:
                raw = json.loads(enriched.read_text(encoding="utf-8"))
                profs = raw.get("profiles") if isinstance(raw, dict) else raw
                if isinstance(profs, list) and profs:
                    return profs
            except Exception:
                pass

        reddit_prof = self.sim_dir / "reddit_profiles.json"
        if reddit_prof.exists():
            try:
                raw = json.loads(reddit_prof.read_text(encoding="utf-8"))
                if isinstance(raw, list) and raw:
                    return raw
            except Exception:
                pass
        return []

    def load_actor_memories(self, actor_name: str, actor_id: Optional[int] = None, limit: int = 8) -> List[str]:
        """Recupera citas o acciones reales del actor en `simulation_channels.db` o JSONL legado."""
        memories: List[str] = []
        channels_db = self.sim_dir / "simulation_channels.db"
        if channels_db.exists():
            conn = sqlite3.connect(str(channels_db), timeout=15.0)
            conn.row_factory = sqlite3.Row
            try:
                if actor_id is not None:
                    rows = conn.execute(
                        "SELECT channel_id, content_text FROM channel_events WHERE actor_agent_id = ? LIMIT ?",
                        (actor_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT channel_id, content_text FROM channel_events WHERE LOWER(actor_name) = LOWER(?) LIMIT ?",
                        (actor_name, limit),
                    ).fetchall()
                for r in rows:
                    memories.append(f"[{r['channel_id']}] {r['content_text']}")
            finally:
                conn.close()

        if not memories:
            for plat in ("reddit", "twitter"):
                jsonl = self.sim_dir / plat / "actions.jsonl"
                if not jsonl.exists():
                    continue
                for line in jsonl.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if raw.get("event_type"):
                        continue
                    same_id = actor_id is not None and raw.get("agent_id") == actor_id
                    same_name = str(raw.get("agent_name") or "").lower() == actor_name.lower()
                    if same_id or same_name:
                        args = raw.get("action_args") or {}
                        text = args.get("content") or args.get("quote_content") or raw.get("action_type", "")
                        if text:
                            memories.append(f"[legacy_{plat}] {text}")
                            if len(memories) >= limit:
                                break
        return memories

    def load_analytics_bundle(self) -> Optional[Dict[str, Any]]:
        path = self.sim_dir / "analytics_bundle.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def query_channel_sql(self, channel_id: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        channels_db = self.sim_dir / "simulation_channels.db"
        if not channels_db.exists():
            return []
        conn = sqlite3.connect(str(channels_db), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            if channel_id:
                rows = conn.execute(
                    "SELECT actor_name, city_name, stratum_code, channel_id, content_text, objection_tag "
                    "FROM channel_events WHERE channel_id = ? LIMIT ?",
                    (channel_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT actor_name, city_name, stratum_code, channel_id, content_text, objection_tag "
                    "FROM channel_events LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def rehydrate_context(self) -> Dict[str, Any]:
        profiles = self.load_profiles()
        bundle = self.load_analytics_bundle()
        env_status = "stopped"
        env_path = self.sim_dir / "env_status.json"
        if env_path.exists():
            try:
                env_status = json.loads(env_path.read_text(encoding="utf-8")).get("status", "stopped")
            except Exception:
                pass
        return {
            "simulation_id": self.simulation_id,
            "env_status": env_status,
            "profiles_count": len(profiles),
            "known_agents": [
                str(p.get("name") or p.get("username") or f"Agente_{i}")
                for i, p in enumerate(profiles)
            ],
            "has_analytics_bundle": bundle is not None,
        }
