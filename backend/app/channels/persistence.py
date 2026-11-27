"""Persistencia unificada en SQLite WAL (`simulation_channels.db`) y archivos JSONL por canal."""

from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import ChannelEvent


class JSONLAppender:
    """Escritor incremental por canal en `channels/<channel_id>/actions.jsonl`."""

    def __init__(self, sim_dir: Path):
        self.sim_dir = Path(sim_dir)

    def append_event(self, event: ChannelEvent) -> Path:
        channel_dir = self.sim_dir / "channels" / event.channel_id
        channel_dir.mkdir(parents=True, exist_ok=True)
        path = channel_dir / "actions.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return path

    def read_events(self, channel_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        path = self.sim_dir / "channels" / channel_id / "actions.jsonl"
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows[-limit:]


class ChannelSQLiteStore:
    """Almacén SQLite WAL con las 5 tablas canónicas de Fase 3 + lectura legada."""

    SCHEMA_SQL = """
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;

    CREATE TABLE IF NOT EXISTS channel_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        simulation_id TEXT NOT NULL,
        actor_agent_id INTEGER NOT NULL,
        actor_name TEXT NOT NULL,
        city_divipola TEXT NOT NULL,
        city_name TEXT NOT NULL,
        stratum_code TEXT NOT NULL,
        region_macro TEXT NOT NULL,
        attitude_segment TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        round_num INTEGER NOT NULL,
        simulated_hour INTEGER NOT NULL,
        action_type TEXT NOT NULL,
        content_text TEXT NOT NULL,
        sentiment_score REAL DEFAULT 0.0,
        objection_tag TEXT,
        is_friction INTEGER DEFAULT 0,
        metadata_json TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS whatsapp_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        simulation_id TEXT NOT NULL,
        session_key TEXT NOT NULL,
        actor_agent_id INTEGER NOT NULL,
        actor_name TEXT NOT NULL,
        city_divipola TEXT NOT NULL,
        city_name TEXT NOT NULL,
        stratum_code TEXT NOT NULL,
        region_macro TEXT NOT NULL,
        round_num INTEGER NOT NULL,
        message_role TEXT NOT NULL,
        message_type TEXT NOT NULL,
        content_text TEXT NOT NULL,
        audio_transcript TEXT,
        duration_sec INTEGER DEFAULT 0,
        payment_friction_tag TEXT,
        objection_tag TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS focus_group_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        simulation_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        block_name TEXT NOT NULL,
        round_num INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        actor_agent_id INTEGER NOT NULL,
        actor_name TEXT NOT NULL,
        city_divipola TEXT NOT NULL,
        city_name TEXT NOT NULL,
        stratum_code TEXT NOT NULL,
        region_macro TEXT NOT NULL,
        attitude_segment TEXT NOT NULL,
        content_text TEXT NOT NULL,
        objection_tag TEXT,
        consensus_signal REAL DEFAULT 0.0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS survey_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        simulation_id TEXT NOT NULL,
        respondent_id TEXT NOT NULL,
        actor_agent_id INTEGER,
        channel_origin TEXT NOT NULL DEFAULT 'structured_survey',
        status TEXT NOT NULL DEFAULT 'completed',
        city_divipola TEXT NOT NULL,
        city_name TEXT NOT NULL,
        region_macro TEXT NOT NULL,
        stratum_code TEXT NOT NULL,
        wealth_tier_norm INTEGER NOT NULL,
        age INTEGER NOT NULL,
        gender TEXT NOT NULL,
        dynamic_study_role TEXT NOT NULL,
        attitude_segment TEXT NOT NULL,
        pain_score INTEGER,
        trust_score INTEGER,
        nps_score INTEGER,
        csat_score INTEGER,
        ces_score INTEGER,
        vw_too_cheap REAL,
        vw_cheap REAL,
        vw_expensive REAL,
        vw_too_expensive REAL,
        nms_intent_cheap INTEGER,
        nms_intent_expensive INTEGER,
        gg_grid_json TEXT,
        preferred_channel TEXT,
        main_objection TEXT,
        verbatim_response TEXT,
        respondent_weight REAL DEFAULT 1.0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS media_exposures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        simulation_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        round_num INTEGER NOT NULL,
        simulated_hour INTEGER NOT NULL,
        actor_agent_id INTEGER NOT NULL,
        actor_name TEXT NOT NULL,
        city_divipola TEXT NOT NULL,
        stratum_code TEXT NOT NULL,
        region_macro TEXT NOT NULL,
        piece_format TEXT NOT NULL,
        time_slot TEXT,
        recall_score REAL DEFAULT 0.0,
        comprehension_score REAL DEFAULT 0.0,
        credibility_score REAL DEFAULT 0.0,
        prohibited_promise_rejected INTEGER DEFAULT 0,
        reaction_text TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_channel_events_sim_chan ON channel_events(simulation_id, channel_id, round_num);
    CREATE INDEX IF NOT EXISTS idx_whatsapp_sim ON whatsapp_sessions(simulation_id);
    CREATE INDEX IF NOT EXISTS idx_focus_sim ON focus_group_turns(simulation_id);
    CREATE INDEX IF NOT EXISTS idx_survey_sim ON survey_responses(simulation_id, status);
    CREATE INDEX IF NOT EXISTS idx_media_sim ON media_exposures(simulation_id, channel_id);
    """

    def __init__(self, sim_dir: Path):
        self.sim_dir = Path(sim_dir)
        self.sim_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.sim_dir / "simulation_channels.db"
        self.jsonl = JSONLAppender(self.sim_dir)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript(self.SCHEMA_SQL)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(channel_events)").fetchall()}
            if "is_friction" not in cols:
                conn.execute("ALTER TABLE channel_events ADD COLUMN is_friction INTEGER DEFAULT 0")
            conn.commit()

    def record_channel_event(self, simulation_id: str, event: ChannelEvent, write_jsonl: bool = True) -> None:
        is_fric = int(bool(getattr(event, "is_friction", bool(event.objection_tag))))
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO channel_events (
                    simulation_id, actor_agent_id, actor_name, city_divipola, city_name,
                    stratum_code, region_macro, attitude_segment, channel_id, round_num,
                    simulated_hour, action_type, content_text, sentiment_score, objection_tag,
                    is_friction, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    simulation_id,
                    event.actor_agent_id,
                    event.actor_name,
                    event.city_divipola,
                    event.city_name,
                    event.stratum_code,
                    event.region_macro,
                    event.attitude_segment,
                    event.channel_id,
                    event.round_num,
                    event.simulated_hour,
                    event.action_type,
                    event.content_text,
                    event.sentiment_score,
                    event.objection_tag,
                    is_fric,
                    json.dumps(event.metadata, ensure_ascii=False),
                    event.created_at,
                ),
            )
            conn.commit()
        if write_jsonl:
            self.jsonl.append_event(event)

    def record_whatsapp_session(self, simulation_id: str, row: Dict[str, Any]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO whatsapp_sessions (
                    simulation_id, session_key, actor_agent_id, actor_name, city_divipola,
                    city_name, stratum_code, region_macro, round_num, message_role,
                    message_type, content_text, audio_transcript, duration_sec,
                    payment_friction_tag, objection_tag, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    simulation_id,
                    row["session_key"],
                    row["actor_agent_id"],
                    row["actor_name"],
                    row["city_divipola"],
                    row["city_name"],
                    row["stratum_code"],
                    row["region_macro"],
                    row["round_num"],
                    row["message_role"],
                    row["message_type"],
                    row["content_text"],
                    row.get("audio_transcript"),
                    row.get("duration_sec", 0),
                    row.get("payment_friction_tag"),
                    row.get("objection_tag"),
                    row["created_at"],
                ),
            )
            conn.commit()

    def record_focus_group_turn(self, simulation_id: str, row: Dict[str, Any]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO focus_group_turns (
                    simulation_id, session_id, block_name, round_num, turn_index,
                    actor_agent_id, actor_name, city_divipola, city_name, stratum_code,
                    region_macro, attitude_segment, content_text, objection_tag,
                    consensus_signal, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    simulation_id,
                    row["session_id"],
                    row["block_name"],
                    row["round_num"],
                    row["turn_index"],
                    row["actor_agent_id"],
                    row["actor_name"],
                    row["city_divipola"],
                    row["city_name"],
                    row["stratum_code"],
                    row["region_macro"],
                    row["attitude_segment"],
                    row["content_text"],
                    row.get("objection_tag"),
                    row.get("consensus_signal", 0.0),
                    row["created_at"],
                ),
            )
            conn.commit()

    def record_survey_responses_bulk(self, simulation_id: str, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        with closing(self._connect()) as conn, conn:
            conn.executemany(
                """
                INSERT INTO survey_responses (
                    simulation_id, respondent_id, actor_agent_id, channel_origin, status,
                    city_divipola, city_name, region_macro, stratum_code, wealth_tier_norm,
                    age, gender, dynamic_study_role, attitude_segment, pain_score,
                    trust_score, nps_score, csat_score, ces_score, vw_too_cheap,
                    vw_cheap, vw_expensive, vw_too_expensive, nms_intent_cheap,
                    nms_intent_expensive, gg_grid_json, preferred_channel,
                    main_objection, verbatim_response, respondent_weight, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        simulation_id,
                        r["respondent_id"],
                        r.get("actor_agent_id"),
                        r.get("channel_origin", "structured_survey"),
                        r.get("status", "completed"),
                        r["city_divipola"],
                        r["city_name"],
                        r["region_macro"],
                        r["stratum_code"],
                        r["wealth_tier_norm"],
                        r["age"],
                        r["gender"],
                        r["dynamic_study_role"],
                        r["attitude_segment"],
                        r.get("pain_score"),
                        r.get("trust_score"),
                        r.get("nps_score"),
                        r.get("csat_score"),
                        r.get("ces_score"),
                        r.get("vw_too_cheap"),
                        r.get("vw_cheap"),
                        r.get("vw_expensive"),
                        r.get("vw_too_expensive"),
                        r.get("nms_intent_cheap"),
                        r.get("nms_intent_expensive"),
                        json.dumps(r.get("gg_grid") or {}, ensure_ascii=False)
                        if not isinstance(r.get("gg_grid_json"), str)
                        else r["gg_grid_json"],
                        r.get("preferred_channel"),
                        r.get("main_objection"),
                        r.get("verbatim_response"),
                        r.get("respondent_weight", 1.0),
                        r["created_at"],
                    )
                    for r in rows
                ],
            )
            conn.commit()
        return len(rows)

    def record_media_exposure(self, simulation_id: str, row: Dict[str, Any]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO media_exposures (
                    simulation_id, channel_id, round_num, simulated_hour,
                    actor_agent_id, actor_name, city_divipola, stratum_code, region_macro,
                    piece_format, time_slot, recall_score, comprehension_score,
                    credibility_score, prohibited_promise_rejected, reaction_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    simulation_id,
                    row["channel_id"],
                    row["round_num"],
                    row["simulated_hour"],
                    row["actor_agent_id"],
                    row["actor_name"],
                    row["city_divipola"],
                    row["stratum_code"],
                    row["region_macro"],
                    row["piece_format"],
                    row.get("time_slot"),
                    row.get("recall_score", 0.0),
                    row.get("comprehension_score", 0.0),
                    row.get("credibility_score", 0.0),
                    1 if row.get("prohibited_promise_rejected") else 0,
                    row["reaction_text"],
                    row["created_at"],
                ),
            )
            conn.commit()

    def query_events(
        self,
        channel_id: Optional[str] = None,
        round_num: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
        simulation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM channel_events WHERE 1=1"
        params: List[Any] = []
        if simulation_id:
            sql += " AND simulation_id = ?"
            params.append(simulation_id)
        if channel_id:
            sql += " AND channel_id = ?"
            params.append(channel_id)
        if round_num is not None:
            sql += " AND round_num = ?"
            params.append(round_num)
        sql += " ORDER BY id ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with closing(self._connect()) as conn, conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            for r in rows:
                raw_meta = r.pop("metadata_json", None)
                r["metadata"] = json.loads(raw_meta) if raw_meta else {}
        if rows:
            return rows
        if simulation_id and self.sim_dir.name != simulation_id:
            return []
        return self._read_legacy_jsonl_fallback(channel_id=channel_id, limit=limit, offset=offset)

    def _read_legacy_jsonl_fallback(
        self,
        channel_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Lee `twitter/actions.jsonl` y `reddit/actions.jsonl` cuando la simulación es legada."""
        targets = []
        if channel_id in (None, "legacy_twitter", "twitter"):
            targets.append(("legacy_twitter", self.sim_dir / "twitter" / "actions.jsonl"))
        if channel_id in (None, "legacy_reddit", "reddit"):
            targets.append(("legacy_reddit", self.sim_dir / "reddit" / "actions.jsonl"))
        collected: List[Dict[str, Any]] = []
        for cid, path in targets:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if raw.get("event_type"):
                    continue
                args = raw.get("action_args") or {}
                text = args.get("content") or args.get("quote_content") or raw.get("action_type", "")
                collected.append(
                    {
                        "channel_id": cid,
                        "round_num": raw.get("round_num", 0),
                        "simulated_hour": 12,
                        "actor_agent_id": raw.get("agent_id", 0),
                        "actor_name": raw.get("agent_name", "Agente"),
                        "city_divipola": "11001",
                        "city_name": "Legado",
                        "stratum_code": "N/D",
                        "region_macro": "Legado",
                        "attitude_segment": "neutral",
                        "action_type": raw.get("action_type", "ACTION"),
                        "content_text": str(text),
                        "sentiment_score": 0.0,
                        "objection_tag": None,
                        "metadata": args,
                        "created_at": raw.get("timestamp", ""),
                    }
                )
        return collected[offset : offset + limit]

    def query_sessions(
        self,
        channel_id: str,
        limit: int = 200,
        simulation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with closing(self._connect()) as conn, conn:
            if channel_id == "whatsapp_1on1":
                if simulation_id:
                    sql = "SELECT * FROM whatsapp_sessions WHERE simulation_id = ? ORDER BY id ASC LIMIT ?"
                    params: tuple[Any, ...] = (simulation_id, limit)
                else:
                    sql = "SELECT * FROM whatsapp_sessions ORDER BY id ASC LIMIT ?"
                    params = (limit,)
                rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
                return {"channel_id": channel_id, "table": "whatsapp_sessions", "items": rows}
            if channel_id == "focus_group":
                if simulation_id:
                    sql = "SELECT * FROM focus_group_turns WHERE simulation_id = ? ORDER BY id ASC LIMIT ?"
                    params = (simulation_id, limit)
                else:
                    sql = "SELECT * FROM focus_group_turns ORDER BY id ASC LIMIT ?"
                    params = (limit,)
                rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
                return {"channel_id": channel_id, "table": "focus_group_turns", "items": rows}
            if channel_id in ("street_survey", "structured_survey"):
                sql = "SELECT * FROM survey_responses WHERE 1=1"
                q_params: List[Any] = []
                if simulation_id:
                    sql += " AND simulation_id = ?"
                    q_params.append(simulation_id)
                if channel_id == "street_survey":
                    sql += " AND channel_origin = 'street_survey'"
                elif channel_id == "structured_survey":
                    sql += " AND channel_origin = 'structured_survey'"
                sql += " ORDER BY id ASC LIMIT ?"
                q_params.append(limit)
                rows = [dict(r) for r in conn.execute(sql, q_params).fetchall()]
                return {"channel_id": channel_id, "table": "survey_responses", "items": rows}
            if channel_id in ("advertising", "tv", "radio", "tiktok", "instagram", "news_portals"):
                sql = "SELECT * FROM media_exposures WHERE channel_id = ?"
                m_params: List[Any] = [channel_id]
                if simulation_id:
                    sql += " AND simulation_id = ?"
                    m_params.append(simulation_id)
                sql += " ORDER BY id ASC LIMIT ?"
                m_params.append(limit)
                rows = [dict(r) for r in conn.execute(sql, m_params).fetchall()]
                if rows:
                    return {"channel_id": channel_id, "table": "media_exposures", "items": rows}

        events = self.query_events(
            channel_id=channel_id,
            limit=limit,
            offset=0,
            simulation_id=simulation_id,
        )
        return {"channel_id": channel_id, "table": "channel_events", "items": events}

    def query_surveys(
        self,
        simulation_id: Optional[str] = None,
        channel_origin: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Consulta respuestas de encuesta filtradas por simulación, origen y estado."""
        sql = "SELECT * FROM survey_responses WHERE 1=1"
        params: List[Any] = []
        if simulation_id:
            sql += " AND simulation_id = ?"
            params.append(simulation_id)
        if channel_origin:
            sql += " AND channel_origin = ?"
            params.append(channel_origin)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with closing(self._connect()) as conn, conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for r in rows:
            raw_gg = r.get("gg_grid_json")
            if isinstance(raw_gg, str) and raw_gg.strip():
                try:
                    r["gg_grid"] = json.loads(raw_gg)
                except json.JSONDecodeError:
                    r["gg_grid"] = {}
            elif not isinstance(r.get("gg_grid"), dict):
                r["gg_grid"] = {}
        return rows

    def clear_simulation_channel_data(
        self,
        simulation_id: str,
        include_street_surveys: bool = True,
        clear_jsonl: bool = True,
    ) -> Dict[str, int]:
        """Limpia eventos/sesiones/medios previos de `simulation_id` sin tocar encuestas estructuradas."""
        deleted: Dict[str, int] = {}
        with closing(self._connect()) as conn, conn:
            for table in ("channel_events", "whatsapp_sessions", "focus_group_turns", "media_exposures"):
                cur = conn.execute(f"DELETE FROM {table} WHERE simulation_id = ?", (simulation_id,))
                deleted[table] = int(cur.rowcount or 0)
            if include_street_surveys:
                cur = conn.execute(
                    "DELETE FROM survey_responses WHERE simulation_id = ? AND channel_origin = 'street_survey'",
                    (simulation_id,),
                )
                deleted["street_survey_responses"] = int(cur.rowcount or 0)
            remaining_other = conn.execute(
                "SELECT COUNT(*) AS cnt FROM channel_events WHERE simulation_id != ?",
                (simulation_id,),
            ).fetchone()["cnt"]
            conn.commit()

        if clear_jsonl and (self.sim_dir.name == simulation_id or remaining_other == 0):
            channels_root = self.sim_dir / "channels"
            if channels_root.exists():
                for jsonl_path in channels_root.glob("*/actions.jsonl"):
                    try:
                        jsonl_path.unlink()
                    except OSError:
                        pass
        return deleted

    def clear_simulation_surveys(
        self,
        simulation_id: str,
        channel_origin: Optional[str] = "structured_survey",
    ) -> int:
        """Limpia respuestas de encuesta previas de `simulation_id` (acotadas por `channel_origin`)."""
        with closing(self._connect()) as conn, conn:
            if channel_origin is not None:
                cur = conn.execute(
                    "DELETE FROM survey_responses WHERE simulation_id = ? AND channel_origin = ?",
                    (simulation_id, channel_origin),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM survey_responses WHERE simulation_id = ?",
                    (simulation_id,),
                )
            conn.commit()
            return int(cur.rowcount or 0)

    def summarize_channels(self, simulation_id: Optional[str] = None) -> Dict[str, Any]:
        """Devuelve conteos y última ronda por canal para monitoreo del runner."""
        summary: Dict[str, Dict[str, Any]] = {}
        with closing(self._connect()) as conn, conn:
            if simulation_id:
                rows = conn.execute(
                    """
                    SELECT channel_id, COUNT(*) AS actions_count, MAX(round_num) AS current_round
                    FROM channel_events
                    WHERE simulation_id = ?
                    GROUP BY channel_id
                    """,
                    (simulation_id,),
                ).fetchall()
                survey_count = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM survey_responses WHERE simulation_id = ?",
                    (simulation_id,),
                ).fetchone()["cnt"]
            else:
                rows = conn.execute(
                    """
                    SELECT channel_id, COUNT(*) AS actions_count, MAX(round_num) AS current_round
                    FROM channel_events
                    GROUP BY channel_id
                    """
                ).fetchall()
                survey_count = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM survey_responses"
                ).fetchone()["cnt"]

            for r in rows:
                summary[r["channel_id"]] = {
                    "actions_count": r["actions_count"],
                    "current_round": r["current_round"] or 0,
                }
            if survey_count > 0:
                summary["structured_survey"] = {
                    "actions_count": survey_count,
                    "current_round": 1,
                }
        return summary
