"""Tier 1: Core Feature Tests (30 tests — 5 per Feature Area FA1–FA6).

Derived strictly from ORIGINAL_REQUEST.md (R1–R4 + Acceptance Criteria) and
PROJECT.md § Interface Contracts. All tests run opaque-box in isolated tmp_path.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from io import BytesIO
from pathlib import Path

from app.channels import CANONICAL_CHANNEL_IDS
from app.channels.adapters._helpers import build_event, select_diverse_actors
from app.channels.engine import ChannelSimulationEngine
from app.channels.persistence import ChannelSQLiteStore
from app.services.analytics import AnalyticsBundleBuilder
from app.services.report_agent_v2 import ReportAgentV2, verify_numeric_consistency
from app.services.survey_engine import SurveyEngine

from .conftest import (
    extract_ch8_quotes,
    extract_download_filename,
    parse_ch7_friction_table,
    parse_gabor_granger_table,
    query_sqlite_rows,
)
from .fixtures_colombia import (
    build_agrocafe_tolima_fixture,
    build_clinica_dental_fixture,
    build_miscelanea_esperanza_fixture,
    build_rutafacil_saas_fixture,
    load_cofre_fixture,
)


# ===========================================================================
# FA1: Dynamic StudyContext & Pipeline Generation from PDF + Home Prompt (R1)
# ===========================================================================


def test_t1_fa1_study_context_persisted_and_populated(run_pipeline):
    """Uploading PDF + Home prompt persists `study_context.json` with all contract fields."""
    fx = build_miscelanea_esperanza_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=["whatsapp_1on1", "street_survey", "focus_group"])

    sc_path = res.project_dir / "study_context.json"
    assert sc_path.exists(), "study_context.json must be persisted in project_dir (R1 / F1)"
    sc = res.study_context
    assert isinstance(sc, dict)

    required_keys = {
        "project_id", "project_name", "project_slug", "sector", "business_model",
        "geographic_scope", "value_proposition", "offer_summary",
        "price_ladder_cop", "reference_price_cop", "unit_var_cost_cop",
        "monthly_opex_cop", "unit_label", "target_roles", "competitors",
        "key_channels", "key_risks_objections", "regulatory_scope",
        "domain_keywords", "codebook_rules", "dofa_seed",
    }
    missing = required_keys - set(sc.keys())
    assert not missing, f"study_context.json missing contract keys: {missing}"
    assert sc["project_id"] == res.project_id
    assert isinstance(sc["price_ladder_cop"], list) and len(sc["price_ladder_cop"]) == 5
    assert sc["price_ladder_cop"] == sorted(sc["price_ladder_cop"])
    assert all(isinstance(p, (int, float)) and p > 0 for p in sc["price_ladder_cop"])
    assert sc["sector"] and sc["value_proposition"] and sc["unit_label"]
    assert len(sc["target_roles"]) >= 2
    assert len(sc["domain_keywords"]) >= 2
    assert isinstance(sc["codebook_rules"], list) and len(sc["codebook_rules"]) >= 3
    assert isinstance(sc["dofa_seed"], dict)


def test_t1_fa1_profiles_reflect_project_domain_not_nexo(run_pipeline):
    """OASIS profiles for a coffee cooperative reflect coffee domain and zero NEXO fallbacks."""
    fx = build_agrocafe_tolima_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=["whatsapp_1on1", "focus_group"])

    assert len(res.profiles) >= 8
    serialized = json.dumps(res.profiles, ensure_ascii=False)
    assert "Conductor_Movilidad" not in serialized, "Hardcoded NEXO role leaked into profiles"
    assert "Seguros y Reclamaciones" not in serialized, "Hardcoded NEXO topic leaked into profiles"


def test_t1_fa1_channel_events_reflect_project_offer(run_pipeline):
    """Multichannel DB events reflect the uploaded business offer and omit NEXO insurance jargon."""
    fx = build_miscelanea_esperanza_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=1)

    db_path = res.sim_dir / "simulation_channels.db"
    events = query_sqlite_rows(db_path, "SELECT content_text FROM channel_events")
    wa = query_sqlite_rows(db_path, "SELECT content_text FROM whatsapp_sessions")
    fg = query_sqlite_rows(db_path, "SELECT content_text FROM focus_group_turns")
    all_text = " ".join(r["content_text"] for r in (events + wa + fg)).lower()

    assert len(events) >= 11
    for forbidden in ("choque", "aseguradora", "nexo", "indemnizaci"):
        assert forbidden not in all_text, f"Residual domain leakage '{forbidden}' in Miscelánea channel texts"
    assert any(kw in all_text for kw in ("miscelánea", "esperanza", "papelería", "útiles", "barrio")), (
        "Channel events do not mention uploaded business domain"
    )


def test_t1_fa1_survey_prices_anchored_to_study_context(run_pipeline):
    """Structured survey Gabor-Granger ladder reflects StudyContext micro-prices, not NEXO 35k-140k."""
    fx = build_miscelanea_esperanza_fixture()
    res = run_pipeline(fx, sample_size=50, channel_ids=["whatsapp_1on1", "street_survey"])

    gg = res.analytics_bundle["pricing_econometrics"]["gabor_granger"]
    points = gg.get("points") or []
    assert len(points) >= 3
    prices = [int(pt["price"]) for pt in points]
    assert prices != [35000, 50000, 70000, 100000, 140000], (
        "Survey defaulted to hardcoded NEXO price ladder instead of Miscelánea COP 2k-20k"
    )
    assert max(prices) <= 45_000, f"Micro-retail prices escalated unexpectedly: {prices}"


def test_t1_fa1_finance_and_dofa_dynamic(run_pipeline):
    """Unit economics uses domain unit_label (not 'casos/mes'), omits 'Servicio B', and charts_spec has DOFA."""
    fx = build_rutafacil_saas_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=["whatsapp_1on1", "colombian_web", "focus_group"])

    fin = res.analytics_bundle["funnel_finance"]
    fin_str = json.dumps(fin, ensure_ascii=False)
    be_unit = str(((fin.get("unit_economics_ranges") or {}).get("break_even_cases") or {}).get("unit") or "")
    assert be_unit and be_unit.lower() != "casos/mes", f"Hardcoded 'casos/mes' in SaaS break-even unit: {be_unit}"
    assert "Servicio B" not in fin_str, "Hardcoded 'Servicio B' leaked into finance output"
    assert "Decreto 196/1971" not in fin_str, "Hardcoded legal decree leaked into SaaS regulatory warnings"

    dofa = (res.analytics_bundle.get("charts_spec") or {}).get("dofa_matrix")
    assert isinstance(dofa, dict) and "scores" in dofa and "items" in dofa, (
        "charts_spec.dofa_matrix missing dynamic DOFA contract"
    )


# ===========================================================================
# FA2: Real Project Name Extraction, Brand Replacement & Download Filename (R2)
# ===========================================================================


def test_t1_fa2_extracts_cofre_from_5block_prompt_and_pdf(run_pipeline, tmp_path):
    """Real COFRE PDF + 5-block prompt without explicit project_name extracts 'COFRE'."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, explicit_project_name=None, sample_size=40, channel_ids=["whatsapp_1on1", "focus_group"])

    assert res.project_name.upper().startswith("COFRE"), (
        f"Expected extracted project name 'COFRE', got {res.project_name!r}"
    )
    assert "unnamed project" not in res.project_name.lower()
    assert "disenar un plan" not in res.project_name.lower()
    assert "bloque" not in res.project_name.lower()


