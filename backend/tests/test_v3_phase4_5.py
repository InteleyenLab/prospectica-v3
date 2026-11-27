"""Pruebas de Fase 4 y Fase 5 (≥40 anclas Colombia, Dashboard Backtesting 15 casos y UI V3)."""

from __future__ import annotations

from app import create_app
from app.services.backtesting import DEFAULT_BACKTEST_CASES, BacktestingEngine
from app.services.calibration import COLOMBIA_ANCHORS


def test_p5_40_colombia_anchors_and_backtesting_dashboard():
    assert len(COLOMBIA_ANCHORS) >= 40
    assert len(DEFAULT_BACKTEST_CASES) >= 15

    dash = BacktestingEngine.run_benchmark_suite(DEFAULT_BACKTEST_CASES)
    assert dash["cases_count"] == 15
    assert dash["decision_accuracy_pct"] == 100.0
    assert dash["mean_conversion_mae_pp"] <= 5.0

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/api/backtesting/dashboard")
    assert r.status_code == 200
    assert r.get_json()["data"]["cases_count"] == 15
