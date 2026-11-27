"""Tier 2: Boundary & Corner Case Tests (30 tests — 5 per Feature Area FA1–FA6).

Exercises extreme COP ranges, malformed/boilerplate prompts, special characters,
empty/degenerate distributions, isotonic PAV smoothing, 0% vs 100% friction,
and duplicate/empty Ch.8 corpora.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from io import BytesIO
from pathlib import Path

from app.channels import CANONICAL_CHANNEL_IDS
from app.channels.adapters._helpers import build_event
from app.channels.engine import ChannelSimulationEngine
from app.channels.persistence import ChannelSQLiteStore
from app.services.analytics import AnalyticsBundleBuilder
from app.services.analytics.data_loader import DataLoader
from app.services.analytics.funnel_and_cdj import FunnelAndCDJEngine
from app.services.analytics.pricing_econometrics import PricingEconometricsEngine
from app.services.report_agent_v2 import ReportAgentV2
from app.services.survey_engine import SurveyEngine

from .conftest import extract_ch8_quotes, parse_gabor_granger_table
from .fixtures_colombia import (
    build_5block_prompt,
    build_edge_high_ticket_b2b_fixture,
    build_edge_micro_ticket_fixture,
    build_edge_minimal_noisy_fixture,
    build_edge_special_chars_fixture,
    build_pdf_bytes,
)


def _upload_and_get_project(client, fx, explicit_name=None):
    form = {
        "files": (BytesIO(fx.pdf_bytes), fx.pdf_filename),
        "simulation_requirement": fx.simulation_requirement,
        "country_code": fx.country_code,
        "target_cities": json.dumps(fx.target_cities),
        "target_strata": json.dumps(fx.target_strata),
        "use_official_sources": "false",
        "use_live_web": "false",
    }
    if explicit_name is not None:
        form["project_name"] = explicit_name
    resp = client.post("/api/graph/ontology/generate", data=form, content_type="multipart/form-data")
    assert resp.status_code == 200, f"Upload failed: {resp.get_json(silent=True)}"
    pid = resp.get_json()["data"]["project_id"]
    p_resp = client.get(f"/api/graph/project/{pid}")
    assert p_resp.status_code == 200
    return pid, p_resp.get_json()["data"]


def _make_survey_record(idx: int, gg_grid: dict, attitude: str = "neutral", price_base: float = 50000.0) -> dict:
    return {
        "respondent_id": f"resp_{idx:04d}",
        "actor_agent_id": idx,
        "channel_origin": "structured_survey",
        "status": "completed",
        "city_divipola": "11001",
        "city_name": "Bogotá D.C.",
        "region_macro": "Andina Centro",
        "stratum_code": "E3",
        "wealth_tier_norm": 3,
        "age": 30 + (idx % 20),
        "gender": "F" if idx % 2 == 0 else "M",
        "dynamic_study_role": "Comprador",
        "attitude_segment": attitude,
        "pain_score": 6,
        "trust_score": 7 if attitude == "promotor" else 5,
        "nps_score": 9 if attitude == "promotor" else 5,
        "csat_score": 4,
        "ces_score": 3,
        "vw_too_cheap": price_base * 0.4,
        "vw_cheap": price_base * 0.7,
        "vw_expensive": price_base * 1.3,
        "vw_too_expensive": price_base * 1.8,
        "nms_intent_cheap": 4,
        "nms_intent_expensive": 2,
        "gg_grid": gg_grid,
        "preferred_channel": "whatsapp_1on1",
        "main_objection": "Ninguna" if attitude == "promotor" else "Precio",
        "verbatim_response": f"Opinión de prueba #{idx} sobre precio y confianza del servicio.",
        "respondent_weight": 1.0,
        "created_at": "2026-11-26T00:00:00Z",
    }


# ===========================================================================
# FA1 Boundaries (5 tests)
# ===========================================================================


def test_t2_fa1_micro_price_floor_cop_1500(run_pipeline):
    """Micro-business COP 1,500–12,000 scales StudyContext price ladder and OPEX without clamping to 50k/4.2M."""
    fx = build_edge_micro_ticket_fixture()
    res = run_pipeline(fx, sample_size=30, channel_ids=["street_survey"])

    sc = res.study_context
    assert sc is not None, "Missing study_context.json"
    assert min(sc["price_ladder_cop"]) <= 3000
    assert max(sc["price_ladder_cop"]) <= 25000
    assert sc["monthly_opex_cop"] < 2_500_000, f"Micro-business OPEX inflated: {sc['monthly_opex_cop']}"


def test_t2_fa1_high_ticket_b2b_enterprise_cop_5000000(run_pipeline):
    """High-ticket B2B industrial service COP 2M–10M scales ladder and OPEX proportionally."""
    fx = build_edge_high_ticket_b2b_fixture()
    res = run_pipeline(fx, sample_size=30, channel_ids=["colombian_web"])

    sc = res.study_context
    assert sc is not None, "Missing study_context.json"
    assert min(sc["price_ladder_cop"]) >= 500_000, f"High-ticket B2B collapsed to low price: {sc['price_ladder_cop']}"
    assert max(sc["price_ladder_cop"]) >= 5_000_000
    assert sc["monthly_opex_cop"] >= 5_000_000


def test_t2_fa1_minimal_short_prompt_and_1_paragraph_pdf(client, tmp_path):
    """Minimal 2-sentence prompt and 1-paragraph PDF still builds valid non-empty StudyContext."""
    fx = build_edge_minimal_noisy_fixture()
    pid, _ = _upload_and_get_project(client, fx)
    sc_path = Path(tmp_path / "uploads" / "projects" / pid / "study_context.json")
    assert sc_path.exists(), "study_context.json not generated for minimal PDF/prompt"
    sc = json.loads(sc_path.read_text(encoding="utf-8"))
    assert len(sc["price_ladder_cop"]) == 5
    assert sc["value_proposition"] and sc["unit_label"]


def test_t2_fa1_missing_files_or_empty_requirement_returns_400(client):
    """POST /api/graph/ontology/generate returns HTTP 400 when `files` or `simulation_requirement` is missing."""
    fx = build_edge_minimal_noisy_fixture()
    r_no_req = client.post(
        "/api/graph/ontology/generate",
        data={"files": (BytesIO(fx.pdf_bytes), fx.pdf_filename), "simulation_requirement": ""},
        content_type="multipart/form-data",
    )
    assert r_no_req.status_code == 400
    assert r_no_req.get_json()["success"] is False

    r_no_file = client.post(
        "/api/graph/ontology/generate",
        data={"simulation_requirement": "Evaluar tienda en Bogotá"},
        content_type="multipart/form-data",
    )
    assert r_no_file.status_code == 400
    assert r_no_file.get_json()["success"] is False


def test_t2_fa1_unrecognized_or_noisy_text_falls_back_cleanly(run_pipeline):
    """Noisy PDF with no explicit prices produces sane defaults with zero NEXO/Decreto 196 leakage."""
    fx = build_edge_minimal_noisy_fixture()
    res = run_pipeline(fx, sample_size=30, channel_ids=["whatsapp_1on1"])

    corpus = json.dumps(res.study_context or {}, ensure_ascii=False) + "\n" + res.full_report_md
    for leak in ("Conductor_Movilidad", "Decreto 196/1971", "Seguros y Reclamaciones", "Servicio B"):
        assert leak not in corpus, f"Fallback leaked {leak!r} on noisy minimal input"


# ===========================================================================
# FA2 Boundaries (5 tests)
# ===========================================================================


def test_t2_fa2_prompt_only_boilerplate_headers_no_brand_in_bloque1(client, tmp_path):
    """Prompt with generic BLOQUE 1 and brand only in BLOQUE 2 / PDF extracts the true brand name."""
    brand = "Verdulería La Cosecha"
    pdf_bytes = build_pdf_bytes(
        f"{brand} — Frutas y Verduras a Domicilio",
        [f"{brand} distribuye mercados frescos en Medellín entre COP 25.000 y COP 80.000."],
    )
    prompt = (
        "BLOQUE 1 - ROL Y MISION\r\n"
        "Actua como un analista senior de investigacion de mercados con Colombia como mercado inicial.\r\n"
        "BLOQUE 2 - CONTEXTO DE LA IDEA (Verdulería La Cosecha)\r\n"
        "Servicio de entrega semanal de frutas y verduras en Medellín."
    )
    resp = client.post(
        "/api/graph/ontology/generate",
        data={
            "files": (BytesIO(pdf_bytes), "La_Cosecha.pdf"),
            "simulation_requirement": prompt,
            "use_official_sources": "false",
            "use_live_web": "false",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    name = resp.get_json()["data"]["project_name"]
    assert "cosecha" in name.lower(), f"Failed to extract brand from BLOQUE 2/PDF: {name!r}"
    assert "bloque" not in name.lower() and "actua" not in name.lower()


def test_t2_fa2_accents_ampersand_legal_suffix_slugification(run_pipeline):
    """Accents, `&`, and `S.A.S.` produce readable `project_name` and ASCII-safe download slug."""
    fx = build_edge_special_chars_fixture(
        brand_name="Panadería & Café El Trébol S.A.S.",
        expected_slug="panaderia_cafe_el_trebol_sas",
    )
    res = run_pipeline(fx, sample_size=30, channel_ids=["whatsapp_1on1"])

    assert "Trébol" in res.project_name or "Trebol" in res.project_name
    assert res.download_filename.endswith(f"{res.report_id}.md")
    assert re.match(r"^[a-z0-9_]+_report_[a-z0-9]+\.md$", res.download_filename), (
        f"Download filename is not ASCII-safe slug: {res.download_filename!r}"
    )


def test_t2_fa2_long_project_name_over_80_chars_no_midword_truncation(run_pipeline):
    """Long project title (>80 chars) never breaks mid-word like 'confianza par)' in Ch.6/Ch.11."""
    long_name = "Plataforma Integral Comunitaria de Logística Fría y Distribución Rural Sostenible Colombia"
    fx = build_edge_special_chars_fixture(brand_name=long_name, expected_slug="plataforma_integral")
    res = run_pipeline(fx, explicit_project_name=long_name, sample_size=30, channel_ids=["whatsapp_1on1"])

    ch6 = res.chapters[6]["content_markdown"]
    assert "Oferta Principal / Entrada" in ch6
    m = re.search(r"Oferta Principal / Entrada \(([^)]+)\)", ch6)
    assert m, "Missing Oferta Principal line in Ch.6"
    inside = m.group(1)
    assert len(inside) > 0
    # Must not cut mid-word (e.g. ending with partial token when source has full words)
    if len(inside) < len(long_name):
        prefix_words = inside.rstrip(".…").split()
        full_words = long_name.split()
        for pw, fw in zip(prefix_words, full_words):
            assert pw == fw, f"Mid-word truncation detected: {inside!r} vs {long_name!r}"


def test_t2_fa2_placeholder_names_rejected_and_replaced(client):
    """Passing placeholder `project_name` values triggers extraction of the real project name."""
    fx = build_edge_micro_ticket_fixture()
    for placeholder in ("Unnamed Project", "Proyecto sin título", "Prospéctica Inc.", "   "):
        _, proj = _upload_and_get_project(client, fx, explicit_name=placeholder)
        assert proj["name"] != placeholder.strip()
        assert "Unnamed Project" not in proj["name"]
        assert "Prospéctica Inc." not in proj["name"]
        assert "empanadas" in proj["name"].lower() or "luz" in proj["name"].lower(), (
            f"Placeholder {placeholder!r} yielded {proj['name']!r} instead of Empanadas Doña Luz"
        )


def test_t2_fa2_brand_name_containing_special_regex_chars(run_pipeline):
    """Brand name with regex metacharacters (`A+B [Salud] (CO)`) does not crash sanitizers or report generation."""
    fx = build_edge_special_chars_fixture(brand_name="A+B [Salud] (CO)", expected_slug="a_b_salud_co")
    res = run_pipeline(fx, explicit_project_name="A+B [Salud] (CO)", sample_size=30, channel_ids=["whatsapp_1on1"])

    assert "A+B [Salud] (CO)" in res.full_report_md.splitlines()[0]
    assert len(res.chapters) == 12


# ===========================================================================
# FA3 Boundaries (5 tests)
# ===========================================================================


def test_t2_fa3_shared_sqlite_db_multiple_sim_ids_strict_isolation(tmp_path):
    """Two simulations sharing one `ChannelSQLiteStore` strictly isolate queries & summaries by `simulation_id`."""
    store = ChannelSQLiteStore(tmp_path / "shared_db")
    store.record_channel_event("sim_iso_1", build_event({"user_id": 1, "name": "A1", "attitude_segment": "esceptico"}, "tiktok", 1, 10, "VIDEO", "Evento Sim 1"))
    store.record_channel_event("sim_iso_2", build_event({"user_id": 2, "name": "A2", "attitude_segment": "promotor"}, "tiktok", 1, 11, "VIDEO", "Evento Sim 2"))
    store.record_channel_event("sim_iso_2", build_event({"user_id": 3, "name": "A3", "attitude_segment": "promotor"}, "instagram", 1, 12, "POST", "Evento Sim 2 B"))

    store.record_survey_responses_bulk("sim_iso_1", [_make_survey_record(1, {"10000": 1.0})])
    store.record_survey_responses_bulk("sim_iso_2", [_make_survey_record(1, {"20000": 1.0}), _make_survey_record(2, {"20000": 0.0})])

    ev1 = store.query_events(simulation_id="sim_iso_1")
    ev2 = store.query_events(simulation_id="sim_iso_2")
    assert len(ev1) == 1 and ev1[0]["content_text"] == "Evento Sim 1"
    assert len(ev2) == 2 and all("Sim 2" in r["content_text"] for r in ev2)

    sv1 = store.query_surveys(simulation_id="sim_iso_1")
    sv2 = store.query_surveys(simulation_id="sim_iso_2")
    assert len(sv1) == 1 and len(sv2) == 2

    sum1 = store.summarize_channels(simulation_id="sim_iso_1")
    assert set(sum1.keys()) == {"tiktok", "structured_survey"}
    assert sum1["tiktok"]["actions_count"] == 1
    assert sum1["structured_survey"]["actions_count"] == 1


def test_t2_fa3_unknown_project_sim_report_ids_return_404(client):
    """Unknown IDs across graph, channels, analytics, and report endpoints consistently return HTTP 404."""
    assert client.get("/api/graph/project/proj_missing_999").status_code == 404
    assert client.get("/api/channels/sim_missing_999/events").status_code == 404
    assert client.get("/api/analytics/sim_missing_999/bundle").status_code == 404
    assert client.get("/api/report/report_missing_999/download").status_code == 404
    assert client.get("/api/report/by-simulation/sim_missing_999").status_code == 404


def test_t2_fa3_concurrent_or_back_to_back_project_creations(client, tmp_path):
    """Creating 3 distinct projects back-to-back yields 3 disjoint project IDs and StudyContexts."""
    fixtures = [
        build_edge_micro_ticket_fixture(),
        build_edge_high_ticket_b2b_fixture(),
        build_edge_minimal_noisy_fixture(),
    ]
    seen_ids = set()
    seen_prices = []
    for fx in fixtures:
        pid, proj = _upload_and_get_project(client, fx)
        assert pid not in seen_ids
        seen_ids.add(pid)
        sc_path = Path(tmp_path / "uploads" / "projects" / pid / "study_context.json")
        assert sc_path.exists()
        sc = json.loads(sc_path.read_text(encoding="utf-8"))
        seen_prices.append(tuple(sc["price_ladder_cop"]))
    assert len(set(seen_prices)) == 3, f"Back-to-back uploads shared price ladders: {seen_prices}"


def test_t2_fa3_empty_simulation_before_channels_or_survey(client, tmp_path):
    """Building analytics on an empty simulation dir degrades cleanly without borrowing another sim's rows."""
    other_dir = tmp_path / "uploads" / "simulations" / "sim_other_populated"
    other_dir.mkdir(parents=True, exist_ok=True)
    SurveyEngine("co").run_survey("sim_other_populated", other_dir, sample_size=20, use_llm=False)

    empty_id = "sim_empty_isolated"
    empty_dir = tmp_path / "uploads" / "simulations" / empty_id
    empty_dir.mkdir(parents=True, exist_ok=True)
    r_ana = client.post(f"/api/analytics/{empty_id}/run")
    assert r_ana.status_code == 200
    bundle = client.get(f"/api/analytics/{empty_id}/bundle").get_json()["data"]
    assert bundle["data_audit"]["surveys_analyzed"] == 0
    assert bundle["data_audit"]["events_analyzed"] == 0