def test_t1_fa2_no_prospectica_inc_in_report_h1_or_headers(run_pipeline, tmp_path):
    """Report H1, manifest title, brand, and header_label replace 'Prospéctica Inc.' with real name."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, sample_size=40, channel_ids=["whatsapp_1on1", "focus_group"])

    first_line = res.full_report_md.splitlines()[0] if res.full_report_md else ""
    assert "Prospéctica Inc." not in first_line, f"H1 still contains Prospéctica Inc.: {first_line}"
    assert "COFRE" in first_line.upper(), f"H1 missing extracted project name: {first_line}"

    man = res.manifest
    for field in ("title", "brand", "header_label", "project_name"):
        val = str(man.get(field) or "")
        assert "Prospéctica Inc." not in val, f"manifest[{field!r}] leaked Prospéctica Inc.: {val}"
    assert "COFRE" in str(man.get("title") or "").upper()
    assert "COFRE" in str(man.get("project_name") or "").upper()


def test_t1_fa2_download_filename_uses_project_slug(run_pipeline, tmp_path):
    """GET /api/report/<report_id>/download returns `<project_slug>_<report_id>.md`."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, sample_size=40, channel_ids=["whatsapp_1on1"])

    assert res.download_filename.startswith("cofre_"), (
        f"Expected download filename starting with 'cofre_', got {res.download_filename!r}"
    )
    assert res.download_filename.endswith(f"{res.report_id}.md")
    assert "prospectica" not in res.download_filename.lower()


