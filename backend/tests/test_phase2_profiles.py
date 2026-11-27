"""Pruebas de Fase 2 (Gate G2): muestreo colombiano, sesgos cero, varianza y smoke LLM real."""

from __future__ import annotations

import json
import re
import statistics
import time
from typing import List
from unittest.mock import patch

import pytest

from app import create_app
from app.config import Config
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.simulation_config_generator import SimulationConfigGenerator
from app.services.zep_entity_reader import EntityNode


def _build_nexo_mixed_entities(human_count: int) -> List[EntityNode]:
    """Construye mezcla realista con entidades humanas/organizacionales y trampas no humanas."""
    entities: List[EntityNode] = [
        EntityNode(uuid="trap-1", name="Servicio A Orientación", labels=["Entity", "Service"], summary="Servicio", attributes={}),
        EntityNode(uuid="trap-2", name="WhatsApp Canal", labels=["Entity", "Channel"], summary="Canal", attributes={}),
        EntityNode(uuid="trap-3", name="Reclamación Daños", labels=["Entity", "Claim"], summary="Reclamo", attributes={}),
        EntityNode(uuid="trap-4", name="Medellín Métrica", labels=["Entity", "City"], summary="Ciudad", attributes={}),
    ]
    for i in range(human_count):
        etype = "Organization" if i % 8 == 7 else ("InsuranceCompany" if i % 10 == 9 else "Citizen")
        entities.append(
            EntityNode(
                uuid=f"actor-{i}",
                name=f"Ciudadano NEXO {i+1}",
                labels=["Entity", etype],
                summary=f"Actor colombiano del ecosistema de movilidad y reclamaciones #{i+1}.",
                attributes={"sector": "movilidad/seguros"},
            )
        )
    return entities


@pytest.mark.parametrize("sample_size", [24, 100])
def test_demographic_audit_on_nexo_samples_24_and_100(sample_size: int):
    entities = _build_nexo_mixed_entities(sample_size)
    gen = OasisProfileGenerator(
        api_key="test-key",
        base_url="http://127.0.0.1:3001/v1",
        model_name="auto",
        zep_api_key="",
        country_code="co",
        target_cities=["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga"],
    )
    profiles = gen.generate_profiles_from_entities(
        entities=entities,
        use_llm=False,
        parallel_count=4,
    )

    assert len(profiles) == sample_size
    for p in profiles:
        assert p.country not in {"中国", "China"}
        assert p.source_entity_type not in {"Service", "Channel", "Claim", "City"}
        assert len(p.persona) <= 650
        assert p.city_name
        assert p.divipola_code and len(p.divipola_code) == 5
        assert p.stratum_code

    skeptic_ratio = sum(1 for p in profiles if p.attitude_segment in {"esceptico", "critico_hate"}) / len(profiles)
    assert skeptic_ratio >= 0.40

    istj_ratio = sum(1 for p in profiles if (p.mbti or "").upper() == "ISTJ") / len(profiles)
    assert istj_ratio <= 0.25


def test_simulation_config_generator_behavioral_variance_and_bogota_timezone(tmp_path):
    entities = [
        EntityNode(uuid=f"e-{i}", name=f"Actor {i}", labels=["Entity", "Citizen"], summary="Usuario colombiano", attributes={})
        for i in range(16)
    ]
    cfg_gen = SimulationConfigGenerator(
        api_key="test-key",
        base_url="http://127.0.0.1:3001/v1",
        model_name="auto",
    )

    with patch.object(cfg_gen, "_call_llm_with_retry", side_effect=RuntimeError("offline fallback check")):
        params = cfg_gen.generate_config(
            simulation_id="sim_phase2_check",
            project_id="proj_phase2_check",
            graph_id="graph_phase2_check",
            simulation_requirement="Validar tarifa Servicio A COP $70.000 para conductores y pymes en Colombia",
            document_text="NEXO Reclamaciones acompaña trámites de responsabilidad civil en Colombia.",
            entities=entities,
            country_code="co",
            target_cities=["Bogotá", "Medellín", "Cali"],
        )

    raw_json = params.to_json()
    out_file = tmp_path / "simulation_config.json"
    out_file.write_text(raw_json, encoding="utf-8")
    parsed = json.loads(out_file.read_text(encoding="utf-8"))

    assert parsed["time_config"]["timezone"] == "America/Bogota"
    assert parsed["time_config"]["utc_offset"] == "UTC-5"
    assert not re.search(r"[\u4e00-\u9fff]", raw_json)

    stances = {a["stance"] for a in parsed["agent_configs"]}
    activities = [a["activity_level"] for a in parsed["agent_configs"]]
    assert len(stances) >= 3
    assert statistics.stdev(activities) > 0.10


def test_live_llm_smoke_10_profiles_under_60s():
    """Smoke test en vivo contra FreeLLMAPI (`127.0.0.1:3001/v1`) generando 10 perfiles."""
    entities = _build_nexo_mixed_entities(10)[4:]
    gen = OasisProfileGenerator(
        api_key=Config.LLM_API_KEY or "free",
        base_url=Config.LLM_BASE_URL or "http://127.0.0.1:3001/v1",
        model_name=Config.LLM_MODEL_NAME or "auto",
        zep_api_key="",
        country_code="co",
        target_cities=["Bogotá", "Medellín", "Cali"],
    )
    t0 = time.monotonic()
    profiles = gen.generate_profiles_from_entities(
        entities=entities,
        use_llm=True,
        parallel_count=4,
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 60.0
    assert len(profiles) == 10
    for p in profiles:
        assert p.country not in {"中国", "China"}
        assert len(p.persona) <= 650
        assert p.bio


def test_historical_simulation_sim_345b78a4490f_still_accessible():
    app = create_app()
    client = app.test_client()
    r = client.get("/api/simulation/sim_345b78a4490f")
    assert r.status_code == 200
    assert r.get_json()["success"] is True
