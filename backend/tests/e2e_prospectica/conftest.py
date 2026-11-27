"""Airtight tmp_path isolation, offline domain-reflecting stubs, and opaque-box pipeline helpers."""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pytest

from app import create_app
from app.channels.base import CANONICAL_CHANNEL_IDS
from app.config import Config
from app.models.project import ProjectManager
from app.models.task import TaskManager
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import RunnerStatus, SimulationRunState, SimulationRunner
from app.utils.zep import clear_zep_client_cache

from .fixtures_colombia import ColombianBusinessFixture

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REAL_UPLOADS_DIR = BACKEND_ROOT / "uploads"

_SPANISH_STOPWORDS = frozenset({
    "para", "como", "sobre", "entre", "desde", "hasta", "donde", "cuando", "porque",
    "bloque", "rol", "mision", "actua", "senior", "analista", "investigacion",
    "mercados", "validacion", "startups", "especializado", "colombia", "mercado",
    "inicial", "plan", "permita", "decidir", "idea", "debe", "avanzar", "pivotar",
    "detenerse", "busqueda", "apoyar", "cada", "afirmacion", "fuentes", "verificables",
    "contexto", "tareas", "formato", "salida", "reglas", "responde", "espanol",
    "cifras", "veredicto", "hipotesis", "criticas", "experimentos", "evaluada",
    "estructura", "precios", "estima", "analiza", "revisa", "marco", "define",
    "con", "los", "las", "del", "una", "uno", "unos", "unas", "por", "que", "sus",
    "este", "esta", "estos", "estas", "pero", "mas", "sin", "todo", "toda", "todos",
    "todas", "puede", "tener", "hacer", "ser", "son", "esta", "este", "mediante",
})


def _snapshot_uploads_dir(base: Path) -> Dict[str, Tuple[bool, int, int]]:
    """Snapshot relative paths -> (is_dir, size, mtime_ns) for leak detection."""
    if not base.exists():
        return {}
    snap: Dict[str, Tuple[bool, int, int]] = {}
    for p in base.rglob("*"):
        rel = str(p.relative_to(base))
        st = p.stat()
        snap[rel] = (p.is_dir(), 0 if p.is_dir() else st.st_size, st.st_mtime_ns)
    return snap


def _extract_domain_terms(text: str, limit: int = 8) -> List[str]:
    """Extract top domain keywords dynamically from prompt/document text (zero hardcoded brands)."""
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", text or "")
    counts = Counter(
        tok.lower()
        for tok in tokens
        if tok.lower() not in _SPANISH_STOPWORDS
    )
    return [word for word, _ in counts.most_common(limit)]


def _extract_cop_numbers(text: str) -> List[int]:
    """Extract plausible COP amounts mentioned in prompt/document text."""
    matches = re.findall(r"(?:COP|\$)\s*([\d.,]+)", text or "", re.I)
    values: List[int] = []
    for raw in matches:
        cleaned = raw.replace(".", "").replace(",", "").strip()
        if cleaned.isdigit():
            val = int(cleaned)
            if 500 <= val <= 100_000_000:
                values.append(val)
    return sorted(set(values))


def _guess_brand_from_messages(text: str) -> str:
    """Heuristically extract a non-boilerplate subject/brand from LLM messages."""
    for pat in (
        r"BLOQUE\s*2\s*-\s*CONTEXTO\s+DE\s+LA\s+IDEA\s*\(([^)]+)\)",
        r"investigar\s+el\s+mercado\s+de\s+([A-ZÁÉÍÓÚÑ][^\n,.]{2,55}?)\s+y\s+disenar",
        r"===\s*([^=\n]+?)\.(?:pdf|md|txt)\s*===",
    ):
        m = re.search(pat, text or "", re.I)
        if m:
            cand = m.group(1).strip().replace("_", " ")
            if cand and "BLOQUE" not in cand.upper():
                return cand[:80]
    terms = _extract_domain_terms(text, limit=3)
    return " ".join(w.capitalize() for w in terms) if terms else "Iniciativa Colombia"


