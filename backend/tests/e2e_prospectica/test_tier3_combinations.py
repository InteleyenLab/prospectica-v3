"""Tier 3: Pairwise Cross-Feature Combination Tests (15 tests — all pairs of FA1–FA6).

Verifies interactions between:
  FA1 (Dynamic StudyContext), FA2 (Name/Brand/Filename), FA3 (Isolation),
  FA4 (Gabor-Granger Math), FA5 (Channel Friction Nuance), FA6 (Ch.8 Dedup & Editorial).
"""

from __future__ import annotations

import json
import re
from collections import Counter

from app.channels import CANONICAL_CHANNEL_IDS
from app.channels.engine import ChannelSimulationEngine
from app.services.analytics import AnalyticsBundleBuilder
from app.services.report_agent_v2 import ReportAgentV2, verify_numeric_consistency
from app.services.survey_engine import SurveyEngine

from .conftest import (
    extract_ch8_quotes,
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


def test_t3_01_fa1_x_fa2_5block_cofre_extracts_name_and_fintech_study_context(run_pipeline, tmp_path):
    """FA1 x FA2: 5-block COFRE PDF without explicit project_name extracts 'COFRE' AND builds fintech StudyContext."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, explicit_project_name=None, sample_size=40, channel_ids=["whatsapp_1on1", "instagram"])

    assert res.project_name.upper().startswith("COFRE")
    sc = res.study_context
    assert sc is not None
    assert "COFRE" in sc["project_name"].upper()
    sc_str = json.dumps(sc, ensure_ascii=False).lower()
    assert any(k in sc_str for k in ("comercio social", "pago", "escrow", "confianza", "cofre"))
    assert "nexo" not in sc_str and "decreto 196" not in sc_str


def test_t3_02_fa1_x_fa3_sequential_micro_retail_vs_b2b_saas_zero_bleed(run_pipeline):
    """FA1 x FA3: Micro-retail (COP 2k-20k) then B2B SaaS (COP 180k-650k) preserve distinct StudyContexts and OPEX."""
    res_a = run_pipeline(build_miscelanea_esperanza_fixture(), sample_size=35, channel_ids=["whatsapp_1on1"])
    res_b = run_pipeline(build_rutafacil_saas_fixture(), sample_size=35, channel_ids=["colombian_web"])

    sc_a, sc_b = res_a.study_context, res_b.study_context
    assert sc_a is not None and sc_b is not None
    assert max(sc_a["price_ladder_cop"]) < min(sc_b["price_ladder_cop"])
    assert sc_a["monthly_opex_cop"] < sc_b["monthly_opex_cop"]
    assert "miscelánea" not in res_b.full_report_md.lower()
    assert "rutafácil" not in res_a.full_report_md.lower()


def test_t3_03_fa1_x_fa4_custom_micro_prices_flow_into_gabor_granger_table(run_pipeline):
    """FA1 x FA4: Miscelánea micro-prices flow from StudyContext -> Survey -> Gabor-Granger -> non-zero Ch.6 table."""
    fx = build_miscelanea_esperanza_fixture()
    res = run_pipeline(fx, sample_size=50, channel_ids=["street_survey", "whatsapp_1on1"])

    sc = res.study_context
    assert sc is not None
    rows = parse_gabor_granger_table(res.chapters[6]["content_markdown"])
    assert len(rows) == len(sc["price_ladder_cop"])
    assert [p for p, _, _ in rows] == [int(x) for x in sc["price_ladder_cop"]]
    assert any(acc > 0.0 and rev > 0 for _, acc, rev in rows)


def test_t3_04_fa1_x_fa5_domain_risks_drive_friction_while_promoters_stay_non_friction(run_pipeline):
    """FA1 x FA5: Domain risks appear in friction tags/texts while promoters remain non-friction (<100% rate)."""
    fx = build_clinica_dental_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    loops = res.analytics_bundle["funnel_and_cdj"]["cdj_channel_loops"]
    assert any(c["friction_rate"] < 1.0 for c in loops), f"All channels stuck at 100% friction: {loops}"
    events = query_sqlite_rows(res.sim_dir / "simulation_channels.db", "SELECT content_text, is_friction, objection_tag FROM channel_events")
    non_fric = [e for e in events if not e["is_friction"]]
    assert non_fric and all(e["objection_tag"] is None for e in non_fric)


def test_t3_05_fa1_x_fa6_domain_codebook_and_clean_ch10_ch12(run_pipeline):
    """FA1 x FA6: Coffee domain drives Ch.8 codebook & Ch.10/Ch.12 without NEXO/Servicio B/casos/mes leakage."""
    fx = build_agrocafe_tolima_fixture()
    res = run_pipeline(fx, sample_size=45, channel_ids=["whatsapp_1on1", "instagram", "focus_group"])

    joined = res.chapters[8]["content_markdown"] + res.chapters[9]["content_markdown"] + res.chapters[10]["content_markdown"]
    assert "Servicio B" not in joined
    assert "casos/mes" not in joined.lower()
    assert "Decreto 196/1971" not in joined
    quotes = extract_ch8_quotes(res.chapters[8]["content_markdown"])
    assert len(quotes) == len({q for _, q in quotes})


def test_t3_06_fa2_x_fa3_sequential_projects_keep_distinct_filenames_and_manifests(client, run_pipeline, tmp_path):
    """FA2 x FA3: Project A (COFRE) then Project B (Miscelánea) maintain disjoint download filenames & manifests."""
    res_a = run_pipeline(load_cofre_fixture(tmp_path), sample_size=30, channel_ids=["whatsapp_1on1"])
    res_b = run_pipeline(build_miscelanea_esperanza_fixture(), sample_size=30, channel_ids=["whatsapp_1on1"])

    assert res_a.download_filename.startswith("cofre_")
    assert res_b.download_filename.startswith("miscelanea_la_esperanza_")
    assert "Prospéctica Inc." not in res_a.manifest.get("title", "")
    assert "Prospéctica Inc." not in res_b.manifest.get("title", "")
    assert "COFRE" not in res_b.manifest.get("title", "").upper()

    by_sim_b = client.get(f"/api/report/by-simulation/{res_b.simulation_id}").get_json()["data"]
    assert by_sim_b["report_id"] == res_b.report_id


def test_t3_07_fa2_x_fa4_extracted_name_in_ch6_alongside_consistent_gg_table(run_pipeline, tmp_path):
    """FA2 x FA4: Clean extracted project name appears untruncated in Ch.6 alongside consistent GG table."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, sample_size=50, channel_ids=["whatsapp_1on1", "street_survey"])

    ch6 = res.chapters[6]["content_markdown"]
    assert "COFRE" in ch6.upper()
    assert "disenar un plan" not in ch6.lower()
    rows = parse_gabor_granger_table(ch6)
    assert len(rows) >= 3 and any(acc > 0 and rev > 0 for _, acc, rev in rows)


def test_t3_08_fa2_x_fa5_clean_brand_in_events_with_mixed_friction(run_pipeline):
    """FA2 x FA5: Clean brand name (no BLOQUE 1) appears in channel texts while mixed attitudes yield <100% friction."""
    fx = build_agrocafe_tolima_fixture()
    res = run_pipeline(fx, sample_size=40, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    events = query_sqlite_rows(res.sim_dir / "simulation_channels.db", "SELECT content_text FROM channel_events")
    joined = " ".join(e["content_text"] for e in events)
    assert "BLOQUE 1" not in joined and "ACTUA COMO" not in joined.upper()
    loops = res.analytics_bundle["funnel_and_cdj"]["cdj_channel_loops"]
    assert sum(c["friction_rate"] for c in loops) / len(loops) < 0.90


def test_t3_09_fa2_x_fa6_real_brand_h1_and_unique_clean_ch8_quotes(run_pipeline, tmp_path):
    """FA2 x FA6: Report uses real brand H1 and Ch.8 quotes have zero prompt fragments and zero duplication."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, sample_size=50, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    h1 = res.full_report_md.splitlines()[0]
    assert "COFRE" in h1.upper() and "Prospéctica Inc." not in h1
    ch8 = res.chapters[8]["content_markdown"]
    assert "BLOQUE 1" not in ch8 and "disenar un plan" not in ch8.lower()
    quotes = extract_ch8_quotes(ch8)
    assert len(quotes) == len({q for _, q in quotes})


def test_t3_10_fa3_x_fa4_survey_price_shift_rerun_updates_gg_table_without_double_count(client, tmp_path):
    """FA3 x FA4: Re-running survey on same `sim_id` with shifted prices updates GG table without stale cache or 2x N."""
    sim_id = "sim_t3_price_shift"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    client.post(f"/api/channels/{sim_id}/run", json={"enabled_channels": ["whatsapp_1on1"], "rounds": 1})
    client.post(
        f"/api/swarm/{sim_id}/survey/run",
        json={"sample_size": 30, "price_ladder": [5000, 10000, 15000, 20000, 30000], "use_llm": False, "sync": True},
    )
    b1 = client.get(f"/api/analytics/{sim_id}/bundle").get_json()["data"]
    assert b1["data_audit"]["surveys_analyzed"] == 30

    # Re-run with shifted higher ladder
    client.post(
        f"/api/swarm/{sim_id}/survey/run",
        json={"sample_size": 30, "price_ladder": [80000, 120000, 160000, 200000, 250000], "use_llm": False, "sync": True},
    )
    b2 = client.get(f"/api/analytics/{sim_id}/bundle").get_json()["data"]
    assert b2["data_audit"]["surveys_analyzed"] == 30, "Re-run doubled survey respondents"
    prices2 = [int(pt["price"]) for pt in b2["pricing_econometrics"]["gabor_granger"]["points"]]
    assert prices2 == [80000, 120000, 160000, 200000, 250000]

    rep = ReportAgentV2(use_llm=False).generate_report("rep_shift", sim_id, "Servicio Shifted", bundle=b2)
    rows = parse_gabor_granger_table(rep["chapters"][5]["content_markdown"])
    assert [p for p, _, _ in rows] == prices2


def test_t3_11_fa3_x_fa5_rerun_channels_with_new_actor_mix_updates_friction_without_inflation(client, tmp_path):
    """FA3 x FA5: Re-running channels on same `sim_id` with promoter cohort replaces critic events cleanly."""
    sim_id = "sim_t3_friction_rerun"
    sim_dir = tmp_path / "uploads" / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    critics = [
        {"user_id": i, "name": f"Crit{i}", "city_name": "Cali", "divipola_code": "76001", "stratum_code": "E3", "region_macro": "Pacífica", "attitude_segment": "critico_hate"}
        for i in range(10)
    ]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(critics), encoding="utf-8")
    client.post(f"/api/channels/{sim_id}/run", json={"enabled_channels": ["whatsapp_1on1", "tiktok"], "rounds": 1})
    b1 = client.get(f"/api/analytics/{sim_id}/bundle").get_json()["data"]
    n1 = b1["data_audit"]["events_analyzed"]
    fr1 = b1["funnel_and_cdj"]["cdj_channel_loops"][0]["friction_rate"]

    # Replace actor pool with promoters and re-run same sim_id
    promoters = [
        {"user_id": i, "name": f"Prom{i}", "city_name": "Cali", "divipola_code": "76001", "stratum_code": "E3", "region_macro": "Pacífica", "attitude_segment": "promotor"}
        for i in range(10)
    ]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(promoters), encoding="utf-8")
    client.post(f"/api/channels/{sim_id}/run", json={"enabled_channels": ["whatsapp_1on1", "tiktok"], "rounds": 1})
    b2 = client.get(f"/api/analytics/{sim_id}/bundle").get_json()["data"]
    n2 = b2["data_audit"]["events_analyzed"]
    fr2 = b2["funnel_and_cdj"]["cdj_channel_loops"][0]["friction_rate"]

    assert n2 == n1, f"Channel re-run inflated event count: {n1} -> {n2}"
    assert fr1 > 0.7 and fr2 == 0.0, f"Expected critic->promoter replacement: {fr1} -> {fr2}"


def test_t3_12_fa3_x_fa6_project_b_ch8_has_zero_project_a_quotes_and_zero_duplication(run_pipeline, tmp_path):
    """FA3 x FA6: Project B run after Project A has zero Project A terms in Ch.8 and zero duplicate quotes."""
    res_a = run_pipeline(load_cofre_fixture(tmp_path), sample_size=35, channel_ids=["whatsapp_1on1", "tiktok"])
    res_b = run_pipeline(build_miscelanea_esperanza_fixture(), sample_size=35, channel_ids=["whatsapp_1on1", "tiktok"])

    ch8_b = res_b.chapters[8]["content_markdown"]
    assert "cofre" not in ch8_b.lower()
    assert "social finder" not in ch8_b.lower()
    quotes_b = extract_ch8_quotes(ch8_b)
    assert len(quotes_b) == len({q for _, q in quotes_b})


def test_t3_13_fa4_x_fa5_promoter_vs_skeptic_cohort_shifts_gg_and_friction_coherently(tmp_path):
    """FA4 x FA5: Promoter-heavy vs critic-heavy simulation shifts both GG acceptance and Ch.7 friction coherently."""
    def _run_cohort(tag: str, att: str):
        sim_id = f"sim_cohort_{tag}"
        sim_dir = tmp_path / "uploads" / "simulations" / sim_id
        sim_dir.mkdir(parents=True, exist_ok=True)
        actors = [
            {"user_id": i, "name": f"A{i}", "city_name": "Bogotá", "divipola_code": "11001", "stratum_code": "E3", "region_macro": "Andina Centro", "attitude_segment": att}
            for i in range(12)
        ]
        (sim_dir / "reddit_profiles.json").write_text(json.dumps(actors), encoding="utf-8")
        ChannelSimulationEngine(sim_id, sim_dir, "co").run_rounds(["whatsapp_1on1", "street_survey"], rounds=1, study_context={"topic_short": "Café Tolima"})
        # Build surveys matching cohort sentiment
        from .test_tier2_boundaries import _make_survey_record
        from app.channels.persistence import ChannelSQLiteStore
        store = ChannelSQLiteStore(sim_dir)
        rows = []
        for i in range(20):
            grid = (
                {"10000": 1.0, "20000": 0.9, "30000": 0.8, "40000": 0.6, "50000": 0.4}
                if att == "promotor"
                else {"10000": 0.3, "20000": 0.1, "30000": 0.0, "40000": 0.0, "50000": 0.0}
            )
            r = _make_survey_record(i + 1, grid, attitude=att)
            r["gg_grid_json"] = json.dumps(r.pop("gg_grid"))
            rows.append(r)
        store.record_survey_responses_bulk(sim_id, rows)
        bundle = AnalyticsBundleBuilder().build(sim_id, sim_dir, country_code="co", write_file=True)
        rep = ReportAgentV2(use_llm=False).generate_report(f"rep_{tag}", sim_id, "Café Tolima", bundle=bundle)
        return bundle, rep

    b_prom, r_prom = _run_cohort("prom", "promotor")
    b_crit, r_crit = _run_cohort("crit", "critico_hate")

    gg_prom = parse_gabor_granger_table(r_prom["chapters"][5]["content_markdown"])
    gg_crit = parse_gabor_granger_table(r_crit["chapters"][5]["content_markdown"])
    assert gg_prom[0][1] > gg_crit[0][1]

    fr_prom = parse_ch7_friction_table(r_prom["chapters"][6]["content_markdown"])
    fr_crit = parse_ch7_friction_table(r_crit["chapters"][6]["content_markdown"])
    assert fr_prom[0]["friction_pct"] < fr_crit[0]["friction_pct"]


def test_t3_14_fa4_x_fa6_gg_optimal_price_matches_ch11_and_passes_numeric_consistency(run_pipeline):
    """FA4 x FA6: Ch.6 GG optimal price matches Ch.11 SMART target and passes `verify_numeric_consistency` on all chapters."""
    fx = build_rutafacil_saas_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=["whatsapp_1on1", "colombian_web"])

    opt_p = int(round(res.analytics_bundle["pricing_econometrics"]["gabor_granger"]["optimal_price"]))
    assert f"{opt_p:,}" in res.chapters[11]["content_markdown"] or str(opt_p) in res.chapters[11]["content_markdown"]
    for ch_num, ch_data in res.chapters.items():
        chk = verify_numeric_consistency(ch_data["content_markdown"], ch_data.get("metrics_payload") or {})
        assert chk["consistent"] is True, f"Chapter {ch_num} failed numeric consistency: {chk['mismatches']}"


def test_t3_15_fa5_x_fa6_mixed_friction_feeds_ch8_drivers_and_objections_uniquely(run_pipeline):
    """FA5 x FA6: Mixed-friction channels (<100% friction) feed 100% corpus coverage into Ch.8 with zero duplicate quotes."""
    fx = build_clinica_dental_fixture()
    res = run_pipeline(fx, sample_size=50, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    loops = res.analytics_bundle["funnel_and_cdj"]["cdj_channel_loops"]
    assert any(c["friction_rate"] < 1.0 for c in loops)
    assert res.analytics_bundle["qualitative_coding"]["corpus_coverage_pct"] == 100.0
    quotes = extract_ch8_quotes(res.chapters[8]["content_markdown"])
    assert len(quotes) >= 2
    assert Counter(q for _, q in quotes).most_common(1)[0][1] == 1
