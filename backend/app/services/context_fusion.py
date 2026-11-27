"""Servicio de fusión contextual (Fuente A pack país + Fuente B APIs/Web + Fuente C usuario) y almacén quant_store.sqlite."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from country_packs import get_country_pack
from country_packs.base_contracts import CityRecord, CountryPack
from country_packs.co.connectors import SocrataColombiaConnector
from .live_web_researcher import LiveWebResearcher
from ..utils.logger import get_logger

logger = get_logger("mirofish.context_fusion")


class ContextFusionService:
    """Orquesta la ingesta cuantitativa territorial, resuelve precedencia y persiste `quant_store.sqlite`."""

    def __init__(
        self,
        socrata_connector: Optional[SocrataColombiaConnector] = None,
        web_researcher: Optional[LiveWebResearcher] = None,
    ):
        self.socrata_connector = socrata_connector or SocrataColombiaConnector()
        self.web_researcher = web_researcher or LiveWebResearcher()

    def build_and_persist(
        self,
        project_id: str,
        project_dir: Path,
        country_code: str = "co",
        target_cities: Optional[List[str]] = None,
        target_strata: Optional[List[str]] = None,
        simulation_requirement: str = "",
        document_texts: Optional[List[str]] = None,
        use_official_sources: bool = True,
        use_live_web: bool = False,
    ) -> Dict[str, Any]:
        """Fusiona las tres fuentes y crea `quant_store.sqlite` en el proyecto."""
        pack = get_country_pack(country_code or "co")
        selected_cities = self._resolve_cities(pack, target_cities)
        selected_strata = self._resolve_strata(pack, target_strata)

        indicators: List[Dict[str, Any]] = []
        citations: List[Dict[str, Any]] = []
        data_gaps: List[Dict[str, str]] = []
        conflicts: List[Dict[str, Any]] = []

        # 1. Fuente A (CountryPack verificado local)
        indicators.append(
            {
                "metric_key": "smmlv_local",
                "category": "macroeconomia",
                "scope": pack.country_code.upper(),
                "value_num": pack.min_wage_local,
                "value_text": f"{pack.currency} {int(pack.min_wage_local):,}",
                "unit": pack.currency,
                "source_authority": pack.min_wage_source or "Oficial",
                "source_tier": "A",
                "observed_at": "2026-01-01",
                "is_stale": False,
                "precedence_rule": "Fuente Oficial > Documento usuario para marco macro",
            }
        )
        if pack.transport_aid_local > 0:
            indicators.append(
                {
                    "metric_key": "auxilio_transporte_local",
                    "category": "macroeconomia",
                    "scope": pack.country_code.upper(),
                    "value_num": pack.transport_aid_local,
                    "value_text": f"{pack.currency} {int(pack.transport_aid_local):,}",
                    "unit": pack.currency,
                    "source_authority": pack.min_wage_source or "Oficial",
                    "source_tier": "A",
                    "observed_at": "2026-01-01",
                    "is_stale": False,
                    "precedence_rule": "Fuente Oficial > Documento usuario para marco macro",
                }
            )

        for city in selected_cities:
            indicators.append(
                {
                    "metric_key": "city_population",
                    "category": "demografia",
                    "scope": f"{city.city_name} ({city.divipola_code})",
                    "value_num": float(city.population_2026 or 0),
                    "value_text": f"{city.population_2026:,} hab." if city.population_2026 else "N/D",
                    "unit": "habitantes",
                    "source_authority": city.source_citation,
                    "source_tier": "A",
                    "observed_at": "2026-Q2",
                    "is_stale": False,
                    "precedence_rule": "Fuente Oficial > Documento usuario",
                }
            )
            indicators.append(
                {
                    "metric_key": "city_fixed_internet_penetration_pct",
                    "category": "conectividad",
                    "scope": f"{city.city_name} ({city.divipola_code})",
                    "value_num": city.fixed_internet_penetration_pct,
                    "value_text": f"{city.fixed_internet_penetration_pct}%" if city.fixed_internet_penetration_pct is not None else "N/D",
                    "unit": "%",
                    "source_authority": city.source_citation,
                    "source_tier": "A",
                    "observed_at": "2026-Q2",
                    "is_stale": False,
                    "precedence_rule": "Fuente Oficial > Documento usuario",
                }
            )
            citations.append(
                {
                    "source_id": f"city_{city.divipola_code}",
                    "title": f"{city.city_name} - {city.source_citation}",
                    "tier": "A",
                    "url": "https://www.datos.gov.co/resource/tvzi-ba2g.json",
                }
            )

        # 2. Fuente B1 (Conectores oficiales en vivo, solo si país activo es Colombia y toggle activo)
        if use_official_sources and pack.country_code == "co":
            trm = self.socrata_connector.fetch_trm()
            if trm.get("value") is not None:
                indicators.append(
                    {
                        "metric_key": "trm_cop_usd",
                        "category": "macroeconomia",
                        "scope": "CO",
                        "value_num": trm["value"],
                        "value_text": f"COP {trm['value']:,.2f}",
                        "unit": "COP/USD",
                        "source_authority": trm["source_authority"],
                        "source_tier": "A",
                        "observed_at": str(trm.get("observed_at") or ""),
                        "is_stale": bool(trm.get("is_stale")),
                        "precedence_rule": "Fuente Oficial > Documento usuario",
                    }
                )
            else:
                data_gaps.append(
                    {
                        "metric_key": "trm_cop_usd",
                        "reason": f"No se pudo consultar TRM en vivo ({trm.get('error')}); no se inventa tasa.",
                    }
                )

            keywords = [simulation_requirement] + (document_texts or [])[:1]
            for sig in self.socrata_connector.fetch_sector_signals(keywords):
                if sig.get("live_available"):
                    indicators.append(
                        {
                            "metric_key": sig["metric_key"],
                            "category": "sectorial",
                            "scope": "CO",
                            "value_num": float(sig.get("rows_count", 0)),
                            "value_text": f"Dataset {sig['dataset_id']} ({sig.get('rows_count', 0)} registros consultados)",
                            "unit": "registros_muestra",
                            "source_authority": f"{sig['authority']} (datos.gov.co:{sig['dataset_id']})",
                            "source_tier": sig.get("source_tier", "A"),
                            "observed_at": datetime.now(timezone.utc).date().isoformat(),
                            "is_stale": False,
                            "precedence_rule": "Fuente Oficial > Estimación web",
                        }
                    )
                else:
                    data_gaps.append(
                        {
                            "metric_key": sig["metric_key"],
                            "reason": f"Dataset {sig['dataset_id']} sin respuesta en vivo ({sig.get('error')}).",
                        }
                    )

        # 3. Fuente B2 (Investigación web en vivo opcional)
        web_findings: List[Dict[str, str]] = []
        if use_live_web:
            city_names = [c.city_name for c in selected_cities]
            web_res = self.web_researcher.research(
                simulation_requirement=simulation_requirement,
                country_name=pack.country_name,
                target_cities=city_names,
            )
            web_findings = web_res.get("findings", [])
            for idx, item in enumerate(web_findings):
                citations.append(
                    {
                        "source_id": f"web_{idx+1}",
                        "title": item.get("title", ""),
                        "tier": "C_WEB",
                        "url": item.get("url", ""),
                    }
                )
            for err in web_res.get("errors", []):
                data_gaps.append({"metric_key": "live_web_search", "reason": err})

        # 4. Fuente C (Documentos propios del usuario) + Detección de precedencia dual
        study_claims = self._extract_user_study_claims(document_texts or [], simulation_requirement, pack)
        conflicts.extend(study_claims["macro_conflicts"])
        for prop_claim in study_claims["product_hypotheses"]:
            indicators.append(prop_claim)

        # 5. Persistir en quant_store.sqlite
        project_dir.mkdir(parents=True, exist_ok=True)
        db_path = project_dir / "quant_store.sqlite"
        self._write_sqlite(
            db_path=db_path,
            project_id=project_id,
            pack=pack,
            selected_cities=selected_cities,
            selected_strata=selected_strata,
            indicators=indicators,
            citations=citations,
            data_gaps=data_gaps,
            conflicts=conflicts,
            web_findings=web_findings,
        )

        context_brief = self._build_context_brief(
            pack=pack,
            selected_cities=selected_cities,
            selected_strata=selected_strata,
            indicators=indicators,
            web_findings=web_findings,
            conflicts=conflicts,
            data_gaps=data_gaps,
        )

        return {
            "quant_store_path": str(db_path),
            "country_code": pack.country_code,
            "selected_cities": [c.city_name for c in selected_cities],
            "selected_strata": selected_strata,
            "indicators_count": len(indicators),
            "citations_count": len(citations),
            "data_gaps": data_gaps,
            "conflicts": conflicts,
            "context_brief": context_brief,
        }

    @staticmethod
    def _resolve_cities(pack: CountryPack, target_cities: Optional[List[str]]) -> List[CityRecord]:
        if not target_cities:
            return pack.cities[:5]
        matched: List[CityRecord] = []
        for q in target_cities:
            city = pack.get_city_by_name_or_code(q)
            if city and city not in matched:
                matched.append(city)
        return matched or pack.cities[:5]

    @staticmethod
    def _resolve_strata(pack: CountryPack, target_strata: Optional[List[str]]) -> List[str]:
        valid_codes = {s.code.upper(): s.code for s in pack.strata}
        if not target_strata:
            return [s.code for s in pack.strata]
        resolved: List[str] = []
        for s in target_strata:
            norm = str(s or "").strip().upper()
            if norm in valid_codes:
                resolved.append(valid_codes[norm])
            elif norm.isdigit() and f"E{norm}" in valid_codes:
                resolved.append(valid_codes[f"E{norm}"])
        return resolved or [s.code for s in pack.strata]

    @staticmethod
    def _extract_user_study_claims(
        document_texts: List[str],
        simulation_requirement: str,
        pack: CountryPack,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Aplica regla dual: detecta choques macro y preserva hipótesis propias del producto."""
        combined = "\n".join([simulation_requirement] + document_texts)
        macro_conflicts: List[Dict[str, Any]] = []
        product_hypotheses: List[Dict[str, Any]] = []

        # Detectar mención de SMMLV / salario mínimo en el texto del usuario y comparar contra pack oficial
        smmlv_match = re.search(
            r"(?:SMMLV|salario\s+m[ií]nimo)[^\d]{0,25}(?:\$|COP)?\s*([\d.,]{6,12})",
            combined,
            re.IGNORECASE,
        )
        if smmlv_match:
            raw_num = smmlv_match.group(1).replace(".", "").replace(",", "")
            if raw_num.isdigit():
                user_val = float(raw_num)
                if abs(user_val - pack.min_wage_local) > 1000:
                    macro_conflicts.append(
                        {
                            "metric_key": "smmlv_local",
                            "official_value": pack.min_wage_local,
                            "user_doc_value": user_val,
                            "resolution": "Prevalece fuente oficial (pack país) para marco macro; se conserva cifra usuario solo como referencia documental.",
                        }
                    )

        # Detectar precios propios del servicio o estudio (regla: documento usuario > externo)
        price_matches = re.findall(
            r"(?:precio|tarifa|ticket|honorario|servicio\s+[a-z])[^\d]{0,30}(?:COP|\$)\s*([\d.,]{4,12})",
            combined,
            re.IGNORECASE,
        )
        for idx, raw_p in enumerate(price_matches[:4]):
            digits = raw_p.replace(".", "").replace(",", "")
            if digits.isdigit():
                product_hypotheses.append(
                    {
                        "metric_key": f"user_study_price_{idx+1}",
                        "category": "producto_estudio",
                        "scope": "DOCUMENTO_USUARIO",
                        "value_num": float(digits),
                        "value_text": f"{pack.currency} {int(digits):,} (hipótesis usuario)",
                        "unit": pack.currency,
                        "source_authority": "Documento del usuario (Fuente C)",
                        "source_tier": "USER_STUDY",
                        "observed_at": datetime.now(timezone.utc).date().isoformat(),
                        "is_stale": False,
                        "precedence_rule": "Documento usuario > Externo (atributo propio del producto)",
                    }
                )

        return {"macro_conflicts": macro_conflicts, "product_hypotheses": product_hypotheses}

    @staticmethod
    def _write_sqlite(
        db_path: Path,
        project_id: str,
        pack: CountryPack,
        selected_cities: List[CityRecord],
        selected_strata: List[str],
        indicators: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        data_gaps: List[Dict[str, str]],
        conflicts: List[Dict[str, Any]],
        web_findings: List[Dict[str, str]],
    ) -> None:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS project_context_meta (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quant_indicators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    value_num REAL,
                    value_text TEXT,
                    unit TEXT,
                    source_authority TEXT,
                    source_tier TEXT,
                    observed_at TEXT,
                    is_stale INTEGER DEFAULT 0,
                    precedence_rule TEXT
                );
                CREATE TABLE IF NOT EXISTS source_citations (
                    source_id TEXT PRIMARY KEY,
                    title TEXT,
                    tier TEXT,
                    url TEXT
                );
                CREATE TABLE IF NOT EXISTS data_gaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_key TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                DELETE FROM quant_indicators;
                DELETE FROM source_citations;
                DELETE FROM data_gaps;
                """
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            meta_payload = {
                "project_id": project_id,
                "country_code": pack.country_code,
                "country_name": pack.country_name,
                "currency": pack.currency,
                "selected_cities": [c.divipola_code for c in selected_cities],
                "selected_strata": selected_strata,
                "conflicts": conflicts,
                "web_findings_count": len(web_findings),
            }
            cur.execute(
                "INSERT OR REPLACE INTO project_context_meta (key, value_json, updated_at) VALUES (?, ?, ?)",
                ("context_summary", json.dumps(meta_payload, ensure_ascii=False), now_iso),
            )
            for ind in indicators:
                cur.execute(
                    """
                    INSERT INTO quant_indicators
                    (metric_key, category, scope, value_num, value_text, unit, source_authority, source_tier, observed_at, is_stale, precedence_rule)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ind["metric_key"],
                        ind["category"],
                        ind["scope"],
                        ind.get("value_num"),
                        ind.get("value_text"),
                        ind.get("unit"),
                        ind.get("source_authority"),
                        ind.get("source_tier"),
                        ind.get("observed_at"),
                        1 if ind.get("is_stale") else 0,
                        ind.get("precedence_rule"),
                    ),
                )
            for cit in citations:
                cur.execute(
                    "INSERT OR REPLACE INTO source_citations (source_id, title, tier, url) VALUES (?, ?, ?, ?)",
                    (cit["source_id"], cit["title"], cit["tier"], cit["url"]),
                )
            for gap in data_gaps:
                cur.execute(
                    "INSERT INTO data_gaps (metric_key, reason) VALUES (?, ?)",
                    (gap["metric_key"], gap["reason"]),
                )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _build_context_brief(
        pack: CountryPack,
        selected_cities: List[CityRecord],
        selected_strata: List[str],
        indicators: List[Dict[str, Any]],
        web_findings: List[Dict[str, str]],
        conflicts: List[Dict[str, Any]],
        data_gaps: List[Dict[str, str]],
    ) -> str:
        lines = [pack.render_prompt_context([c.divipola_code for c in selected_cities])]
        lines.append(f"Estratos objetivo seleccionados: {', '.join(selected_strata)}")

        live_trm = [i for i in indicators if i["metric_key"] == "trm_cop_usd"]
        if live_trm:
            lines.append(f"TRM oficial vigente: {live_trm[0]['value_text']} ({live_trm[0]['source_authority']})")

        if web_findings:
            lines.append("Hallazgos web en vivo:")
            for item in web_findings[:3]:
                lines.append(f"- {item['title']}: {item.get('snippet', '')[:120]}")

        if conflicts:
            lines.append("Regla dual aplicada ante discrepancias:")
            for c in conflicts:
                lines.append(
                    f"- {c['metric_key']}: oficial={c['official_value']} vs doc={c['user_doc_value']} -> {c['resolution']}"
                )

        if data_gaps:
            lines.append("Vacíos de datos registrados (no fabricar cifras):")
            for g in data_gaps[:3]:
                lines.append(f"- {g['metric_key']}: {g['reason']}")

        return "\n".join(lines)
