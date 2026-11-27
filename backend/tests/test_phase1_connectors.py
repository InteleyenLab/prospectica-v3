"""Pruebas de Fase 1 para normalización colombiana, conectores Socrata/Web y fusión en quant_store.sqlite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.context_fusion import ContextFusionService
from app.services.live_web_researcher import LiveWebResearcher
from country_packs.co.connectors import (
    SocrataColombiaConnector,
    is_dataset_stale,
    normalize_divipola,
    parse_colombian_number,
)


def test_colombian_normalization_and_staleness():
    assert normalize_divipola("5001") == "05001"
    assert normalize_divipola("11001.0") == "11001"
    assert normalize_divipola("") == ""

    assert abs(parse_colombian_number("6,246631") - 6.246631) < 1e-6
    assert abs(parse_colombian_number("$ 1.750.905,50") - 1750905.50) < 1e-4

    ref = datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert is_dataset_stale("2026-04-25", max_staleness_days=14, reference_now=ref) is False
    assert is_dataset_stale("2025-12-01", max_staleness_days=14, reference_now=ref) is True
    assert is_dataset_stale(None) is True


def test_socrata_connector_handles_live_success_and_graceful_fallback():
    connector = SocrataColombiaConnector(timeout_seconds=2.0)

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [
        {"valor": "4125,35", "vigenciadesde": "2026-11-24T00:00:00.000"}
    ]
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_resp

    with patch("country_packs.co.connectors.socrata_co.httpx.Client", return_value=mock_client):
        trm = connector.fetch_trm()
        assert trm["fallback_used"] is False
        assert abs(trm["value"] - 4125.35) < 1e-4
        assert trm["unit"] == "COP/USD"

    with patch(
        "country_packs.co.connectors.socrata_co.httpx.Client",
        side_effect=RuntimeError("network unreachable"),
    ):
        trm_fail = connector.fetch_trm()
        assert trm_fail["fallback_used"] is True
        assert trm_fail["value"] is None  # Nunca inventa cifras ante caída


def test_live_web_researcher_parses_html_and_handles_offline():
    sample_html = (
        '<a class="result__a" href="https://example.co/seguros">Mercado de seguros Colombia 2026</a>'
        '<div class="result__snippet">Crecimiento del sector RC y motos en ciudades capitales.</div>'
    )
    parsed = LiveWebResearcher._parse_ddg_html(sample_html)
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Mercado de seguros Colombia 2026"
    assert "seguros" in parsed[0]["url"]

    researcher = LiveWebResearcher(timeout_seconds=1.0)
    with patch("app.services.live_web_researcher.httpx.Client", side_effect=OSError("offline")):
        out = researcher.research("NEXO reclamaciones motos", "Colombia", ["Bogotá", "Cali"])
        assert out["live_web_available"] is False
        assert out["findings"] == []
        assert len(out["errors"]) >= 1


def test_context_fusion_writes_quant_store_and_enforces_dual_precedence(tmp_path: Path):
    fake_connector = MagicMock(spec=SocrataColombiaConnector)
    fake_connector.fetch_trm.return_value = {
        "metric_key": "trm_cop_usd",
        "value": None,
        "unit": "COP/USD",
        "observed_at": None,
        "is_stale": True,
        "source_authority": "Superintendencia Financiera",
        "fallback_used": True,
        "error": "timeout simulado",
    }
    fake_connector.fetch_sector_signals.return_value = [
        {
            "metric_key": "quejas_superfinanciera",
            "dataset_id": "qzsc-9esp",
            "authority": "Superfinanciera",
            "source_tier": "A",
            "rows_count": 3,
            "live_available": True,
        }
    ]

    fake_web = MagicMock(spec=LiveWebResearcher)
    fake_web.research.return_value = {
        "queries": ["Colombia seguros"],
        "findings": [
            {
                "title": "Estudio movilidad",
                "url": "https://ejemplo.co/movilidad",
                "snippet": "Parque de motos activo en Cali y Medellín.",
                "source_tier": "C_WEB",
            }
        ],
        "errors": [],
        "live_web_available": True,
    }

    fusion = ContextFusionService(socrata_connector=fake_connector, web_researcher=fake_web)
    result = fusion.build_and_persist(
        project_id="proj_test_fusion",
        project_dir=tmp_path,
        country_code="co",
        target_cities=["Bogotá", "Medellín"],
        target_strata=["E2", "E3", "E4"],
        simulation_requirement="Estudio NEXO reclamaciones precio Servicio A COP $70.000",
        document_texts=["El salario mínimo estimado antiguo es COP $1.300.000. Tarifa COP $70.000."],
        use_official_sources=True,
        use_live_web=True,
    )

    db_path = Path(result["quant_store_path"])
    assert db_path.exists()
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["official_value"] == 1750905.0
    assert any(g["metric_key"] == "trm_cop_usd" for g in result["data_gaps"])

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT metric_key, source_tier FROM quant_indicators").fetchall()
        keys = {r[0]: r[1] for r in rows}
        assert keys["smmlv_local"] == "A"
        assert "USER_STUDY" in rows[0] or any(r[1] == "USER_STUDY" for r in rows)
        gaps = conn.execute("SELECT metric_key FROM data_gaps").fetchall()
        assert any(g[0] == "trm_cop_usd" for g in gaps)
    finally:
        conn.close()
