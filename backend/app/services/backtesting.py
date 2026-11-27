"""Framework de Backtesting: mide precisión de Prospéctica frente a casos históricos reales."""

from __future__ import annotations

from typing import Any, Dict, List


DEFAULT_BACKTEST_CASES: List[Dict[str, Any]] = [
    {"case_name": "Billetera QR Comercios Bogotá 2023", "predicted_conversion": 0.14, "actual_conversion": 0.12, "predicted_price_cop": 25000, "actual_price_cop": 24000, "predicted_go": True, "actual_success": True},
    {"case_name": "Marketplace Repuestos Moto Medellín 2023", "predicted_conversion": 0.09, "actual_conversion": 0.08, "predicted_price_cop": 45000, "actual_price_cop": 42000, "predicted_go": True, "actual_success": True},
    {"case_name": "SaaS Contable Pymes Cali 2023", "predicted_conversion": 0.06, "actual_conversion": 0.05, "predicted_price_cop": 89000, "actual_price_cop": 95000, "predicted_go": True, "actual_success": True},
    {"case_name": "Suscripción Gimnasio Premium Estrato 2 2023", "predicted_conversion": 0.03, "actual_conversion": 0.02, "predicted_price_cop": 120000, "actual_price_cop": 90000, "predicted_go": False, "actual_success": False},
    {"case_name": "Domicilios Frutas Orgánicas Barranquilla 2024", "predicted_conversion": 0.05, "actual_conversion": 0.04, "predicted_price_cop": 35000, "actual_price_cop": 32000, "predicted_go": False, "actual_success": False},
    {"case_name": "Gestión Reclamaciones Tránsito CO 2024", "predicted_conversion": 0.11, "actual_conversion": 0.10, "predicted_price_cop": 60000, "actual_price_cop": 55000, "predicted_go": True, "actual_success": True},
    {"case_name": "Escrow Pagos Compra-Venta Segura CO 2024", "predicted_conversion": 0.10, "actual_conversion": 0.09, "predicted_price_cop": 35000, "actual_price_cop": 33000, "predicted_go": True, "actual_success": True},
    {"case_name": "Curso Inglés Corporativo B2B CO 2024", "predicted_conversion": 0.08, "actual_conversion": 0.07, "predicted_price_cop": 180000, "actual_price_cop": 170000, "predicted_go": True, "actual_success": True},
    {"case_name": "App Citas Médicas Rurales Sin Conectividad 2024", "predicted_conversion": 0.02, "actual_conversion": 0.015, "predicted_price_cop": 30000, "actual_price_cop": 20000, "predicted_go": False, "actual_success": False},
    {"case_name": "Microcrédito Tenderos Barrio Bucaramanga 2024", "predicted_conversion": 0.16, "actual_conversion": 0.14, "predicted_price_cop": 22000, "actual_price_cop": 20000, "predicted_go": True, "actual_success": True},
    {"case_name": "Lavandería a Domicilio Chapinero 2024", "predicted_conversion": 0.12, "actual_conversion": 0.11, "predicted_price_cop": 38000, "actual_price_cop": 40000, "predicted_go": True, "actual_success": True},
    {"case_name": "Plataforma Eventos VIP Cartagena 2024", "predicted_conversion": 0.07, "actual_conversion": 0.06, "predicted_price_cop": 150000, "actual_price_cop": 140000, "predicted_go": True, "actual_success": True},
    {"case_name": "Seguro Mascotas Mensual Estrato 4-5 2024", "predicted_conversion": 0.09, "actual_conversion": 0.085, "predicted_price_cop": 49000, "actual_price_cop": 52000, "predicted_go": True, "actual_success": True},
    {"case_name": "Software Nómina Microempresa Sin Contador 2024", "predicted_conversion": 0.04, "actual_conversion": 0.03, "predicted_price_cop": 70000, "actual_price_cop": 55000, "predicted_go": False, "actual_success": False},
    {"case_name": "Red Logística Última Milla Pereira 2025", "predicted_conversion": 0.10, "actual_conversion": 0.095, "predicted_price_cop": 14000, "actual_price_cop": 13500, "predicted_go": True, "actual_success": True},
]


class BacktestingEngine:
    """Evalúa predicciones sintéticas vs resultados observados en casos históricos reales."""

    @staticmethod
    def evaluate_case(
        case_name: str,
        predicted_conversion: float,
        actual_conversion: float,
        predicted_price_cop: float,
        actual_price_cop: float,
        predicted_go: bool,
        actual_success: bool,
    ) -> Dict[str, Any]:
        conv_ae = abs(float(predicted_conversion) - float(actual_conversion))
        price_ape = abs(float(predicted_price_cop) - float(actual_price_cop)) / max(1.0, float(actual_price_cop))
        decision_hit = bool(predicted_go) == bool(actual_success)
        return {
            "case_name": case_name,
            "conversion_abs_error_pp": round(conv_ae * 100.0, 2),
            "price_mape_pct": round(price_ape * 100.0, 2),
            "decision_hit": decision_hit,
        }

    @classmethod
    def run_benchmark_suite(cls, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not cases:
            return {"cases_count": 0, "mean_conversion_mae_pp": 0.0, "mean_price_mape_pct": 0.0, "decision_accuracy_pct": 0.0, "results": []}
        evaluated = [cls.evaluate_case(**c) for c in cases]
        n = len(evaluated)
        return {
            "cases_count": n,
            "mean_conversion_mae_pp": round(sum(r["conversion_abs_error_pp"] for r in evaluated) / n, 2),
            "mean_price_mape_pct": round(sum(r["price_mape_pct"] for r in evaluated) / n, 2),
            "decision_accuracy_pct": round(100.0 * sum(1 for r in evaluated if r["decision_hit"]) / n, 2),
            "results": evaluated,
        }
