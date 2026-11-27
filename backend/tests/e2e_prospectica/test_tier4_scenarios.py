"""Tier 4: Realistic Colombian Full-Pipeline E2E Scenarios & Comparative Validation.

Runs 6 complete end-to-end Colombian business scenarios (11 channels, survey N>=60,
analytics, 12-chapter report, download) plus a comparative 2-project validation gate
verifying all Acceptance Criteria in ORIGINAL_REQUEST.md.
"""

from __future__ import annotations

import json
from collections import Counter

from app.channels import CANONICAL_CHANNEL_IDS
from app.services.report_agent_v2 import verify_numeric_consistency

from .conftest import (
    extract_ch8_quotes,
    parse_ch7_friction_table,
    parse_gabor_granger_table,
)
from .fixtures_colombia import (
    build_agrocafe_tolima_fixture,
    build_clinica_dental_fixture,
    build_miscelanea_esperanza_fixture,
    build_nexo_legal_vial_fixture,
    build_rutafacil_saas_fixture,
    load_cofre_fixture,
)


def _assert_universal_r1_to_r4_invariants(res) -> None:
    """Assert core R1–R4 invariants shared by every full-pipeline Colombian scenario."""
    # R1: StudyContext persisted & dynamic
    assert res.study_context is not None, f"Missing study_context.json for {res.fixture.key}"
    assert len(res.study_context.get("price_ladder_cop") or []) == 5

    # R2: Real project name, zero Prospéctica Inc. in study title/headers, slugged download filename
    assert res.project_name
    assert "unnamed project" not in res.project_name.lower()
    assert "bloque" not in res.project_name.lower()
    assert "disenar un plan" not in res.project_name.lower()

    h1 = res.full_report_md.splitlines()[0] if res.full_report_md else ""
    assert "Prospéctica Inc." not in h1, f"H1 leaked Prospéctica Inc.: {h1}"
    assert "Prospéctica Inc." not in str(res.manifest.get("title") or "")
    assert "Prospéctica Inc." not in str(res.manifest.get("header_label") or "")
    assert res.download_filename.endswith(f"_{res.report_id}.md")
    assert res.download_filename != f"{res.report_id}.md"
    assert "prospectica" not in res.download_filename.lower()

    # 12 chapters complete & numeric consistency
    assert len(res.chapters) == 12
    for ch_num, ch_data in res.chapters.items():
        chk = verify_numeric_consistency(ch_data["content_markdown"], ch_data.get("metrics_payload") or {})
        assert chk["consistent"] is True, f"{res.fixture.key} Ch.{ch_num} inconsistent: {chk['mismatches']}"

    # R4a: Gabor-Granger non-zero and consistent with optimal_price
    gg = res.analytics_bundle["pricing_econometrics"]["gabor_granger"]
    opt_p = int(round(gg["optimal_price"]))
    rows = parse_gabor_granger_table(res.chapters[6]["content_markdown"])
    assert len(rows) == len(gg["points"])
    assert any(acc > 0.0 and rev > 0 for _, acc, rev in rows), f"{res.fixture.key} GG table all 0.0% / COP 0"
    assert any(p == opt_p for p, _, _ in rows)

    # R4b: Mixed channel friction (< 100% uniformly)
    cdj_rows = parse_ch7_friction_table(res.chapters[7]["content_markdown"])
    assert len(cdj_rows) >= 5
    mean_fr = sum(r["friction_pct"] for r in cdj_rows) / len(cdj_rows)
    assert mean_fr < 90.0, f"{res.fixture.key} channel friction near-100% uniformly: {cdj_rows}"

    # R4c: Ch.8 zero verbatim quote duplication & zero boilerplate leakage
    ch8 = res.chapters[8]["content_markdown"]
    assert "BLOQUE 1" not in ch8 and "Actua como" not in ch8
    quotes = extract_ch8_quotes(ch8)
    assert len(quotes) >= 2
    assert Counter(q for _, q in quotes).most_common(1)[0][1] == 1, f"{res.fixture.key} Ch.8 repeated quote: {quotes}"
    assert Counter(tag for tag, _ in quotes).most_common(1)[0][1] == 1

    # Dynamic DOFA matrix in charts_spec
    dofa = (res.analytics_bundle.get("charts_spec") or {}).get("dofa_matrix")
    assert isinstance(dofa, dict) and "scores" in dofa and "items" in dofa


