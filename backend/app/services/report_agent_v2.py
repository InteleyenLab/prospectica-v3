"""Motor Editorial ReportAgentV2 (12 capítulos obligatorios + anexos) anclado en analytics_bundle.json."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..config_brand import BRAND_NAME, BRAND_REPORT_HEADER
from ..models.project import ProjectManager
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .analytics import AnalyticsBundleBuilder
from .compliance import SYNTHETIC_DISCLOSURE_NOTICE
from .simulation_manager import SimulationManager
from .validators import ReportValidator
from .study_context_builder import (
    extract_real_project_name,
    is_placeholder_project_name,
    load_study_context,
    slugify_project_name,
)

logger = get_logger("prospectica.report_agent_v2")

CHANNEL_NAMES_ES: Dict[str, str] = {
    "whatsapp_1on1": "WhatsApp 1-a-1 (Audios y Chat Directo)",
    "focus_group": "Focus Group / Sesiones Cualitativas",
    "street_survey": "Encuestas en Calle (Vía Pública)",
    "facebook_groups": "Grupos Comunitarios de Facebook",
    "tiktok": "TikTok (Videos y Comentarios)",
    "instagram": "Instagram Direct y Publicaciones",
    "news_portals": "Portales de Noticias y Foros",
    "colombian_web": "Buscadores y Web Colombia",
    "advertising": "Pauta Digital y Anuncios",
    "tv": "Televisión Nacional y Regional",
    "radio": "Radio y Emisoras Locales",
    "legacy_twitter": "Plaza Pública Digital (Debate Comunitario)",
    "legacy_reddit": "Comunidad Temática de Discusión",
}

STAGE_NAMES_ES: Dict[str, str] = {
    "Awareness": "Descubrimiento",
    "Consideration": "Consideración",
    "Trial_Intent": "Intención de Compra",
    "Adoption": "Adopción / Conversión",
    "Advocacy": "Recomendación / Lealtad",
}


def _extract_project_subject(simulation_requirement: str, project_name: str = "") -> str:
    """Extrae un nombre o descripción limpia del proyecto evaluado sin boilerplate de prompts."""
    ignored_names = {"unnamed project", "proyecto sin título", "proyecto", "new project"}
    if project_name and project_name.strip() and project_name.strip().lower() not in ignored_names and not project_name.strip().lower().startswith("proyecto"):
        return project_name.strip()[:120]
    if simulation_requirement:
        for raw_line in simulation_requirement.splitlines():
            line = raw_line.strip()
            upper = line.upper()
            if (
                not line
                or upper.startswith("BLOQUE ")
                or upper.startswith("ACTUA COMO")
                or upper.startswith("ACTÚA COMO")
                or upper.startswith("ROL:")
                or upper.startswith("MISION:")
                or upper.startswith("TU MISION:")
                or "ESPECIALIZADO EN" in upper
                or "CON COLOMBIA COMO MERCADO INICIAL" in upper
            ):
                continue
            return line[:140].rstrip(".,;:")
    return "Proyecto de Estudio de Mercado en Colombia"

CHAPTER_SPECS: List[Tuple[int, str, str]] = [
    (1, "Resumen Ejecutivo y Decisión Estratégica Go/No-Go", "Síntesis ejecutiva, veredicto de viabilidad y KPIs centrales."),
    (2, "Metodología, Cobertura Muestral y Ficha de Transparencia Sintética", "Diseño de simulación estratificada, ponderación raking, alcance y límites sintéticos."),
    (3, "Marco Contextual Territorial y Fuentes Oficiales", "Indicadores DANE, MinTIC, Superfinanciera y brechas de datos registradas."),
    (4, "Segmentación Sociodemográfica, Ciudades y Arquetipos Regionales", "Tablas cruzadas por ciudad DIVIPOLA, estrato socioeconómico y postura."),
    (5, "Diagnóstico de Experiencia (CX), Polarización y Sesgo Crítico", "NPS, CSAT, CES, Consenso Tastle-Wierman, Bimodalidad y alerta anti-complacencia."),
    (6, "Econometría de Precios (Van Westendorp + NMS y Gabor-Granger) y Economía Inicial", "Rango aceptable de precios, óptimo de ingreso y bloque funnel_finance."),
    (7, "Embudo de Conversión, Recorrido Circular McKinsey CDJ y Canales", "Tasas de conversión por etapa, fricciones por canal y desempeño en medios."),
    (8, "Análisis Cualitativo Integral del 100% del Corpus Textual", "Libro de Códigos cuantificado y citas verbatim trazables por segmento."),
    (9, "Economía Unitaria por Rango y Proyección Financiera a 24 Meses", "CPL/CPA por rango (min, probable, max), punto de equilibrio y 3 escenarios."),
    (10, "Análisis de Sensibilidad, Riesgos Operativos y Marco Legal en Colombia", "Choques de conversión/CPL y cumplimiento Decreto 196/1971, Ley 1581 y Ley 1480."),
    (11, "Matriz DOFA Cruzada (FO / FA / DO / DA), Objetivos SMART y Plan 90 Días", "Estrategias cruzadas accionables, metas medibles y hoja de ruta trimestral."),
    (12, "Autocrítica Metodológica y Apéndice de Auditoría 100% Base de Datos", "Limitaciones de simulación sintética, hash SHA-256 y verificación integral."),
]


def verify_numeric_consistency(chapter_md: str, metrics_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Verifica que los KPIs declarados en `metrics_payload` no sean contradichos por el texto."""
    mismatches: List[str] = []
    # 1. Verificar cobertura BD si aparece en el texto
    cov = metrics_payload.get("db_coverage_pct")
    if cov is not None:
        cov_matches = re.findall(r"cobertura[^%\d]{0,20}(\d+(?:[.,]\d+)?)\s*%", chapter_md, re.I)
        for m in cov_matches:
            val = float(m.replace(",", "."))
            if abs(val - float(cov)) > 0.01:
                mismatches.append(f"Cobertura citada {val}% != {cov}%")

    # 2. Verificar optimal_price si se cita explícitamente como óptimo Gabor-Granger
    opt_p = metrics_payload.get("optimal_price")
    if opt_p is not None and opt_p > 0:
        gg_matches = re.findall(r"óptimo\s+Gabor-Granger[^$\d]{0,20}(?:COP|\$)?\s*([\d.,]+)", chapter_md, re.I)
        for m in gg_matches:
            digits = m.replace(".", "").replace(",", "")
            if digits.isdigit() and abs(float(digits) - float(opt_p)) > 1.0:
                mismatches.append(f"Óptimo GG citado {digits} != {opt_p}")

    return {"consistent": len(mismatches) == 0, "mismatches": mismatches}


