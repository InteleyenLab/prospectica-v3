"""Conector Socrata (datos.gov.co) con normalización colombiana y respaldo local."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from ...registry import get_country_pack


def normalize_divipola(value: Any) -> str:
    """Normaliza un código DIVIPOLA municipal colombiano a 5 dígitos (`'5001'` -> `'05001'`)."""
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if len(digits) <= 5:
        return digits.zfill(5)
    return digits[:5]


def parse_colombian_number(value: Any) -> Optional[float]:
    """Convierte formatos numéricos colombianos (`'6,246631'`, `'1.750.905,50'`) a `float`."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace("COP", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            # Formato es-CO: miles con punto, decimales con coma ("1.750.905,50")
            text = text.replace(".", "").replace(",", ".")
        else:
            # Formato en-US: miles con coma, decimales con punto ("1,750,905.50")
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            text = text.replace(",", ".")
        elif len(parts) == 2 and len(parts[0]) <= 3 and len(parts[1]) == 3:
            # Casos como coordenadas truncadas o miles; si tiene más de 1 dígito o signo, tratar con cuidado
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def is_dataset_stale(
    observed_at_iso: Optional[str],
    max_staleness_days: int = 180,
    reference_now: Optional[datetime] = None,
) -> bool:
    """Evalúa si la fecha observada excede el límite de vigencia configurado."""
    if not observed_at_iso:
        return True
    cleaned = str(observed_at_iso).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m"):
            try:
                dt = datetime.strptime(cleaned[:10], fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = reference_now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - dt).days > max_staleness_days


class SocrataColombiaConnector:
    """Cliente resiliente para datasets Socrata de `datos.gov.co` con fallback al CountryPack CO."""

    BASE_URL = "https://www.datos.gov.co/resource"

    def __init__(self, timeout_seconds: float = 12.0, app_token: Optional[str] = None):
        self.timeout_seconds = timeout_seconds
        self.app_token = app_token

    def fetch_dataset(
        self,
        dataset_id: str,
        params: Optional[Dict[str, Any]] = None,
        limit: int = 25,
    ) -> Dict[str, Any]:
        """Consulta un recurso Socrata devolviendo `{ok, dataset_id, rows, error}` sin lanzar excepciones."""
        query = dict(params or {})
        query.setdefault("$limit", limit)
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        url = f"{self.BASE_URL}/{dataset_id}.json"
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                resp = client.get(url, params=query, headers=headers)
                resp.raise_for_status()
                rows = resp.json()
                return {
                    "ok": True,
                    "dataset_id": dataset_id,
                    "url": url,
                    "rows": rows if isinstance(rows, list) else [],
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "error": None,
                }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "dataset_id": dataset_id,
                "url": url,
                "rows": [],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }

    def fetch_trm(self) -> Dict[str, Any]:
        """Obtiene la TRM más reciente (Socrata `32sa-8pi3`) con fallback informativo si falla red."""
        res = self.fetch_dataset("32sa-8pi3", params={"$order": "vigenciadesde DESC"}, limit=1)
        if res["ok"] and res["rows"]:
            row = res["rows"][0]
            val = parse_colombian_number(row.get("valor"))
            obs = row.get("vigenciadesde") or row.get("vigenciahasta")
            return {
                "metric_key": "trm_cop_usd",
                "value": val,
                "unit": "COP/USD",
                "observed_at": obs,
                "is_stale": is_dataset_stale(obs, max_staleness_days=14),
                "source_authority": "Superintendencia Financiera (datos.gov.co:32sa-8pi3)",
                "source_tier": "A",
                "fallback_used": False,
                "error": None,
            }
        return {
            "metric_key": "trm_cop_usd",
            "value": None,
            "unit": "COP/USD",
            "observed_at": None,
            "is_stale": True,
            "source_authority": "Superintendencia Financiera (datos.gov.co:32sa-8pi3)",
            "source_tier": "A",
            "fallback_used": True,
            "error": res.get("error") or "Sin respuesta de datos.gov.co",
        }

    def fetch_city_indicators(self, city_query: str) -> Dict[str, Any]:
        """Combina el paquete local verificado con consultas vivas opcionales para la ciudad."""
        pack = get_country_pack("co")
        local_city = pack.get_city_by_name_or_code(city_query)
        live_rows: List[Dict[str, Any]] = []
        live_error: Optional[str] = None

        if local_city is not None:
            mintic = self.fetch_dataset(
                "tvzi-ba2g",
                params={"$where": f"cod_municipio='{int(local_city.divipola_code)}' OR cod_municipio='{local_city.divipola_code}'"},
                limit=3,
            )
            if mintic["ok"]:
                live_rows = mintic["rows"]
            else:
                live_error = mintic["error"]

        return {
            "city": local_city.model_dump() if local_city else None,
            "live_mintic_rows": live_rows,
            "live_available": bool(live_rows),
            "fallback_used": not bool(live_rows),
            "error": live_error,
        }

    def fetch_sector_signals(self, topic_keywords: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Consulta señales vivas complementarias (quejas Superfinanciera `qzsc-9esp`, ANSV `6jmc-vaxk`, RUNT `kgyi-qc7j`)."""
        keywords_lower = " ".join(topic_keywords or []).lower()
        targets: List[tuple[str, str, int, str]] = []
        if any(k in keywords_lower for k in ("seguro", "reclam", "póliza", "poliza", "siniestro", "responsabilidad")):
            targets.append(("quejas_superfinanciera", "qzsc-9esp", 180, "Superfinanciera"))
        if any(k in keywords_lower for k in ("moto", "veh", "transito", "tránsito", "accidente", "vial", "siniestro")):
            targets.append(("siniestros_ansv", "6jmc-vaxk", 365, "ANSV / Medicina Legal"))
            targets.append(("parque_automotor_runt", "kgyi-qc7j", 365, "RUNT / MinTransporte"))
        if not targets:
            targets.append(("quejas_superfinanciera", "qzsc-9esp", 180, "Superfinanciera"))

        signals: List[Dict[str, Any]] = []
        for metric_key, ds_id, staleness, authority in targets:
            res = self.fetch_dataset(ds_id, limit=5)
            signals.append(
                {
                    "metric_key": metric_key,
                    "dataset_id": ds_id,
                    "authority": authority,
                    "source_tier": "A",
                    "rows_count": len(res["rows"]),
                    "sample_rows": res["rows"][:2],
                    "live_available": res["ok"],
                    "max_staleness_days": staleness,
                    "error": res["error"],
                }
            )
        return signals