def _build_offline_llm_payload(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Deterministic domain-reflecting JSON generator for external LLM boundaries."""
    sys_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
    user_text = "\n".join(m.get("content", "") for m in messages if m.get("role") != "system")
    combined = f"{sys_text}\n{user_text}"
    low = combined.lower()

    terms = _extract_domain_terms(user_text, limit=8)
    terms_label = ", ".join(terms[:5]) if terms else "comercio y servicios en Colombia"
    brand_guess = _guess_brand_from_messages(user_text)
    cop_vals = _extract_cop_numbers(user_text)

    # 1. OntologyGenerator schema
    if "entity_types" in low and "edge_types" in low:
        return {
            "entity_types": [
                {
                    "name": "Person",
                    "description": f"Ciudadano o usuario final interesado en {terms_label[:40]}",
                    "attributes": [{"name": "role", "type": "text", "description": "Rol en el mercado"}],
                    "examples": ["Comprador local", "Usuario frecuente"],
                },
                {
                    "name": "Customer",
                    "description": f"Cliente objetivo evaluando oferta de {brand_guess[:35]}",
                    "attributes": [{"name": "role", "type": "text", "description": "Segmento de cliente"}],
                    "examples": ["Cliente recurrente", "Comprador nuevo"],
                },
                {
                    "name": "Merchant",
                    "description": "Comerciante, operador o aliado prestador del servicio",
                    "attributes": [{"name": "role", "type": "text", "description": "Rol operativo"}],
                    "examples": ["Operador local", "Aliado comercial"],
                },
                {
                    "name": "Organization",
                    "description": f"Organización o empresa vinculada a {terms_label[:35]}",
                    "attributes": [{"name": "field", "type": "text", "description": "Sector económico"}],
                    "examples": [brand_guess[:40], "Competidor regional"],
                },
                {
                    "name": "Competitor",
                    "description": "Alternativa tradicional o competidor directo en Colombia",
                    "attributes": [{"name": "field", "type": "text", "description": "Modelo alternativo"}],
                    "examples": ["Alternativa tradicional", "Competidor digital"],
                },
                {
                    "name": "Regulator",
                    "description": "Entidad regulatoria o norma aplicable en Colombia",
                    "attributes": [{"name": "field", "type": "text", "description": "Ámbito normativo"}],
                    "examples": ["SIC Ley 1480", "Superintendencia / DIAN"],
                },
            ],
            "edge_types": [
                {
                    "name": "EVALUATES",
                    "description": "Cliente evalúa propuesta de valor y precio",
                    "source_targets": [{"source": "Customer", "target": "Organization"}],
                    "attributes": [],
                },
                {
                    "name": "USES",
                    "description": "Persona interactúa con el servicio u oferta",
                    "source_targets": [{"source": "Person", "target": "Organization"}],
                    "attributes": [],
                },
                {
                    "name": "COMPETES_WITH",
                    "description": "Competencia directa frente a alternativas actuales",
                    "source_targets": [{"source": "Organization", "target": "Competitor"}],
                    "attributes": [],
                },
                {
                    "name": "REGULATES",
                    "description": "Supervisión o cumplimiento normativo en Colombia",
                    "source_targets": [{"source": "Regulator", "target": "Organization"}],
                    "attributes": [],
                },
                {
                    "name": "PARTNERS_WITH",
                    "description": "Alianza operativa entre comercios y plataforma",
                    "source_targets": [{"source": "Merchant", "target": "Organization"}],
                    "attributes": [],
                },
            ],
            "analysis_summary": f"Ontología dinámica para {brand_guess} centrada en {terms_label} en Colombia.",
        }

    # 2. StudyContext schema (if study_context_builder uses LLM)
    if "price_ladder_cop" in low or "study_context" in low or "codebook_rules" in low:
        if len(cop_vals) >= 5:
            ladder = cop_vals[:5]
        elif cop_vals:
            mid = cop_vals[len(cop_vals) // 2]
            ladder = sorted({max(500, int(mid * f)) for f in (0.5, 0.75, 1.0, 1.4, 1.9)})
            while len(ladder) < 5:
                ladder.append(int(ladder[-1] * 1.35))
            ladder = ladder[:5]
        else:
            ladder = [15000, 25000, 40000, 60000, 85000]
        ref_price = ladder[len(ladder) // 2]
        slug = re.sub(r"[^a-z0-9]+", "_", brand_guess.lower()).strip("_") or "proyecto"
        return {
            "project_name": brand_guess,
            "project_slug": slug,
            "sector": f"mercado_{terms[0] if terms else 'colombia'}",
            "business_model": "B2B" if "b2b" in low or "saas" in low else "B2C",
            "geographic_scope": "Colombia",
            "value_proposition": f"Propuesta de valor de {brand_guess} enfocada en {terms_label}.",
            "offer_summary": f"{brand_guess}: solución enfocada en {terms_label}.",
            "price_ladder_cop": ladder,
            "reference_price_cop": ref_price,
            "unit_var_cost_cop": round(ref_price * 0.35, 2),
            "monthly_opex_cop": float(max(500_000, min(25_000_000, ref_price * 45))),
            "unit_label": "ventas/mes",
            "upsell_offer": None,
            "target_roles": [f"Cliente de {brand_guess}", f"Operador {terms[0] if terms else 'local'}", "Comprador digital", "Aliado comercial"],
            "competitors": ["Alternativa tradicional", "Oferta informal local"],
            "key_channels": ["whatsapp_1on1", "instagram", "street_survey", "facebook_groups"],
            "key_risks_objections": [f"Duda sobre precio de {brand_guess}", "Desconfianza en pago digital", "Preferencia por compra directa"],
            "regulatory_scope": ["Ley 1480 de 2011 (Protección al Consumidor)", "Ley 1581 de 2012 (Habeas Data)"],
            "domain_keywords": terms[:6] or ["servicio", "colombia", "precio"],
        }

    # 3. SurveyEngine batch schema
    if "respondentes colombianos" in low and "'responses'" in low:
        m_resp = re.search(r"Respondentes colombianos:\s*(\[.*?\])\s*\n", user_text, re.S)
        respondents = []
        if m_resp:
            try:
                respondents = json.loads(m_resp.group(1))
            except Exception:
                respondents = []
        out_resps = []
        for item in respondents:
            att = item.get("attitude", "neutral")
            slot = int(item.get("slot", 0))
            is_pos = att == "promotor"
            out_resps.append({
                "slot": slot,
                "pain_score": 7 if not is_pos else 8,
                "trust_score": 8 if is_pos else (4 if "critico" in att else 6),
                "nps_score": 9 if is_pos else (3 if "critico" in att else 7),
                "main_objection": "" if is_pos else f"Duda frente a {terms[0] if terms else 'la oferta'}",
                "verbatim": (
                    f"Me parece útil {brand_guess} para {terms[0] if terms else 'el día a día'}."
                    if is_pos
                    else f"Revisaría primero el precio y respaldo de {brand_guess}."
                ),
            })
        return {"responses": out_resps}

    # 4. SimulationConfigGenerator schemas
    if "total_simulation_hours" in low and "timezone" in low:
        return {
            "timezone": "America/Bogota",
            "utc_offset": "UTC-5",
            "total_simulation_hours": 72,
            "minutes_per_round": 60,
            "agents_per_hour_min": 2,
            "agents_per_hour_max": 10,
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4],
            "morning_hours": [5, 6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Configuración horaria offline para Colombia.",
        }

    if "hot_topics" in low and "initial_posts" in low:
        poster_types = re.findall(r"-\s*([A-Za-z0-9_]+)\s*:", user_text)
        pt_default = poster_types[0] if poster_types else "Person"
        return {
            "hot_topics": terms[:5] or ["precio", "confianza", "servicio"],
            "narrative_direction": f"Debate colombiano sobre {brand_guess} y {terms_label}.",
            "initial_posts": [
                {"content": f"Opiniones sobre {brand_guess} y su propuesta de {terms_label}?", "poster_type": pt_default},
            ],
            "reasoning": "Eventos iniciales derivados del estudio.",
        }

    if '"agent_configs"' in low:
        m_ents = re.search(r"```json\s*(\[.*?\])\s*```", user_text, re.S)
        ent_list = []
        if m_ents:
            try:
                ent_list = json.loads(m_ents.group(1))
            except Exception:
                ent_list = []
        stance_map = {
            "supportive": ("supportive", 0.65, 0.72),
            "opposing": ("opposing", -0.55, 0.60),
            "neutral": ("neutral", 0.05, 0.45),
            "observer": ("observer", 0.0, 0.25),
        }
        cfgs = []
        for idx, ent in enumerate(ent_list):
            sug = ent.get("suggested_stance", "neutral")
            stance, bias, act = stance_map.get(sug, ("neutral", 0.0, 0.5))
            cfgs.append({
                "agent_id": int(ent.get("agent_id", idx)),
                "activity_level": act,
                "posts_per_hour": 1.0,
                "comments_per_hour": 2.0,
                "active_hours": [9, 12, 19, 20, 21],
                "response_delay_min": 5,
                "response_delay_max": 45,
                "sentiment_bias": bias,
                "stance": stance,
                "influence_weight": 1.0,
            })
        return {"agent_configs": cfgs}

    return {"summary": f"Análisis de {brand_guess} ({terms_label})."}


class _FakeZepRegistry:
    """In-memory isolated graph/batch store keyed strictly by graph_id and batch_id."""

    def __init__(self) -> None:
        self.graphs: Dict[str, Dict[str, Any]] = {}
        self.batches: Dict[str, Dict[str, Any]] = {}
        self.episodes: Dict[str, Dict[str, Any]] = {}


def _build_fake_zep_client(registry: _FakeZepRegistry):
    """Build a Zep SDK-compatible in-memory client scoped per graph_id."""

    class _GraphNodeAPI:
        @property
        def with_raw_response(self):
            return self

        @staticmethod
        def get_by_graph_id(graph_id: str, limit: int = 100, cursor: Any = None):
            g = registry.graphs.get(graph_id, {})
            return SimpleNamespace(data=list(g.get("nodes", [])), headers={})

        @staticmethod
        def get(uuid_: str):
            for g in registry.graphs.values():
                for n in g.get("nodes", []):
                    if n.uuid_ == uuid_:
                        return n
            return None

        @staticmethod
        def get_edges(node_uuid: str):
            out = []
            for g in registry.graphs.values():
                for e in g.get("edges", []):
                    if e.source_node_uuid == node_uuid or e.target_node_uuid == node_uuid:
                        out.append(e)
            return out

    class _GraphEdgeAPI:
        @property
        def with_raw_response(self):
            return self

        @staticmethod
        def get_by_graph_id(graph_id: str, limit: int = 100, cursor: Any = None):
            g = registry.graphs.get(graph_id, {})
            return SimpleNamespace(data=list(g.get("edges", [])), headers={})

    class _GraphEpisodeAPI:
        @staticmethod
        def get(uuid_: str):
            ep = registry.episodes.get(uuid_, {})
            return SimpleNamespace(uuid_=uuid_, processed=ep.get("processed", True))

    class _GraphAPI:
        node = _GraphNodeAPI()
        edge = _GraphEdgeAPI()
        episode = _GraphEpisodeAPI()

        @staticmethod
        def create(graph_id: str, name: str = "", description: str = ""):
            registry.graphs[graph_id] = {
                "graph_id": graph_id,
                "name": name,
                "description": description,
                "entity_types": ["Person", "Customer", "Merchant", "Organization"],
                "nodes": [],
                "edges": [],
            }
            return SimpleNamespace(graph_id=graph_id, name=name)

        @staticmethod
        def get(graph_id: str):
            if graph_id not in registry.graphs:
                raise KeyError(graph_id)
            return SimpleNamespace(**registry.graphs[graph_id])

        @staticmethod
        def delete(graph_id: str):
            registry.graphs.pop(graph_id, None)

        @staticmethod
        def set_ontology(graph_ids: List[str], entities: Dict[str, Any], edges: Any = None):
            etypes = list((entities or {}).keys()) or ["Person", "Organization"]
            for gid in graph_ids:
                g = registry.graphs.setdefault(gid, {"graph_id": gid, "nodes": [], "edges": []})
                g["entity_types"] = etypes

        @staticmethod
        def search(graph_id: str, query: str = "", limit: int = 10, scope: str = "edges", **kwargs):
            g = registry.graphs.get(graph_id, {})
            edges = g.get("edges", [])[:limit]
            nodes = g.get("nodes", [])[:limit]
            return SimpleNamespace(edges=edges, nodes=nodes)

    class _BatchAPI:
        @staticmethod
        def create(metadata: Optional[Dict[str, Any]] = None):
            bid = f"batch_{uuid.uuid4().hex[:12]}"
            registry.batches[bid] = {
                "batch_id": bid,
                "metadata": dict(metadata or {}),
                "status": "draft",
                "items": [],
            }
            return SimpleNamespace(batch_id=bid, status="draft", metadata=metadata or {})

        @staticmethod
        def add(batch_id: str, items: List[Any]):
            b = registry.batches[batch_id]
            start_seq = len(b["items"])
            details = []
            combined_chunks: List[str] = []
            target_gid = None
            for idx, item in enumerate(items):
                ep_uuid = f"ep_{uuid.uuid4().hex[:12]}"
                gid = getattr(item, "graph_id", None)
                target_gid = target_gid or gid
                chunk_data = str(getattr(item, "data", "") or "")
                combined_chunks.append(chunk_data)
                registry.episodes[ep_uuid] = {"uuid_": ep_uuid, "graph_id": gid, "processed": True}
                rec = SimpleNamespace(
                    sequence_index=start_seq + idx,
                    episode_uuid=ep_uuid,
                    source_uuid=ep_uuid,
                    status="succeeded",
                    error=None,
                )
                b["items"].append(rec)
                details.append(rec)

            # Synthesize domain-specific isolated graph nodes from actual uploaded chunks
            if target_gid:
                g = registry.graphs.setdefault(target_gid, {"graph_id": target_gid, "nodes": [], "edges": [], "entity_types": ["Person", "Organization"]})
                if not g["nodes"]:
                    full_text = "\n".join(combined_chunks)
                    kws = _extract_domain_terms(full_text, limit=6)
                    kw_str = ", ".join(kws[:4]) if kws else "mercado colombiano"
                    human_types = [t for t in g.get("entity_types", []) if t.lower() not in {"service", "channel", "claim", "regulator"}] or ["Person"]
                    names = [
                        "Camila Rodríguez", "Andrés Gómez", "Valentina Martínez", "Santiago López",
                        "Laura Hernández", "Juan David Torres", "Mariana Díaz", "Felipe Castro",
                        "Sofía Vargas", "Carlos Morales", "Natalia Rojas", "Mateo Ospina",
                    ]
                    nodes = []
                    for i, person_name in enumerate(names):
                        etype = human_types[i % len(human_types)]
                        nuuid = f"node_{target_gid[:8]}_{i:02d}"
                        nodes.append(
                            SimpleNamespace(
                                uuid_=nuuid,
                                uuid=nuuid,
                                name=person_name,
                                labels=["Entity", etype],
                                summary=f"{person_name} participa en el ecosistema de {kw_str} en Colombia.",
                                attributes={"role": f"Actor {kws[i % len(kws)]}" if kws else "Consumidor"},
                                created_at="2026-11-26T00:00:00Z",
                            )
                        )
                    edges = []
                    for i in range(len(nodes) - 1):
                        euuid = f"edge_{target_gid[:8]}_{i:02d}"
                        edges.append(
                            SimpleNamespace(
                                uuid_=euuid,
                                uuid=euuid,
                                name="INTERACTS_WITH",
                                fact=f"{nodes[i].name} evalúa opciones relacionadas con {kw_str}.",
                                fact_type="INTERACTS_WITH",
                                source_node_uuid=nodes[i].uuid_,
                                target_node_uuid=nodes[i + 1].uuid_,
                                attributes={},
                                created_at="2026-11-26T00:00:00Z",
                                valid_at=None,
                                invalid_at=None,
                                expired_at=None,
                                episodes=[details[0].episode_uuid] if details else [],
                            )
                        )
                    g["nodes"] = nodes
                    g["edges"] = edges
            return details

        @staticmethod
        def process(batch_id: str):
            b = registry.batches[batch_id]
            b["status"] = "succeeded"
            return SimpleNamespace(batch_id=batch_id, status="succeeded")

        @staticmethod
        def get(batch_id: str):
            b = registry.batches[batch_id]
            total = len(b["items"])
            return SimpleNamespace(
                batch_id=batch_id,
                status=b["status"],
                progress=SimpleNamespace(percent_complete=100.0, succeeded_items=total),
            )

        @staticmethod
        def list(limit: int = 100, cursor: Any = None):
            batches = [
                SimpleNamespace(batch_id=bid, metadata=b["metadata"], status=b["status"])
                for bid, b in registry.batches.items()
            ]
            return SimpleNamespace(batches=batches, next_cursor=None)

        @staticmethod
        def list_items(batch_id: str, limit: int = 100, cursor: Any = None):
            b = registry.batches[batch_id]
            return SimpleNamespace(items=list(b["items"]), next_cursor=None)

    return SimpleNamespace(graph=_GraphAPI(), batch=_BatchAPI())


@pytest.fixture(autouse=True)
def isolated_prospectica_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Airtight tmp_path isolation + offline boundary stubs + backend/uploads sentinel."""
    before_snap = _snapshot_uploads_dir(REAL_UPLOADS_DIR)

    uploads_dir = tmp_path / "uploads"
    projects_dir = uploads_dir / "projects"
    sims_dir = uploads_dir / "simulations"
    reports_dir = uploads_dir / "reports"
    for d in (projects_dir, sims_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Patch Config & all import-time storage attributes / singletons
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(uploads_dir))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims_dir))
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-offline-llm-key")
    monkeypatch.setattr(Config, "ZEP_API_KEY", "test-offline-zep-key")
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(projects_dir))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports_dir))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims_dir))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(sims_dir))
    monkeypatch.setattr(TaskManager, "DEFAULT_DB_PATH", str(uploads_dir / "system_tasks.db"))

    TaskManager._instance = None
    SimulationRunner._run_states.clear()
    clear_zep_client_cache()

    # Guard hardcoded ../../uploads/reports helper in api/simulation.py if invoked
    try:
        import app.api.simulation as sim_api

        def _safe_get_report_id_for_sim(simulation_id: str) -> Optional[str]:
            rep = ReportManager.get_report_by_simulation(simulation_id)
            return rep.report_id if rep else None

        monkeypatch.setattr(sim_api, "_get_report_id_for_simulation", _safe_get_report_id_for_sim, raising=False)
    except Exception:
        pass

    # 2. Offline deterministic domain-reflecting LLM stubs
    from app.utils.llm_client import LLMClient

    def _fake_chat_json(self, messages, temperature=0.3, max_tokens=4096, max_attempts=1):
        return _build_offline_llm_payload(messages)

    def _fake_chat(self, messages, temperature=0.7, max_tokens=2000, response_format=None, tools=None, tool_choice=None):
        payload = _build_offline_llm_payload(messages)
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(LLMClient, "chat_json", _fake_chat_json)
    monkeypatch.setattr(LLMClient, "chat", _fake_chat)

    # Also stub OpenAI compat call inside SimulationConfigGenerator
    try:
        import app.services.simulation_config_generator as scg_mod

        def _fake_create_chat_completion(client, *, model, messages, temperature=None, max_tokens=None, response_format=None, tools=None, tool_choice=None):
            payload = _build_offline_llm_payload(messages)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
                    )
                ]
            )

        monkeypatch.setattr(scg_mod, "create_chat_completion", _fake_create_chat_completion)
    except Exception:
        pass

    # 3. Offline in-memory Fake Zep Client
    zep_registry = _FakeZepRegistry()
    fake_zep = _build_fake_zep_client(zep_registry)

    import app.utils.zep as zep_mod
    monkeypatch.setattr(zep_mod, "get_zep_client", lambda *a, **kw: fake_zep)
    for mod_path in (
        "app.services.graph_builder",
        "app.services.zep_entity_reader",
        "app.services.oasis_profile_generator",
        "app.services.zep_tools",
    ):
        try:
            mod = __import__(mod_path, fromlist=["get_zep_client"])
            if hasattr(mod, "get_zep_client"):
                monkeypatch.setattr(mod, "get_zep_client", lambda *a, **kw: fake_zep)
        except Exception:
            pass

    # 4. Prevent accidental external official/web network fetches
    try:
        from app.services.socrata_connector import SocrataColombiaConnector
        monkeypatch.setattr(SocrataColombiaConnector, "fetch_all_indicators", lambda self, *a, **kw: ([], []))
    except Exception:
        pass

    yield {
        "tmp_path": tmp_path,
        "uploads_dir": uploads_dir,
        "projects_dir": projects_dir,
        "sims_dir": sims_dir,
        "reports_dir": reports_dir,
        "zep_registry": zep_registry,
    }

    # Upload-leak sentinel: verify process isolation & zero test artifacts in backend/uploads/
    assert Path(Config.UPLOAD_FOLDER).resolve() == uploads_dir.resolve()
    assert Path(ProjectManager.PROJECTS_DIR).resolve() == projects_dir.resolve()
    assert Path(ReportManager.REPORTS_DIR).resolve() == reports_dir.resolve()
    assert Path(SimulationManager.SIMULATION_DATA_DIR).resolve() == sims_dir.resolve()
    assert Path(SimulationRunner.RUN_STATE_DIR).resolve() == sims_dir.resolve()
    assert Path(TaskManager.DEFAULT_DB_PATH).resolve() == (uploads_dir / "system_tasks.db").resolve()
    if TaskManager._instance is not None:
        assert Path(TaskManager._instance._db_path).resolve().is_relative_to(tmp_path.resolve()), (
            f"ISOLATION BREACH: TaskManager used {TaskManager._instance._db_path} outside tmp_path!"
        )

    for sub, real_sub in (
        (projects_dir, REAL_UPLOADS_DIR / "projects"),
        (sims_dir, REAL_UPLOADS_DIR / "simulations"),
        (reports_dir, REAL_UPLOADS_DIR / "reports"),
    ):
        for created in sub.iterdir():
            assert not (real_sub / created.name).exists(), (
                f"ISOLATION BREACH: artifact {created.name} leaked into {real_sub}"
            )

    # Verify read-only COFRE reference fixture in backend/uploads/ was not altered
    cofre_rel = r"projects\proj_9972d0d47dbc\files\d5165656.pdf"
    after_snap = _snapshot_uploads_dir(REAL_UPLOADS_DIR)
    if cofre_rel in before_snap:
        assert after_snap.get(cofre_rel) == before_snap.get(cofre_rel), (
            "ISOLATION BREACH: COFRE reference PDF in backend/uploads/ was modified!"
        )

    TaskManager._instance = None
    SimulationRunner._run_states.clear()
    clear_zep_client_cache()