def test_t1_fa2_explicit_user_project_name_preserved(run_pipeline):
    """Explicit valid `project_name` from Home is preserved across project, manifest, H1, and filename."""
    fx = build_agrocafe_tolima_fixture()
    custom_name = "Café Quindío Directo"
    res = run_pipeline(fx, explicit_project_name=custom_name, sample_size=40, channel_ids=["whatsapp_1on1"])

    assert res.project_name == custom_name
    assert custom_name in res.full_report_md.splitlines()[0]
    assert custom_name in str(res.manifest.get("title") or "")
    assert res.download_filename == f"cafe_quindio_directo_{res.report_id}.md"


def test_t1_fa2_no_truncated_prompt_lines_in_ch6_ch11(run_pipeline, tmp_path):
    """Ch.6 'Oferta Principal' and Ch.11 'Matriz DOFA' contain real subject, never truncated prompt lines."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, sample_size=40, channel_ids=["whatsapp_1on1", "focus_group"])

    ch6 = res.chapters[6]["content_markdown"]
    ch11 = res.chapters[11]["content_markdown"]
    for label, text in (("Ch.6", ch6), ("Ch.11", ch11)):
        low = text.lower()
        assert "disenar un plan" not in low, f"{label} leaked raw prompt line"
        assert "bloque 1" not in low and "actua como" not in low, f"{label} leaked prompt boilerplate"
        assert "mercad)" not in low and "confianza par)" not in low, f"{label} truncated mid-word"


# ===========================================================================
# FA3: Project & Simulation Isolation (R3)
# ===========================================================================


def test_t1_fa3_two_projects_zero_entity_and_text_cross_contamination(run_pipeline, tmp_path):
    """Running Project A (COFRE) then Project B (Miscelánea La Esperanza) yields zero cross-bleed."""
    fx_a = load_cofre_fixture(tmp_path)
    fx_b = build_miscelanea_esperanza_fixture()

    res_a = run_pipeline(fx_a, sample_size=40, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=1)
    res_b = run_pipeline(fx_b, sample_size=40, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=1)

    b_corpus = " ".join([
        json.dumps(res_b.study_context or {}, ensure_ascii=False),
        json.dumps(res_b.profiles, ensure_ascii=False),
        json.dumps(res_b.analytics_bundle, ensure_ascii=False),
        res_b.full_report_md,
    ]).lower()

    for leak in ("cofre", "social finder", "pago protegido", "escrow"):
        assert leak not in b_corpus, f"Project A term {leak!r} leaked into Project B ({res_b.project_id})"
    assert "cofre" in res_a.full_report_md.lower()


def test_t1_fa3_artifacts_strictly_separated_by_ids(run_pipeline, tmp_path):
    """Distinct projects use disjoint IDs and `ChannelSQLiteStore` scopes queries by `simulation_id`."""
    fx_a = load_cofre_fixture(tmp_path)
    fx_b = build_clinica_dental_fixture()

    res_a = run_pipeline(fx_a, sample_size=30, channel_ids=["whatsapp_1on1"])
    res_b = run_pipeline(fx_b, sample_size=30, channel_ids=["whatsapp_1on1"])

    assert res_a.project_id != res_b.project_id
    assert res_a.graph_id != res_b.graph_id
    assert res_a.simulation_id != res_b.simulation_id
    assert res_a.report_id != res_b.report_id
    assert res_a.project_dir != res_b.project_dir
    assert res_a.sim_dir != res_b.sim_dir
    assert res_a.report_dir != res_b.report_dir

    # Shared SQLite store scoped by simulation_id must isolate rows
    shared_dir = tmp_path / "shared_isolation_check"
    shared_dir.mkdir(parents=True, exist_ok=True)
    store = ChannelSQLiteStore(shared_dir)
    store.record_channel_event(
        res_a.simulation_id,
        build_event({"user_id": 1, "name": "ActorA", "attitude_segment": "esceptico"}, "whatsapp_1on1", 1, 10, "MSG", "Texto A"),
    )
    store.record_channel_event(
        res_b.simulation_id,
        build_event({"user_id": 2, "name": "ActorB", "attitude_segment": "promotor"}, "whatsapp_1on1", 1, 10, "MSG", "Texto B"),
    )
    ev_a = store.query_events(simulation_id=res_a.simulation_id)
    ev_b = store.query_events(simulation_id=res_b.simulation_id)
    assert len(ev_a) == 1 and ev_a[0]["content_text"] == "Texto A"
    assert len(ev_b) == 1 and ev_b[0]["content_text"] == "Texto B"


def test_t1_fa3_rerun_channels_and_survey_does_not_duplicate_rows(client, tmp_path):
    """Re-running channels and survey on the same `sim_id` replaces prior rows instead of 2x accumulation."""
    sim_id = "sim_rerun_dedup_check"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    r1_ch = client.post(f"/api/channels/{sim_id}/run", json={"enabled_channels": ["whatsapp_1on1"], "rounds": 1})
    assert r1_ch.status_code == 200
    ev_count_1 = len(query_sqlite_rows(sim_dir / "simulation_channels.db", "SELECT id FROM channel_events WHERE simulation_id=?", (sim_id,)))

    r2_ch = client.post(f"/api/channels/{sim_id}/run", json={"enabled_channels": ["whatsapp_1on1"], "rounds": 1})
    assert r2_ch.status_code == 200
    ev_count_2 = len(query_sqlite_rows(sim_dir / "simulation_channels.db", "SELECT id FROM channel_events WHERE simulation_id=?", (sim_id,)))
    assert ev_count_2 == ev_count_1, f"Re-running channels duplicated rows: {ev_count_1} -> {ev_count_2}"

    r1_sv = client.post(f"/api/swarm/{sim_id}/survey/run", json={"sample_size": 25, "use_llm": False, "sync": True})
    assert r1_sv.status_code == 200
    sv_count_1 = len(query_sqlite_rows(sim_dir / "simulation_channels.db", "SELECT id FROM survey_responses WHERE simulation_id=?", (sim_id,)))

    r2_sv = client.post(f"/api/swarm/{sim_id}/survey/run", json={"sample_size": 25, "use_llm": False, "sync": True})
    assert r2_sv.status_code == 200
    sv_count_2 = len(query_sqlite_rows(sim_dir / "simulation_channels.db", "SELECT id FROM survey_responses WHERE simulation_id=?", (sim_id,)))
    assert sv_count_1 == 25 and sv_count_2 == 25, f"Re-running survey duplicated rows: {sv_count_1} -> {sv_count_2}"


def test_t1_fa3_analytics_bundle_invalidates_stale_cache_on_rebuild(client, tmp_path):
    """Updating DB data invalidates stale `analytics_bundle.json` on `GET /api/analytics/<sim_id>/bundle`."""
    sim_id = "sim_cache_invalidation"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    client.post(f"/api/channels/{sim_id}/run", json={"enabled_channels": ["whatsapp_1on1"], "rounds": 1})
    client.post(f"/api/swarm/{sim_id}/survey/run", json={"sample_size": 20, "use_llm": False, "sync": True})
    r_ana1 = client.post(f"/api/analytics/{sim_id}/run")
    assert r_ana1.status_code == 200
    hash1 = r_ana1.get_json()["data"]["sha256_hash"]

    # Mutate survey sample_size -> 45 in DB (making bundle stale)
    time.sleep(0.02)
    client.post(f"/api/swarm/{sim_id}/survey/run", json={"sample_size": 45, "use_llm": False, "sync": True})
    r_get = client.get(f"/api/analytics/{sim_id}/bundle")
    assert r_get.status_code == 200
    bundle2 = r_get.get_json()["data"]
    assert bundle2["data_audit"]["surveys_analyzed"] == 45, (
        f"GET /bundle served stale cache (surveys_analyzed={bundle2['data_audit']['surveys_analyzed']} instead of 45)"
    )
    assert bundle2["sha256_hash"] != hash1


def test_t1_fa3_by_simulation_returns_latest_report(client, run_pipeline):
    """Generating report_1 then report_2 for the same simulation causes `by-simulation` to return report_2."""
    fx = build_miscelanea_esperanza_fixture()
    res1 = run_pipeline(fx, sample_size=30, channel_ids=["whatsapp_1on1"], force_regenerate=True)
    time.sleep(0.05)

    resp_gen2 = client.post(
        "/api/report/generate",
        json={"simulation_id": res1.simulation_id, "force_regenerate": True},
    )
    assert resp_gen2.status_code == 200
    rep2_data = resp_gen2.get_json()["data"]
    rep2_id = rep2_data["report_id"]
    assert rep2_id != res1.report_id

    # Poll using BOTH task_id AND simulation_id (must prioritize task_id!)
    deadline = time.time() + 20.0
    while time.time() < deadline:
        st_resp = client.post(
            "/api/report/generate/status",
            json={"task_id": rep2_data["task_id"], "simulation_id": res1.simulation_id},
        )
        st_data = (st_resp.get_json() or {}).get("data") or {}
        if st_data.get("task_id") == rep2_data["task_id"] and st_data.get("status") == "completed":
            break
        time.sleep(0.05)

    r_latest = client.get(f"/api/report/by-simulation/{res1.simulation_id}")
    assert r_latest.status_code == 200
    latest_id = r_latest.get_json()["data"]["report_id"]
    assert latest_id == rep2_id, f"by-simulation returned {latest_id} instead of latest {rep2_id}"


# ===========================================================================
# FA4: Gabor-Granger Table Mathematical Consistency (R4)
# ===========================================================================


def test_t1_fa4_table_values_nonzero_and_match_bundle_points(run_pipeline):
    """Ch.6 Gabor-Granger table renders non-zero % and COP values matching `gabor_granger.points`."""
    fx = build_clinica_dental_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=["whatsapp_1on1", "street_survey"])

    gg = res.analytics_bundle["pricing_econometrics"]["gabor_granger"]
    points = gg["points"]
    rows = parse_gabor_granger_table(res.chapters[6]["content_markdown"])

    assert len(rows) == len(points), f"Row count mismatch: table={len(rows)} vs points={len(points)}"
    assert any(acc > 0.0 and rev > 0 for _, acc, rev in rows), (
        f"Gabor-Granger table rendered 0.0% / COP 0 across all rows: {rows}"
    )
    for (t_price, t_acc, t_rev), pt in zip(rows, points):
        assert t_price == int(round(pt["price"]))
        expected_acc = round(float(pt["demand_monotonic"]) * 100.0, 1)
        assert abs(t_acc - expected_acc) <= 0.2, f"Acceptance mismatch at {t_price}: {t_acc} vs {expected_acc}"
        expected_rev = int(round(float(pt["expected_revenue"]) * 100.0))
        assert abs(t_rev - expected_rev) <= 100, f"Revenue/100 mismatch at {t_price}: {t_rev} vs {expected_rev}"


def test_t1_fa4_optimal_price_maximizes_expected_revenue_in_table(run_pipeline):
    """The table row matching `optimal_price` achieves the maximum expected revenue among all rows."""
    fx = build_agrocafe_tolima_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=["whatsapp_1on1"])

    gg = res.analytics_bundle["pricing_econometrics"]["gabor_granger"]
    opt_price = int(round(gg["optimal_price"]))
    rows = parse_gabor_granger_table(res.chapters[6]["content_markdown"])
    assert rows, "Ch.6 Gabor-Granger table is empty"

    max_rev = max(rev for _, _, rev in rows)
    assert max_rev > 0, f"Gabor-Granger table expected revenues are all zero: {rows}"
    matching = [rev for p, _, rev in rows if p == opt_price]
    assert matching, f"Optimal price {opt_price} not present in table rows: {rows}"
    assert matching[0] >= max_rev - 5, f"Optimal price {opt_price} rev={matching[0]} < max_rev={max_rev}"


def test_t1_fa4_demand_curve_is_monotonically_non_increasing(run_pipeline):
    """Acceptance % in both bundle and Ch.6 table is monotonically non-increasing across ascending prices."""
    fx = build_rutafacil_saas_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=["whatsapp_1on1"])

    rows = parse_gabor_granger_table(res.chapters[6]["content_markdown"])
    assert len(rows) >= 3
    assert any(acc > 0.0 for _, acc, _ in rows), f"Acceptance curve collapsed to 0.0% across all rows: {rows}"
    for i in range(len(rows) - 1):
        assert rows[i][0] < rows[i + 1][0], "Prices must be ascending"
        assert rows[i][1] >= rows[i + 1][1] - 0.1, (
            f"Non-monotonic demand in Ch.6 table: {rows[i]} -> {rows[i + 1]}"
        )


def test_t1_fa4_expected_revenue_equals_price_times_acceptance(run_pipeline):
    """For every row `(P, acc_pct, rev_cop)` in Ch.6 table, `rev_cop` ≈ `P * acc_pct / 100` * 100 = `P * acc_pct`."""
    fx = build_miscelanea_esperanza_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=["street_survey"])

    rows = parse_gabor_granger_table(res.chapters[6]["content_markdown"])
    assert rows
    assert any(rev > 0 for _, _, rev in rows), f"All table revenues are zero: {rows}"
    for price, acc_pct, rev_cop in rows:
        expected = price * acc_pct  # (price * (acc_pct / 100)) * 100 prospects
        tol = max(150.0, expected * 0.015)
        assert abs(rev_cop - expected) <= tol, (
            f"Row math inconsistent: P={price}, acc={acc_pct}%, rev={rev_cop}, expected≈{expected:.1f}"
        )


def test_t1_fa4_optimal_price_matches_kpi_tables_across_ch1_ch6_ch11(run_pipeline):
    """Declared optimal price matches across Ch.1, Ch.6, Ch.11 and passes `verify_numeric_consistency`."""
    fx = build_clinica_dental_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=["whatsapp_1on1"])

    opt_price = int(round(res.analytics_bundle["pricing_econometrics"]["gabor_granger"]["optimal_price"]))
    formatted = f"{opt_price:,}"
    for ch_num in (1, 6, 11):
        md = res.chapters[ch_num]["content_markdown"]
        assert formatted in md or str(opt_price) in md, (
            f"Ch.{ch_num} missing optimal price {formatted}"
        )
        check = verify_numeric_consistency(md, res.chapters[ch_num]["metrics_payload"])
        assert check["consistent"] is True, f"Ch.{ch_num} numeric mismatch: {check['mismatches']}"


# ===========================================================================
# FA5: Channel Friction Classification Nuance (R4)
# ===========================================================================


def test_t1_fa5_promoters_and_non_conflictive_neutrals_emit_no_friction():
    """Promoter and supportive/non-conflictive neutral events emit `is_friction=False` and `objection_tag=None`."""
    ev_prom = build_event(
        {"user_id": 1, "name": "Promotor", "attitude_segment": "promotor"},
        "whatsapp_1on1", 1, 10, "WHATSAPP_MESSAGE", "Excelente servicio, muy claro y práctico.",
    )
    ev_neut = build_event(
        {"user_id": 2, "name": "Neutral", "attitude_segment": "neutral"},
        "instagram", 1, 12, "COMMENT", "Interesante propuesta, lo tendría en cuenta para probar.",
    )
    assert getattr(ev_prom, "is_friction", None) is False, "ChannelEvent must expose is_friction=False for promoters"
    assert ev_prom.objection_tag is None
    assert getattr(ev_neut, "is_friction", None) is False, (
        "Non-conflictive neutral interaction must have is_friction=False"
    )
    assert ev_neut.objection_tag is None


def test_t1_fa5_mixed_cohort_produces_below_100pct_friction(tmp_path):
    """A mixed actor cohort (promoters + neutrals + skeptics + critics) yields <100% channel friction."""
    sim_id = "sim_mixed_friction_t1"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    mixed_actors = []
    attitudes = ["promotor"] * 8 + ["neutral"] * 6 + ["esceptico"] * 4 + ["critico_hate"] * 2
    for i, att in enumerate(attitudes):
        mixed_actors.append({
            "user_id": i + 1,
            "username": f"actor_{i + 1}",
            "name": f"Actor {i + 1}",
            "city_name": "Bogotá D.C.",
            "divipola_code": "11001",
            "stratum_code": "E3",
            "region_macro": "Andina Centro",
            "attitude_segment": att,
            "dynamic_study_role": "Comprador",
        })
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(mixed_actors), encoding="utf-8")

    ChannelSimulationEngine(sim_id, sim_dir, country_code="co").run_rounds(
        enabled_channels=list(CANONICAL_CHANNEL_IDS),
        rounds=2,
        study_context={"topic_short": "Panadería Artesanal El Trébol"},
    )
    SurveyEngine("co").run_survey(simulation_id=sim_id, sim_dir=sim_dir, sample_size=30, use_llm=False)
    bundle = AnalyticsBundleBuilder().build(simulation_id=sim_id, sim_dir=sim_dir, country_code="co", write_file=True)

    loops = bundle["funnel_and_cdj"]["cdj_channel_loops"]
    assert loops
    rates = [float(c["friction_rate"]) for c in loops]
    assert sum(rates) / len(rates) < 0.85, f"Mixed cohort friction too high (uniform bias): {rates}"
    assert sum(1 for r in rates if r < 1.0) >= len(rates) - 1, (
        f"Almost all channels still reporting 100% friction on mixed cohort: {loops}"
    )


def test_t1_fa5_friction_rate_equals_friction_events_over_touchpoints(run_pipeline):
    """In Ch.7 CDJ table and bundle, `friction_rate == round(friction_events / touchpoints, 4)`."""
    fx = build_agrocafe_tolima_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    loops = res.analytics_bundle["funnel_and_cdj"]["cdj_channel_loops"]
    assert loops
    for c in loops:
        tp = c["touchpoints"]
        fe = c["friction_events"]
        assert 0 <= fe <= tp
        assert abs(c["friction_rate"] - round(fe / max(1, tp), 4)) <= 1e-4

    table_rows = parse_ch7_friction_table(res.chapters[7]["content_markdown"])
    assert len(table_rows) == len(loops)
    for tr in table_rows:
        expected_pct = round((tr["friction_events"] / max(1, tr["touchpoints"])) * 100.0, 1)
        assert abs(tr["friction_pct"] - expected_pct) <= 0.2


def test_t1_fa5_channel_actor_selection_includes_diverse_attitudes():
    """`select_diverse_actors` includes promoters alongside skeptics/critics when present."""
    pool = [
        {"user_id": i, "region_macro": "Andina Centro", "attitude_segment": att}
        for i, att in enumerate(["promotor"] * 6 + ["neutral"] * 4 + ["esceptico"] * 4 + ["critico_hate"] * 4)
    ]
    selected = select_diverse_actors(pool, limit=8, round_num=1)
    att_set = {a["attitude_segment"] for a in selected}
    assert "promotor" in att_set, f"select_diverse_actors excluded promoters: {att_set}"
    assert ("esceptico" in att_set or "critico_hate" in att_set)


def test_t1_fa5_friction_events_have_valid_domain_objection_tags(run_pipeline):
    """Every friction event has a non-empty `objection_tag`, and non-friction events have None."""
    fx = build_miscelanea_esperanza_fixture()
    res = run_pipeline(fx, sample_size=30, channel_ids=["whatsapp_1on1", "tiktok", "street_survey"], rounds=2)

    rows = query_sqlite_rows(
        res.sim_dir / "simulation_channels.db",
        "SELECT attitude_segment, objection_tag, content_text, is_friction FROM channel_events",
    )
    assert rows
    for row in rows:
        if row["is_friction"]:
            assert row["objection_tag"], f"Friction event missing objection_tag: {row}"
        else:
            assert row["objection_tag"] is None, f"Non-friction event should have objection_tag=None: {row}"


# ===========================================================================
# FA6: Chapter 8 Verbatim Quote Zero Triplication & Editorial Integrity (R4)
# ===========================================================================


def test_t1_fa6_ch8_no_verbatim_quote_repeated_three_times(run_pipeline, tmp_path):
    """Ch.8 Evidencia Verbatim Trazable has zero duplicated quote texts or citation tags."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, sample_size=50, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    quotes = extract_ch8_quotes(res.chapters[8]["content_markdown"])
    assert len(quotes) >= 2, "Ch.8 must include traceable verbatim quotes"

    quote_texts = [q for _, q in quotes]
    citation_tags = [tag for tag, _ in quotes]
    text_counts = Counter(quote_texts)
    tag_counts = Counter(citation_tags)

    dups_text = {k: v for k, v in text_counts.items() if v > 1}
    dups_tags = {k: v for k, v in tag_counts.items() if v > 1}
    assert not dups_text, f"Ch.8 duplicated verbatim quotes: {dups_text}"
    assert not dups_tags, f"Ch.8 duplicated citation tags: {dups_tags}"