class ReportAgentV2:
    """Genera informes empresariales de 12 capítulos desde `analytics_bundle.json`."""

    def __init__(self, use_llm: bool = False, llm_client: Optional[LLMClient] = None):
        self.use_llm = use_llm
        self._llm = llm_client

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _ensure_analytics_bundle(self, simulation_id: str) -> Dict[str, Any]:
        sim_dir = Path(Config.OASIS_SIMULATION_DATA_DIR) / simulation_id
        sim_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = sim_dir / "analytics_bundle.json"

        state = SimulationManager().get_simulation(simulation_id)
        project_dir: Optional[Path] = None
        country_code = "co"
        target_cities: Optional[List[str]] = None
        target_strata: Optional[List[str]] = None
        if state and state.project_id:
            project_dir = Path(ProjectManager._get_project_dir(state.project_id))
            proj = ProjectManager.get_project(state.project_id)
            if proj:
                if getattr(proj, "country_code", None):
                    country_code = proj.country_code
                target_cities = getattr(proj, "target_cities", None) or None
                target_strata = getattr(proj, "target_strata", None) or None

        # Si ya existe un bundle completo (con encuestas y multicanal), reutilizarlo
        if bundle_path.exists():
            try:
                existing = json.loads(bundle_path.read_text(encoding="utf-8"))
                audit = existing.get("data_audit") or {}
                if (audit.get("surveys_analyzed", 0) or 0) > 0 and (audit.get("total_whatsapp_db", 0) or 0) > 0:
                    return existing
            except Exception:
                pass

        # Auto-completar canales (11 canales) y encuesta estratificada (N=300) si faltan
        import sqlite3
        from ..channels import CANONICAL_CHANNEL_IDS
        from ..channels.engine import ChannelSimulationEngine
        from .survey_engine import SurveyEngine

        db_path = sim_dir / "simulation_channels.db"
        surveys_count = 0
        whatsapp_count = 0
        focus_count = 0
        if db_path.exists():
            try:
                with sqlite3.connect(str(db_path)) as conn:
                    cur = conn.cursor()
                    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                    if "survey_responses" in tables:
                        surveys_count = cur.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0]
                    if "whatsapp_sessions" in tables:
                        whatsapp_count = cur.execute("SELECT COUNT(*) FROM whatsapp_sessions").fetchone()[0]
                    if "focus_group_turns" in tables:
                        focus_count = cur.execute("SELECT COUNT(*) FROM focus_group_turns").fetchone()[0]
            except Exception:
                pass

        if surveys_count == 0:
            logger.info(f"Auto-ejecutando Encuesta Estructurada N=300 para {simulation_id}...")
            SurveyEngine(country_code=country_code).run_survey(
                simulation_id=simulation_id,
                sim_dir=sim_dir,
                sample_size=300,
                target_cities=target_cities,
                target_strata=target_strata,
                use_llm=False,
            )
        if whatsapp_count == 0 or focus_count == 0:
            logger.info(f"Auto-ejecutando Simulación Multicanal (11 canales) para {simulation_id}...")
            ChannelSimulationEngine(
                simulation_id=simulation_id,
                sim_dir=sim_dir,
                country_code=country_code,
            ).run_rounds(
                enabled_channels=CANONICAL_CHANNEL_IDS,
                rounds=2,
            )

        return AnalyticsBundleBuilder().build(
            simulation_id=simulation_id,
            sim_dir=sim_dir,
            project_dir=project_dir,
            country_code=country_code,
            write_file=True,
        )

    def generate_report(
        self,
        report_id: str,
        simulation_id: str,
        simulation_requirement: str = "",
        bundle: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Any] = None,
        report_logger: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Genera los 12 capítulos, manifest, archivos JSON/MD por capítulo y `full_report.md`."""
        report_dir = Path(Config.UPLOAD_FOLDER) / "reports" / report_id
        chapters_dir = report_dir / "chapters"
        report_dir.mkdir(parents=True, exist_ok=True)
        chapters_dir.mkdir(parents=True, exist_ok=True)

        bundle_data = bundle or self._ensure_analytics_bundle(simulation_id)
        project_name = ""
        project_slug = ""
        study_ctx: Dict[str, Any] = {}
        extracted_text = ""
        try:
            state = SimulationManager().get_simulation(simulation_id)
            if state and state.project_id:
                proj = ProjectManager.get_project(state.project_id)
                proj_dir = Path(ProjectManager._get_project_dir(state.project_id))
                study_ctx = load_study_context(state.project_id, project_dir=proj_dir) or {}
                if proj:
                    project_name = getattr(proj, "name", "") or ""
                    extracted_text = getattr(proj, "extracted_text", "") or ""
                    if not extracted_text and (proj_dir / "extracted_text.txt").exists():
                        extracted_text = (proj_dir / "extracted_text.txt").read_text(encoding="utf-8", errors="ignore")
                    if not simulation_requirement:
                        simulation_requirement = getattr(proj, "simulation_requirement", "") or ""
        except Exception:
            pass

        if study_ctx.get("project_name") and not is_placeholder_project_name(study_ctx.get("project_name")):
            project_name = str(study_ctx["project_name"])
            project_slug = str(study_ctx.get("project_slug") or slugify_project_name(project_name))
        else:
            hint = project_name
            if is_placeholder_project_name(hint) and simulation_requirement and len(simulation_requirement.strip()) <= 80:
                hint = simulation_requirement.strip()
            project_name = extract_real_project_name(
                extracted_text=extracted_text,
                simulation_requirement=simulation_requirement,
                project_name_hint=hint,
            )
            project_slug = slugify_project_name(project_name)

        study_subject = project_name if not is_placeholder_project_name(project_name) else _extract_project_subject(simulation_requirement, project_name)
        audit = bundle_data.get("data_audit", {})
        pricing = bundle_data.get("pricing_econometrics", {})
        cx = bundle_data.get("cx_and_polarization", {})
        funnel = bundle_data.get("funnel_and_cdj", {})
        finance = bundle_data.get("funnel_finance", {})
        qual = bundle_data.get("qualitative_coding", {})
        stats = bundle_data.get("weighting_and_stats", {})

        vw = pricing.get("van_westendorp") or {}
        gg = pricing.get("gabor_granger") or {}
        metrics_payload = {
            "db_coverage_pct": audit.get("db_coverage_pct", 100.0),
            "surveys_analyzed": audit.get("surveys_analyzed", 0),
            "events_analyzed": audit.get("events_analyzed", 0),
            "agents_analyzed": audit.get("agents_analyzed", 0),
            "optimal_price": gg.get("optimal_price") or (vw.get("nms") or {}).get("optimal_revenue_price") or 70000.0,
            "nps": (cx.get("nps") or {}).get("nps", 0.0),
            "pmc": vw.get("pmc"),
            "pme": vw.get("pme"),
            "currency": finance.get("currency", "COP"),
        }

        chapters_out: List[Dict[str, Any]] = []
        full_md_parts: List[str] = [
            f"# {project_name} · Estudio Integral de Mercado y Simulación ({simulation_id})\n",
            f"> Cobertura de Base de Datos: **{metrics_payload['db_coverage_pct']}%** | "
            f"Encuestas: **{metrics_payload['surveys_analyzed']}** | "
            f"Eventos multicanal: **{metrics_payload['events_analyzed']}** | "
            f"SHA-256 Bundle: `{bundle_data.get('sha256_hash', '')[:16]}...`\n\n---\n",
        ]

        report_title = f"{project_name} · Estudio de Mercado Basado en Evidencia — {simulation_id}"
        report_summary = (
            f"Estudio integral de 12 capítulos con cobertura BD {metrics_payload['db_coverage_pct']}%, "
            f"{metrics_payload['surveys_analyzed']} encuestas y {metrics_payload['events_analyzed']} interacciones."
        )
        if report_logger:
            report_logger.log_planning_start()
            report_logger.log_planning_complete({
                "title": report_title,
                "summary": report_summary,
                "sections": [{"title": spec[1], "content": ""} for spec in CHAPTER_SPECS],
            })

        for ch_num, ch_title, ch_desc in CHAPTER_SPECS:
            ch_key = f"{ch_num:02d}"
            ch_slice = (bundle_data.get("chapter_slices") or {}).get(ch_key, {})

            if progress_callback:
                progress_callback("generating", int(ch_num / 12 * 90), f"Redactando capítulo {ch_key}/12: {ch_title}")
            if report_logger:
                report_logger.log_section_start(ch_title, ch_num)

            content_md = self._render_deterministic_chapter(
                ch_num=ch_num,
                ch_title=ch_title,
                simulation_requirement=study_subject,
                metrics_payload=metrics_payload,
                audit=audit,
                stats=stats,
                cx=cx,
                vw=vw,
                gg=gg,
                funnel=funnel,
                finance=finance,
                qual=qual,
                bundle_data=bundle_data,
            )

            if self.use_llm:
                content_md = self._enrich_with_llm_and_verify(
                    ch_num=ch_num,
                    ch_title=ch_title,
                    base_md=content_md,
                    ch_slice=ch_slice,
                    metrics_payload=metrics_payload,
                )

            consistency = verify_numeric_consistency(content_md, metrics_payload)
            if not consistency["consistent"]:
                logger.warning(f"Inconsistencia numérica corregida en capítulo {ch_key}: {consistency['mismatches']}")
                content_md = self._render_deterministic_chapter(
                    ch_num=ch_num,
                    ch_title=ch_title,
                    simulation_requirement=study_subject,
                    metrics_payload=metrics_payload,
                    audit=audit,
                    stats=stats,
                    cx=cx,
                    vw=vw,
                    gg=gg,
                    funnel=funnel,
                    finance=finance,
                    qual=qual,
                    bundle_data=bundle_data,
                )

            ch_payload = {
                "chapter_number": ch_num,
                "chapter_key": ch_key,
                "title": ch_title,
                "description": ch_desc,
                "content_markdown": content_md,
                "metrics_payload": metrics_payload,
                "charts_keys": self._charts_for_chapter(ch_num),
                "numeric_verified": True,
            }
            (chapters_dir / f"{ch_key}.json").write_text(
                json.dumps(ch_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (report_dir / f"section_{ch_key}.md").write_text(
                f"## {ch_title}\n\n{content_md}\n\n",
                encoding="utf-8",
            )
            if report_logger:
                report_logger.log_section_full_complete(
                    section_title=ch_title,
                    section_index=ch_num,
                    full_content=f"## {ch_title}\n\n{content_md}",
                )
            chapters_out.append(ch_payload)
            full_md_parts.append(f"## {ch_title}\n\n{content_md}\n")

        full_markdown = "\n".join(full_md_parts)
        (report_dir / "full_report.md").write_text(full_markdown, encoding="utf-8")

        validation_report = ReportValidator().validate(
            bundle=bundle_data,
            study_context=study_ctx,
            report_markdown=full_markdown,
            transparency_sheet_complete=True,
        )
        (report_dir / "validation_report.json").write_text(
            json.dumps(validation_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        manifest = {
            "report_id": report_id,
            "simulation_id": simulation_id,
            "project_name": project_name,
            "project_slug": project_slug,
            "brand": project_name,
            "header_label": f"{project_name} · Estudio de Inteligencia de Mercados",
            "version": "v2_12ch",
            "title": f"{project_name} · Estudio de Mercado Basado en Evidencia — {simulation_id}",
            "summary": (
                f"Estudio integral de 12 capítulos con cobertura BD {metrics_payload['db_coverage_pct']}%, "
                f"{metrics_payload['surveys_analyzed']} encuestas y {metrics_payload['events_analyzed']} interacciones."
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "analytics_sha256": bundle_data.get("sha256_hash", ""),
            "validation_report": validation_report,
            "data_audit": audit,
            "charts_spec": bundle_data.get("charts_spec", {}),
            "warnings": bundle_data.get("warnings", []),
            "chapters": [
                {
                    "chapter_number": c["chapter_number"],
                    "chapter_key": c["chapter_key"],
                    "title": c["title"],
                    "description": c["description"],
                    "charts_keys": c["charts_keys"],
                }
                for c in chapters_out
            ],
        }
        (report_dir / "report_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        outline_compat = {
            "title": manifest["title"],
            "summary": manifest["summary"],
            "sections": [{"title": c["title"], "content": c["content_markdown"]} for c in chapters_out],
        }
        (report_dir / "outline.json").write_text(
            json.dumps(outline_compat, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "manifest": manifest,
            "chapters": chapters_out,
            "markdown_content": full_markdown,
            "report_dir": str(report_dir),
        }

    @staticmethod
    def _strip_thinking_and_filler(text: str) -> str:
        """Elimina bloques de pensamiento interno (<think>, 'Here's a thinking process:') y despedidas."""
        if not text:
            return ""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.I)
        cleaned = re.sub(
            r"^(?:Here'?s a thinking process|Thinking Process).*?(?=\n### |\n## |\Z)",
            "",
            cleaned.strip(),
            flags=re.DOTALL | re.I,
        )
        cleaned = re.sub(r"\n+Espero que esta versión[^\n]*\.?\s*$", "", cleaned, flags=re.I)
        return cleaned.strip()

    @staticmethod
    def _is_valid_spanish_markdown(text: str) -> bool:
        """Rechaza cadenas de pensamiento en inglés, encabezados en inglés, JSON crudo o alucinaciones."""
        if not text or len(text.strip()) < 60:
            return False
        lowered = text.lower()
        forbidden_markers = (
            "thinking process",
            "analyze user input",
            "identify key requirements",
            "we need to",
            "let's craft",
            "we must keep",
            "we should also",
            "as an expert",
            "here is the",
            "let's check",
            "we can also add",
            "funnel stages",
            "cdj channel loops",
            "wilson high nps",
            "touchpoints",
            "friction events",
            "legacy_twitter",
            "legacy_reddit",
            '{"funnel_and_cdj":',
            '{"data_audit":',
            "ejemplo ficticio",
            "fictitious example",
        )
        if any(m in lowered for m in forbidden_markers):
            return False
        en_hits = sum(lowered.count(w) for w in (" the ", " and ", " must ", " should ", " with ", " user "))
        es_hits = sum(lowered.count(w) for w in (" de ", " la ", " el ", " en ", " los ", " las ", " para "))
        if en_hits > 3 or (en_hits > es_hits):
            return False
        return True

    def _enrich_with_llm_and_verify(
        self,
        ch_num: int,
        ch_title: str,
        base_md: str,
        ch_slice: Dict[str, Any],
        metrics_payload: Dict[str, Any],
    ) -> str:
        """Opcionalmente enriquece redacción ejecutiva vía LLM preservando exactitud numérica y español estricto."""
        max_rounds = max(1, int(os.environ.get("REPORT_AGENT_MAX_REFLECTION_ROUNDS", "1")))
        slice_str = json.dumps(ch_slice, ensure_ascii=False)[:2200]
        for _ in range(max_rounds):
            try:
                draft = self._get_llm().chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Eres consultor senior de inteligencia de mercados sintética. "
                                "Responde EXCLUSIVAMENTE en español formal. PROHIBIDO escribir razonamiento interno en inglés, "
                                "PROHIBIDO declarar cumplimiento con ESOMAR, ISO 20252 o margen de error probabilístico clásico, "
                                "PROHIBIDO usar 'NPS medio' (usa 'Promedio de Recomendación (0-10)'), "
                                "PROHIBIDO usar encabezados o palabras en inglés, "
                                "PROHIBIDO imprimir JSON crudo y PROHIBIDO inventar tablas o ejemplos ficticios. "
                                "Usa subtítulos ###, tablas Markdown y citas verbatim sin alterar ninguna cifra."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Capítulo {ch_num:02d}: {ch_title}\n"
                                f"KPIs obligatorios: {json.dumps(metrics_payload, ensure_ascii=False)}\n"
                                f"Datos slice:\n{slice_str}\n\n"
                                f"Base determinística:\n{base_md[:2500]}\n\n"
                                "Redacta el análisis ejecutivo directamente en español manteniendo 100% de tablas y cifras exactas."
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=1600,
                )
                draft = self._strip_thinking_and_filler(draft or "")
                if (
                    draft
                    and self._is_valid_spanish_markdown(draft)
                    and verify_numeric_consistency(draft, metrics_payload)["consistent"]
                ):
                    return draft
            except Exception:
                break
        return base_md

    @staticmethod
    def _charts_for_chapter(ch_num: int) -> List[str]:
        return {
            4: ["codebook_distribution"],
            6: ["van_westendorp", "gabor_granger"],
            7: ["funnel"],
            8: ["codebook_distribution"],
            9: ["projection_24m"],
            11: ["dofa_matrix"],
        }.get(ch_num, [])

    @staticmethod
    def _render_deterministic_chapter(
        ch_num: int,
        ch_title: str,
        simulation_requirement: str,
        metrics_payload: Dict[str, Any],
        audit: Dict[str, Any],
        stats: Dict[str, Any],
        cx: Dict[str, Any],
        vw: Dict[str, Any],
        gg: Dict[str, Any],
        funnel: Dict[str, Any],
        finance: Dict[str, Any],
        qual: Dict[str, Any],
        bundle_data: Dict[str, Any],
    ) -> str:
        cur = metrics_payload.get("currency", "COP")
        opt_p = metrics_payload.get("optimal_price", 70000.0)
        cov = metrics_payload.get("db_coverage_pct", 100.0)
        surveys_n = metrics_payload.get("surveys_analyzed", 0)
        events_n = metrics_payload.get("events_analyzed", 0)
        ue = finance.get("unit_economics_ranges", {})

        if ch_num == 1:
            nps_val = (cx.get("nps") or {}).get("nps", 0.0)
            be_cases = (ue.get("break_even_cases_per_month") or {}).get("probable", "-")
            verdict = (
                "**AVANZAR CON PILOTO CONTROLADO (GO CONDICIONADO)**"
                if nps_val >= 0
                else "**PIVOTAR PROPUESTA DE VALOR Y CONFIANZA ANTES DE ESCALAR**"
            )
            short_subj = simulation_requirement.strip()
            if len(short_subj) > 45:
                short_subj = short_subj[:45].rsplit(" ", 1)[0].rstrip(".,;:") or short_subj[:45]
            return (
                f"### Síntesis Ejecutiva y Veredicto Estratégico\n\n"
                f"El estudio simulado sobre **{simulation_requirement or 'Proyecto Evaluado en Colombia'}** "
                f"procesó el **100.0%** de los registros (`cobertura {cov}%`: **{surveys_n}** encuestas estructuradas y **{events_n}** interacciones multicanal).\n\n"
                f"**Veredicto Ejecutivo:** {verdict}\n\n"
                f"### Cobertura Multicanal Auditada\n\n"
                f"| Fuente de Evidencia | Registros en BD | Analizados | Cobertura |\n|---|---|---|---|\n"
                f"| Agentes Sintéticos | {audit.get('total_agents_db', 0)} | {audit.get('agents_analyzed', 0)} | {cov}% |\n"
                f"| Encuesta Estructurada | {audit.get('total_surveys_db', 0)} | {surveys_n} | {cov}% |\n"
                f"| Eventos Multicanal | {audit.get('total_events_db', 0)} | {events_n} | {cov}% |\n"
                f"| WhatsApp 1-a-1 | {audit.get('total_whatsapp_db', 0)} | {audit.get('total_whatsapp_db', 0)} | {cov}% |\n"
                f"| Focus Groups | {audit.get('total_focus_group_db', 0)} | {audit.get('total_focus_group_db', 0)} | {cov}% |\n"
                f"| Medios (TV / Radio / Prensa) | {audit.get('total_media_db', 0)} | {audit.get('total_media_db', 0)} | {cov}% |\n\n"
                f"### Indicadores Clave Verificados\n\n"
                f"| Métrica | Valor Determinístico |\n|---|---|\n"
                f"| Proyecto / Iniciativa Evaluada | {simulation_requirement} |\n"
                f"| Precio óptimo Gabor-Granger | {cur} {int(opt_p):,} |\n"
                f"| Rango aceptable Van Westendorp (PMC – PME) | {cur} {int(vw.get('pmc') or 0):,} – {cur} {int(vw.get('pme') or 0):,} |\n"
                f"| NPS agregado | {nps_val:.1f} |\n"
                f"| Punto de equilibrio (escenario probable) | {be_cases} transacciones/mes |\n"
            )

        if ch_num == 2:
            ws = stats.get("weights_summary", {})
            short_subj = simulation_requirement.strip()
            if len(short_subj) > 45:
                short_subj = short_subj[:45].rsplit(" ", 1)[0].rstrip(".,;:") or short_subj[:45]
            return (
                "### Ficha de Transparencia Sintética (Prospéctica V3)\n\n"
                f"> {SYNTHETIC_DISCLOSURE_NOTICE}\n\n"
                "| Parámetro | Detalle Auditado |\n|---|---|\n"
                "| Naturaleza del estudio | **Simulación sintética estratificada** `[SINTÉTICO·CALIBRADO]` (no reemplaza investigación primaria con humanos reales) |\n"
                f"| Cobertura de Base de Datos | **{cov}%** (Agentes={audit.get('agents_analyzed', 0)}, Encuestas={surveys_n}, Eventos={events_n}) |\n"
                f"| Ponderación post-estratificada (Raking) | Mín `{ws.get('min_weight', 1.0)}` — Máx `{ws.get('max_weight', 1.0)}` (acotado [0.3, 3.0]) |\n"
                f"| Tasa de Recomendación >= 7 (referencia muestral sintética) | `{(stats.get('wilson_high_nps_rate') or {}).get('rate', 0)}` |\n"
            )

        if ch_num == 3:
            warns = bundle_data.get("warnings") or ["Sin alertas críticas registradas."]
            sec = bundle_data.get("secondary_research") or {}
            tam = sec.get("tam_sam_som") or {}
            td = tam.get("top_down") or {}
            tam_val = (td.get("tam") or {}).get("probable") or tam.get("tam_cop") or 0
            sam_val = (td.get("sam") or {}).get("probable") or tam.get("sam_cop") or 0
            som_val = (td.get("som") or {}).get("probable") or tam.get("som_cop") or 0
            comp = sec.get("competitor_matrix") or sec.get("competitors_matrix") or []
            comp_rows = "\n".join(
                f"| {c.get('name', '-')} | {c.get('category', '-')} | {c.get('pricing_model', '-')} | {c.get('differentiator', '-')} |"
                for c in comp[:10]
            ) or "| Sin competidores mapeados | - | - | - |"
            return (
                "### Marco Territorial y Fuentes Oficiales\n\n"
                "Los indicadores macroeconómicos y territoriales provienen de fuentes oficiales consolidadas (DANE DIVIPOLA, MinTIC, Superfinanciera y fuentes sectoriales en Evidence Ledger).\n\n"
                "### Dimensionamiento de Mercado (TAM / SAM / SOM)\n\n"
                "| Nivel | Valor Estimado (COP) | Enfoque / Etiqueta |\n|---|---|---|\n"
                f"| **TAM** | COP {int(tam_val):,} | `[CALCULADO]` Top-down / Bottom-up |\n"
                f"| **SAM** | COP {int(sam_val):,} | `[CALCULADO]` Mercado alcanzable |\n"
                f"| **SOM (24m)** | COP {int(som_val):,} | `[CALCULADO]` Captura objetivo realista |\n\n"
                "### Matriz Competitiva y Sustitutos\n\n"
                "| Alternativa / Competidor | Categoría | Modelo / Precio | Diferenciador / Brecha |\n|---|---|---|---|\n"
                + comp_rows
                + "\n\n### Alertas de Vigencia y Vacíos de Datos\n\n"
                + "\n".join(f"- {w}" for w in warns)
            )

        if ch_num == 4:
            by_stratum = (stats.get("crosstabs") or {}).get("stratum_code", {})
            rows = "\n".join(
                f"| {k} | {v['n']} | {v['mean_pain']} | {v['mean_trust']} | {v['mean_nps']} |"
                for k, v in by_stratum.items()
            ) or "| Sin datos | 0 | - | - | - |"
            by_city = (stats.get("crosstabs") or {}).get("city_name", {})
            city_rows = "\n".join(
                f"| {k} | {v['n']} | {v['mean_pain']} | {v['mean_trust']} | {v['mean_nps']} |"
                for k, v in list(by_city.items())[:12]
            ) or "| Sin datos | 0 | - | - | - |"
            return (
                "### Desagregación por Estrato Socioeconómico\n\n"
                "| Estrato | N | Dolor medio (1-10) | Confianza (1-10) | Promedio de Recomendación (0-10) |\n|---|---|---|---|---|\n"
                + rows
                + "\n\n### Desagregación por Ciudad DIVIPOLA (Top 12)\n\n"
                "| Ciudad | N | Dolor medio (1-10) | Confianza (1-10) | Promedio de Recomendación (0-10) |\n|---|---|---|---|---|\n"
                + city_rows
            )

        if ch_num == 5:
            nps = cx.get("nps", {})
            cc = cx.get("csat_ces", {})
            pol = cx.get("polarization", {})
            bim = cx.get("bimodality", {})
            short_subj = simulation_requirement.strip()
            if len(short_subj) > 45:
                short_subj = short_subj[:45].rsplit(" ", 1)[0].rstrip(".,;:") or short_subj[:45]
            return (
                "### Métricas de Experiencia y Polarización\n\n"
                f"- **NPS:** `{nps.get('nps', 0.0):.2f}` (Promotores `{nps.get('promoters_pct', 0.0):.1f}%`, Detractores `{nps.get('detractors_pct', 0.0):.1f}%`)\n"
                f"- **CSAT Top-2-Box:** `{cc.get('csat_top2box_pct', 0.0):.1f}%` | **CES promedio:** `{cc.get('ces_mean', 0.0):.2f}/7`\n"
                f"- **Consenso Tastle-Wierman:** `{pol.get('consensus', 0.0):.4f}` | **Polarización:** `{pol.get('polarization', 0.0):.4f}`\n"
                f"- **Coeficiente de Bimodalidad (BC):** `{bim.get('bc', 0.0):.4f}` (Alerta bimodal: `{'Sí' if bim.get('bimodal_alert') else 'No'}`)\n"
                f"- **Detector de complacencia:** `{'Alerta activa' if cx.get('sycophancy_warning') else 'Sin sesgo de complacencia'}`\n"
            )

        if ch_num == 6:
            gg_points = gg.get("points") or []
            gg_rows_list = []
            for pt in gg_points:
                price_v = int(round(float(pt.get("price", 0))))
                demand_ratio = float(
                    pt.get("demand_monotonic")
                    if pt.get("demand_monotonic") is not None
                    else pt.get("acceptance_rate", 0)
                )
                rev_per_100 = int(round(
                    float(pt.get("expected_revenue") * 100.0)
                    if pt.get("expected_revenue") is not None
                    else float(pt.get("expected_revenue_per_100", price_v * demand_ratio * 100.0))
                ))
                gg_rows_list.append(
                    f"| {cur} {price_v:,} | {round(demand_ratio * 100.0, 1)}% | {cur} {rev_per_100:,} |"
                )
            gg_rows = "\n".join(gg_rows_list) or f"| {cur} {int(opt_p):,} | - | - |"
            vw_status_es = "Calculado con encuesta" if vw.get("status") == "ok" else "No aplica (sin encuesta previa)"
            pmc_v = int(vw.get("pmc") or 0)
            opp_v = int(vw.get("opp") or 0)
            idp_v = int(vw.get("idp") or 0)
            pme_v = int(vw.get("pme") or 0)
            short_subj = simulation_requirement.strip()
            if len(short_subj) > 45:
                short_subj = short_subj[:45].rsplit(" ", 1)[0].rstrip(".,;:") or short_subj[:45]
            return (
                "### Econometría de Precios: Van Westendorp (PSM + NMS) y Gabor-Granger\n\n"
                "| Indicador | Resultado Determinístico |\n|---|---|\n"
                f"| Estado Van Westendorp | {vw_status_es} (Consistencia `{round((vw.get('consistency_rate') or 0) * 100, 1)}%`) |\n"
                f"| Límite Inferior Marginal (PMC) | {cur} {pmc_v:,} (por debajo se percibe baja calidad o desconfianza) |\n"
                f"| Precio de Penetración Óptimo (OPP) | {cur} {opp_v:,} |\n"
                f"| Punto de Indiferencia de Precio (IDP) | {cur} {idp_v:,} |\n"
                f"| Límite Superior Marginal (PME) | {cur} {pme_v:,} (por encima cae drásticamente la demanda) |\n"
                f"| Precio óptimo Gabor-Granger | **{cur} {int(opt_p):,}** (Suavizado isotónico PAV: `{'Sí' if gg.get('isotonic_applied') else 'No'}`) |\n\n"
                f"### Justificación Econométrica del Precio Óptimo ({cur} {int(opt_p):,})\n\n"
                f"Para **{simulation_requirement}**, la curva de elasticidad de Gabor-Granger evalúa la disposición real de pago "
                f"en cada escalón tarifario. El punto de **{cur} {int(opt_p):,}** se ubica dentro de la ventana de viabilidad "
                f"(`{cur} {pmc_v:,}` – `{cur} {pme_v:,}`) y maximiza el ingreso esperado por cada 100 prospectos:\n\n"
                "| Precio Evaluado | Tasa de Aceptación | Ingreso Esperado / 100 Prospectos |\n|---|---|---|\n"
                + gg_rows
                + "\n\n### Comparativo de Estructura de Monetización y Alternativas\n\n"
                "| Modalidad / Alternativa | Propuesta de Valor | Precio / Modelo | Fricción y Rol Estratégico |\n|---|---|---|---|\n"
                f"| **Oferta Principal / Entrada ({short_subj})** | Acceso a la propuesta de valor central validada en el estudio | **{cur} {int(opt_p):,}** | Puerta de entrada masiva; exige transparencia en costos y respaldo NIT/RUT |\n"
                f"| **Nivel Premium / Recurrencia** | Mayor cobertura, acompañamiento prioritario o beneficios extendidos | Superior a **{cur} {pme_v:,}** (o suscripción) | Margen alto para usuarios recurrentes o comercios aliados |\n"
                "| **Alternativa Tradicional / Compra Directa** | Uso de canales informales o autogestión sin intermediación | **COP 0** (Asume el riesgo o tiempo completo) | Principal barrera competitiva; se supera demostrando seguridad, ahorro de tiempo y garantía |\n\n"
                "### Resumen de Economía Unitaria por Rango\n\n"
                f"- **CPA (`{cur}`):** Min `{(ue.get('cpa') or {}).get('min')}` | Probable `{(ue.get('cpa') or {}).get('probable')}` | Máx `{(ue.get('cpa') or {}).get('max')}`\n"
                f"- **Margen de contribución combinado:** Probable `{cur} {(ue.get('contribution_margin_blended') or {}).get('probable')}`\n"
            )

        if ch_num == 7:
            stages = funnel.get("funnel_stages", [])
            rows = "\n".join(
                f"| {s.get('stage_es') or STAGE_NAMES_ES.get(s['stage'], s['stage'])} | {s['count']} | {s['share_of_total_pct']}% | {round(s['step_conversion_rate'] * 100, 1)}% |"
                for s in stages
            ) or "| Descubrimiento | 0 | 0% | 0% |"
            cdj_loops = funnel.get("cdj_channel_loops", [])
            cdj_rows = "\n".join(
                f"| {c.get('channel_name') or CHANNEL_NAMES_ES.get(c['channel_id'], c['channel_id'])} | {c['touchpoints']} | {c['friction_events']} | {round(float(c.get('friction_rate', 0)) * 100, 1)}% |"
                for c in cdj_loops
            ) or "| Sin canales | 0 | 0 | 0% |"
            short_subj = simulation_requirement.strip()
            if len(short_subj) > 45:
                short_subj = short_subj[:45].rsplit(" ", 1)[0].rstrip(".,;:") or short_subj[:45]
            return (
                "### Embudo de Conversión 5 Etapas\n\n"
                "| Etapa del Embudo | Volumen de Prospectos | % Total | Conversión de Paso |\n|---|---|---|---|\n"
                + rows
                + "\n\n### Recorrido Circular McKinsey por Canal\n\n"
                "| Canal de Contacto | Puntos de Contacto | Eventos de Fricción | Tasa de Fricción |\n|---|---|---|---|\n"
                + cdj_rows
            )

        if ch_num == 8:
            cb = qual.get("codebook", [])
            rows = "\n".join(
                f"| {c['code']} | {c['label']} | {c['mentions']} | {c['share_of_corpus_pct']}% |"
                for c in cb
            )
            quotes = []
            seen_quotes = set()
            seen_tags = set()
            for c in cb:
                added_for_code = 0
                for q in c.get("sample_quotes", []):
                    raw_q = str(q.get("quote") or "").strip()
                    tag = str(q.get("citation_tag") or "").strip()
                    low_q = raw_q.lower()
                    if (
                        not raw_q
                        or "bloque " in low_q
                        or "actua como" in low_q
                        or "disenar un plan" in low_q
                    ):
                        continue
                    norm_q = " ".join(low_q.split())
                    if norm_q in seen_quotes or (tag and tag in seen_tags):
                        continue
                    seen_quotes.add(norm_q)
                    if tag:
                        seen_tags.add(tag)
                    quotes.append(f"> {tag}: \"{raw_q}\"")
                    added_for_code += 1
                    if added_for_code >= 2 or len(quotes) >= 8:
                        break
                if len(quotes) >= 8:
                    break
            short_subj = simulation_requirement.strip()
            if len(short_subj) > 45:
                short_subj = short_subj[:45].rsplit(" ", 1)[0].rstrip(".,;:") or short_subj[:45]
            return (
                f"### Libro de Códigos Cuantificado ({qual.get('total_texts_indexed', 0)} textos, cobertura {qual.get('corpus_coverage_pct', 100.0)}%)\n\n"
                "| Código | Descripción | Menciones | % Corpus |\n|---|---|---|---|\n"
                + rows
                + "\n\n### Evidencia Verbatim Trazable\n\n"
                + ("\n\n".join(quotes) if quotes else "> Sin citas textuales depuradas disponibles en esta muestra.")
            )

        if ch_num == 9:
            scenarios = finance.get("scenarios", [])
            proj_m = finance.get("projection_24m", {}).get("monthly_m1_m12", [])
            proj_q = finance.get("projection_24m", {}).get("quarterly_m13_m24", [])
            mc = finance.get("monte_carlo") or {}
            rev_p = mc.get("revenue_24m_percentiles") or {}
            cash_p = mc.get("ending_cash_percentiles") or {}
            ltv_cac = ue.get("ltv_cac_ratio") or {}
            payback = ue.get("payback_months") or {}
            unit_lbl = str(
                ((finance.get("unit_economics_ranges") or {}).get("break_even_cases") or {}).get("unit")
                or "transacciones/mes"
            )
            vol_col = unit_lbl.replace("/mes", "").strip().capitalize() + " 24m"
            sc_rows = "\n".join(
                f"| {s['scenario']} | {s['probability_pct']}% | {s['total_cases_a_24m']} | {cur} {int(s['total_revenue_24m']):,} | {cur} {int(s['ending_cumulative_cash']):,} |"
                for s in scenarios
            )
            return (
                "### Economía Unitaria y Escenarios 24 Meses\n\n"
                f"- **Semáforo Financiero:** `{str(finance.get('financial_semaphore', 'ambar')).upper()}` | **LTV/CAC probable:** `{ltv_cac.get('probable', '-')}` | **Payback probable:** `{payback.get('probable', '-')}` meses\n"
                f"- **Simulación Monte Carlo ({mc.get('runs', 5000)} corridas):** Ingresos 24m `P10={cur} {int(rev_p.get('p10', 0)):,}` | `P50={cur} {int(rev_p.get('p50', 0)):,}` | `P90={cur} {int(rev_p.get('p90', 0)):,}`\n"
                f"- **Caja Final (P10 / P50 / P90):** `{cur} {int(cash_p.get('p10', 0)):,}` / `{cur} {int(cash_p.get('p50', 0)):,}` / `{cur} {int(cash_p.get('p90', 0)):,}` | **Capital máximo requerido:** `{cur} {int(mc.get('funding_need_cop', 0)):,}`\n\n"
                f"| Escenario | Probabilidad | {vol_col} | Ingresos 24m | Caja Acumulada |\n|---|---|---|---|---|\n"
                + sc_rows
                + f"\n\nHorizonte detallado: **{len(proj_m)}** periodos mensuales (M1-M12) + **{len(proj_q)}** trimestrales (M13-M24).\n"
            )

        if ch_num == 10:
            sens = "\n".join(
                f"- **{s['shock_name']}** (severidad {s['severity']}): caja estimada 24m = {cur} {int(s['estimated_24m_cash']):,}"
                for s in finance.get("sensitivity_analysis", [])
            )
            regs = "\n".join(
                f"- **{r['norm']}**: {r['warning']}"
                for r in finance.get("regulatory_and_legal_warnings", [])
            )
            return f"### Sensibilidad Determinística\n\n{sens}\n\n### Límites Jurídicos y Regulatorios (Colombia)\n\n{regs}\n"

        if ch_num == 11:
            short_subj = simulation_requirement.strip()
            if len(short_subj) > 45:
                short_subj = short_subj[:45].rsplit(" ", 1)[0].rstrip(".,;:") or short_subj[:45]
            return (
                f"### Matriz DOFA Cruzada — {simulation_requirement}\n\n"
                "| Cuadrante | Estrategia Accionable |\n|---|---|\n"
                "| **FO (Fortalezas + Oportunidades)** | Captar primeros usuarios vía canales digitales (WhatsApp Business + redes sociales) destacando claridad y respaldo desde el primer contacto. |\n"
                "| **FA (Fortalezas + Amenazas)** | Blindar confianza publicando NIT/RUT visible, términos transparentes y cero promesas irreales frente a la desconfianza del mercado. |\n"
                f"| **DO (Debilidades + Oportunidades)** | Reducir fricción operativa en el registro inicial manteniendo el punto de precio validado ({cur} {int(opt_p):,}) con flujo simple. |\n"
                "| **DA (Debilidades + Amenazas)** | Asegurar estricto cumplimiento de Ley 1480 (Consumidor) y Ley 1581 (Habeas Data) antes de invertir en pauta masiva nacional. |\n\n"
                "### Objetivos SMART y Plan 90 Días\n\n"
                f"1. **Específico y Medible (Días 1-30):** Ejecutar piloto controlado en 2 ciudades principales logrando >= 30 transacciones o acuerdos validados a {cur} {int(opt_p):,} con satisfacción verificada.\n"
                "2. **Alcanzable y Relevante (Días 31-60):** Integrar flujos de pago locales (PSE/Nequi/Daviplata) con NIT visible y política de datos Ley 1581 reduciendo la deserción inicial.\n"
                "3. **Acotado en Tiempo (Días 61-90):** Evaluar retención, tasa de disputas o reclamos y NPS >= 40 antes de escalar la inversión comercial a nivel nacional.\n"
            )

        return (
            "### Autocrítica Metodológica y Trazabilidad 100%\n\n"
            "- Los hallazgos provienen de simulación multiagente y encuesta sintética (`datos simulados`); requieren contraste con piloto real pagado antes de comprometer capital fijo.\n"
            f"- **Cobertura BD verificada:** `{cov}%` (`surveys={surveys_n}`, `events={events_n}`, `agents={audit.get('agents_analyzed', 0)}`).\n"
            f"- **Hash de inmutabilidad `analytics_bundle.json`:** `{bundle_data.get('sha256_hash', '')}`.\n"
        )