def test_t2_fa3_reused_project_name_different_project_ids(run_pipeline):
    """Two projects explicitly given the same name but different PDFs remain isolated by `project_id`."""
    fx_low = build_edge_micro_ticket_fixture()
    fx_high = build_edge_high_ticket_b2b_fixture()

    res_1 = run_pipeline(fx_low, explicit_project_name="Piloto Alpha", sample_size=25, channel_ids=["whatsapp_1on1"])
    res_2 = run_pipeline(fx_high, explicit_project_name="Piloto Alpha", sample_size=25, channel_ids=["whatsapp_1on1"])

    assert res_1.project_id != res_2.project_id
    opt_1 = res_1.analytics_bundle["pricing_econometrics"]["gabor_granger"]["optimal_price"]
    opt_2 = res_2.analytics_bundle["pricing_econometrics"]["gabor_granger"]["optimal_price"]
    assert opt_1 < 50_000 and opt_2 >= 1_000_000, f"Same-name projects leaked pricing: {opt_1} vs {opt_2}"


# ===========================================================================
# FA4 Boundaries (5 tests)
# ===========================================================================


def test_t2_fa4_non_monotonic_raw_demand_triggers_pav_and_matches_table(tmp_path):
    """Non-monotonic raw demand triggers `isotonic_applied=True` and Ch.6 table uses smoothed `demand_monotonic`."""
    sim_id = "sim_pav_test"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    # Create intentional inversion: 50k has higher acceptance (0.8) than 30k (0.4)
    recs = []
    for i in range(10):
        grid = {
            "10000": 1.0 if i < 9 else 0.0,
            "30000": 1.0 if i < 4 else 0.0,
            "50000": 1.0 if i < 8 else 0.0,
            "70000": 1.0 if i < 2 else 0.0,
            "90000": 0.0,
        }
        recs.append(_make_survey_record(i + 1, grid, price_base=50000.0))

    store = ChannelSQLiteStore(sim_dir)
    for r in recs:
        r_db = dict(r)
        r_db["gg_grid_json"] = json.dumps(r_db.pop("gg_grid"))
        store.record_survey_responses_bulk(sim_id, [r_db])
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1)

    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
    gg = bundle["pricing_econometrics"]["gabor_granger"]
    assert gg["isotonic_applied"] is True

    rep = ReportAgentV2(use_llm=False).generate_report("rep_pav", sim_id, "Proyecto PAV", bundle=bundle)
    rows = parse_gabor_granger_table(rep["chapters"][5]["content_markdown"])
    assert len(rows) == 5
    assert any(acc > 0 and rev > 0 for _, acc, rev in rows)
    for i in range(len(rows) - 1):
        assert rows[i][1] >= rows[i + 1][1] - 0.1