@pytest.fixture()
def flask_app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


@dataclass
class PipelineResult:
    """Artifacts collected from one opaque-box E2E pipeline execution."""

    fixture: ColombianBusinessFixture
    project_id: str
    project_name: str
    project_json: Dict[str, Any]
    study_context: Optional[Dict[str, Any]]
    graph_id: str
    simulation_id: str
    profiles: List[Dict[str, Any]]
    channels_summary: Dict[str, Any]
    survey_result: Dict[str, Any]
    analytics_bundle: Dict[str, Any]
    report_id: str
    manifest: Dict[str, Any]
    chapters: Dict[int, Dict[str, Any]]
    full_report_md: str
    download_filename: str
    download_content: str
    project_dir: Path
    sim_dir: Path
    report_dir: Path


def _poll_until_done(
    getter,
    *,
    terminal_statuses=("completed", "ready"),
    failed_statuses=("failed", "error"),
    timeout_sec: float = 20.0,
) -> Dict[str, Any]:
    deadline = time.time() + timeout_sec
    last_payload: Dict[str, Any] = {}
    while time.time() < deadline:
        resp = getter()
        payload = resp.get_json(silent=True) or {}
        last_payload = payload
        data = payload.get("data") or {}
        st = str(data.get("status") or "").lower()
        if st in terminal_statuses:
            return payload
        if st in failed_statuses:
            raise AssertionError(f"Async task failed: {payload}")
        time.sleep(0.05)
    raise TimeoutError(f"Task did not finish within {timeout_sec}s; last={last_payload}")


