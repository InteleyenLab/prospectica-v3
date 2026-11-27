"""Actores del enjambre estilo Orkas: ModeratorCommander, ArchetypeAgent y SurveyWorker."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..utils.llm_client import LLMClient
from .memory import SwarmMemoryStore
from .rehydrator import SwarmRehydrator
from .router import parse_mentions
from .scheduler import SwarmScheduler
from .state import SwarmMessage, SwarmSessionState, TurnOutcome
from .task_board import TaskBoard
from .transcript import SwarmTranscript


class SurveyWorker:
    """Worker anónimo paralelo invocado por `ModeratorCommander.run_worker` o `dispatch_to`."""

    tools: List[str] = []

    def execute(self, prompt: str, context: str = "", llm: Optional[LLMClient] = None) -> str:
        if llm is not None:
            try:
                return llm.chat(
                    messages=[
                        {"role": "system", "content": "Eres un asistente investigador cuantitativo en español. Responde de forma concisa con evidencia."},
                        {"role": "user", "content": f"Contexto:\n{context[:1200]}\n\nTarea:\n{prompt}"},
                    ],
                    temperature=0.3,
                    max_tokens=450,
                )
            except Exception:
                pass
        return f"Análisis resumido del worker sobre '{prompt[:80]}': {context[:240] or 'Sin datos adicionales en caché.'}"


class ArchetypeAgent:
    """Agente ciudadano/actor sintético sin herramientas de despacho (`tools = []`)."""

    tools: List[str] = []

    def __init__(self, profile: Dict[str, Any], memories: Optional[List[str]] = None):
        self.profile = profile
        self.name = str(profile.get("name") or profile.get("username") or "Ciudadano")
        self.username = str(profile.get("username") or self.name)
        self.memories = memories or []

    def respond(self, prompt: str, llm: Optional[LLMClient] = None) -> TurnOutcome:
        if "<handback />" in prompt:
            return TurnOutcome(
                kind="handoff",
                content=f"@{self.name} devuelve la palabra al moderador.",
                active_recipient="ModeratorCommander",
            )

        city = self.profile.get("city_name") or "Colombia"
        stratum = self.profile.get("stratum_code") or "N/D"
        attitude = self.profile.get("attitude_segment") or "neutral"
        persona = self.profile.get("persona") or self.profile.get("bio") or ""
        mem_block = "\n".join(f"- {m}" for m in self.memories[:4]) if self.memories else "- Sin intervenciones previas."

        if llm is not None:
            try:
                reply = llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"Actúas en primera persona como {self.name} ({city}, {stratum}, postura {attitude}). "
                                f"Perfil: {persona[:400]}\nMemorias:\n{mem_block}\n"
                                "Responde estrictamente en español en 2-4 oraciones coherentes con tu postura."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.55,
                    max_tokens=380,
                )
                return TurnOutcome(kind="reply", content=reply.strip(), active_recipient=self.name)
            except Exception:
                pass

        mem_snippet = f" Recuerdo haber comentado: \"{self.memories[0][:100]}\"." if self.memories else ""
        text = (
            f"Hablando desde {city} (estrato {stratum}, postura {attitude}): "
            f"frente a '{prompt[:90]}', priorizo ver respaldo verificable, claridad en costos en COP "
            f"y cero promesas irreales.{mem_snippet}"
        )
        return TurnOutcome(kind="reply", content=text, active_recipient=self.name)


class ModeratorCommander:
    """Orquestador central del enjambre con herramientas de despacho, handoff y consultas SQL/bundle."""

    tools: List[str] = [
        "dispatch_to",
        "hand_off_to",
        "run_worker",
        "query_analytics_bundle",
        "query_channel_sql",
    ]

    def __init__(
        self,
        simulation_id: str,
        sim_dir: Path,
        scheduler: Optional[SwarmScheduler] = None,
        use_llm: bool = False,
        llm_client: Optional[LLMClient] = None,
    ):
        self.simulation_id = simulation_id
        self.sim_dir = Path(sim_dir)
        self.rehydrator = SwarmRehydrator(simulation_id, self.sim_dir)
        self.transcript = SwarmTranscript(self.sim_dir)
        self.task_board = TaskBoard(self.sim_dir / "swarm_memory")
        self.memory_store = SwarmMemoryStore(self.sim_dir)
        self.scheduler = scheduler or SwarmScheduler(global_slots=2, nested_worker_slots=4)
        self.use_llm = use_llm
        self.llm = llm_client if llm_client is not None else (LLMClient() if use_llm else None)

    def _find_profile(self, target_name: str) -> Dict[str, Any]:
        profiles = self.rehydrator.load_profiles()
        t_low = (target_name or "").strip().lower()
        for p in profiles:
            if str(p.get("name", "")).lower() == t_low or str(p.get("username", "")).lower() == t_low:
                return p
        for p in profiles:
            if t_low and (t_low in str(p.get("name", "")).lower() or t_low in str(p.get("username", "")).lower()):
                return p
        return profiles[0] if profiles else {"user_id": 0, "name": target_name, "username": target_name}

    def query_analytics_bundle(self, chapter: Optional[str] = None) -> Dict[str, Any]:
        bundle = self.rehydrator.load_analytics_bundle()
        if not bundle:
            return {"available": False, "note": "Aún no existe analytics_bundle.json"}
        if chapter:
            return {"available": True, "slice": (bundle.get("chapter_slices") or {}).get(chapter.zfill(2), {})}
        return {
            "available": True,
            "data_audit": bundle.get("data_audit"),
            "optimal_price": (bundle.get("pricing_econometrics") or {}).get("gabor_granger", {}).get("optimal_price"),
            "nps": (bundle.get("cx_and_polarization") or {}).get("nps"),
        }

    def query_channel_sql(self, channel_id: Optional[str] = None, limit: int = 8) -> List[Dict[str, Any]]:
        return self.rehydrator.query_channel_sql(channel_id=channel_id, limit=limit)

    def run_worker(self, prompt: str) -> str:
        ctx = str(self.query_analytics_bundle())
        return SurveyWorker().execute(prompt=prompt, context=ctx, llm=self.llm)

    def dispatch_to(
        self,
        session_id: str,
        subtasks: List[Dict[str, Any]],
        worker_runner: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Valida DAG acíclico y ejecuta en paralelo sobre `SwarmScheduler` sin deadlocks."""
        for st in subtasks:
            self.task_board.upsert_task(
                task_id=str(st["id"]),
                session_id=session_id,
                target_actor=str(st.get("target") or "SurveyWorker"),
                prompt=str(st.get("prompt") or ""),
                status="running",
            )

        def _default_worker(task: Dict[str, Any]) -> Dict[str, Any]:
            target = str(task.get("target") or "SurveyWorker")
            prompt = str(task.get("prompt") or "")
            if target == "SurveyWorker":
                out_text = self.run_worker(prompt)
            else:
                prof = self._find_profile(target)
                mems = self.rehydrator.load_actor_memories(
                    actor_name=str(prof.get("name") or target),
                    actor_id=prof.get("user_id"),
                )
                out_text = ArchetypeAgent(prof, mems).respond(prompt, llm=self.llm).content
            self.task_board.upsert_task(
                task_id=str(task["id"]),
                session_id=session_id,
                target_actor=target,
                prompt=prompt,
                status="completed",
                result_text=out_text,
            )
            return {"task_id": task["id"], "target": target, "content": out_text, "status": "completed"}

        runner = worker_runner or _default_worker
        return self.scheduler.execute_dispatch_dag(subtasks, runner)

    def hand_off_to(self, session: SwarmSessionState, target_actor: str, user_message: str) -> tuple[TurnOutcome, TurnOutcome]:
        """Cede control a `target_actor`: Commander retorna `TurnOutcome(kind='silent')` y el agente responde."""
        prof = self._find_profile(target_actor)
        canonical_name = str(prof.get("name") or target_actor)
        session.active_recipient = canonical_name
        session.updated_at = datetime.now(timezone.utc).isoformat()
        self.transcript.save_session(session)

        mems = self.rehydrator.load_actor_memories(
            actor_name=canonical_name,
            actor_id=prof.get("user_id"),
        )
        agent_outcome = ArchetypeAgent(prof, mems).respond(user_message, llm=self.llm)
        commander_outcome = TurnOutcome(kind="silent", content="", active_recipient=canonical_name)
        return commander_outcome, agent_outcome

    def handle_user_message(self, session: SwarmSessionState, user_text: str) -> Dict[str, Any]:
        """Procesa un mensaje humano, aplica enrutamiento anti-bucle y persiste el turno completo."""
        human_msg = SwarmMessage(
            message_id=f"msg_{uuid.uuid4().hex[:10]}",
            session_id=session.session_id,
            from_kind="human",
            sender_name="Usuario",
            recipient_name=session.active_recipient,
            content=user_text,
            mentions=parse_mentions(user_text, from_kind="human", known_agents=session.known_agents),
        )
        self.transcript.append_message(human_msg)

        # Solicitud de regreso al Commander
        if "<handback />" in user_text or "@ModeratorCommander" in user_text:
            session.active_recipient = "ModeratorCommander"
            session.updated_at = datetime.now(timezone.utc).isoformat()
            self.transcript.save_session(session)
            reply_msg = SwarmMessage(
                message_id=f"msg_{uuid.uuid4().hex[:10]}",
                session_id=session.session_id,
                from_kind="commander",
                sender_name="ModeratorCommander",
                recipient_name="Usuario",
                content="Control retomado por ModeratorCommander. ¿Qué consulta o segmento deseas explorar?",
            )
            self.transcript.append_message(reply_msg)
            return {"session": session.to_dict(), "replies": [reply_msg.to_dict()], "tool_calls": []}

        # Caso 1: Sesión actualmente en handoff con un agente específico
        if session.active_recipient != "ModeratorCommander" and not human_msg.mentions:
            prof = self._find_profile(session.active_recipient)
            mems = self.rehydrator.load_actor_memories(
                actor_name=session.active_recipient,
                actor_id=prof.get("user_id"),
            )
            agent_out = ArchetypeAgent(prof, mems).respond(user_text, llm=self.llm)
            reply_msg = SwarmMessage(
                message_id=f"msg_{uuid.uuid4().hex[:10]}",
                session_id=session.session_id,
                from_kind="agent",
                sender_name=session.active_recipient,
                recipient_name="Usuario",
                content=agent_out.content,
                outcome_kind=agent_out.kind,
            )
            self.transcript.append_message(reply_msg)
            return {"session": session.to_dict(), "replies": [reply_msg.to_dict()], "tool_calls": []}

        # Caso 2: Usuario menciona explícitamente @Agente(s) -> handoff si es 1, dispatch paralelo si son >=2
        tool_calls_log: List[Dict[str, Any]] = []
        if len(human_msg.mentions) == 1:
            target = human_msg.mentions[0]
            cmd_out, agent_out = self.hand_off_to(session, target, user_text)
            tool_calls_log.append({"tool": "hand_off_to", "target": target, "commander_outcome": cmd_out.kind})
            reply_msg = SwarmMessage(
                message_id=f"msg_{uuid.uuid4().hex[:10]}",
                session_id=session.session_id,
                from_kind="agent",
                sender_name=session.active_recipient,
                recipient_name="Usuario",
                content=agent_out.content,
                tool_calls=tool_calls_log,
            )
            self.transcript.append_message(reply_msg)
            return {
                "session": session.to_dict(),
                "commander_outcome": cmd_out.to_dict(),
                "replies": [reply_msg.to_dict()],
                "tool_calls": tool_calls_log,
            }

        # Caso 3: Consulta amplia o multi-mención -> ModeratorCommander despacha DAG en paralelo + consulta bundle/SQL
        targets = human_msg.mentions or (session.known_agents[:3] if session.known_agents else ["SurveyWorker"])
        subtasks = [
            {"id": f"st_{idx+1}", "target": tgt, "prompt": user_text}
            for idx, tgt in enumerate(targets[:5])
        ]
        dispatch_results = self.dispatch_to(session.session_id, subtasks)
        bundle_stats = self.query_analytics_bundle()
        sql_samples = self.query_channel_sql(limit=4)
        tool_calls_log.append({"tool": "dispatch_to", "count": len(dispatch_results)})
        tool_calls_log.append({"tool": "query_analytics_bundle", "available": bundle_stats.get("available")})
        tool_calls_log.append({"tool": "query_channel_sql", "rows": len(sql_samples)})

        lines = [
            f"Síntesis del Enjambre ({len(dispatch_results)} agentes consultados):",
            *[f"- **{r['target']}**: {r['content']}" for r in dispatch_results],
        ]
        if bundle_stats.get("available"):
            lines.append(
                f"\nRespaldo cuantitativo (`analytics_bundle.json`): precio óptimo Gabor-Granger = "
                f"{bundle_stats.get('optimal_price')} | cobertura BD = "
                f"{(bundle_stats.get('data_audit') or {}).get('db_coverage_pct', 100.0)}%."
            )

        reply_msg = SwarmMessage(
            message_id=f"msg_{uuid.uuid4().hex[:10]}",
            session_id=session.session_id,
            from_kind="commander",
            sender_name="ModeratorCommander",
            recipient_name="Usuario",
            content="\n".join(lines),
            mentions=[],  # Commander nunca dispara menciones salientes
            tool_calls=tool_calls_log,
        )
        self.transcript.append_message(reply_msg)
        return {"session": session.to_dict(), "replies": [reply_msg.to_dict()], "tool_calls": tool_calls_log}


