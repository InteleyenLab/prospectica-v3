"""Pruebas unitarias e integración de Fase 3 (Conectores GitHub/Web, Cumplimiento/Eliminación Ley 1581)."""

from __future__ import annotations

from pathlib import Path

from app import create_app
from app.services.github_connector import GitHubReadOnlyConnector
from app.services.live_web_researcher import LiveWebResearcher
from app.services.secondary_research import EvidenceLedger


def test_p3_github_readonly_connector_and_secret_redaction():
    res = GitHubReadOnlyConnector.analyze_repository_snapshot(
        repo_url="https://github.com/org/proyecto-colombia",
        readme_text="Plataforma Flask + Vue con token ghp_123456789012345678901234567890",
        file_tree=["backend/app.py", "frontend/package.json"],
    )
    assert res["mode"] == "read_only"
    assert res["training_opt_out"] is True
    assert res["secrets_detected_count"] >= 1
    assert res["secrets_redacted"] is True
    assert "ghp_" not in res["product_summary"]
    assert "flask" in res["detected_stack"]


def test_p3_live_web_researcher_robots_and_evidence_ledger(tmp_path: Path):
    researcher = LiveWebResearcher(rate_limit_seconds=0.0)
    assert researcher.check_robots_allowed("http://127.0.0.1:9999/test") is True
    ledger = EvidenceLedger(project_dir=tmp_path)
    out = researcher.research("Validar ecommerce en Colombia", evidence_ledger=ledger)
    assert len(out["queries"]) >= 1


def test_p3_compliance_and_connector_endpoints():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    pid = "proj_p3_compliance_test"
    r_brief = client.post(
        "/api/brief",
        json={
            "project_id": pid,
            "brief": {"project_name": "TiendaCO", "description": "Ecommerce local en Bogotá"},
            "consent": {"accepted_privacy": True, "accepted_synthetic_nature": True, "no_unnecessary_pii": True},
        },
    )
    assert r_brief.status_code == 200

    r_rec = client.get(f"/api/compliance/records?project_id={pid}")
    assert r_rec.status_code == 200
    assert r_rec.get_json()["data"]["count"] == 1

    r_gh = client.post(
        "/api/connectors/github/inspect",
        json={"repo_url": "https://github.com/org/tiendaco", "readme_text": "Vue app"},
    )
    assert r_gh.status_code == 200
    assert r_gh.get_json()["data"]["mode"] == "read_only"

    r_del = client.delete(f"/api/project/{pid}/data")
    assert r_del.status_code == 200
    assert r_del.get_json()["data"]["deleted"] is True