def test_t2_fa4_all_zero_demand_corner_case(tmp_path):
    """100% rejection across all price tiers renders Ch.6 cleanly without ZeroDivisionError."""
    sim_id = "sim_zero_demand"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    store = ChannelSQLiteStore(sim_dir)
    zero_grid = {"10000": 0.0, "20000": 0.0, "30000": 0.0, "40000": 0.0, "50000": 0.0}
    rows_db = []
    for i in range(10):
        r = _make_survey_record(i + 1, zero_grid)
        r["gg_grid_json"] = json.dumps(r.pop("gg_grid"))
        rows_db.append(r)
    store.record_survey_responses_bulk(sim_id, rows_db)
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1)

    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
    rep = ReportAgentV2(use_llm=False).generate_report("rep_zero", sim_id, "Proyecto Cero", bundle=bundle)
    table = parse_gabor_granger_table(rep["chapters"][5]["content_markdown"])
    assert len(table) == 5
    assert all(acc == 0.0 and rev == 0 for _, acc, rev in table)


def test_t2_fa4_100pct_acceptance_at_all_tiers(tmp_path):
    """100% acceptance at all tiers picks highest tier as optimal_price and renders 100.0% in Ch.6."""
    sim_id = "sim_full_demand"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    store = ChannelSQLiteStore(sim_dir)
    full_grid = {"10000": 1.0, "20000": 1.0, "30000": 1.0, "40000": 1.0, "50000": 1.0}
    rows_db = []
    for i in range(10):
        r = _make_survey_record(i + 1, full_grid, attitude="promotor")
        r["gg_grid_json"] = json.dumps(r.pop("gg_grid"))
        rows_db.append(r)
    store.record_survey_responses_bulk(sim_id, rows_db)
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1)

    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
    gg = bundle["pricing_econometrics"]["gabor_granger"]
    assert int(gg["optimal_price"]) == 50000

    rep = ReportAgentV2(use_llm=False).generate_report("rep_full", sim_id, "Proyecto Full", bundle=bundle)
    table = parse_gabor_granger_table(rep["chapters"][5]["content_markdown"])
    assert len(table) == 5
    assert all(acc == 100.0 for _, acc, _ in table)
    assert table[-1] == (50000, 100.0, 5_000_000)


