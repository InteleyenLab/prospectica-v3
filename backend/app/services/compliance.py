"""Módulo de cumplimiento legal, exclusiones, privacidad (Ley 1581) y lenguaje permitido (V-40, V-42, V-43)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config

# Categorías excluidas (§14.7)
EXCLUDED_CATEGORY_PATTERNS: List[Tuple[str, str, re.Pattern[str]]] = [
    (
        "electoral_politica",
        "Estudios electorales o de opinión política (excluidos por Ley 2494 de 2025 y política ética).",
        re.compile(r"\b(intenci[oó]n\s+de\s+voto|encuesta\s+electoral|candidato\s+presidencial|elecciones\s+presidenciales|partido\s+pol[ií]tico|tarjet[oó]n\s+electoral|alcald[ií]a\s+voto)\b", re.I),
    ),
    (
        "menores_de_edad",
        "Población objetivo compuesta por menores de edad (<18 años).",
        re.compile(r"\b(encuestar\s+(?:a\s+)?ni[nñ]os|menores\s+de\s+18|adolescentes\s+de\s+12|colegios\s+primaria\s+encuesta)\b", re.I),
    ),
    (
        "decision_individual_credito_empleo",
        "Decisiones individuales automatizadas sobre crédito, empleo o seguros.",
        re.compile(r"\b(scoring\s+crediticio\s+individual|aprobar\s+cr[eé]dito\s+a\s+persona|descartar\s+candidatos\s+de\s+empleo)\b", re.I),
    ),
    (
        "contenido_ilicito",
        "Contenido ilícito, armas o fraude.",
        re.compile(r"\b(lavado\s+de\s+activos|estafa\s+piramidal|venta\s+de\s+armas|suplantaci[oó]n\s+de\s+identidad)\b", re.I),
    ),
]

# Lenguaje prohibido en informes sintéticos (§14.6 / V-40)
FORBIDDEN_LANGUAGE_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("esomar_iso_compliance_claim", re.compile(r"ficha\s+t[eé]cnica\s+esomar\s*/\s*iso\s*20252|rigor\s+esomar\s*/\s*iso\s*20252|cumple\s+iso\s*20252", re.I)),
    ("margin_of_error_claim", re.compile(r"margen\s+de\s+error\s*[±+\-]\s*\d", re.I)),
    ("national_representativeness_claim", re.compile(r"representativ[oa]\s+(?:a\s+nivel\s+)?nacional\s+de\s+colombia", re.I)),
    ("guaranteed_results_claim", re.compile(r"resultados?\s+garantizados?|100%\s+precis[oa]s?|predice\s+con\s+precisi[oó]n\s+la\s+demanda", re.I)),
    ("replaces_survey_claim", re.compile(r"reemplaza\s+(?:a\s+)?una\s+encuesta\s+real", re.I)),
]

# Patrones PII (§14.4 / V-43)
PII_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("telefono_co", re.compile(r"\b(?:\+?57\s*)?3\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b")),
    ("cedula_explicita", re.compile(r"\b(?:c\.?c\.?|c[eé]dula)\s*(?:no\.?|n[uú]mero|#|:)?\s*\d{6,10}\b", re.I)),
]

SYNTHETIC_DISCLOSURE_NOTICE = (
    "Este documento es el resultado de una simulación con agentes sintéticos calibrados con fuentes públicas. "
    "No es una encuesta a personas reales ni permite inferencias estadísticas sobre la población. "
    "Sirve para generar hipótesis, priorizar riesgos y diseñar una validación real. "
    "Las decisiones de inversión o lanzamiento deben apoyarse además en evidencia obtenida de personas reales."
)


def check_exclusions(text: str) -> Dict[str, Any]:
    """Evalúa si el proyecto o texto cae en categorías excluidas (§14.7 / V-42)."""
    matches: List[Dict[str, str]] = []
    for code, reason, pat in EXCLUDED_CATEGORY_PATTERNS:
        if pat.search(text or ""):
            matches.append({"code": code, "reason": reason})
    return {"allowed": len(matches) == 0, "excluded_matches": matches}


def scan_forbidden_claims(text: str) -> List[Dict[str, str]]:
    """Detecta lenguaje comercial o metodológico prohibido en informes sintéticos (§14.6 / V-40)."""
    hits: List[Dict[str, str]] = []
    for code, pat in FORBIDDEN_LANGUAGE_PATTERNS:
        for m in pat.finditer(text or ""):
            hits.append({"code": code, "excerpt": m.group(0)})
    return hits


def scan_pii(text: str) -> List[Dict[str, str]]:
    """Escanea posibles datos personales identificables (V-43)."""
    hits: List[Dict[str, str]] = []
    for kind, pat in PII_PATTERNS:
        for m in pat.finditer(text or ""):
            hits.append({"type": kind, "match": m.group(0)[:6] + "***"})
    return hits


def redact_pii(text: str) -> str:
    """Redacta correos, teléfonos móviles y cédulas antes de enviar a proveedores LLM (§13.6)."""
    cleaned = text or ""
    for kind, pat in PII_PATTERNS:
        cleaned = pat.sub(f"[REDACTADO_{kind.upper()}]", cleaned)
    return cleaned


def record_consent(
    project_id: str,
    accepted_privacy: bool,
    accepted_synthetic_nature: bool,
    no_unnecessary_pii: bool,
    actor_name: str = "cliente",
    project_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Registra trazabilidad de consentimientos del brief (Anexo A22 / §14.3)."""
    pdir = project_dir or (Path(Config.UPLOAD_FOLDER) / "projects" / project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    record = {
        "project_id": project_id,
        "accepted_privacy": bool(accepted_privacy),
        "accepted_synthetic_nature": bool(accepted_synthetic_nature),
        "no_unnecessary_pii": bool(no_unnecessary_pii),
        "actor_name": actor_name,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "privacy_notice_version": "v3.0-col",
    }
    (pdir / "compliance_consent.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record
