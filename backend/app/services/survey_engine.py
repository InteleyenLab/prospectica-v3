"""Motor de encuestas estructuradas estratificadas (N=300+) con Van Westendorp, Gabor-Granger y CX."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from ..channels.persistence import ChannelSQLiteStore
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .demographic_sampler import DemographicAllocation, DemographicSampler

logger = get_logger("mirofish.survey_engine")

DEFAULT_GG_PRICES_COP: List[int] = [35000, 50000, 70000, 100000, 140000]


class StructuredSurveyRecord(BaseModel):
    """Registro auditado de un respondente sintético colombiano/LATAM."""

    respondent_id: str
    actor_agent_id: Optional[int] = None
    channel_origin: str = "structured_survey"
    status: str = "completed"
    city_divipola: str
    city_name: str
    region_macro: str
    stratum_code: str
    wealth_tier_norm: int = Field(..., ge=1, le=5)
    age: int = Field(..., ge=18, le=90)
    gender: str
    dynamic_study_role: str
    attitude_segment: str
    pain_score: int = Field(..., ge=1, le=10)
    trust_score: int = Field(..., ge=1, le=10)
    nps_score: int = Field(..., ge=0, le=10)
    csat_score: int = Field(..., ge=1, le=5)
    ces_score: int = Field(..., ge=1, le=7)
    vw_too_cheap: float = Field(..., gt=0)
    vw_cheap: float = Field(..., gt=0)
    vw_expensive: float = Field(..., gt=0)
    vw_too_expensive: float = Field(..., gt=0)
    nms_intent_cheap: int = Field(..., ge=1, le=5)
    nms_intent_expensive: int = Field(..., ge=1, le=5)
    gg_grid: Dict[str, float]
    preferred_channel: str
    main_objection: str
    verbatim_response: str
    respondent_weight: float = 1.0
    created_at: str


class SurveyEngine:
    """Genera, valida y persiste encuestas estructuradas (N=300+) en `simulation_channels.db`."""

    def __init__(
        self,
        country_code: str = "co",
        llm_client: Optional[LLMClient] = None,
    ):
        self.country_code = (country_code or "co").strip().lower()
        self.sampler = DemographicSampler(country_code=self.country_code)
        self._llm_client = llm_client

    def _get_llm(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def run_survey(
        self,
        simulation_id: str,
        sim_dir: Path,
        sample_size: int = 300,
        target_cities: Optional[List[str]] = None,
        target_strata: Optional[List[str]] = None,
        study_topic: str = "Estudio de Mercado en Colombia",
        price_ladder: Optional[List[int]] = None,
        use_llm: bool = False,
        batch_size: int = 10,
        max_workers: int = 3,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_checker: Optional[Callable[[], bool]] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Ejecuta encuesta estratificada y persiste 100% de registros en `survey_responses`."""
        is_commission_mode = False
        if not price_ladder:
            try:
                from .simulation_manager import SimulationManager
                from .study_context_builder import load_study_context
                st = SimulationManager().get_simulation(simulation_id)
                if st and st.project_id:
                    sctx = load_study_context(st.project_id)
                    if sctx:
                        bmt = sctx.get("business_model_template") or {}
                        if bmt.get("revenue_mechanism") == "comision_pct" and bmt.get("commission_ladder_pct"):
                            price_ladder = [float(p) for p in bmt["commission_ladder_pct"]]
                            is_commission_mode = True
                        elif isinstance(sctx.get("price_ladder_cop"), list) and sctx["price_ladder_cop"]:
                            price_ladder = [int(p) for p in sctx["price_ladder_cop"]]
            except Exception:
                pass
        prices = sorted(price_ladder or DEFAULT_GG_PRICES_COP)
        if prices and max(prices) <= 100:
            is_commission_mode = True
        study_seed = (
            int(seed)
            if seed is not None
            else (int(hashlib.sha256(f"{simulation_id}:{study_topic}".encode("utf-8")).hexdigest()[:8], 16) % 100000)
        )
        allocations = self.sampler.sample_allocations(
            count=sample_size,
            country_code=self.country_code,
            target_cities=target_cities,
            target_strata=target_strata,
            seed=study_seed + sample_size,
        )

        # Dividir en lotes compactos para prevenir HTTP 413 en FreeLLMAPI
        batches: List[List[DemographicAllocation]] = [
            allocations[i : i + max(1, batch_size)]
            for i in range(0, len(allocations), max(1, batch_size))
        ]
        all_records: List[StructuredSurveyRecord] = []
        llm_recovered_batches = 0

        if not use_llm:
            for b_idx, batch in enumerate(batches):
                if cancel_checker and cancel_checker():
                    break
                for alloc in batch:
                    all_records.append(self._synthesize_record(alloc, study_topic, prices, seed_offset=study_seed))
                if progress_callback:
                    progress_callback(len(all_records), sample_size, f"Lote {b_idx+1}/{len(batches)}")
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
                futures = {
                    pool.submit(
                        self._run_llm_batch_safe, batch, study_topic, prices
                    ): b_idx
                    for b_idx, batch in enumerate(batches)
                }
                for fut in concurrent.futures.as_completed(futures):
                    if cancel_checker and cancel_checker():
                        break
                    recs, recovered = fut.result()
                    if recovered:
                        llm_recovered_batches += 1
                    all_records.extend(recs)
                    if progress_callback:
                        progress_callback(
                            min(len(all_records), sample_size),
                            sample_size,
                            f"Encuestas recolectadas: {len(all_records)}/{sample_size}",
                        )

        # Ordenar por respondent_id numérico y persistir en simulation_channels.db
        all_records.sort(key=lambda r: int(r.respondent_id.split("_")[-1]))
        store = ChannelSQLiteStore(Path(sim_dir))
        rows_to_insert = []
        for rec in all_records:
            d = rec.model_dump()
            d["gg_grid_json"] = json.dumps(d.pop("gg_grid"), ensure_ascii=False)
            rows_to_insert.append(d)
        inserted = store.record_survey_responses_bulk(simulation_id, rows_to_insert)

        return {
            "simulation_id": simulation_id,
            "requested_n": sample_size,
            "completed_n": inserted,
            "use_llm": use_llm,
            "llm_recovered_batches": llm_recovered_batches,
            "pricing_mode": "comision_pct" if is_commission_mode else "cop",
            "evaluated_ladder": prices,
            "db_path": str(store.db_path),
            "table": "survey_responses",
        }

    def _run_llm_batch_safe(
        self,
        batch: List[DemographicAllocation],
        study_topic: str,
        prices: List[int],
    ) -> tuple[List[StructuredSurveyRecord], bool]:
        """Consulta el LLM en un lote pequeño; ante error/413 divide o respalda sin fallar."""
        compact_respondents = [
            {
                "slot": a.slot_index,
                "city": a.city_name,
                "stratum": a.stratum_code,
                "role": a.dynamic_study_role,
                "attitude": a.attitude_segment,
            }
            for a in batch
        ]
        prompt = (
            f"Estudio: {study_topic[:140]}\n"
            f"Respondentes colombianos: {json.dumps(compact_respondents, ensure_ascii=False)}\n"
            "Devuelve JSON con clave 'responses': lista del mismo largo con "
            "{'slot': int, 'pain_score': 1-10, 'trust_score': 1-10, 'nps_score': 0-10, "
            "'main_objection': texto corto, 'verbatim': opinión colombiana realista <=140 chars}."
        )
        recovered = False
        llm_by_slot: Dict[int, Dict[str, Any]] = {}
        try:
            res = self._get_llm().chat_json(
                messages=[
                    {
                        "role": "system",
                        "content": "Simulador de panel de encuesta colombiano. Responde SOLO JSON válido en español.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=900,
                max_attempts=1,
            )
            for item in res.get("responses", []):
                if isinstance(item, dict) and "slot" in item:
                    llm_by_slot[int(item["slot"])] = item
        except Exception as exc:  # noqa: BLE001
            recovered = True
            logger.warning(f"Lote LLM encuesta recuperado por respaldo determinista ({len(batch)} items): {exc}")

        records: List[StructuredSurveyRecord] = []
        for alloc in batch:
            llm_override = llm_by_slot.get(alloc.slot_index)
            records.append(self._synthesize_record(alloc, study_topic, prices, llm_override=llm_override))
        return records, recovered

    @staticmethod
    def _synthesize_record(
        alloc: DemographicAllocation,
        study_topic: str,
        prices: List[int],
        llm_override: Optional[Dict[str, Any]] = None,
        seed_offset: int = 7000,
    ) -> StructuredSurveyRecord:
        rng = random.Random(seed_offset + alloc.slot_index * 31)

        tier = alloc.wealth_tier_norm
        att = alloc.attitude_segment

        # Ancla económica Van Westendorp monótona (COP) escalada dinámicamente a `prices`
        sorted_p = sorted(prices) if prices else DEFAULT_GG_PRICES_COP
        ref_price = float(sorted_p[len(sorted_p) // 2])
        tier_mult = {1: 0.62, 2: 0.82, 3: 1.00, 4: 1.32, 5: 1.80}[tier]
        att_mult = {
            "promotor": 1.15,
            "neutral": 1.00,
            "esceptico": 0.85,
            "critico_hate": 0.70,
            "outlier": 0.95,
        }[att]
        anchor = ref_price * tier_mult * att_mult * rng.uniform(0.90, 1.12)
        if ref_price < 100:
            # Modo porcentaje de comisión (%)
            round_digits = 2
            min_step = max(0.2, ref_price * 0.12)
            vw_tc = round(max(0.25, anchor * 0.45), round_digits)
            vw_c = round(max(vw_tc + min_step, anchor * 0.78), round_digits)
            vw_e = round(max(vw_c + min_step * 1.4, anchor * 1.20), round_digits)
            vw_te = round(max(vw_e + min_step * 1.8, anchor * 1.65), round_digits)
        else:
            round_digits = -2 if ref_price >= 5000 else 0
            min_step = max(100.0, ref_price * 0.08)
            vw_tc = round(max(100.0, anchor * 0.42), round_digits)
            vw_c = round(max(vw_tc + min_step, anchor * 0.75), round_digits)
            vw_e = round(max(vw_c + min_step * 1.5, anchor * 1.20), round_digits)
            vw_te = round(max(vw_e + min_step * 2.0, anchor * 1.75), round_digits)

        # Curva Gabor-Granger monótona no creciente P(compra | precio)
        gg_grid: Dict[str, float] = {}
        prev_p = 1.0
        for p in prices:
            ratio = p / max(1.0, vw_e)
            raw_prob = max(0.02, min(0.95, (1.15 - 0.65 * ratio) * (0.55 + 0.6 * alloc.purchase_probability)))
            prob = round(min(prev_p, raw_prob), 2)
            gg_grid[str(p)] = prob
            prev_p = prob

        tier_trust_adj = {1: -1.1, 2: -0.5, 3: 0.1, 4: 0.7, 5: 1.2}[tier]
        age_pain_adj = 0.7 if alloc.age >= 45 else (-0.4 if alloc.age <= 25 else 0.1)
        region_adj = {
            "Andina": 0.2,
            "Andina Centro": 0.2,
            "Antioquia": 0.35,
            "Paisa / Eje Cafetero": 0.35,
            "Caribe": -0.25,
            "Pacífica": -0.3,
        }.get(alloc.region_macro, 0.0)

        pain_raw = {"promotor": 7, "neutral": 6, "esceptico": 7, "critico_hate": 8, "outlier": 5}[att]
        pain_base = max(1, min(10, int(round(pain_raw + age_pain_adj + (3 - tier) * 0.35 + rng.choice([-1, 0, 1])))))

        trust_raw = {"promotor": 8, "neutral": 6, "esceptico": 4, "critico_hate": 2, "outlier": 5}[att]
        trust_base = max(1, min(10, int(round(trust_raw + tier_trust_adj + region_adj + rng.choice([-1, 0, 1])))))

        # NPS 0-10 dependiente de actitud, estrato/tier, confianza y probabilidad de compra (con pasivos 7-8 reales)
        nps_raw = {"promotor": 9, "neutral": 7, "esceptico": 5, "critico_hate": 2, "outlier": 6}[att]
        nps_adj = (trust_base - 5) * 0.30 + tier_trust_adj * 0.45 + (alloc.purchase_probability - 0.5) * 1.2
        nps_base = max(0, min(10, int(round(nps_raw + nps_adj + rng.choice([-1, 0, 0, 1])))))

        # CSAT (1-5) y CES (1-7) desacoplados de NPS>=7
        csat_raw = {"promotor": 4, "neutral": 3, "esceptico": 3, "critico_hate": 2, "outlier": 3}[att]
        csat_base = max(1, min(5, int(round(csat_raw + (0.4 if tier >= 4 else -0.2) + rng.choice([-1, 0, 0, 1])))))
        ces_raw = {"promotor": 5, "neutral": 4, "esceptico": 3, "critico_hate": 2, "outlier": 4}[att]
        ces_base = max(1, min(7, int(round(ces_raw + (0.5 if alloc.age < 38 else -0.4) + rng.choice([-1, 0, 1])))))

        default_objections = {
            "promotor": "Claridad en tiempos de entrega y soporte",
            "neutral": "Verificar valor real frente a opciones tradicionales",
            "esceptico": "Desconfianza de pago anticipado o falta de garantías",
            "critico_hate": "Temor a estafa o falta de respaldo verificable",
            "outlier": "Prefiere compra o trato directo tradicional",
        }
        default_verbatim = (
            f"Desde {alloc.city_name} ({alloc.stratum_code}, {alloc.dynamic_study_role}): "
            + {
                "promotor": "Sí utilizaría el servicio si me entregan condiciones claras, seguimiento y soporte directo por WhatsApp.",
                "neutral": "Me interesa comparar primero si ofrece una ventaja real frente a hacerlo por mi cuenta o en canales tradicionales.",
                "esceptico": "No pago por adelantado sin ver NIT, términos claros, garantía y respaldo real sin promesas falsas.",
                "critico_hate": "La gente desconfía de plataformas nuevas sin historial; sin respaldo verificable no transfiero nada.",
                "outlier": "Acá resolvemos casi todo directamente en el comercio local o con personas de confianza.",
            }[att]
        )

        ov = llm_override or {}
        pain_score = max(1, min(10, int(ov.get("pain_score", pain_base))))
        trust_score = max(1, min(10, int(ov.get("trust_score", trust_base))))
        nps_score = max(0, min(10, int(ov.get("nps_score", nps_base))))
        main_obj = str(ov.get("main_objection") or default_objections[att])[:160]
        verbatim = str(ov.get("verbatim") or default_verbatim)[:280]

        return StructuredSurveyRecord(
            respondent_id=f"resp_{alloc.slot_index + 1:04d}",
            actor_agent_id=alloc.slot_index,
            channel_origin="structured_survey",
            status="completed",
            city_divipola=alloc.divipola_code,
            city_name=alloc.city_name,
            region_macro=alloc.region_macro,
            stratum_code=alloc.stratum_code,
            wealth_tier_norm=tier,
            age=alloc.age,
            gender=alloc.gender,
            dynamic_study_role=alloc.dynamic_study_role,
            attitude_segment=att,
            pain_score=pain_score,
            trust_score=trust_score,
            nps_score=nps_score,
            csat_score=csat_base,
            ces_score=ces_base,
            vw_too_cheap=vw_tc,
            vw_cheap=vw_c,
            vw_expensive=vw_e,
            vw_too_expensive=vw_te,
            nms_intent_cheap=4 if att in ("promotor", "neutral") else 3,
            nms_intent_expensive=3 if att == "promotor" else 1,
            gg_grid=gg_grid,
            preferred_channel=alloc.preferred_channels[0] if alloc.preferred_channels else "whatsapp_1on1",
            main_objection=main_obj,
            verbatim_response=verbatim,
            respondent_weight=1.0,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