def test_t1_fa6_ch8_quotes_drawn_from_multiple_distinct_codes_and_actors(run_pipeline):
    """Ch.8 draws diverse quotes across multiple respondents/channels, not cloning 2 quotes across codes."""
    fx = build_clinica_dental_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    quotes = extract_ch8_quotes(res.chapters[8]["content_markdown"])
    assert len(quotes) >= 4
    unique_texts = {q for _, q in quotes}
    assert len(unique_texts) == len(quotes), "Ch.8 quotes must all be unique"


def test_t1_fa6_ch8_filters_prompt_boilerplate_from_quotes(tmp_path):
    """Even if a codebook sample quote contains `BLOQUE 1` or `Actua como`, Ch.8 excludes it cleanly."""
    sim_id = "sim_poisoned_quote"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    SurveyEngine("co").run_survey(simulation_id=sim_id, sim_dir=sim_dir, sample_size=30, use_llm=False)
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1)
    bundle = AnalyticsBundleBuilder().build(simulation_id=sim_id, sim_dir=sim_dir, country_code="co", write_file=True)

    # Inject a boilerplate quote at top of codebook
    cb = bundle["qualitative_coding"]["codebook"]
    cb[0]["sample_quotes"].insert(0, {
        "citation_tag": "[99 | Bogotá | E3 | 30 | Test | whatsapp_1on1 | neutral]",
        "quote": "BLOQUE 1 - ROL Y MISION Actua como un analista senior especializado en fintech",
        "source_table": "channel_events",
    })

    rep = ReportAgentV2(use_llm=False).generate_report(
        report_id="report_poisoned_quote",
        simulation_id=sim_id,
        simulation_requirement="Panadería Artesanal Bogotá",
        bundle=bundle,
    )
    ch8_md = rep["chapters"][7]["content_markdown"]
    assert "BLOQUE 1" not in ch8_md
    assert "Actua como" not in ch8_md