class SwarmOrchestrator:
    """Fachada principal para crear/reanudar sesiones persistentes y enviar mensajes."""

    def __init__(self, simulation_id: str, sim_dir: Path, use_llm: bool = False):
        self.simulation_id = simulation_id
        self.sim_dir = Path(sim_dir)
        self.rehydrator = SwarmRehydrator(simulation_id, self.sim_dir)
        self.transcript = SwarmTranscript(self.sim_dir)
        self.commander = ModeratorCommander(simulation_id, self.sim_dir, use_llm=use_llm)

    def create_or_get_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        if session_id:
            existing = self.transcript.get_session(session_id)
            if existing:
                return {
                    "session": existing.to_dict(),
                    "messages": self.transcript.list_messages(session_id=session_id),
                    "rehydration": self.rehydrator.rehydrate_context(),
                }

        ctx = self.rehydrator.rehydrate_context()
        sid = session_id or f"sws_{uuid.uuid4().hex[:10]}"
        session = SwarmSessionState(
            session_id=sid,
            simulation_id=self.simulation_id,
            active_recipient="ModeratorCommander",
            known_agents=ctx["known_agents"][:40],
        )
        self.transcript.save_session(session)
        return {
            "session": session.to_dict(),
            "messages": self.transcript.list_messages(session_id=sid),
            "rehydration": ctx,
        }

    def send_message(self, session_id: str, text: str) -> Dict[str, Any]:
        session = self.transcript.get_session(session_id)
        if not session:
            created = self.create_or_get_session(session_id=session_id)
            session = self.transcript.get_session(created["session"]["session_id"])
        assert session is not None
        return self.commander.handle_user_message(session, text)
