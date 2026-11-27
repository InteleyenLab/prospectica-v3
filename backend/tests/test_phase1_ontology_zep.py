"""Pruebas de Fase 1 para ZepEntityReader (actores vs contexto) y OntologyGenerator con país."""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import create_app
from app.services.ontology_generator import MAX_ONTOLOGY_TYPES, OntologyGenerator
from app.services.zep_entity_reader import NON_HUMAN_ENTITY_TYPES, ZepEntityReader


def test_zep_entity_reader_separates_context_nodes_from_simulatable_actors():
    reader = ZepEntityReader.__new__(ZepEntityReader)
    sample_nodes = [
        {"uuid": "u1", "name": "Carlos Motociclista", "labels": ["Entity", "Citizen"], "summary": "Usuario Cali", "attributes": {}},
        {"uuid": "u2", "name": "Aseguradora Sur", "labels": ["Entity", "InsuranceCompany"], "summary": "Aseguradora", "attributes": {}},
        {"uuid": "u3", "name": "SMMLV Colombia 2026", "labels": ["Entity", "MacroIndicator"], "summary": "1.750.905 COP", "attributes": {}},
        {"uuid": "u4", "name": "Estrato 3 Urbano", "labels": ["Entity", "DemographicStratum"], "summary": "31% hogares", "attributes": {}},
        {"uuid": "u5", "name": "Medellín DIVIPOLA 05001", "labels": ["Entity", "TerritoryMetric"], "summary": "Población", "attributes": {}},
    ]

    with patch.object(reader, "get_all_nodes", return_value=sample_nodes), patch.object(
        reader, "get_all_edges", return_value=[]
    ):
        actors = reader.fetch_simulatable_actors("graph_test")
        assert {a.name for a in actors.entities} == {"Carlos Motociclista", "Aseguradora Sur"}
        for a in actors.entities:
            assert a.get_entity_type() not in NON_HUMAN_ENTITY_TYPES

        ctx = reader.fetch_context_nodes("graph_test")
        assert {c.name for c in ctx.entities} == {
            "SMMLV Colombia 2026",
            "Estrato 3 Urbano",
            "Medellín DIVIPOLA 05001",
        }

        # Compatibilidad hacia atrás de filter_defined_entities sin filtro de humanos
        all_filtered = reader.filter_defined_entities("graph_test")
        assert all_filtered.filtered_count == 5


def test_ontology_generator_injects_country_pack_context_and_respects_zep_cap():
    captured_messages = {}

    def fake_chat_json(messages, temperature=0.2, max_tokens=8000, max_attempts=2):
        captured_messages["user"] = messages[1]["content"]
        return {
            "entity_types": [
                {"name": f"Type{i}", "description": f"Desc {i}", "attributes": [], "examples": []}
                for i in range(12)
            ],
            "edge_types": [],
            "analysis_summary": "Resumen de prueba colombiano.",
        }

    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = fake_chat_json
    gen = OntologyGenerator(llm_client=mock_llm)

    res = gen.generate(
        document_texts=["Documento NEXO reclamaciones en Colombia."],
        simulation_requirement="Validar demanda de orientación inicial COP $70.000",
        country_code="co",
        target_cities=["Medellín", "Bogotá"],
    )

    assert "Medellín" in captured_messages["user"]
    assert "05001" in captured_messages["user"]
    assert len(res["entity_types"]) <= MAX_ONTOLOGY_TYPES


def test_ontology_generate_endpoint_accepts_territorial_fields(tmp_path):
    app = create_app()
    client = app.test_client()

    mock_ontology = {
        "entity_types": [
            {"name": "Citizen", "description": "Ciudadano", "attributes": [{"name": "city", "type": "text", "description": "Ciudad"}], "examples": ["Ana"]},
            {"name": "Organization", "description": "Organización", "attributes": [], "examples": ["NEXO"]},
        ],
        "edge_types": [
            {"name": "CONSULTS", "description": "Consulta", "source_targets": [{"source": "Citizen", "target": "Organization"}], "attributes": []}
        ],
        "analysis_summary": "Ontología colombiana generada correctamente.",
    }

    with patch("app.api.graph.OntologyGenerator") as mock_gen_cls:
        mock_gen_cls.return_value.generate.return_value = mock_ontology
        resp = client.post(
            "/api/graph/ontology/generate",
            data={
                "simulation_requirement": "Estudio de mercado NEXO en Colombia",
                "project_name": "Test Territorial Fase 1",
                "country_code": "co",
                "target_cities": '["Medellín", "Bogotá"]',
                "target_strata": '["E2", "E3"]',
                "use_official_sources": "false",
                "use_live_web": "false",
                "files": (io.BytesIO(b"Texto de prueba para validar flujo territorial."), "brief.txt"),
            },
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["country_code"] == "co"
    assert data["target_cities"] == ["Medellín", "Bogotá"]
    assert data["quant_store_path"]
    assert isinstance(data["extraction_audit"], list)
    assert "country_context" in data

    # Limpieza de proyecto temporal creado durante la prueba
    client.delete(f"/api/graph/project/{data['project_id']}")
