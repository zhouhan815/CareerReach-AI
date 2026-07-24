from __future__ import annotations

from typing import Any, TypedDict

from boss_agent_cli.ai.service import AIService
from boss_agent_cli.communication.memory import CommunicationMemoryStore
from boss_agent_cli.communication.models import OpportunityContext, OpportunitySeed
from boss_agent_cli.communication.planner import CommunicationPlanner
from boss_agent_cli.communication.retrieval import CommunicationRetriever, evidence_from_text


class CommunicationState(TypedDict, total=False):
	seed: OpportunitySeed
	context: OpportunityContext
	plan: Any
	runtime: dict[str, Any]


class BossDataAgent:
	"""Data-only agent that prepares facts and evidence for communication planning."""

	def __init__(self, retriever: CommunicationRetriever | None = None) -> None:
		self._retriever = retriever

	def collect(self, seed: OpportunitySeed) -> OpportunityContext:
		evidence = list(self._retriever.retrieve(seed)) if self._retriever else []
		evidence.extend(evidence_from_text(text, prefix="direct") for text in seed.extra_context if text.strip())
		missing_info: list[str] = []
		if not seed.company:
			missing_info.append("company")
		if not seed.job_title:
			missing_info.append("job_title")
		if not evidence:
			missing_info.append("rag_evidence")
		return OpportunityContext(
			company=seed.company,
			job_title=seed.job_title,
			job_id=seed.job_id,
			security_id=seed.security_id,
			contact_id=seed.contact_id,
			goal=seed.goal,
			latest_message=seed.latest_message,
			facts=seed.facts,
			evidence=evidence,
			missing_info=missing_info,
			risk_flags=[],
		)


class CommunicationWorkflow:
	"""Two-agent orchestration with optional LangGraph runtime."""

	def __init__(
		self,
		*,
		retriever: CommunicationRetriever | None = None,
		ai_service: AIService | None = None,
		mode: str = "auto",
		memory_store: CommunicationMemoryStore | None = None,
		outreach_playbook: dict[str, Any] | None = None,
		use_langgraph: bool = True,
	) -> None:
		self._data_agent = BossDataAgent(retriever)
		self._communication_agent = CommunicationPlanner(
			ai_service=ai_service,
			mode=mode,
			outreach_playbook=outreach_playbook,
		)
		self._memory_store = memory_store
		self._use_langgraph = use_langgraph

	def run(self, seed: OpportunitySeed, *, save: bool = True) -> dict[str, Any]:
		state = {"seed": seed}
		if self._use_langgraph:
			result = self._run_with_langgraph(state)
		else:
			result = self._run_sequential(state)
		if save and self._memory_store:
			path = self._memory_store.save_plan(result["context"], result["plan"], runtime=result["runtime"])
			result["memory_path"] = str(path)
		return {
			"context": result["context"].to_dict(),
			"plan": result["plan"].to_dict(),
			"runtime": result["runtime"],
			"memory_path": result.get("memory_path"),
		}

	def _run_with_langgraph(self, initial_state: dict[str, Any]) -> dict[str, Any]:
		try:
			from langgraph.graph import END, START, StateGraph
		except Exception:
			return self._run_sequential(initial_state, langgraph_available=False)

		def boss_data_node(state: dict[str, Any]) -> dict[str, Any]:
			return {"context": self._data_agent.collect(state["seed"])}

		def communication_node(state: dict[str, Any]) -> dict[str, Any]:
			return {"plan": self._communication_agent.plan(state["context"])}

		graph = StateGraph(CommunicationState)
		graph.add_node("boss_data_agent", boss_data_node)
		graph.add_node("communication_agent", communication_node)
		graph.add_edge(START, "boss_data_agent")
		graph.add_edge("boss_data_agent", "communication_agent")
		graph.add_edge("communication_agent", END)
		app = graph.compile()
		result = app.invoke(initial_state)
		result["runtime"] = {"orchestrator": "langgraph", "langgraph_available": True}
		return result

	def _run_sequential(self, initial_state: dict[str, Any], *, langgraph_available: bool | None = None) -> dict[str, Any]:
		context = self._data_agent.collect(initial_state["seed"])
		plan = self._communication_agent.plan(context)
		return {
			"seed": initial_state["seed"],
			"context": context,
			"plan": plan,
			"runtime": {
				"orchestrator": "sequential_fallback",
				"langgraph_available": langgraph_available,
			},
		}
