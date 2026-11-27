"""Motor de post-estratificación (raking acotado), IC Wilson, tablas cruzadas y pruebas de hipótesis."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from country_packs import get_country_pack

Z_95 = float(stats.norm.ppf(0.975))
MIN_SUBGROUP_FOR_PARAMETRIC = 15


def wilson_ci_95(successes: int, total: int) -> Tuple[float, float]:
    """Calcula intervalo de confianza Wilson Score al 95% en proporción [0, 1]."""
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    z2 = Z_95 * Z_95
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    margin = (Z_95 * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def compute_raking_weights(
    strata_observed: Sequence[str],
    target_pct_by_stratum: Dict[str, float],
    lower_bound: float = 0.3,
    upper_bound: float = 3.0,
) -> np.ndarray:
    """Calcula pesos post-estratificados acotados en [0.3, 3.0] normalizados a media 1.0."""
    n = len(strata_observed)
    if n == 0:
        return np.array([], dtype=float)
    series = pd.Series(list(strata_observed), dtype=str)
    counts = series.value_counts().to_dict()
    total_target = sum(target_pct_by_stratum.get(k, 0.0) for k in counts)
    if total_target <= 0:
        return np.ones(n, dtype=float)

    weights = np.ones(n, dtype=float)
    for idx, st in enumerate(strata_observed):
        obs_share = counts[st] / n
        tgt_share = target_pct_by_stratum.get(st, 0.0) / total_target
        raw_w = (tgt_share / obs_share) if obs_share > 0 and tgt_share > 0 else 1.0
        weights[idx] = min(upper_bound, max(lower_bound, raw_w))

    mean_w = float(np.mean(weights))
    if mean_w > 0:
        weights = weights / mean_w
    return np.clip(weights, lower_bound, upper_bound)


def chi2_or_fisher(contingency_table: Sequence[Sequence[int]]) -> Dict[str, Any]:
    """Ejecuta Chi-cuadrado con fallback exacto de Fisher si >20% de celdas tienen E_ij < 5."""
    arr = np.asarray(contingency_table, dtype=float)
    if arr.ndim != 2 or arr.size == 0 or np.sum(arr) == 0:
        return {"test_used": "insufficient_data", "statistic": 0.0, "p_value": 1.0, "cramers_v": 0.0}

    chi2, p_val, dof, expected = stats.chi2_contingency(arr, correction=False)
    low_expected_ratio = float(np.mean(expected < 5.0))
    n_total = float(np.sum(arr))
    min_dim = max(1, min(arr.shape[0] - 1, arr.shape[1] - 1))
    cramers_v = math.sqrt(float(chi2) / (n_total * min_dim)) if n_total > 0 else 0.0

    test_used = "chi2"
    stat_out = float(chi2)
    p_out = float(p_val)

    if low_expected_ratio > 0.20 and arr.shape == (2, 2):
        odds_ratio, p_fisher = stats.fisher_exact(arr.astype(int))
        test_used = "fisher_exact"
        stat_out = float(odds_ratio)
        p_out = float(p_fisher)

    return {
        "test_used": test_used,
        "statistic": stat_out,
        "p_value": p_out,
        "dof": int(dof),
        "low_expected_cell_ratio": low_expected_ratio,
        "cramers_v": cramers_v,
    }


def welch_t_and_cohen_d(group_a: Sequence[float], group_b: Sequence[float]) -> Dict[str, Any]:
    """Prueba t de Welch y tamaño del efecto d de Cohen (bloqueada si n < 15 en algún subgrupo)."""
    a = np.asarray(group_a, dtype=float)
    b = np.asarray(group_b, dtype=float)
    if len(a) < MIN_SUBGROUP_FOR_PARAMETRIC or len(b) < MIN_SUBGROUP_FOR_PARAMETRIC:
        return {
            "parametric_blocked": True,
            "reason": f"Subgrupo menor a n={MIN_SUBGROUP_FOR_PARAMETRIC} (n_a={len(a)}, n_b={len(b)})",
            "n_a": int(len(a)),
            "n_b": int(len(b)),
            "t_statistic": None,
            "p_value": None,
            "cohens_d": None,
        }

    t_stat, p_val = stats.ttest_ind(a, b, equal_var=False)
    s1 = float(np.var(a, ddof=1))
    s2 = float(np.var(b, ddof=1))
    pooled_sd = math.sqrt(((len(a) - 1) * s1 + (len(b) - 1) * s2) / (len(a) + len(b) - 2))
    cohens_d = (float(np.mean(a)) - float(np.mean(b))) / pooled_sd if pooled_sd > 0 else 0.0
    return {
        "parametric_blocked": False,
        "n_a": int(len(a)),
        "n_b": int(len(b)),
        "t_statistic": float(t_stat),
        "p_value": float(p_val),
        "cohens_d": float(cohens_d),
    }


def anova_or_kruskal(groups: Dict[str, Sequence[float]]) -> Dict[str, Any]:
    """ANOVA unifactorial con verificación Shapiro-Wilk, fallback Kruskal-Wallis y eta^2."""
    clean_groups = {k: np.asarray(v, dtype=float) for k, v in groups.items() if len(v) > 0}
    if len(clean_groups) < 2:
        return {"parametric_blocked": True, "reason": "Menos de 2 grupos disponibles"}

    too_small = {k: int(len(v)) for k, v in clean_groups.items() if len(v) < MIN_SUBGROUP_FOR_PARAMETRIC}
    if too_small:
        return {
            "parametric_blocked": True,
            "reason": f"Subgrupos por debajo de n={MIN_SUBGROUP_FOR_PARAMETRIC}: {too_small}",
            "group_sizes": {k: int(len(v)) for k, v in clean_groups.items()},
        }

    arrays = list(clean_groups.values())
    f_stat, p_anova = stats.f_oneway(*arrays)

    # Shapiro-Wilk por grupo (máximo 5000 muestras por grupo)
    shapiro_p_values = []
    for arr in arrays:
        if len(arr) >= 3 and float(np.std(arr)) > 0:
            _, sp_p = stats.shapiro(arr[:5000])
            shapiro_p_values.append(float(sp_p))
        else:
            shapiro_p_values.append(1.0)
    min_shapiro = min(shapiro_p_values) if shapiro_p_values else 1.0

    # Eta^2 = SS_between / SS_total
    all_vals = np.concatenate(arrays)
    grand_mean = float(np.mean(all_vals))
    ss_total = float(np.sum((all_vals - grand_mean) ** 2))
    ss_between = sum(float(len(a)) * ((float(np.mean(a)) - grand_mean) ** 2) for a in arrays)
    eta_sq = (ss_between / ss_total) if ss_total > 0 else 0.0

    kw_stat, kw_p = stats.kruskal(*arrays)
    use_nonparametric = min_shapiro < 0.05

    return {
        "parametric_blocked": False,
        "recommended_test": "kruskal_wallis" if use_nonparametric else "anova_oneway",
        "anova_f": float(f_stat),
        "anova_p": float(p_anova),
        "shapiro_min_p": float(min_shapiro),
        "kruskal_h": float(kw_stat),
        "kruskal_p": float(kw_p),
        "eta_squared": float(eta_sq),
        "group_sizes": {k: int(len(v)) for k, v in clean_groups.items()},
    }


class WeightingAndStatsEngine:
    """Calcula ponderación demográfica, tablas cruzadas y pruebas sobre `survey_responses`."""

    def __init__(self, country_code: str = "co"):
        self.pack = get_country_pack(country_code or "co")
        self.target_stratum_weights = {s.code: s.urban_weight_pct for s in self.pack.strata}

    def analyze(self, survey_responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        completed = [r for r in survey_responses if r.get("status", "completed") == "completed"]
        if not completed:
            return {
                "status": "not_applicable_legacy",
                "n_completed": 0,
                "weights_summary": {},
                "crosstabs": {},
                "hypothesis_tests": {},
            }

        df = pd.DataFrame(completed)
        weights = compute_raking_weights(df["stratum_code"].astype(str).tolist(), self.target_stratum_weights)
        df["post_weight"] = weights

        # Proporción de intención positiva (pain_score >= 6 y trust_score >= 5 o promotor/neutral)
        promoters = int((df["nps_score"].fillna(0) >= 7).sum())
        ci_low, ci_high = wilson_ci_95(promoters, len(df))

        # Tablas cruzadas por ciudad, estrato, género y rol
        crosstabs: Dict[str, Any] = {}
        for col in ("city_name", "stratum_code", "gender", "dynamic_study_role", "attitude_segment"):
            if col not in df.columns:
                continue
            grp = df.groupby(col, dropna=False).agg(
                n=("respondent_id", "count"),
                mean_pain=("pain_score", "mean"),
                mean_trust=("trust_score", "mean"),
                mean_nps=("nps_score", "mean"),
            )
            crosstabs[col] = {
                str(k): {
                    "n": int(row["n"]),
                    "mean_pain": round(float(row["mean_pain"]), 3),
                    "mean_trust": round(float(row["mean_trust"]), 3),
                    "mean_nps": round(float(row["mean_nps"]), 3),
                }
                for k, row in grp.iterrows()
            }

        # Pruebas de hipótesis entre grupos principales
        strata_groups = {
            str(k): g["trust_score"].dropna().astype(float).tolist()
            for k, g in df.groupby("stratum_code")
        }
        anova_trust_by_stratum = anova_or_kruskal(strata_groups)

        skeptics = df[df["attitude_segment"].isin(["esceptico", "critico_hate"])]["trust_score"].dropna().tolist()
        non_skeptics = df[~df["attitude_segment"].isin(["esceptico", "critico_hate"])]["trust_score"].dropna().tolist()
        welch_trust = welch_t_and_cohen_d(skeptics, non_skeptics)

        # Chi2 entre estrato (bajo E1-E3 vs medio-alto E4-E6) y disposición (>=3)
        df["high_stratum"] = df["wealth_tier_norm"] >= 4
        df["high_intent"] = df["nms_intent_cheap"].fillna(0) >= 4
        ct = pd.crosstab(df["high_stratum"], df["high_intent"])
        chi2_intent = chi2_or_fisher(ct.values) if ct.shape == (2, 2) else {"test_used": "skipped_shape"}

        return {
            "status": "ok",
            "n_completed": int(len(df)),
            "wilson_high_nps_rate": {
                "rate": round(promoters / len(df), 4),
                "ci_95_low": round(ci_low, 4),
                "ci_95_high": round(ci_high, 4),
            },
            "weights_summary": {
                "min_weight": round(float(np.min(weights)), 4),
                "max_weight": round(float(np.max(weights)), 4),
                "mean_weight": round(float(np.mean(weights)), 4),
            },
            "crosstabs": crosstabs,
            "hypothesis_tests": {
                "anova_trust_by_stratum": anova_trust_by_stratum,
                "welch_trust_skeptics_vs_rest": welch_trust,
                "chi2_stratum_vs_intent": chi2_intent,
            },
        }
