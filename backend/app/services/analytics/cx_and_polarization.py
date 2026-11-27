"""Motor de métricas CX (NPS, CSAT, CES), consenso Tastle-Wierman, bimodalidad y sesgo de complacencia."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

import numpy as np
from scipy import stats


def tastle_wierman_consensus(values: Sequence[float], categories: Sequence[float]) -> Dict[str, float]:
    """Calcula Consenso Tastle-Wierman Cns(X) y Polarización Pol(X) = 1 - Cns(X)."""
    vals = np.asarray(values, dtype=float)
    cats = np.asarray(sorted(categories), dtype=float)
    if len(vals) == 0 or len(cats) < 2:
        return {"consensus": 0.0, "polarization": 1.0, "mean": 0.0}

    width = float(cats[-1] - cats[0])
    if width <= 0:
        return {"consensus": 1.0, "polarization": 0.0, "mean": float(cats[0])}

    # Asignar cada observación a la categoría más cercana para distribución discreta exacta
    probs = np.zeros(len(cats), dtype=float)
    for v in vals:
        idx = int(np.argmin(np.abs(cats - v)))
        probs[idx] += 1.0
    probs /= float(len(vals))

    mu = float(np.sum(probs * cats))
    cns = 1.0
    for p, x in zip(probs, cats):
        if p <= 0:
            continue
        ratio = abs(float(x) - mu) / width
        inner = max(1e-12, 1.0 - ratio)
        cns += float(p) * math.log2(inner)

    cns = max(0.0, min(1.0, cns))
    return {
        "consensus": float(cns),
        "polarization": float(1.0 - cns),
        "mean": float(mu),
    }


def bimodality_coefficient(values: Sequence[float]) -> Dict[str, Any]:
    """Calcula Coeficiente de Bimodalidad BC; alerta si BC > 0.555."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < 4 or float(np.std(arr)) == 0.0:
        return {"bc": 0.0, "bimodal_alert": False, "skewness": 0.0, "excess_kurtosis": 0.0}

    skew = float(stats.skew(arr, bias=False))
    kurt = float(stats.kurtosis(arr, fisher=True, bias=False))
    denom = kurt + (3.0 * ((n - 1) ** 2)) / ((n - 2) * (n - 3))
    bc = ((skew ** 2) + 1.0) / denom if denom > 0 else 0.0
    return {
        "bc": float(bc),
        "bimodal_alert": bool(bc > 0.555),
        "skewness": float(skew),
        "excess_kurtosis": float(kurt),
    }


def compute_nps(scores: Sequence[int]) -> Dict[str, Any]:
    """Calcula NPS estándar (promotores 9-10, pasivos 7-8, detractores 0-6)."""
    arr = np.asarray(scores, dtype=int)
    n = len(arr)
    if n == 0:
        return {"nps": 0.0, "promoters_pct": 0.0, "passives_pct": 0.0, "detractors_pct": 0.0, "n": 0}
    prom = float(np.mean(arr >= 9) * 100.0)
    pasv = float(np.mean((arr >= 7) & (arr <= 8)) * 100.0)
    detr = float(np.mean(arr <= 6) * 100.0)
    return {
        "nps": float(prom - detr),
        "promoters_pct": prom,
        "passives_pct": pasv,
        "detractors_pct": detr,
        "n": int(n),
    }


def compute_csat_and_ces(csat_scores: Sequence[int], ces_scores: Sequence[int]) -> Dict[str, float]:
    """Calcula CSAT Top-2-Box (4-5 de 1-5) y CES promedio + Top-3-Box (5-7 de 1-7)."""
    csat_arr = np.asarray(csat_scores, dtype=float)
    ces_arr = np.asarray(ces_scores, dtype=float)
    csat_top2 = float(np.mean(csat_arr >= 4) * 100.0) if len(csat_arr) else 0.0
    csat_mean = float(np.mean(csat_arr)) if len(csat_arr) else 0.0
    ces_mean = float(np.mean(ces_arr)) if len(ces_arr) else 0.0
    ces_top3 = float(np.mean(ces_arr >= 5) * 100.0) if len(ces_arr) else 0.0
    return {
        "csat_top2box_pct": csat_top2,
        "csat_mean": csat_mean,
        "ces_mean": ces_mean,
        "ces_top3box_pct": ces_top3,
    }


class CXAndPolarizationEngine:
    """Evalúa métricas CX, polarización y detector anti-complacencia (sycophancy)."""

    def analyze(
        self,
        survey_responses: List[Dict[str, Any]],
        channel_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        completed = [r for r in survey_responses if r.get("status", "completed") == "completed"]
        if not completed:
            sentiments = [float(e.get("sentiment_score", 0.0)) for e in (channel_events or [])]
            pos_share = float(np.mean(np.asarray(sentiments) > 0.15)) if sentiments else 0.0
            return {
                "status": "not_applicable_legacy",
                "nps": {"nps": 0.0, "n": 0},
                "csat_ces": {},
                "polarization": {"consensus": 0.5, "polarization": 0.5},
                "bimodality": {"bc": 0.0, "bimodal_alert": False},
                "sycophancy_warning": bool(pos_share > 0.85),
                "positive_share": pos_share,
            }

        nps_list = [int(r["nps_score"]) for r in completed if r.get("nps_score") is not None]
        csat_list = [int(r["csat_score"]) for r in completed if r.get("csat_score") is not None]
        ces_list = [int(r["ces_score"]) for r in completed if r.get("ces_score") is not None]
        trust_list = [int(r["trust_score"]) for r in completed if r.get("trust_score") is not None]

        nps_res = compute_nps(nps_list)
        csat_ces = compute_csat_and_ces(csat_list, ces_list)
        tw = tastle_wierman_consensus(trust_list, categories=list(range(1, 11)))
        bc = bimodality_coefficient(trust_list)

        positive_share = float(np.mean(np.asarray(trust_list) >= 6)) if trust_list else 0.0
        sycophancy_warning = bool(positive_share > 0.85 or tw["polarization"] < 0.15)

        return {
            "status": "ok",
            "nps": nps_res,
            "csat_ces": csat_ces,
            "polarization": tw,
            "bimodality": bc,
            "positive_share": positive_share,
            "sycophancy_warning": sycophancy_warning,
        }