def test_t4_scenario_1_cofre_fintech_escrow_nacional(run_pipeline, tmp_path):
    """Scenario 1: Real COFRE PDF + 5-block prompt -> national fintech escrow study."""
    fx = load_cofre_fixture(tmp_path)
    res = run_pipeline(fx, sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    _assert_universal_r1_to_r4_invariants(res)
    assert res.project_name.upper().startswith("COFRE")
    assert res.download_filename == f"cofre_{res.report_id}.md"

    full_low = res.full_report_md.lower()
    assert "cofre" in full_low
    for leak in ("conductor_movilidad", "decreto 196/1971", "servicio b", "casos/mes", "choque"):
        assert leak not in full_low, f"COFRE report leaked NEXO term {leak!r}"


def test_t4_scenario_2_miscelanea_la_esperanza_barrio_bogota(run_pipeline):
    """Scenario 2: Micro-neighborhood shop in Bogotá (tickets COP 2k–20k, local OPEX)."""
    fx = build_miscelanea_esperanza_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    _assert_universal_r1_to_r4_invariants(res)
    assert "miscelánea" in res.project_name.lower() or "esperanza" in res.project_name.lower()
    assert res.download_filename.startswith("miscelanea_la_esperanza_")

    sc = res.study_context
    assert max(sc["price_ladder_cop"]) <= 40_000
    assert sc["monthly_opex_cop"] < 3_000_000
    assert sc["unit_label"].lower() != "casos/mes"

    full_low = res.full_report_md.lower()
    for leak in ("cofre", "nexo", "escrow", "aseguradora", "decreto 196/1971", "servicio b"):
        assert leak not in full_low, f"Miscelánea report leaked {leak!r}"


def test_t4_scenario_3_nexo_asistencia_legal_vial_6_ciudades(run_pipeline):
    """Scenario 3: NEXO legal mobility service preserves its own legal context cleanly when uploaded."""
    fx = build_nexo_legal_vial_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    _assert_universal_r1_to_r4_invariants(res)
    assert "nexo" in res.project_name.lower()
    assert res.download_filename.startswith("nexo_")
    full_low = res.full_report_md.lower()
    assert "cofre" not in full_low and "miscelánea" not in full_low


def test_t4_scenario_4_agrocafe_origen_tolima_b2b2c(run_pipeline):
    """Scenario 4: Specialty coffee cooperative B2B2C (Ibagué + Eje Cafetero)."""
    fx = build_agrocafe_tolima_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    _assert_universal_r1_to_r4_invariants(res)
    assert "agrocafé" in res.project_name.lower() or "agrocafe" in res.project_name.lower()
    full_low = res.full_report_md.lower()
    assert any(k in full_low for k in ("café", "tolima", "tostado", "invima"))
    for leak in ("cofre", "nexo", "escrow", "decreto 196/1971", "conductor_movilidad"):
        assert leak not in full_low


def test_t4_scenario_5_clinica_dental_sonrisa_bogota(run_pipeline):
    """Scenario 5: Private dental clinic in Bogotá (E3–E5, COP 90k–450k)."""
    fx = build_clinica_dental_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    _assert_universal_r1_to_r4_invariants(res)
    assert "sonrisa" in res.project_name.lower() or "dental" in res.project_name.lower()
    full_low = res.full_report_md.lower()
    assert any(k in full_low for k in ("dental", "odontolog", "sonrisa", "salud"))
    for leak in ("cofre", "nexo", "escrow", "decreto 196/1971", "casos/mes"):
        assert leak not in full_low


def test_t4_scenario_6_rutafacil_logistica_saas_b2b(run_pipeline):
    """Scenario 6: B2B SaaS last-mile logistics platform for Colombian SMEs (COP 180k–650k/mo)."""
    fx = build_rutafacil_saas_fixture()
    res = run_pipeline(fx, sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    _assert_universal_r1_to_r4_invariants(res)
    assert "rutafácil" in res.project_name.lower() or "rutafacil" in res.project_name.lower()
    assert min(res.study_context["price_ladder_cop"]) >= 100_000
    full_low = res.full_report_md.lower()
    assert any(k in full_low for k in ("logística", "saas", "flota", "rutas", "rutafácil"))
    for leak in ("cofre", "nexo", "escrow", "decreto 196/1971", "casos/mes"):
        assert leak not in full_low


def test_t4_comparative_two_project_validation_cofre_vs_miscelanea(run_pipeline, tmp_path):
    """Acceptance Gate: Full comparative validation of COFRE vs Miscelánea La Esperanza."""
    res_cofre = run_pipeline(load_cofre_fixture(tmp_path), sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)
    res_misc = run_pipeline(build_miscelanea_esperanza_fixture(), sample_size=60, channel_ids=list(CANONICAL_CHANNEL_IDS), rounds=2)

    _assert_universal_r1_to_r4_invariants(res_cofre)
    _assert_universal_r1_to_r4_invariants(res_misc)

    # Disjoint IDs & artifacts
    assert res_cofre.project_id != res_misc.project_id
    assert res_cofre.simulation_id != res_misc.simulation_id
    assert res_cofre.report_id != res_misc.report_id
    assert res_cofre.download_filename != res_misc.download_filename

    # Distinct economic scaling
    opt_cofre = res_cofre.analytics_bundle["pricing_econometrics"]["gabor_granger"]["optimal_price"]
    opt_misc = res_misc.analytics_bundle["pricing_econometrics"]["gabor_granger"]["optimal_price"]
    assert opt_misc < opt_cofre or res_misc.study_context["monthly_opex_cop"] < res_cofre.study_context["monthly_opex_cop"]

    # Zero cross-contamination in either direction
    cofre_all = json.dumps(res_cofre.profiles, ensure_ascii=False).lower() + res_cofre.full_report_md.lower()
    misc_all = json.dumps(res_misc.profiles, ensure_ascii=False).lower() + res_misc.full_report_md.lower()
    assert "miscelánea la esperanza" not in cofre_all
    assert "cofre" not in misc_all and "social finder" not in misc_all