def test_t2_fa4_custom_3_tier_vs_7_tier_ladder(tmp_path):
    """Non-standard 3-tier and 7-tier ladders render exact matching row counts in Ch.6."""
    for n_tiers, ladder in ((3, [5000, 15000, 30000]), (7, [2000, 4000, 6000, 8000, 10000, 15000, 20000])):
        sim_id = f"sim_ladder_{n_tiers}"
        sim_dir = tmp_path / "uploads" / "simulations" / sim_id
        sim_dir.mkdir(parents=True, exist_ok=True)
        SurveyEngine("co").run_survey(sim_id, sim_dir, sample_size=20, price_ladder=ladder, use_llm=False)
        ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1)
        bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
        rep = ReportAgentV2(use_llm=False).generate_report(f"rep_ladder_{n_tiers}", sim_id, "Escalera Custom", bundle=bundle)
        rows = parse_gabor_granger_table(rep["chapters"][5]["content_markdown"])
        assert len(rows) == n_tiers
        assert [p for p, _, _ in rows] == ladder
        assert any(acc > 0 and rev > 0 for _, acc, rev in rows), f"All 0.0%/COP 0 for {n_tiers}-tier ladder: {rows}"


def test_t2_fa4_tiny_sample_size_n_5(tmp_path):
    """Tiny survey sample size (N=5) yields valid non-zero Gabor-Granger table without crash."""
    sim_id = "sim_tiny_n5"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    SurveyEngine("co").run_survey(sim_id, sim_dir, sample_size=5, price_ladder=[5000, 10000, 15000, 20000, 30000], use_llm=False)
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1)
    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
    rep = ReportAgentV2(use_llm=False).generate_report("rep_n5", sim_id, "Muestra N5", bundle=bundle)
    rows = parse_gabor_granger_table(rep["chapters"][5]["content_markdown"])
    assert len(rows) == 5
    assert any(acc > 0 and rev > 0 for _, acc, rev in rows)


