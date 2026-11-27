"""Motor econométrico determinístico para Van Westendorp (PSM + NMS) y Gabor-Granger."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


def _linear_crossing_x(xs: np.ndarray, y1: np.ndarray, y2: np.ndarray) -> float:
    """Encuentra el primer cruce donde (y1 - y2) cambia de signo usando interpolación lineal."""
    diff = y1 - y2
    exact = np.where(np.isclose(diff, 0.0, atol=1e-9))[0]
    if len(exact) > 0:
        return float(xs[int(exact[len(exact) // 2])])
    for i in range(len(xs) - 1):
        d0, d1 = float(diff[i]), float(diff[i + 1])
        if (d0 >= 0.0 and d1 <= 0.0) or (d0 <= 0.0 and d1 >= 0.0):
            denom = d0 - d1
            if abs(denom) < 1e-12:
                return float(xs[i])
            frac = d0 / denom
            return float(xs[i] + frac * (xs[i + 1] - xs[i]))
    idx = int(np.argmin(np.abs(diff)))
    return float(xs[idx])


def pav_decreasing(values: Sequence[float]) -> np.ndarray:
    """Pool Adjacent Violators Algorithm (PAV) garantizando secuencia monótona NO creciente."""
    arr = np.asarray(values, dtype=float)
    if len(arr) <= 1:
        return arr.copy()
    # Minimizar sum (y - (-arr))^2 sujeto a y_0 <= y_1 <= ... (no decreciente sobre -arr)
    neg = -arr
    blocks: List[List[Any]] = [[float(v), 1] for v in neg]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            total_w = blocks[i][1] + blocks[i + 1][1]
            avg = (blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / total_w
            blocks[i] = [avg, total_w]
            blocks.pop(i + 1)
            if i > 0:
                i -= 1
        else:
            i += 1
    out: List[float] = []
    for val, cnt in blocks:
        out.extend([-val] * cnt)
    return np.asarray(out, dtype=float)


def compute_van_westendorp(records: List[Dict[str, Any]], unit_var_cost: float = 18000.0) -> Dict[str, Any]:
    """Calcula curvas Van Westendorp + NMS con limpieza monotónica estricta."""
    if not records:
        return {"status": "not_applicable_legacy", "valid_n": 0, "total_n": 0}

    valid_rows: List[Tuple[float, float, float, float, int, int]] = []
    for r in records:
        tc = r.get("vw_too_cheap")
        c = r.get("vw_cheap")
        e = r.get("vw_expensive")
        te = r.get("vw_too_expensive")
        if None in (tc, c, e, te):
            continue
        tc_f, c_f, e_f, te_f = float(tc), float(c), float(e), float(te)
        if 0.0 < tc_f < c_f < e_f < te_f:
            ic = int(r.get("nms_intent_cheap") or 3)
            ie = int(r.get("nms_intent_expensive") or 2)
            valid_rows.append((tc_f, c_f, e_f, te_f, ic, ie))

    total_n = len(records)
    valid_n = len(valid_rows)
    if valid_n == 0:
        return {
            "status": "insufficient_valid_rows",
            "total_n": total_n,
            "valid_n": 0,
            "discarded_non_monotonic": total_n,
            "consistency_rate": 0.0,
        }

    arr = np.asarray([row[:4] for row in valid_rows], dtype=float)
    tc_arr, c_arr, e_arr, te_arr = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    ic_arr = np.asarray([row[4] for row in valid_rows], dtype=float)
    ie_arr = np.asarray([row[5] for row in valid_rows], dtype=float)

    grid = np.unique(np.sort(arr.ravel()))
    if len(grid) == 1:
        p0 = float(grid[0])
        grid = np.linspace(p0 * 0.8, p0 * 1.2, 5)

    # Curvas estándar monotónicas: PMC <= min(OPP, IDP) <= max(OPP, IDP) <= PME
    y_too_cheap = np.array([np.mean(tc_arr >= p) for p in grid], dtype=float)
    y_not_cheap = np.array([np.mean(c_arr < p) for p in grid], dtype=float)
    y_not_expensive = np.array([np.mean(e_arr > p) for p in grid], dtype=float)
    y_too_expensive = np.array([np.mean(te_arr <= p) for p in grid], dtype=float)

    pmc = _linear_crossing_x(grid, y_too_cheap, y_not_cheap)
    opp = _linear_crossing_x(grid, y_too_cheap, y_too_expensive)
    idp = _linear_crossing_x(grid, y_not_cheap, y_not_expensive)
    pme = _linear_crossing_x(grid, y_not_expensive, y_too_expensive)
    opp_idp_reordered = False
    if opp > idp:
        opp, idp = min(opp, idp), max(opp, idp)
        opp_idp_reordered = True

    # Extensión Newton-Miller-Smith (NMS): transformación estándar de intención 1..5 -> [0, 0.7]
    nms_map = {1: 0.0, 2: 0.1, 3: 0.3, 4: 0.5, 5: 0.7}
    w_c = np.vectorize(lambda k: nms_map.get(int(k), 0.3))(ic_arr)
    w_e = np.vectorize(lambda k: nms_map.get(int(k), 0.1))(ie_arr)

    nms_points: List[Dict[str, float]] = []
    for p in grid:
        # Interpolación por respondente entre P_C (intent_cheap) y P_E (intent_expensive)
        prob_i = np.where(
            p <= c_arr,
            w_c,
            np.where(
                p >= e_arr,
                w_e * np.maximum(0.0, 1.0 - (p - e_arr) / np.maximum(1.0, te_arr - e_arr)),
                w_c + (w_e - w_c) * ((p - c_arr) / np.maximum(1.0, e_arr - c_arr)),
            ),
        )
        s_p = float(np.mean(np.clip(prob_i, 0.0, 1.0)))
        r_p = float(p) * s_p
        m_p = (float(p) - unit_var_cost) * s_p
        nms_points.append(
            {
                "price": float(p),
                "trial_share": s_p,
                "relative_revenue": r_p,
                "relative_margin": m_p,
            }
        )

    best_rev = max(nms_points, key=lambda x: x["relative_revenue"])
    best_margin = max(nms_points, key=lambda x: x["relative_margin"])

    return {
        "status": "ok",
        "total_n": total_n,
        "valid_n": valid_n,
        "discarded_non_monotonic": total_n - valid_n,
        "consistency_rate": float(valid_n / total_n),
        "pmc": float(pmc),
        "opp": float(opp),
        "idp": float(idp),
        "pme": float(pme),
        "rap": [float(pmc), float(pme)],
        "curves": {
            "prices": [float(x) for x in grid],
            "too_cheap": [float(x) for x in y_too_cheap],
            "not_cheap": [float(x) for x in y_not_cheap],
            "not_expensive": [float(x) for x in y_not_expensive],
            "too_expensive": [float(x) for x in y_too_expensive],
        },
        "nms": {
            "optimal_revenue_price": float(best_rev["price"]),
            "optimal_margin_price": float(best_margin["price"]),
            "points": nms_points,
        },
    }


def compute_gabor_granger(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcula demanda empírica GG, aplica PAV si es no monótona, elasticidad arco e ingreso óptimo P*."""
    grids: List[Dict[str, float]] = []
    for r in records:
        g = r.get("gg_grid")
        if isinstance(g, str) and g:
            try:
                g = json.loads(g)
            except json.JSONDecodeError:
                g = None
        if isinstance(g, dict) and g:
            grids.append({str(k): float(v) for k, v in g.items()})

    if not grids:
        return {"status": "not_applicable_legacy", "points": []}

    all_prices = sorted({float(k) for g in grids for k in g.keys()})
    raw_demands: List[float] = []
    for p in all_prices:
        key_opts = [str(int(p)) if p.is_integer() else str(p), str(p)]
        vals = []
        for g in grids:
            for ko in key_opts:
                if ko in g:
                    vals.append(float(g[ko]))
                    break
        raw_demands.append(float(np.mean(vals)) if vals else 0.0)

    has_inversion = any(raw_demands[i + 1] > raw_demands[i] + 1e-12 for i in range(len(raw_demands) - 1))
    smoothed = pav_decreasing(raw_demands) if has_inversion else np.asarray(raw_demands, dtype=float)

    points: List[Dict[str, Any]] = []
    for idx, p in enumerate(all_prices):
        q = float(smoothed[idx])
        arc_e: Optional[float] = None
        if idx > 0:
            p0, q0 = all_prices[idx - 1], float(smoothed[idx - 1])
            q_mid = (q + q0) / 2.0
            p_mid = (p + p0) / 2.0
            if q_mid > 0 and p_mid > 0 and abs(p - p0) > 1e-12:
                arc_e = float(((q - q0) / q_mid) / ((p - p0) / p_mid))
        points.append(
            {
                "price": float(p),
                "demand_raw": float(raw_demands[idx]),
                "demand_monotonic": q,
                "expected_revenue": float(p * q),
                "arc_elasticity": arc_e,
            }
        )

    best_pt = max(points, key=lambda pt: pt["expected_revenue"])
    return {
        "status": "ok",
        "n_respondents": len(grids),
        "isotonic_applied": bool(has_inversion),
        "optimal_price": float(best_pt["price"]),
        "max_expected_revenue": float(best_pt["expected_revenue"]),
        "points": points,
    }


class PricingEconometricsEngine:
    """Agrupa análisis Van Westendorp + NMS y Gabor-Granger global y segmentado."""

    def analyze(self, survey_responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        completed = [r for r in survey_responses if r.get("status", "completed") == "completed"]
        if not completed:
            return {
                "van_westendorp": {"status": "not_applicable_legacy"},
                "gabor_granger": {"status": "not_applicable_legacy"},
                "by_stratum": {},
            }

        vw_global = compute_van_westendorp(completed)
        gg_global = compute_gabor_granger(completed)

        by_stratum: Dict[str, Any] = {}
        strata_seen = sorted({str(r.get("stratum_code") or "N/D") for r in completed})
        for st in strata_seen:
            sub = [r for r in completed if str(r.get("stratum_code") or "N/D") == st]
            if len(sub) >= 3:
                by_stratum[st] = {
                    "n": len(sub),
                    "vw": compute_van_westendorp(sub),
                    "gg": compute_gabor_granger(sub),
                }

        return {
            "van_westendorp": vw_global,
            "gabor_granger": gg_global,
            "by_stratum": by_stratum,
        }