def test_t1_fa6_no_residual_nexo_jargon_in_ch9_ch10_ch12(run_pipeline):
    """Ch.9, Ch.10, and Ch.12 for a non-legal coffee business have zero NEXO/Decreto 196/casos/mes leakage."""
    fx = build_agrocafe_tolima_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=["whatsapp_1on1", "focus_group"])

    ch9 = res.chapters[9]["content_markdown"]
    ch10 = res.chapters[10]["content_markdown"]
    ch12 = res.chapters[12]["content_markdown"]

    assert "Casos A 24m" not in ch9 and "casos/mes" not in ch9.lower(), (
        f"Ch.9 leaked legal 'Casos A 24m / casos/mes': {ch9[:200]}"
    )
    assert "Decreto 196/1971" not in ch10, f"Ch.10 leaked 'Decreto 196/1971' for coffee business"
    assert "NEXO" not in ch12.upper()


def test_t1_fa6_dofa_matrix_in_charts_spec_is_dynamic_and_complete(run_pipeline):
    """`charts_spec.dofa_matrix` contains numeric scores in 0..100 and domain items aligned with Ch.11."""
    fx = build_rutafacil_saas_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=["whatsapp_1on1"])

    dofa = (res.analytics_bundle.get("charts_spec") or {}).get("dofa_matrix")
    assert isinstance(dofa, dict), "Missing charts_spec.dofa_matrix"
    scores = dofa.get("scores") or {}
    for key in ("fortalezas", "oportunidades", "debilidades", "amenazas"):
        assert key in scores, f"dofa_matrix.scores missing {key}"
        assert 0 <= int(scores[key]) <= 100
    items = dofa.get("items") or {}
    assert any(items.get(k) for k in ("fortalezas", "oportunidades", "debilidades", "amenazas"))