# ===========================================================================
# FA5 Boundaries (5 tests)
# ===========================================================================


def test_t2_fa5_100pct_promoter_cohort_zero_friction(tmp_path):
    """100% promoter cohort produces 0.0% (or near-zero) channel friction, never 100.0%."""
    sim_id = "sim_all_promoters"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    actors = [
        {
            "user_id": i + 1, "username": f"prom_{i}", "name": f"Promotor {i}",
            "city_name": "Bogotá D.C.", "divipola_code": "11001", "stratum_code": "E4",
            "region_macro": "Andina Centro", "attitude_segment": "promotor",
        }
        for i in range(12)
    ]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(actors), encoding="utf-8")
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(list(CANONICAL_CHANNEL_IDS), rounds=1, study_context={"topic_short": "Servicio Local"})
    SurveyEngine("co").run_survey(sim_id, sim_dir, sample_size=20, use_llm=False)
    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
    loops = bundle["funnel_and_cdj"]["cdj_channel_loops"]
    assert loops
    assert all(c["friction_rate"] == 0.0 for c in loops), f"Promoters emitted friction: {loops}"


def test_t2_fa5_100pct_critic_cohort_high_friction(tmp_path):
    """100% critic cohort legitimately yields high friction (~100%) with `is_friction=True` and non-None tags."""
    sim_id = "sim_all_critics"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    actors = [
        {
            "user_id": i + 1, "username": f"crit_{i}", "name": f"Crítico {i}",
            "city_name": "Medellín", "divipola_code": "05001", "stratum_code": "E3",
            "region_macro": "Paisa / Eje Cafetero", "attitude_segment": "critico_hate",
        }
        for i in range(12)
    ]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(actors), encoding="utf-8")
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1", "tiktok", "street_survey"], rounds=1, study_context={"topic_short": "Servicio Local"})
    SurveyEngine("co").run_survey(sim_id, sim_dir, sample_size=20, use_llm=False)
    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
    loops = bundle["funnel_and_cdj"]["cdj_channel_loops"]
    assert all(c["friction_rate"] >= 0.80 for c in loops)