def extract_download_filename(content_disposition: str) -> str:
    """Parse filename from Content-Disposition HTTP header."""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]+)"?', content_disposition or "", re.I)
    return m.group(1).strip() if m else ""


def parse_gabor_granger_table(section_06_md: str) -> List[Tuple[int, float, int]]:
    """Parse `(price_cop, acceptance_pct, expected_revenue_cop)` rows from Ch.6 GG table."""
    rows: List[Tuple[int, float, int]] = []
    in_table = False
    for line in (section_06_md or "").splitlines():
        s = line.strip()
        if "Precio Evaluado" in s and "Tasa de Aceptaci" in s:
            in_table = True
            continue
        if in_table:
            if s.startswith("|---"):
                continue
            if not s.startswith("|"):
                if rows:
                    break
                continue
            cols = [c.strip() for c in s.strip("|").split("|")]
            if len(cols) >= 3:
                p_digits = re.sub(r"[^\d]", "", cols[0])
                pct_m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", cols[1])
                rev_digits = re.sub(r"[^\d]", "", cols[2])
                if p_digits and pct_m and rev_digits:
                    rows.append((int(p_digits), float(pct_m.group(1).replace(",", ".")), int(rev_digits)))
    return rows


def parse_ch7_friction_table(section_07_md: str) -> List[Dict[str, Any]]:
    """Parse `(channel_name, touchpoints, friction_events, friction_pct)` rows from Ch.7 CDJ table."""
    rows: List[Dict[str, Any]] = []
    in_table = False
    for line in (section_07_md or "").splitlines():
        s = line.strip()
        if "Canal de Contacto" in s and "Tasa de Fricci" in s:
            in_table = True
            continue
        if in_table:
            if s.startswith("|---"):
                continue
            if not s.startswith("|"):
                if rows:
                    break
                continue
            cols = [c.strip() for c in s.strip("|").split("|")]
            if len(cols) >= 4:
                tp_m = re.search(r"(\d+)", cols[1])
                fe_m = re.search(r"(\d+)", cols[2])
                fr_m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", cols[3])
                if tp_m and fe_m and fr_m:
                    rows.append({
                        "channel_name": cols[0],
                        "touchpoints": int(tp_m.group(1)),
                        "friction_events": int(fe_m.group(1)),
                        "friction_pct": float(fr_m.group(1).replace(",", ".")),
                    })
    return rows


