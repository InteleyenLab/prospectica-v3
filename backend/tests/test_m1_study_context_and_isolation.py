"""Pruebas de Milestone M1: Identidad real, StudyContext dinámico y aislamiento estricto por proyecto/simulación."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.api import graph as graph_api
from app.channels.base import ChannelEvent
from app.channels.persistence import ChannelSQLiteStore
from app.config import Config
from app.models.project import ProjectManager
from app.models.task import TaskManager, TaskStatus
from app.services.report_agent import (
    CHAT_FAST_SYSTEM_PROMPT_TEMPLATE,
    Report,
    ReportAgent,
    ReportManager,
    ReportOutline,
    ReportStatus,
)
from app.services.simulation_manager import SimulationManager
from app.services.study_context_builder import (
    _enrich_with_llm,
    _parse_cop_number,
    clean_study_topic,
    ensure_study_context,
    extract_and_build_study_context,
    extract_real_project_name,
    is_placeholder_project_name,
    load_study_context,
    slugify_project_name,
)

REQUIRED_STUDY_CONTEXT_KEYS = {
    "project_id",
    "project_name",
    "project_slug",
    "sector",
    "business_model",
    "geographic_scope",
    "value_proposition",
    "offer_summary",
    "price_ladder_cop",
    "reference_price_cop",
    "unit_var_cost_cop",
    "monthly_opex_cop",
    "unit_label",
    "upsell_offer",
    "target_roles",
    "competitors",
    "key_channels",
    "key_risks_objections",
    "regulatory_scope",
    "domain_keywords",
    "codebook_rules",
    "dofa_seed",
}


def _assert_valid_study_context(ctx: dict) -> None:
    assert REQUIRED_STUDY_CONTEXT_KEYS.issubset(ctx.keys())
    assert ctx["project_name"]
    assert not is_placeholder_project_name(ctx["project_name"])
    assert "prospéctica" not in ctx["project_name"].lower()
    assert "unnamed" not in ctx["project_name"].lower()
    assert ctx["project_slug"] == slugify_project_name(ctx["project_name"])

    ladder = ctx["price_ladder_cop"]
    assert isinstance(ladder, list) and len(ladder) == 5
    assert all(isinstance(p, int) and p > 0 for p in ladder)
    assert ladder == sorted(ladder) and len(set(ladder)) == 5

    assert isinstance(ctx["reference_price_cop"], int) and ctx["reference_price_cop"] > 0
    assert isinstance(ctx["unit_var_cost_cop"], float)
    assert 0 < ctx["unit_var_cost_cop"] < ctx["reference_price_cop"]
    assert isinstance(ctx["monthly_opex_cop"], float) and ctx["monthly_opex_cop"] > 0
    assert isinstance(ctx["unit_label"], str) and "/" in ctx["unit_label"]
    assert ctx["upsell_offer"] is None or isinstance(ctx["upsell_offer"], dict)
    assert 4 <= len(ctx["target_roles"]) <= 8
    assert len(ctx["competitors"]) >= 2
    assert len(ctx["key_channels"]) >= 2
    assert len(ctx["key_risks_objections"]) >= 2
    assert isinstance(ctx["regulatory_scope"], list)
    assert len(ctx["domain_keywords"]) >= 4
    assert isinstance(ctx["codebook_rules"], list) and len(ctx["codebook_rules"]) >= 4
    for rule in ctx["codebook_rules"]:
        assert {"code", "label", "patterns"}.issubset(rule.keys())
        assert isinstance(rule["patterns"], list) and len(rule["patterns"]) >= 1

    dofa = ctx["dofa_seed"]
    assert {"fortalezas", "oportunidades", "debilidades", "amenazas", "scores"}.issubset(dofa.keys())
    for k in ("fortalezas", "oportunidades", "debilidades", "amenazas"):
        assert isinstance(dofa[k], list) and len(dofa[k]) >= 2
        score = dofa["scores"][k]
        assert isinstance(score, int) and 0 <= score <= 100


# =====================================================================
# 1. Extracción real del nombre del proyecto (cero fugas de prompt)
# =====================================================================


def test_extract_real_project_name_across_real_and_synthetic_businesses():
    # A. COFRE (BLOQUE 1 + banner espaciado + PDF)
    cofre_req = (
        "BLOQUE 1 - ROL Y MISION\n"
        "Actua como un analista senior de investigacion de mercados y validacion de startups,\n"
        "especializado en fintech de confianza, comercio social y mercados latinoamericanos,\n"
        "con Colombia como mercado inicial. Tu mision: investigar el mercado de COFRE y\n"
        "disenar un plan de validacion que permita decidir si la idea debe avanzar, pivotar\n"
        "o detenerse.\n"
        "BLOQUE 2 - CONTEXTO DE LA IDEA (COFRE)\n"
        "COFRE es la capa de confianza y proteccion de transacciones de SOCIAL FINDER."
    )
    cofre_doc = (
        "=== COFRE_Descripcion_y_Prompt_Validacion.pdf ===\n"
        "D E S C R I P C I O N  D E L  P R O Y E C T O  +  P R O M P T  D E\n"
        "V A L I D A C I O N\n"
        "COFRE\n"
        "Infraestructura de confianza para el comercio social\n"
        "COFRE es la capa de confianza y proteccion de transacciones de SOCIAL FINDER."
    )
    assert extract_real_project_name(
        extracted_text=cofre_doc,
        simulation_requirement=cofre_req,
        filenames=["COFRE_Descripcion_y_Prompt_Validacion.pdf"],
        project_name_hint="Unnamed Project",
    ) == "COFRE"
    topic_cofre = clean_study_topic(cofre_req, "Unnamed Project", cofre_doc)
    assert topic_cofre == "COFRE"
    assert "disenar un plan" not in topic_cofre.lower()

    # B. NEXO (# ROL + CONTEXTO DEL NEGOCIO)
    nexo_req = (
        "# ROL\n"
        "Actúa como un equipo experto compuesto por investigador de mercados.\n"
        "# CONTEXTO DEL NEGOCIO\n"
        "Empresa: NEXO Reclamaciones (Colombia). Lema: \"Orientación. Orden. Acompañamiento.\"\n"
    )
    assert extract_real_project_name(
        extracted_text="NEXO RECLAMACIONES | MANUAL TÉCNICO DE MARCA",
        simulation_requirement=nexo_req,
        project_name_hint="Unnamed Project",
    ) == "NEXO Reclamaciones"

    # C. NEXO con enlace ChatGPT compartido + SIMULA Y PREDICE (no debe filtrar URL ni instrucción)
    share_req = "https://chatgpt.com/share/6b04c2ed-4598-83ea-905c-a4b46c6a95ea\n\nSIMULA Y PREDICE ESTA EMPRESA EN COLOMBIA"
    share_name = extract_real_project_name(
        extracted_text="Documento estratégico integral\nPágina 1\nServicio especializado de orientación de reclamaciones.",
        simulation_requirement=share_req,
        filenames=["Documento_Integral_Reclamaciones_Version_Ampliada.pdf"],
        project_name_hint="",
    )
    assert "http" not in share_name.lower()
    assert "simula" not in share_name.lower()
    assert not is_placeholder_project_name(share_name) or share_name == "Estudio de Mercado"

    # D. NEXO en minúsculas inline ("la empresa se llama nexo")
    nexo_inline = extract_real_project_name(
        extracted_text="NEXO Reclamaciones ofrece orientación inicial.",
        simulation_requirement="la empresa se llama nexo, necesito hacer un estudio de mercado para colombia",
        project_name_hint="Unnamed Project",
    )
    assert "nexo" in nexo_inline.lower()
    assert "necesito" not in nexo_inline.lower()

    # E. Prompta
    prompta_doc = "# PROMPTA: Generador Inteligente de Prompts Estructurados en Español\n**Prompta** es una aplicación web ligera."
    assert extract_real_project_name(
        extracted_text=prompta_doc,
        simulation_requirement="Validar adopción de Prompta en LATAM",
        filenames=["prompta_analisis.md"],
        project_name_hint="Unnamed Project",
    ) == "PROMPTA"

    # F. Miscelánea de barrio colombiana
    misc_req = (
        "Evaluar la apertura de la miscelánea de barrio Miscelánea La Esperanza en Suba, Bogotá, "
        "con venta de útiles escolares, papelería, recargas y snacks entre COP $2.000 y $15.000."
    )
    assert extract_real_project_name(
        extracted_text="Miscelánea La Esperanza es una tienda de barrio para útiles y papelería en Suba.",
        simulation_requirement=misc_req,
        filenames=["plan_miscelanea.pdf"],
        project_name_hint="Unnamed Project",
    ) == "Miscelánea La Esperanza"


# =====================================================================
# 2. StudyContext dinámico multi-sector en Colombia
# =====================================================================


def test_dynamic_study_context_across_diverse_colombian_businesses(tmp_path: Path):
    # 1) Fintech Escrow (COFRE)
    cofre_ctx = extract_and_build_study_context(
        project_id="proj_cofre",
        project_name_hint="Unnamed Project",
        extracted_text=(
            "COFRE es la capa de confianza y proteccion de transacciones de SOCIAL FINDER para comercio social "
            "en Instagram, WhatsApp y TikTok en Colombia y Latinoamérica. Flujo de cinco pasos: acuerdo, pago "
            "protegido simulado, envio, confirmacion y liberacion. Tarifa por transaccion protegida desde COP $12.000."
        ),
        simulation_requirement=(
            "BLOQUE 1 - ROL Y MISION\nActua como analista senior con Colombia como mercado inicial. "
            "Tu mision: investigar el mercado de COFRE."
        ),
        filenames=["COFRE_Descripcion_y_Prompt_Validacion.pdf"],
        use_llm=False,
        project_dir=tmp_path / "proj_cofre",
    )
    _assert_valid_study_context(cofre_ctx)
    assert cofre_ctx["project_name"] == "COFRE"
    assert cofre_ctx["sector"] == "fintech_escrow"
    assert cofre_ctx["unit_label"] == "transacciones/mes"
    assert not any("196" in reg for reg in cofre_ctx["regulatory_scope"])
    assert (tmp_path / "proj_cofre" / "study_context.json").exists()

    # 2) Miscelánea de barrio (Miscelánea La Esperanza)
    misc_ctx = extract_and_build_study_context(
        project_id="proj_misc",
        project_name_hint=None,
        extracted_text=(
            "Negocio: Miscelánea La Esperanza\n"
            "Tienda de barrio ubicada en Suba, Bogotá, enfocada en útiles escolares, papelería, recargas Nequi, "
            "fotocopias y snacks diarios con precios entre COP $2.000 y COP $15.000."
        ),
        simulation_requirement="Validar demanda de miscelánea de barrio en Suba, Bogotá.",
        filenames=["miscelanea.txt"],
        use_llm=False,
        project_dir=tmp_path / "proj_misc",
    )
    _assert_valid_study_context(misc_ctx)
    assert misc_ctx["project_name"] == "Miscelánea La Esperanza"
    assert misc_ctx["sector"] == "comercio_minorista"
    assert misc_ctx["business_model"] == "comercio_local"
    assert misc_ctx["geographic_scope"] == "Barrio / Local"
    assert misc_ctx["unit_label"] == "ventas/mes"
    assert misc_ctx["upsell_offer"] is None
    assert misc_ctx["price_ladder_cop"][0] >= 1000 and misc_ctx["price_ladder_cop"][-1] <= 30000
    assert misc_ctx["monthly_opex_cop"] < cofre_ctx["monthly_opex_cop"]
    assert not any("196" in reg for reg in misc_ctx["regulatory_scope"])

    # 3) Restaurante local
    food_ctx = extract_and_build_study_context(
        project_id="proj_food",
        project_name_hint="Arepería El Fogón Paisa",
        extracted_text=(
            "Arepería El Fogón Paisa es un restaurante de barrio en Medellín con menú del día, almuerzos "
            "y arepas artesanales entre COP $12.000 y COP $28.000, además de combos familiares."
        ),
        simulation_requirement="Evaluar apertura de restaurante local en Laureles, Medellín.",
        use_llm=False,
        project_dir=tmp_path / "proj_food",
    )
    _assert_valid_study_context(food_ctx)
    assert food_ctx["sector"] == "alimentos_bebidas"
    assert food_ctx["unit_label"] == "pedidos/mes"
    assert food_ctx["upsell_offer"] is not None
    assert any("INVIMA" in r for r in food_ctx["regulatory_scope"])

    # 4) Reclamaciones / Seguros (NEXO)
    nexo_ctx = extract_and_build_study_context(
        project_id="proj_nexo",
        project_name_hint="Unnamed Project",
        extracted_text=(
            "NEXO Reclamaciones orienta y acompaña reclamaciones de terceros ante aseguradoras en Bogotá, Medellín, Cali y Barranquilla.\n"
            "Servicio A — Orientación inicial: precio de referencia COP $70.000.\n"
            "Servicio B — Acompañamiento y gestión: tarifa fija por expediente."
        ),
        simulation_requirement="Empresa: NEXO Reclamaciones (Colombia). Validar Servicio A COP $70.000 y Servicio B.",
        use_llm=False,
        project_dir=tmp_path / "proj_nexo",
    )
    _assert_valid_study_context(nexo_ctx)
    assert nexo_ctx["project_name"] == "NEXO Reclamaciones"
    assert nexo_ctx["sector"] == "movilidad_seguros"
    assert nexo_ctx["reference_price_cop"] == 70000
    assert nexo_ctx["upsell_offer"] is not None and "Servicio B" in nexo_ctx["upsell_offer"]["name"]
    assert any("196" in r for r in nexo_ctx["regulatory_scope"])

    # 5) SaaS (Prompta) con fallback seguro si use_llm=True falla
    with patch.object(Config, "LLM_API_KEY", "fake-key"), patch(
        "app.utils.llm_client.LLMClient", side_effect=RuntimeError("LLM down")
    ):
        saas_ctx = extract_and_build_study_context(
            project_id="proj_saas",
            project_name_hint="Unnamed Project",
            extracted_text=(
                "# PROMPTA: Generador Inteligente de Prompts Estructurados en Español\n"
                "**Prompta** es una aplicación web SaaS con versión Pro por suscripción de COP $29.900."
            ),
            simulation_requirement="Validar adopción de Prompta en Colombia y LATAM.",
            use_llm=True,
            project_dir=tmp_path / "proj_saas",
        )
    _assert_valid_study_context(saas_ctx)
    assert saas_ctx["project_name"] == "PROMPTA"
    assert saas_ctx["sector"] == "tecnologia_saas"
    assert saas_ctx["unit_label"] == "suscripciones/mes"


# =====================================================================
# 3. Graph API (/ontology/generate, /build) & Simulation History
# =====================================================================


def test_graph_ontology_and_build_persist_real_name_and_study_context(tmp_path: Path, monkeypatch):
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(projects_dir))
    monkeypatch.setattr(Config, "ZEP_API_KEY", "test-zep-key")

    mock_ontology = {
        "entity_types": [{"name": "Citizen", "description": "Comprador", "attributes": [], "examples": ["Ana"]}],
        "edge_types": [],
        "analysis_summary": "Ontología de prueba.",
    }

    captured_task_names = []

    class FakeTaskManager:
        def create_task(self, description, **kwargs):
            captured_task_names.append(description)
            return "task_fake_graph"

        def update_task(self, *args, **kwargs):
            pass

        def complete_task(self, *args, **kwargs):
            pass

        def fail_task(self, *args, **kwargs):
            pass

    class DummyThread:
        def __init__(self, target, daemon=True):
            self.target = target

        def start(self):
            pass  # no ejecutar Zep real en hilo de fondo

    monkeypatch.setattr(graph_api, "TaskManager", FakeTaskManager)
    monkeypatch.setattr(graph_api.threading, "Thread", DummyThread)

    app = create_app()
    client = app.test_client()

    with patch("app.api.graph.OntologyGenerator") as mock_gen_cls:
        mock_gen_cls.return_value.generate.return_value = mock_ontology
        resp = client.post(
            "/api/graph/ontology/generate",
            data={
                "simulation_requirement": (
                    "BLOQUE 1 - ROL Y MISION\n"
                    "Tu mision: investigar el mercado de COFRE y disenar un plan de validacion."
                ),
                "files": (
                    io.BytesIO(b"COFRE\nCOFRE es la capa de confianza para el comercio social en Colombia."),
                    "COFRE_Descripcion.txt",
                ),
            },
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    data = resp.get_json()["data"]
    project_id = data["project_id"]
    assert data["project_name"] == "COFRE"
    assert data["project_slug"] == "cofre"
    assert data["study_context"]["project_name"] == "COFRE"

    persisted_proj = ProjectManager.get_project(project_id)
    assert persisted_proj.name == "COFRE"
    loaded_ctx = load_study_context(project_id)
    assert loaded_ctx is not None and loaded_ctx["project_name"] == "COFRE"

    # Build graph sin enviar graph_name: debe usar "COFRE", nunca "Prospéctica Market Intelligence Graph"
    build_resp = client.post("/api/graph/build", json={"project_id": project_id})
    assert build_resp.status_code == 200
    assert captured_task_names and "COFRE" in captured_task_names[0]
    assert "Prospéctica" not in captured_task_names[0]


def test_simulation_history_includes_project_name_and_requirement_fallback(tmp_path: Path, monkeypatch):
    projects_dir = tmp_path / "projects"
    sims_dir = tmp_path / "simulations"
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(projects_dir))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims_dir))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims_dir))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))

    # Simular proyecto legacy con "Unnamed Project" y sin simulation_config.json
    proj = ProjectManager.create_project(name="Unnamed Project")
    proj.simulation_requirement = "Negocio: Miscelánea La Esperanza\nEvaluar ventas en Suba, Bogotá desde COP $2.000."
    ProjectManager.save_project(proj)
    ProjectManager.save_extracted_text(proj.project_id, "Miscelánea La Esperanza es una tienda de barrio en Suba.")

    sim_mgr = SimulationManager()
    state = sim_mgr.create_simulation(project_id=proj.project_id, graph_id="graph_misc_1")

    app = create_app()
    client = app.test_client()
    resp = client.get("/api/simulation/history")
    assert resp.status_code == 200
    items = resp.get_json()["data"]
    item = next(x for x in items if x["simulation_id"] == state.simulation_id)
    assert item["project_name"] == "Miscelánea La Esperanza"
    assert item["project_slug"] == "miscelanea_la_esperanza"
    assert "Miscelánea La Esperanza" in item["simulation_requirement"]

    # Helper de SimulationManager también asegura study_context
    assert sim_mgr.get_project_name(state.simulation_id) == "Miscelánea La Esperanza"
    assert (projects_dir / proj.project_id / "study_context.json").exists()


# =====================================================================
# 4. Aislamiento SQLite por simulation_id y limpieza en re-ejecuciones
# =====================================================================


def test_channel_sqlite_store_strict_simulation_id_isolation_and_survey_separation(tmp_path: Path):
    shared_dir = tmp_path / "shared_sim_db"
    store = ChannelSQLiteStore(shared_dir)

    for sim_id, actor_name, msg in [
        ("sim_cofre", "Comprador COFRE", "COFRE protege mi pago en Instagram"),
        ("sim_nexo", "Conductor NEXO", "NEXO orienta mi reclamación"),
    ]:
        store.record_channel_event(
            sim_id,
            ChannelEvent(
                actor_agent_id=1,
                actor_name=actor_name,
                city_divipola="11001",
                city_name="Bogotá",
                stratum_code="E3",
                region_macro="Andina",
                attitude_segment="promotor",
                channel_id="whatsapp_1on1",
                round_num=1,
                simulated_hour=10,
                action_type="WA_MSG",
                content_text=msg,
                sentiment_score=0.5,
            ),
            write_jsonl=False,
        )
        store.record_whatsapp_session(
            sim_id,
            {
                "session_key": f"wa_{sim_id}",
                "actor_agent_id": 1,
                "actor_name": actor_name,
                "city_divipola": "11001",
                "city_name": "Bogotá",
                "stratum_code": "E3",
                "region_macro": "Andina",
                "round_num": 1,
                "message_role": "user",
                "message_type": "text",
                "content_text": msg,
                "created_at": "2026-11-26T10:00:00Z",
            },
        )
        store.record_focus_group_turn(
            sim_id,
            {
                "session_id": f"fg_{sim_id}",
                "block_name": "B1",
                "round_num": 1,
                "turn_index": 1,
                "actor_agent_id": 1,
                "actor_name": actor_name,
                "city_divipola": "11001",
                "city_name": "Bogotá",
                "stratum_code": "E3",
                "region_macro": "Andina",
                "attitude_segment": "neutral",
                "content_text": msg,
                "created_at": "2026-11-26T10:00:00Z",
            },
        )
        store.record_media_exposure(
            sim_id,
            {
                "channel_id": "advertising",
                "round_num": 1,
                "simulated_hour": 11,
                "actor_agent_id": 1,
                "actor_name": actor_name,
                "city_divipola": "11001",
                "stratum_code": "E3",
                "region_macro": "Andina",
                "piece_format": "banner",
                "reaction_text": msg,
                "created_at": "2026-11-26T10:00:00Z",
            },
        )
        store.record_survey_responses_bulk(
            sim_id,
            [
                {
                    "respondent_id": f"st_{sim_id}",
                    "channel_origin": "street_survey",
                    "city_divipola": "11001",
                    "city_name": "Bogotá",
                    "region_macro": "Andina",
                    "stratum_code": "E3",
                    "wealth_tier_norm": 3,
                    "age": 30,
                    "gender": "M",
                    "dynamic_study_role": "Comprador",
                    "attitude_segment": "promotor",
                    "gg_grid": {"25000": 1},
                    "verbatim_response": msg,
                    "created_at": "2026-11-26T10:00:00Z",
                },
                {
                    "respondent_id": f"sv_{sim_id}",
                    "channel_origin": "structured_survey",
                    "city_divipola": "11001",
                    "city_name": "Bogotá",
                    "region_macro": "Andina",
                    "stratum_code": "E3",
                    "wealth_tier_norm": 3,
                    "age": 32,
                    "gender": "F",
                    "dynamic_study_role": "Vendedor",
                    "attitude_segment": "neutral",
                    "gg_grid": {"25000": 0},
                    "verbatim_response": msg,
                    "created_at": "2026-11-26T10:00:00Z",
                },
            ],
        )

    # Verificar aislamiento estricto en todas las consultas
    cofre_events = store.query_events(simulation_id="sim_cofre")
    assert len(cofre_events) == 1 and cofre_events[0]["actor_name"] == "Comprador COFRE"

    for ch_id in ("whatsapp_1on1", "focus_group", "street_survey", "structured_survey", "advertising"):
        sess = store.query_sessions(ch_id, simulation_id="sim_nexo")
        assert all(row["simulation_id"] == "sim_nexo" for row in sess["items"])
        assert len(sess["items"]) >= 1

    st_sess = store.query_sessions("street_survey", simulation_id="sim_cofre")
    assert len(st_sess["items"]) == 1
    assert {r["channel_origin"] for r in st_sess["items"]} == {"street_survey"}

    sv_sess = store.query_sessions("structured_survey", simulation_id="sim_cofre")
    assert len(sv_sess["items"]) == 1
    assert {r["channel_origin"] for r in sv_sess["items"]} == {"structured_survey"}

    cofre_surveys = store.query_surveys(simulation_id="sim_cofre", channel_origin="structured_survey")
    assert len(cofre_surveys) == 1
    assert cofre_surveys[0]["respondent_id"] == "sv_sim_cofre"
    assert cofre_surveys[0]["gg_grid"] == {"25000": 0}

    summary_cofre = store.summarize_channels(simulation_id="sim_cofre")
    assert summary_cofre["whatsapp_1on1"]["actions_count"] == 1
    assert summary_cofre["structured_survey"]["actions_count"] == 2

    # Limpieza selectiva por origen: limpiar canales NO borra structured_survey; limpiar surveys NO borra street_survey
    store.clear_simulation_channel_data("sim_cofre", include_street_surveys=True, clear_jsonl=False)
    assert len(store.query_events(simulation_id="sim_cofre")) == 0
    assert len(store.query_surveys(simulation_id="sim_cofre", channel_origin="street_survey")) == 0
    assert len(store.query_surveys(simulation_id="sim_cofre", channel_origin="structured_survey")) == 1
    assert len(store.query_events(simulation_id="sim_nexo")) == 1

    store.clear_simulation_surveys("sim_cofre", channel_origin="structured_survey")
    assert len(store.query_surveys(simulation_id="sim_cofre", channel_origin="structured_survey")) == 0
    assert len(store.query_surveys(simulation_id="sim_nexo")) == 2


def test_channels_and_survey_reruns_do_not_duplicate_rows(tmp_path: Path, monkeypatch):
    sims_dir = tmp_path / "simulations"
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims_dir))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims_dir))

    app = create_app()
    client = app.test_client()
    sim_id = "sim_rerun_iso"

    # Ejecutar encuesta N=20 dos veces + canales dos veces en distinto orden
    r_sv1 = client.post(f"/api/swarm/{sim_id}/survey/run", json={"sample_size": 20, "use_llm": False, "sync": True})
    assert r_sv1.status_code == 200
    r_ch1 = client.post(f"/api/channels/{sim_id}/run", json={"rounds": 1, "enabled_channels": ["whatsapp_1on1", "street_survey"]})
    assert r_ch1.status_code == 200

    store = ChannelSQLiteStore(sims_dir / sim_id)
    ch_count_1 = len(store.query_events(simulation_id=sim_id, limit=500))
    st_count_1 = len(store.query_surveys(simulation_id=sim_id, channel_origin="street_survey"))
    sv_count_1 = len(store.query_surveys(simulation_id=sim_id, channel_origin="structured_survey"))
    assert sv_count_1 == 20 and st_count_1 >= 3

    # Re-ejecutar canales y encuesta: los conteos no deben acumularse ni borrar el otro origen
    r_ch2 = client.post(f"/api/channels/{sim_id}/run", json={"rounds": 1, "enabled_channels": ["whatsapp_1on1", "street_survey"]})
    assert r_ch2.status_code == 200
    assert len(store.query_surveys(simulation_id=sim_id, channel_origin="structured_survey")) == 20
    assert len(store.query_events(simulation_id=sim_id, limit=500)) == ch_count_1
    assert len(store.query_surveys(simulation_id=sim_id, channel_origin="street_survey")) == st_count_1

    r_sv2 = client.post(f"/api/swarm/{sim_id}/survey/run", json={"sample_size": 20, "use_llm": False, "sync": True})
    assert r_sv2.status_code == 200
    assert len(store.query_surveys(simulation_id=sim_id, channel_origin="structured_survey")) == 20
    assert len(store.query_surveys(simulation_id=sim_id, channel_origin="street_survey")) == st_count_1


# =====================================================================
# 5. ReportManager ordering, /generate/status, download & prompt neutral
# =====================================================================


def test_report_manager_sorting_status_task_priority_and_slug_download(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    projects_dir = tmp_path / "projects"
    sims_dir = tmp_path / "simulations"
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports_dir))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(projects_dir))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims_dir))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims_dir))
    TaskManager._instance = None

    proj = ProjectManager.create_project(name="COFRE")
    proj.simulation_requirement = "Validar mercado de COFRE en Colombia."
    ProjectManager.save_project(proj)
    ensure_study_context(proj.project_id)

    sim = SimulationManager().create_simulation(project_id=proj.project_id, graph_id="graph_cofre")

    # Dos informes con IDs invertidos alfabéticamente para probar ordenamiento por fecha real
    older = Report(
        report_id="report_zzzz_older",
        simulation_id=sim.simulation_id,
        graph_id="graph_cofre",
        simulation_requirement=proj.simulation_requirement,
        status=ReportStatus.COMPLETED,
        outline=ReportOutline(title="COFRE · Informe Anterior", summary="", sections=[]),
        markdown_content="# COFRE · Informe Anterior\nContenido previo.",
        created_at="2026-11-26T10:00:00",
        completed_at="2026-11-26T10:02:00",
    )
    newer = Report(
        report_id="report_aaaa_newer",
        simulation_id=sim.simulation_id,
        graph_id="graph_cofre",
        simulation_requirement=proj.simulation_requirement,
        status=ReportStatus.COMPLETED,
        outline=ReportOutline(title="COFRE · Informe Nuevo", summary="", sections=[]),
        markdown_content="# COFRE · Informe Nuevo\nAnálisis actualizado con ñ y tildes.",
        created_at="2026-11-26T12:00:00",
        completed_at="2026-11-26T12:03:00",
    )
    ReportManager.save_report(older)
    ReportManager.save_report(newer)

    latest = ReportManager.get_report_by_simulation(sim.simulation_id)
    assert latest is not None
    assert latest.report_id == "report_aaaa_newer"

    # Crear tarea activa de regeneración mientras existe informe previo COMPLETED
    tm = TaskManager()
    active_task_id = tm.create_task("report_generate", metadata={"simulation_id": sim.simulation_id})
    tm.update_task(active_task_id, status=TaskStatus.PROCESSING, progress=35, message="Regenerando...")

    app = create_app()
    client = app.test_client()

    # Con task_id + simulation_id debe priorizar task_id (retorna processing, NO already_completed)
    r_poll_task = client.post(
        "/api/report/generate/status",
        json={"task_id": active_task_id, "simulation_id": sim.simulation_id},
    )
    assert r_poll_task.status_code == 200
    poll_data = r_poll_task.get_json()["data"]
    assert poll_data["status"] == "processing"
    assert poll_data.get("already_completed") is not True

    # Sin task_id debe mantener el respaldo de simulation_id ya completado
    r_poll_sim = client.post(
        "/api/report/generate/status",
        json={"simulation_id": sim.simulation_id},
    )
    assert r_poll_sim.status_code == 200
    sim_data = r_poll_sim.get_json()["data"]
    assert sim_data["already_completed"] is True
    assert sim_data["report_id"] == "report_aaaa_newer"

    # Descarga debe usar {project_slug}_{report_id}.md en UTF-8
    r_dl = client.get("/api/report/report_aaaa_newer/download")
    assert r_dl.status_code == 200
    content_disp = r_dl.headers.get("Content-Disposition", "")
    assert "cofre_report_aaaa_newer.md" in content_disp
    assert "Análisis actualizado con ñ y tildes." in r_dl.get_data(as_text=True)

    # CHAT_FAST_SYSTEM_PROMPT_TEMPLATE sin "Prospéctica Inc." y con placeholders intactos
    assert "Prospéctica Inc." not in CHAT_FAST_SYSTEM_PROMPT_TEMPLATE
    formatted = CHAT_FAST_SYSTEM_PROMPT_TEMPLATE.format(
        simulation_requirement="Estudio COFRE",
        report_content="Resumen COFRE",
    )
    assert "Estudio COFRE" in formatted and "Resumen COFRE" in formatted

    # ReportAgent con llm lazy no debe fallar al instanciarse sin LLM_API_KEY
    with patch.object(Config, "LLM_API_KEY", None):
        agent = ReportAgent(
            graph_id="graph_cofre",
            simulation_id=sim.simulation_id,
            simulation_requirement="Estudio COFRE",
            enable_tools=False,
        )
        assert agent._llm is None


# =====================================================================
# 6. Pruebas adversariales de regresión (Iteración 2 M1)
# =====================================================================


def test_adversarial_word_boundaries_name_extraction_and_cop_pricing(tmp_path: Path):
    # 1. Word-boundary matching: "para", "aseo", "spa" en "transparencia"/"respaldo"/"espacio"/"despacho",
    #    "éxito" en minúsculas, "LocalStorage", "Anexo 1"
    retail_ctx = extract_and_build_study_context(
        project_id="proj_adv_retail",
        extracted_text=(
            "Variedades El Sol ofrece artículos para el hogar en el barrio con transparencia, "
            "respaldo, amplio espacio y despacho rápido por WhatsApp."
        ),
        simulation_requirement=(
            "Empresa: Variedades El Sol\n"
            "El éxito del negocio en el barrio depende de comparar precios sin usar LocalStorage."
        ),
        use_llm=False,
        project_dir=tmp_path / "proj_adv_retail",
    )
    _assert_valid_study_context(retail_ctx)
    assert retail_ctx["project_name"] == "Variedades El Sol"
    assert retail_ctx["sector"] == "comercio_minorista"
    assert "Ara" not in retail_ctx["competitors"]
    assert "PSE" not in retail_ctx["competitors"]
    assert "Éxito" not in retail_ctx["competitors"]
    assert "street_survey" in retail_ctx["key_channels"]

    # Etiqueta UI "Éxito\n#16845B" en proyecto no minorista tampoco debe inyectar supermercado Éxito
    ui_exito_ctx = extract_and_build_study_context(
        project_id="proj_adv_ui_exito",
        extracted_text="RutaYa es una plataforma de logística.\nÉxito\n#16845B\nConfirmaciones.",
        simulation_requirement="Validar RutaYa en Colombia.",
        use_llm=False,
        project_dir=tmp_path / "proj_adv_ui_exito",
    )
    assert "Éxito" not in ui_exito_ctx["competitors"]

    # "Éxito" capitalizado o "Almacenes Éxito" sí debe detectarse como competidor
    exito_ctx = extract_and_build_study_context(
        project_id="proj_adv_exito",
        extracted_text="Mercamás es una tienda de barrio que compite con Almacenes Éxito y D1.",
        simulation_requirement="Evaluar Mercamás frente a Éxito.",
        use_llm=False,
        project_dir=tmp_path / "proj_adv_exito",
    )
    assert "Éxito" in exito_ctx["competitors"]
    assert "D1" in exito_ctx["competitors"]

    # 2. Miscelánea con verbo activo ("vende"), "aseo" (no "seo") y rango entre $2.000 y $15.000
    misc_adv = extract_and_build_study_context(
        project_id="proj_adv_misc",
        extracted_text=(
            "Miscelánea La Esperanza vende útiles escolares, papelería, recargas y productos de aseo "
            "en Suba, Bogotá entre COP $2.000 y $15.000. Pedidos por WhatsApp."
        ),
        simulation_requirement="Validar mercado de Miscelánea La Esperanza para el barrio.",
        filenames=["miscelanea.pdf"],
        use_llm=False,
        project_dir=tmp_path / "proj_adv_misc",
    )
    assert misc_adv["project_name"] == "Miscelánea La Esperanza"
    assert "Ara" not in misc_adv["competitors"]
    assert "colombian_web" not in misc_adv["key_channels"][:2]
    assert misc_adv["reference_price_cop"] == misc_adv["price_ladder_cop"][2]
    assert misc_adv["reference_price_cop"] > 2000

    # 3. Clínica con verbo activo ("ofrece"), "Anexo 1" (no "nexo") y filename genérico clinica.pdf
    clinica_adv = extract_and_build_study_context(
        project_id="proj_adv_clinica",
        extracted_text=(
            "Clínica Dental Sonrisa Viva ofrece consultas odontológicas en Medellín desde $70.000. "
            "Ver Anexo 1 para tarifas."
        ),
        simulation_requirement="Validar demanda de servicios odontológicos.",
        filenames=["clinica.pdf"],
        use_llm=False,
        project_dir=tmp_path / "proj_adv_clinica",
    )
    assert clinica_adv["project_name"] == "Clínica Dental Sonrisa Viva"
    assert clinica_adv["sector"] == "salud_bienestar"
    assert "Ara" not in clinica_adv["competitors"]

    # 4. Saltos de línea en KAVO, abreviaturas, "se llama", inicios genéricos y fragmentos rotos
    assert extract_real_project_name(
        extracted_text="KAVO\nKAVO es una plataforma B2B de logística urbana en Colombia.",
        simulation_requirement="Validar KAVO.",
    ) == "KAVO"
    assert extract_real_project_name(
        extracted_text="La empresa ofrece soluciones logísticas.\nEste proyecto conecta flotas.",
        simulation_requirement="Empresa: RutaYa",
    ) == "RutaYa"
    assert extract_real_project_name(
        simulation_requirement="Empresa: Dr. Sonrisa Vital",
    ) == "Dr. Sonrisa Vital"
    assert extract_real_project_name(
        simulation_requirement="la panadería se llama el trigo dorado y vende pan artesanal en Bogotá",
    ) == "El Trigo Dorado"
    broken_name = extract_real_project_name(
        extracted_text=(
            "DOCUMENTO ESTRATÉGICO INTEGRAL\n"
            "Plan de negocio, ADN de marca y\n"
            "especificaciones de plataforma digital\n"
            "Servicio especializado de orientación, asesoría, acompañamiento y gestión de reclamaciones\n"
            "de terceros ante aseguradoras\n"
            "1. Plan de negocio aterrizado"
        ),
        simulation_requirement="https://chatgpt.com/share/abc\n\nSIMULA Y PREDICE ESTA EMPRESA EN COLOMBIA",
        filenames=["Documento_Integral_Reclamaciones_Version_Ampliada.pdf"],
    )
    assert broken_name == "Estudio de Mercado"
    assert "Plan de negocio" not in broken_name
    assert not broken_name.endswith(" y")

    # 5. Strip de '# ' en value_proposition
    vp_ctx = extract_and_build_study_context(
        project_id="proj_adv_vp",
        extracted_text="# PROMPTA: Generador Inteligente de Prompts Estructurados en Español",
        simulation_requirement="Validar Prompta en Colombia.",
        use_llm=False,
        project_dir=tmp_path / "proj_adv_vp",
    )
    assert not vp_ctx["value_proposition"].startswith("#")

    # 6. COP decimal cents (,00 / .00) sin romper miles (.000) y prefijo "Tienda:"
    assert _parse_cop_number("15.000,00") == 15000
    assert _parse_cop_number("15,000.00") == 15000
    assert _parse_cop_number("15.000") == 15000
    dec_ctx = extract_and_build_study_context(
        project_id="proj_adv_dec",
        extracted_text="Tienda: Miscelánea La Esperanza\nTicket promedio COP $15.000,00 en el barrio.",
        simulation_requirement="Validar Miscelánea La Esperanza con ticket COP $15.000,00.",
        use_llm=False,
        project_dir=tmp_path / "proj_adv_dec",
    )
    assert dec_ctx["project_name"] == "Miscelánea La Esperanza"
    assert dec_ctx["reference_price_cop"] == 15000
    assert dec_ctx["price_ladder_cop"][-1] <= 40000

    # 6b. No backtracking mid-token en rangos "Precio de $X,00 y $Y,00" y "Tarifa de $X a $Y"
    range_dec_ctx = extract_and_build_study_context(
        project_id="proj_adv_range_dec",
        extracted_text="Tienda: Café Real\nPrecio de $15.000,00 y $30.000,00 en Bogotá.",
        simulation_requirement="Validar Café Real en Bogotá.",
        use_llm=False,
        project_dir=tmp_path / "proj_adv_range_dec",
    )
    assert range_dec_ctx["project_name"] == "Café Real"
    assert 15000 <= range_dec_ctx["reference_price_cop"] <= 30000
    assert range_dec_ctx["price_ladder_cop"][-1] <= 40000

    range_pyme_ctx = extract_and_build_study_context(
        project_id="proj_adv_range_pyme",
        extracted_text="Empresa: Consultora Beta\nTarifa de $500.000 a $1.000.000 para pymes.",
        simulation_requirement="Validar Consultora Beta en Colombia.",
        use_llm=False,
        project_dir=tmp_path / "proj_adv_range_pyme",
    )
    assert range_pyme_ctx["project_name"] == "Consultora Beta"
    assert range_pyme_ctx["reference_price_cop"] >= 500000
    assert range_pyme_ctx["price_ladder_cop"][0] >= 350000

    range_corp_ctx = extract_and_build_study_context(
        project_id="proj_adv_range_corp",
        extracted_text="Empresa: Soluciones Alfa\nTarifa de $1.200.000 a $2.500.000 para empresas.",
        simulation_requirement="Validar Soluciones Alfa en Colombia.",
        use_llm=False,
        project_dir=tmp_path / "proj_adv_range_corp",
    )
    assert range_corp_ctx["project_name"] == "Soluciones Alfa"
    assert range_corp_ctx["reference_price_cop"] >= 1200000
    assert range_corp_ctx["price_ladder_cop"][0] >= 800000

    range_cop_ctx = extract_and_build_study_context(
        project_id="proj_adv_range_cop",
        extracted_text="Ferretería: El Tornillo Feliz\nPrecios entre COP $500.000 y $1.000.000 para obras.",
        simulation_requirement="la ferretería se llama El Tornillo Feliz y repara herramientas",
        use_llm=False,
        project_dir=tmp_path / "proj_adv_range_cop",
    )
    assert range_cop_ctx["project_name"] == "El Tornillo Feliz"
    assert range_cop_ctx["reference_price_cop"] >= 500000
    assert range_cop_ctx["price_ladder_cop"][0] >= 350000

    assert extract_real_project_name(
        simulation_requirement="la ferretería se llama El Tornillo Feliz y repara herramientas",
    ) == "El Tornillo Feliz"
    assert extract_real_project_name(
        extracted_text="Tienda: Miscelánea La Esperanza\nTicket promedio COP $15.000,00 en el barrio.",
    ) == "Miscelánea La Esperanza"

    # 7. _enrich_with_llm debe exigir >= 4 elementos para target_roles
    base_roles = ["Rol_1", "Rol_2", "Rol_3", "Rol_4"]
    base_ctx = {
        "project_name": "KAVO",
        "sector": "logistica_domicilios",
        "value_proposition": "Plataforma de logística urbana en Colombia.",
        "offer_summary": "Logística urbana B2B.",
        "target_roles": list(base_roles),
        "competitors": ["Servientrega", "Coordinadora", "Interrapidísimo"],
        "key_risks_objections": ["Demoras", "Costo", "Confianza"],
    }
    with patch("app.utils.llm_client.LLMClient") as mock_llm_cls:
        mock_llm_cls.return_value.chat_json.return_value = {
            "target_roles": ["Solo_1", "Solo_2", "Solo_3"],
            "competitors": ["Comp_A", "Comp_B", "Comp_C"],
        }
        enriched_short = _enrich_with_llm(base_ctx, "texto", "req")
        assert enriched_short["target_roles"] == base_roles
        assert enriched_short["competitors"] == ["Comp_A", "Comp_B", "Comp_C"]

        mock_llm_cls.return_value.chat_json.return_value = {
            "target_roles": ["Rol_A", "Rol_B", "Rol_C", "Rol_D", "Rol_E"],
        }
        enriched_ok = _enrich_with_llm(base_ctx, "texto", "req")
        assert len(enriched_ok["target_roles"]) == 5