def test_t2_fa5_single_round_single_channel_minimum_events(tmp_path):
    """`rounds=1` on a single channel preserves the `is_friction == bool(objection_tag)` invariant."""
    sim_id = "sim_single_ch"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1, study_context={"topic_short": "Servicio Local"})
    events = ChannelSQLiteStore(sim_dir).query_events(simulation_id=sim_id)
    assert len(events) >= 1
    for ev in events:
        assert "is_friction" in ev
        assert bool(ev["is_friction"]) == bool(ev["objection_tag"])


def test_t2_fa5_channel_with_zero_events_no_division_by_zero(tmp_path):
    """Empty channel events list does not trigger ZeroDivisionError in FunnelAndCDJEngine."""
    sim_dir = tmp_path / "uploads" / "simulations" / "sim_no_ev"
    sim_dir.mkdir(parents=True, exist_ok=True)
    data = DataLoader().load("sim_no_ev", sim_dir)
    out = FunnelAndCDJEngine().analyze(data)
    assert out["status"] == "ok"
    assert out["cdj_channel_loops"] == []


def test_t2_fa5_neutral_mixed_sentiment_boundary():
    """Neutral actor with positive/non-conflictive text sets `is_friction=False`, while explicit hesitation sets friction."""
    ev_calm = build_event(
        {"user_id": 1, "name": "N1", "attitude_segment": "neutral"},
        "facebook_groups", 1, 14, "COMMENT", "Me parece interesante la propuesta, voy a revisarla con calma.",
    )
    ev_doubt = build_event(
        {"user_id": 2, "name": "N2", "attitude_segment": "neutral"},
        "facebook_groups", 1, 14, "COMMENT", "Tengo duda con el precio, me parece caro y no veo garantía clara.",
        sentiment_override=-0.35,
    )
    assert getattr(ev_calm, "is_friction", None) is False and ev_calm.objection_tag is None
    assert getattr(ev_doubt, "is_friction", None) is True and ev_doubt.objection_tag is not None


