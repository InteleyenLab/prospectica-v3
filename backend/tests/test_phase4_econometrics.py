"""Pruebas de Fase 4 (Gate G4): exactitud matemática (<1e-6) contra ground truth manual."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from app.services.analytics.cx_and_polarization import (
    bimodality_coefficient,
    compute_csat_and_ces,
    compute_nps,
    tastle_wierman_consensus,
)
from app.services.analytics.funnel_finance import FunnelFinanceEngine
from app.services.analytics.pricing_econometrics import compute_gabor_granger, compute_van_westendorp
from app.services.analytics.weighting_and_stats import (
    anova_or_kruskal,
    chi2_or_fisher,
    welch_t_and_cohen_d,
    wilson_ci_95,
)


def test_wilson_ci_and_hypothesis_tests_ground_truth():
    # Ground truth manual Wilson IC (k=60, n=100)
    z = float(stats.norm.ppf(0.975))
    p = 0.60
    denom = 1.0 + z * z / 100.0
    center = (p + z * z / 200.0) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z * z / 400.0) / 100.0)) / denom
    lo, hi = wilson_ci_95(60, 100)
    assert abs(lo - (center - half)) < 1e-6
    assert abs(hi - (center + half)) < 1e-6

    # Chi2 y V de Cramér manual
    table = [[30, 10], [10, 30]]
    res_chi = chi2_or_fisher(table)
    assert res_chi["test_used"] == "chi2"
    # chi2 exacto = 80*(900-100)^2 / (40*40*40*40) = 20.0 ; V = sqrt(20/80) = 0.5
    assert abs(res_chi["statistic"] - 20.0) < 1e-6
    assert abs(res_chi["cramers_v"] - 0.5) < 1e-6

    # Welch t-test y d de Cohen (n >= 15 en ambos grupos)
    g1 = [10.0, 12.0, 11.0, 13.0, 10.0] * 3
    g2 = [7.0, 8.0, 6.0, 9.0, 8.0] * 3
    wt = welch_t_and_cohen_d(g1, g2)
    assert wt["parametric_blocked"] is False
    ref_t, ref_p = stats.ttest_ind(g1, g2, equal_var=False)
    assert abs(wt["t_statistic"] - float(ref_t)) < 1e-6
    assert abs(wt["p_value"] - float(ref_p)) < 1e-6

    # ANOVA unifactorial y eta^2
    g3 = [14.0, 15.0, 16.0, 15.0, 14.0] * 3
    an = anova_or_kruskal({"A": g1, "B": g2, "C": g3})
    assert an["parametric_blocked"] is False
    all_v = np.array(g1 + g2 + g3)
    gm = np.mean(all_v)
    ss_tot = np.sum((all_v - gm) ** 2)
    ss_bet = sum(len(x) * ((np.mean(x) - gm) ** 2) for x in (g1, g2, g3))
    assert abs(an["eta_squared"] - float(ss_bet / ss_tot)) < 1e-6


def test_cx_tastle_wierman_and_bimodality_exact_math():
    nps = compute_nps([10, 9, 8, 7, 5, 3, 10, 0, 9, 6])  # 4 prom, 2 pas, 4 detr => 0.0
    assert abs(nps["nps"] - 0.0) < 1e-6

    cx = compute_csat_and_ces([5, 4, 3, 2, 5], [7, 6, 5, 4, 3])
    assert abs(cx["csat_top2box_pct"] - 60.0) < 1e-6
    assert abs(cx["ces_mean"] - 5.0) < 1e-6
    assert abs(cx["ces_top3box_pct"] - 60.0) < 1e-6

    # Consenso extremo en polo bimodal {1, 1, 5, 5} => Cns < 0.1 o igual a 1 + log2(1 - 2/4) = 0.0
    tw = tastle_wierman_consensus([1, 1, 5, 5], categories=[1, 2, 3, 4, 5])
    assert abs(tw["consensus"] - 0.0) < 1e-6
    assert abs(tw["polarization"] - 1.0) < 1e-6

    bc = bimodality_coefficient([1, 1, 1, 1, 1, 10, 10, 10, 10, 10])
    assert bc["bimodal_alert"] is True
    assert bc["bc"] > 0.555


def test_van_westendorp_nms_gabor_granger_and_finance_ground_truth():
    records = [
        {"vw_too_cheap": 20000, "vw_cheap": 40000, "vw_expensive": 80000, "vw_too_expensive": 120000, "nms_intent_cheap": 5, "nms_intent_expensive": 2, "gg_grid": {"40000": 0.9, "70000": 0.7, "100000": 0.3}},
        {"vw_too_cheap": 30000, "vw_cheap": 50000, "vw_expensive": 90000, "vw_too_expensive": 140000, "nms_intent_cheap": 4, "nms_intent_expensive": 2, "gg_grid": {"40000": 0.8, "70000": 0.6, "100000": 0.2}},
        {"vw_too_cheap": 25000, "vw_cheap": 45000, "vw_expensive": 85000, "vw_too_expensive": 130000, "nms_intent_cheap": 4, "nms_intent_expensive": 1, "gg_grid": {"40000": 0.7, "70000": 0.5, "100000": 0.1}},
    ]
    vw = compute_van_westendorp(records)
    assert vw["status"] == "ok"
    assert vw["pmc"] <= min(vw["opp"], vw["idp"]) <= max(vw["opp"], vw["idp"]) <= vw["pme"]
    assert vw["nms"]["optimal_revenue_price"] > 0

    gg = compute_gabor_granger(records)
    assert gg["isotonic_applied"] is False
    # En P=40k Q=0.8 (TR=32k), P=70k Q=0.6 (TR=42k), P=100k Q=0.2 (TR=20k) -> óptimo 70000
    assert abs(gg["optimal_price"] - 70000.0) < 1e-6
    assert abs(gg["max_expected_revenue"] - 42000.0) < 1e-6
    # Elasticidad arco entre 40k y 70k: ((0.6-0.8)/0.7) / ((70-40)/55) = (-0.2857142857) / (0.5454545454)
    expected_ed = ((0.6 - 0.8) / 0.7) / ((70000.0 - 40000.0) / 55000.0)
    assert abs(gg["points"][1]["arc_elasticity"] - expected_ed) < 1e-6

    fin = FunnelFinanceEngine().analyze(country_code="co", optimal_price_a=70000.0)
    assert len(fin["projection_24m"]["monthly_m1_m12"]) == 12
    assert len(fin["projection_24m"]["quarterly_m13_m24"]) == 4
    assert abs(fin["scenario_probabilities_sum_pct"] - 100.0) < 1e-6
    for rng_item in fin["unit_economics_ranges"].values():
        if isinstance(rng_item, dict) and "min" in rng_item:
            assert rng_item["min"] <= rng_item["probable"] <= rng_item["max"]
