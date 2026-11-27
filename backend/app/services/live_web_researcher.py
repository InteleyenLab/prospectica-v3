"""Investigador web en vivo opcional (Fuente B complementaria) con tolerancia a fallos."""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..utils.logger import get_logger

logger = get_logger("mirofish.live_web_researcher")


class LiveWebResearcher:
    """Consulta señales públicas recientes en la web y devuelve evidencia citable o vacío explícito."""

    DDG_HTML_URL = "https://html.duckduckgo.com/html/"

    def __init__(self, timeout_seconds: float = 8.0, rate_limit_seconds: float = 0.5):
        self.timeout_seconds = timeout_seconds
        self.rate_limit_seconds = max(0.0, float(rate_limit_seconds))

    @staticmethod
    def check_robots_allowed(url: str, user_agent: str = "ProspecticaResearchBot") -> bool:
        """Verifica respeto básico de robots.txt sin bloquear por fallos de red."""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return True
            rp = RobotFileParser()
            rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
            rp.read()
            return bool(rp.can_fetch(user_agent, url))
        except Exception:
            return True

    def build_queries(
        self,
        simulation_requirement: str,
        country_name: str = "Colombia",
        target_cities: Optional[List[str]] = None,
    ) -> List[str]:
        """Genera hasta 3 consultas enfocadas en estadística sectorial y competencia local."""
        clean_req = re.sub(r"\s+", " ", (simulation_requirement or "").strip())
        snippet = clean_req[:90] if clean_req else "mercado consumo servicios"
        city_hint = f" {target_cities[0]}" if target_cities else ""
        queries = [
            f"{country_name}{city_hint} estadisticas {snippet}",
            f"{country_name} DANE estudio mercado {snippet[:60]}",
        ]
        # De-duplicar manteniendo orden
        seen = set()
        unique: List[str] = []
        for q in queries:
            norm = q.strip()
            if norm and norm.lower() not in seen:
                seen.add(norm.lower())
                unique.append(norm)
        return unique[:2]

    def search_query(self, query: str, max_results: int = 4) -> Dict[str, Any]:
        """Ejecuta una búsqueda ligera en DuckDuckGo HTML sin lanzar excepciones ante bloqueo/red."""
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            url = f"{self.DDG_HTML_URL}?q={quote_plus(query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ProspecticaResearchBot/1.0",
                "Accept-Language": "es-CO,es;q=0.9",
            }
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                body = resp.text

            results = self._parse_ddg_html(body, max_results=max_results)
            return {
                "ok": True,
                "query": query,
                "results": results,
                "fetched_at": now_iso,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.info(f"Búsqueda web en vivo no disponible para '{query}': {exc}")
            return {
                "ok": False,
                "query": query,
                "results": [],
                "fetched_at": now_iso,
                "error": str(exc),
            }

    @staticmethod
    def _parse_ddg_html(raw_html: str, max_results: int = 4) -> List[Dict[str, str]]:
        """Extrae títulos, enlaces y extractos de HTML sin dependencias pesadas obligatorias."""
        results: List[Dict[str, str]] = []
        title_pattern = re.compile(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div)>',
            re.IGNORECASE | re.DOTALL,
        )
        titles = title_pattern.findall(raw_html or "")
        snippets = snippet_pattern.findall(raw_html or "")
        for idx, (href, raw_title) in enumerate(titles[:max_results]):
            clean_title = re.sub(r"<[^>]+>", "", html.unescape(raw_title)).strip()
            clean_snippet = ""
            if idx < len(snippets):
                clean_snippet = re.sub(r"<[^>]+>", "", html.unescape(snippets[idx])).strip()
            if clean_title:
                results.append(
                    {
                        "title": clean_title,
                        "url": html.unescape(href),
                        "snippet": clean_snippet,
                        "source_tier": "C_WEB",
                    }
                )
        return results

    def research(
        self,
        simulation_requirement: str,
        country_name: str = "Colombia",
        target_cities: Optional[List[str]] = None,
        evidence_ledger: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Ejecuta la ronda completa de búsqueda web en vivo y registra en EvidenceLedger."""
        queries = self.build_queries(
            simulation_requirement=simulation_requirement,
            country_name=country_name,
            target_cities=target_cities,
        )
        findings: List[Dict[str, str]] = []
        errors: List[str] = []
        for idx, q in enumerate(queries):
            if idx > 0 and self.rate_limit_seconds > 0:
                time.sleep(min(self.rate_limit_seconds, 0.25))
            res = self.search_query(q)
            if res["ok"]:
                findings.extend(res["results"])
            elif res.get("error"):
                errors.append(f"{q}: {res['error']}")

        if evidence_ledger is not None:
            for idx, item in enumerate(findings[:6], start=1):
                evidence_ledger.record(
                    source_id=f"WEB-{idx:02d}",
                    institution=item.get("title", "Fuente Web"),
                    url=item.get("url", ""),
                    year=datetime.now(timezone.utc).year,
                    claim=item.get("snippet", ""),
                    tier="C_WEB",
                )

        return {
            "queries": queries,
            "findings": findings[:6],
            "errors": errors,
            "live_web_available": len(findings) > 0,
        }