# ===========================================================================
# FA6 Boundaries (5 tests)
# ===========================================================================


def test_t2_fa6_identical_quote_across_all_top_4_codes(tmp_path):
    """When the exact same quote appears in all top 4 codebook categories, Ch.8 renders it ONLY ONCE."""
    sim_id = "sim_dup_4codes"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    SurveyEngine("co").run_survey(sim_id, sim_dir, sample_size=20, use_llm=False)
    ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1)
    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)

    shared_quote = {
        "citation_tag": "[7 | Bogotá D.C. | E3 | 34 | Comprador | whatsapp_1on1 | esceptico]",
        "quote": "Me preocupa pagar por adelantado sin ver el respaldo del negocio.",
        "source_table": "channel_events",
    }
    for code_entry in bundle["qualitative_coding"]["codebook"][:4]:
        code_entry["sample_quotes"] = [dict(shared_quote)] + code_entry.get("sample_quotes", [])

    rep = ReportAgentV2(use_llm=False).generate_report("rep_dup4", sim_id, "Tienda Barrio", bundle=bundle)
    ch8 = rep["chapters"][7]["content_markdown"]
    occurrences = ch8.count(shared_quote["quote"])
    assert occurrences == 1, f"Shared quote appeared {occurrences} times in Ch.8 (expected 1)"


