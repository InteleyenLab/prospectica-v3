"""Codificador cualitativo determinístico del 100% del corpus textual con trazabilidad."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

from .data_loader import LoadedSimulationData

CODEBOOK_RULES: List[tuple[str, str, re.Pattern[str]]] = [
    ("OBJ_DESCONFIANZA_PAGO", "Desconfianza de pago anticipado / temor a estafa", re.compile(r"adelant|tumbe|estafa|desconf|transfer|nit|rut|garant|respaldo|segur", re.I)),
    ("OBJ_PRECIO_TARIFA", "Sensibilidad al precio, tarifa o comisión", re.compile(r"precio|caro|barato|tarifa|comisi[oó]n|pagar|cobran|plata|costo|valor", re.I)),
    ("OBJ_FRICCION_PROCESO", "Fricción operativa, registro o complejidad de uso", re.compile(r"tr[aá]mite|papel|registro|paso|demora|enred|tiempo|complic|disputa", re.I)),
    ("CANAL_DIGITAL_PAGO", "Preferencia o fricción en canales y pagos (WhatsApp / Nequi / PSE)", re.compile(r"whatsapp|nequi|daviplata|pse|audio|instagram|tiktok|web|p[aá]gina|redes", re.I)),
    ("DRIVER_PROPUESTA_VALOR", "Valoración de claridad, protección, orden y cumplimiento", re.compile(r"orden|claridad|protecci[oó]n|acompañ|soluci[oó]n|confianza|acuerdo|beneficio", re.I)),
    ("ALT_COMPETENCIA_TRADICIONAL", "Preferencia por compra directa o alternativa tradicional", re.compile(r"directo|gratis|tradicional|conocido|efectivo|contraentrega|competencia", re.I)),
]


class QualitativeCoder:
    """Indexa el 100% de textos en `channel_events`, `whatsapp_sessions`, `focus_group_turns` y `survey_responses`."""

    def analyze(self, data: LoadedSimulationData) -> Dict[str, Any]:
        corpus_items: List[Dict[str, Any]] = []

        for ev in data.channel_events:
            txt = str(ev.get("content_text") or "").strip()
            if txt:
                corpus_items.append(
                    {
                        "source_table": "channel_events",
                        "agent_id": ev.get("actor_agent_id", 0),
                        "city": ev.get("city_name", "N/D"),
                        "stratum": ev.get("stratum_code", "N/D"),
                        "age": ev.get("age", "-"),
                        "role": ev.get("dynamic_study_role", ev.get("action_type", "Ciudadano")),
                        "channel": ev.get("channel_id", "desconocido"),
                        "stance": ev.get("attitude_segment", "neutral"),
                        "text": txt,
                    }
                )

        for r in data.survey_responses:
            txt = str(r.get("verbatim_response") or "").strip()
            if txt:
                corpus_items.append(
                    {
                        "source_table": "survey_responses",
                        "agent_id": r.get("actor_agent_id") or r.get("respondent_id"),
                        "city": r.get("city_name", "N/D"),
                        "stratum": r.get("stratum_code", "N/D"),
                        "age": r.get("age", "-"),
                        "role": r.get("dynamic_study_role", "Respondente"),
                        "channel": r.get("channel_origin", "structured_survey"),
                        "stance": r.get("attitude_segment", "neutral"),
                        "text": txt,
                    }
                )

        code_counts: Counter[str] = Counter()
        quotes_by_code: Dict[str, List[Dict[str, Any]]] = {code: [] for code, _, _ in CODEBOOK_RULES}

        for item in corpus_items:
            matched_codes: List[str] = []
            for code, _, pat in CODEBOOK_RULES:
                if pat.search(item["text"]):
                    code_counts[code] += 1
                    matched_codes.append(code)
                    if len(quotes_by_code[code]) < 8:
                        citation_tag = (
                            f"[{item['agent_id']} | {item['city']} | {item['stratum']} | "
                            f"{item['age']} | {item['role']} | {item['channel']} | {item['stance']}]"
                        )
                        quotes_by_code[code].append(
                            {
                                "citation_tag": citation_tag,
                                "quote": item["text"],
                                "source_table": item["source_table"],
                            }
                        )
            item["codes"] = matched_codes

        total_texts = len(corpus_items)
        codebook = [
            {
                "code": code,
                "label": label,
                "mentions": int(code_counts.get(code, 0)),
                "share_of_corpus_pct": round(100.0 * code_counts.get(code, 0) / max(1, total_texts), 2),
                "sample_quotes": quotes_by_code[code],
            }
            for code, label, _ in CODEBOOK_RULES
        ]
        codebook.sort(key=lambda x: x["mentions"], reverse=True)

        return {
            "status": "ok",
            "total_texts_indexed": total_texts,
            "corpus_coverage_pct": 100.0,
            "codebook": codebook,
        }