def extract_ch8_quotes(section_08_md: str) -> List[Tuple[str, str]]:
    """Return list of `(citation_tag, quote_text)` extracted from Ch.8 verbatim blockquotes."""
    out: List[Tuple[str, str]] = []
    for line in (section_08_md or "").splitlines():
        s = line.strip()
        if not s.startswith(">"):
            continue
        m = re.match(r'^>\s*(\[[^\]]+\])\s*:\s*"(.+)"\s*$', s)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def run_full_pipeline(
    client,
    fixture: ColombianBusinessFixture,
    *,
    explicit_project_name: Optional[str] = None,
    sample_size: int = 60,
    channel_ids: Optional[List[str]] = None,
    rounds: int = 2,
    force_regenerate: bool = True,
) -> PipelineResult:
    """Execute the opaque-box E2E flow via public Flask endpoints into tmp_path."""
    # 1. Home upload -> ontology + StudyContext
    form_data: Dict[str, Any] = {
        "files": (BytesIO(fixture.pdf_bytes), fixture.pdf_filename),
        "simulation_requirement": fixture.simulation_requirement,
        "country_code": fixture.country_code,
        "target_cities": json.dumps(fixture.target_cities),
        "target_strata": json.dumps(fixture.target_strata),
        "use_official_sources": "false",
        "use_live_web": "false",
    }
    pname = explicit_project_name if explicit_project_name is not None else fixture.explicit_project_name
    if pname is not None:
        form_data["project_name"] = pname

    resp_onto = client.post("/api/graph/ontology/generate", data=form_data, content_type="multipart/form-data")
    assert resp_onto.status_code == 200, f"ontology/generate failed: {resp_onto.get_json(silent=True)}"
    onto_data = resp_onto.get_json()["data"]
    project_id = onto_data["project_id"]

    # 2. Build Zep graph
    resp_build = client.post("/api/graph/build", json={"project_id": project_id})
    assert resp_build.status_code == 200, f"graph/build failed: {resp_build.get_json(silent=True)}"
    build_data = resp_build.get_json()["data"]
    if build_data.get("task_id"):
        _poll_until_done(lambda: client.get(f"/api/graph/task/{build_data['task_id']}"))

    resp_proj = client.get(f"/api/graph/project/{project_id}")
    assert resp_proj.status_code == 200
    project_json = resp_proj.get_json()["data"]
    graph_id = project_json["graph_id"]

    # 3. Create & prepare simulation
    resp_sim = client.post(
        "/api/simulation/create",
        json={
            "project_id": project_id,
            "graph_id": graph_id,
            "enabled_channels": channel_ids or list(CANONICAL_CHANNEL_IDS),
            "survey_target_n": sample_size,
        },
    )
    assert resp_sim.status_code == 200, f"simulation/create failed: {resp_sim.get_json(silent=True)}"
    sim_id = resp_sim.get_json()["data"]["simulation_id"]

    resp_prep = client.post(
        "/api/simulation/prepare",
        json={"simulation_id": sim_id, "use_llm_for_profiles": False, "parallel_profile_count": 2},
    )
    assert resp_prep.status_code == 200, f"simulation/prepare failed: {resp_prep.get_json(silent=True)}"
    prep_data = resp_prep.get_json()["data"]
    if prep_data.get("task_id"):
        _poll_until_done(
            lambda: client.post(
                "/api/simulation/prepare/status",
                json={"task_id": prep_data["task_id"]},
            )
        )

    # Mark OASIS runner state completed so /api/report/generate pre-flight accepts it
    SimulationRunner._save_run_state(
        SimulationRunState(
            simulation_id=sim_id,
            runner_status=RunnerStatus.COMPLETED,
            current_round=rounds,
            total_rounds=rounds,
        )
    )

    # 4. Run multichannel simulation
    resp_ch = client.post(
        f"/api/channels/{sim_id}/run",
        json={"enabled_channels": channel_ids or list(CANONICAL_CHANNEL_IDS), "rounds": rounds},
    )
    assert resp_ch.status_code == 200, f"channels/run failed: {resp_ch.get_json(silent=True)}"
    channels_summary = resp_ch.get_json()["data"]

    # 5. Run structured survey synchronously
    resp_surv = client.post(
        f"/api/swarm/{sim_id}/survey/run",
        json={"sample_size": sample_size, "use_llm": False, "sync": True},
    )
    assert resp_surv.status_code == 200, f"survey/run failed: {resp_surv.get_json(silent=True)}"
    survey_result = resp_surv.get_json()["data"]["result"]

    # 6. Run deterministic analytics & fetch bundle
    resp_ana = client.post(f"/api/analytics/{sim_id}/run")
    assert resp_ana.status_code == 200, f"analytics/run failed: {resp_ana.get_json(silent=True)}"
    resp_bundle = client.get(f"/api/analytics/{sim_id}/bundle")
    assert resp_bundle.status_code == 200
    analytics_bundle = resp_bundle.get_json()["data"]

    # 7. Generate 12-chapter report & poll
    resp_rep = client.post(
        "/api/report/generate",
        json={"simulation_id": sim_id, "force_regenerate": force_regenerate},
    )
    assert resp_rep.status_code == 200, f"report/generate failed: {resp_rep.get_json(silent=True)}"
    rep_data = resp_rep.get_json()["data"]
    report_id = rep_data["report_id"]
    if rep_data.get("task_id"):
        _poll_until_done(
            lambda: client.post(
                "/api/report/generate/status",
                json={"task_id": rep_data["task_id"]},
            )
        )

    # 8. Inspect manifest, chapters, download
    resp_man = client.get(f"/api/report/{report_id}/manifest")
    assert resp_man.status_code == 200
    manifest = resp_man.get_json()["data"]

    chapters: Dict[int, Dict[str, Any]] = {}
    for ch_idx in range(1, 13):
        r_ch = client.get(f"/api/report/{report_id}/chapter/{ch_idx}")
        assert r_ch.status_code == 200, f"chapter/{ch_idx} returned {r_ch.status_code}"
        chapters[ch_idx] = r_ch.get_json()["data"]

    resp_dl = client.get(f"/api/report/{report_id}/download")
    assert resp_dl.status_code == 200
    download_filename = extract_download_filename(resp_dl.headers.get("Content-Disposition", ""))
    download_content = resp_dl.data.decode("utf-8")

    project_dir = Path(ProjectManager.PROJECTS_DIR) / project_id
    sim_dir = Path(Config.OASIS_SIMULATION_DATA_DIR) / sim_id
    report_dir = Path(ReportManager.REPORTS_DIR) / report_id

    sc_path = project_dir / "study_context.json"
    study_context = json.loads(sc_path.read_text(encoding="utf-8")) if sc_path.exists() else None

    prof_path = sim_dir / "reddit_profiles.json"
    profiles = json.loads(prof_path.read_text(encoding="utf-8")) if prof_path.exists() else []

    full_md_path = report_dir / "full_report.md"
    full_report_md = full_md_path.read_text(encoding="utf-8") if full_md_path.exists() else download_content

    return PipelineResult(
        fixture=fixture,
        project_id=project_id,
        project_name=str(project_json.get("name") or ""),
        project_json=project_json,
        study_context=study_context,
        graph_id=graph_id,
        simulation_id=sim_id,
        profiles=profiles,
        channels_summary=channels_summary,
        survey_result=survey_result,
        analytics_bundle=analytics_bundle,
        report_id=report_id,
        manifest=manifest,
        chapters=chapters,
        full_report_md=full_report_md,
        download_filename=download_filename,
        download_content=download_content,
        project_dir=project_dir,
        sim_dir=sim_dir,
        report_dir=report_dir,
    )


@pytest.fixture()
def run_pipeline(client):
    """Fixture wrapper around `run_full_pipeline`."""
    def _runner(fixture: ColombianBusinessFixture, **kwargs) -> PipelineResult:
        return run_full_pipeline(client, fixture, **kwargs)
    return _runner


def query_sqlite_rows(db_path: Path, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Read-only helper to inspect `simulation_channels.db` tables."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