def test_t2_fa6_all_quotes_contain_prompt_boilerplate(tmp_path):
    """If all codebook quotes contain `BLOQUE ` or `Actua como`, Ch.8 outputs clean fallback message."""
    sim_id = "sim_all_boiler"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    SurveyEngine("co").run_survey(sim_id, sim_dir, sample_size=15, use_llm=False)
    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)

    for code_entry in bundle["qualitative_coding"]["codebook"]:
        code_entry["sample_quotes"] = [{
            "citation_tag": "[1 | Bogotá | E3 | - | Rol | whatsapp_1on1 | neutral]",
            "quote": "BLOQUE 1 - ROL Y MISION Actua como un analista senior",
            "source_table": "channel_events",
        }]

    rep = ReportAgentV2(use_llm=False).generate_report("rep_all_boiler", sim_id, "Negocio Limpio", bundle=bundle)
    ch8 = rep["chapters"][7]["content_markdown"]
    assert "BLOQUE 1" not in ch8
    assert "Actua como" not in ch8
    assert "Sin citas textuales depuradas" in ch8


def test_t2_fa6_empty_corpus_zero_quotes(tmp_path):
    """Empty codebook renders Ch.8 gracefully with `0 textos` and fallback quote notice."""
    sim_id = "sim_empty_corpus"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
    bundle["qualitative_coding"]["codebook"] = []
    bundle["qualitative_coding"]["total_texts_indexed"] = 0

    rep = ReportAgentV2(use_llm=False).generate_report("rep_empty_cb", sim_id, "Negocio Vacío", bundle=bundle)
    ch8 = rep["chapters"][7]["content_markdown"]
    assert "0 textos" in ch8
    assert "Sin citas textuales depuradas" in ch8


def test_t2_fa6_very_long_quote_over_500_chars(tmp_path):
    """Very long verbatim quote (>500 chars) renders once cleanly without breaking blockquote markdown."""
    sim_id = "sim_long_quote"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    SurveyEngine("co").run_survey(sim_id, sim_dir, sample_size=15, use_llm=False)
    bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)

    long_txt = "Este es un comentario extenso de cliente real en Colombia sobre logística y confianza. " * 8
    assert len(long_txt) > 500
    bundle["qualitative_coding"]["codebook"][0]["sample_quotes"] = [{
        "citation_tag": "[11 | Cali | E3 | 40 | Cliente | focus_group | neutral]",
        "quote": long_txt.strip(),
        "source_table": "focus_group_turns",
    }]

    rep = ReportAgentV2(use_llm=False).generate_report("rep_long_q", sim_id, "Servicio Largo", bundle=bundle)
    ch8 = rep["chapters"][7]["content_markdown"]
    quotes = extract_ch8_quotes(ch8)
    assert len(quotes) >= 1
    assert Counter(q for _, q in quotes).most_common(1)[0][1] == 1


def test_t2_fa6_dofa_scores_clamped_0_to_100(tmp_path):
    """`charts_spec.dofa_matrix.scores` remains valid integers in [0, 100] under extreme NPS (-100 / +100)."""
    for label, nps_val, att in (("min", 0, "critico_hate"), ("max", 10, "promotor")):
        sim_id = f"sim_dofa_{label}"
        sim_dir = tmp_path / "uploads" / "simulations" / sim_id
        sim_dir.mkdir(parents=True, exist_ok=True)
        store = ChannelSQLiteStore(sim_dir)
        rows = []
        for i in range(12):
            r = _make_survey_record(i + 1, {"10000": 1.0 if nps_val == 10 else 0.0}, attitude=att)
            r["nps_score"] = nps_val
            r["gg_grid_json"] = json.dumps(r.pop("gg_grid"))
            rows.append(r)
        store.record_survey_responses_bulk(sim_id, rows)
        ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1"], rounds=1)
        bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
        dofa = (bundle.get("charts_spec") or {}).get("dofa_matrix")
        assert isinstance(dofa, dict), f"Missing dofa_matrix for {label} extreme"
        for k, v in (dofa.get("scores") or {}).items():
            assert 0 <= int(v) <= 100, f"DOFA score out of [0,100]: {k}={v}"
