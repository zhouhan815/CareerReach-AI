from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from boss_agent_cli.ai.config import AIConfigStore
from boss_agent_cli.ai.service import AIService
from boss_agent_cli.communication.export_excel import (
	CommunicationExcelDependencyError,
	export_communication_workbook,
	load_rows_from_workbook,
)
from boss_agent_cli.communication.memory import CommunicationMemoryStore
from boss_agent_cli.communication.models import OpportunitySeed
from boss_agent_cli.communication.outreach_playbook import load_default_outreach_playbook
from boss_agent_cli.communication.retrieval import build_communication_retriever
from boss_agent_cli.communication.workflow import CommunicationWorkflow
from boss_agent_cli.display import boss_command_for_ctx, handle_error_output, handle_output
from boss_agent_cli.rag.chroma_health import check_chroma_runtime
from boss_agent_cli.rag.store import RagDependencyError


@click.group("communication")
def communication_group() -> None:
	"""Communication Agent for evidence-backed outreach plans."""


@communication_group.command("plan")
@click.option("--company", default="", help="Company name")
@click.option("--job-title", default="", help="Job title")
@click.option("--job-id", default="", help="Job id")
@click.option("--security-id", default="", help="Security id")
@click.option("--contact-id", default="", help="Contact/friend id")
@click.option(
	"--goal",
	default="initial_outreach",
	type=click.Choice(["initial_outreach", "follow_up", "reply", "interview_confirm"]),
	help="Communication goal",
)
@click.option("--latest-message", default="", help="Latest recruiter message")
@click.option("--context", "extra_context", multiple=True, help="Direct evidence/context text")
@click.option("--collection", default="career_rag", help="ChromaDB collection name")
@click.option("--chroma-url", envvar="BOSS_RAG_CHROMA_URL", default=None, help="ChromaDB server URL")
@click.option("--top-k", default=8, type=int, help="RAG evidence count")
@click.option("--mode", default="auto", type=click.Choice(["auto", "ai", "rules"]), help="Planning mode")
@click.option("--use-rag/--no-rag", default=True, help="Retrieve evidence from ChromaDB")
@click.option("--save/--no-save", default=True, help="Save generated plan to communication memory")
@click.pass_context
def plan_cmd(
	ctx: click.Context,
	company: str,
	job_title: str,
	job_id: str,
	security_id: str,
	contact_id: str,
	goal: str,
	latest_message: str,
	extra_context: tuple[str, ...],
	collection: str,
	chroma_url: str | None,
	top_k: int,
	mode: str,
	use_rag: bool,
	save: bool,
) -> None:
	"""Generate one evidence-backed communication plan."""
	workflow = _build_workflow(
		ctx,
		collection=collection,
		chroma_url=chroma_url,
		top_k=top_k,
		mode=mode,
		use_rag=use_rag,
	)
	if workflow is None:
		return
	seed = OpportunitySeed(
		company=company,
		job_title=job_title,
		job_id=job_id,
		security_id=security_id,
		contact_id=contact_id,
		goal=goal,
		latest_message=latest_message,
		extra_context=list(extra_context),
	)
	try:
		result = workflow.run(seed, save=save)
	except Exception as exc:
		handle_error_output(
			ctx,
			"ai communication plan",
			code="COMMUNICATION_PLAN_FAILED",
			message=str(exc),
			recoverable=True,
			recovery_action="Check AI config/RAG evidence, or retry with --mode rules --no-rag.",
		)
		return
	handle_output(
		ctx,
		"ai communication plan",
		result,
		hints={"next_actions": [boss_command_for_ctx(ctx, "ai communication export --input <xlsx>")]},
	)


@communication_group.command("export")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True, dir_okay=False), help="Input workbook")
@click.option("--sheet", "sheet_name", default=None, help="Input sheet name")
@click.option("--output", default=None, help="Output workbook path; omitted means update --input in place")
@click.option("--collection", default="career_rag", help="ChromaDB collection name")
@click.option("--chroma-url", envvar="BOSS_RAG_CHROMA_URL", default=None, help="ChromaDB server URL")
@click.option("--top-k", default=8, type=int, help="RAG evidence count")
@click.option("--limit", default=None, type=int, help="Maximum rows to process")
@click.option("--mode", default="rules", type=click.Choice(["auto", "ai", "rules"]), help="Planning mode")
@click.option("--use-rag/--no-rag", default=True, help="Retrieve evidence from ChromaDB")
@click.pass_context
def export_cmd(
	ctx: click.Context,
	input_path: str,
	sheet_name: str | None,
	output: str | None,
	collection: str,
	chroma_url: str | None,
	top_k: int,
	limit: int | None,
	mode: str,
	use_rag: bool,
) -> None:
	"""Append Communication Agent strategy and draft columns to an opportunity workbook."""
	workflow = _build_workflow(
		ctx,
		collection=collection,
		chroma_url=chroma_url,
		top_k=top_k,
		mode=mode,
		use_rag=use_rag,
	)
	if workflow is None:
		return
	input_workbook = Path(input_path).expanduser().resolve()
	try:
		rows = load_rows_from_workbook(input_workbook, sheet_name=sheet_name, limit=limit)
	except CommunicationExcelDependencyError as exc:
		handle_error_output(
			ctx,
			"ai communication export",
			code="RAG_DEPENDENCY_MISSING",
			message=str(exc),
			recoverable=True,
			recovery_action="pip install 'boss-agent-cli[rag]'",
		)
		return
	if output:
		output_path = Path(output).expanduser().resolve()
	else:
		output_path = input_workbook

	def plan_factory(seed: OpportunitySeed) -> dict[str, Any]:
		return workflow.run(seed, save=True)

	try:
		payload = export_communication_workbook(
			rows,
			output_path,
			plan_factory,
			input_path=input_workbook,
			sheet_name=sheet_name,
		)
	except Exception as exc:
		handle_error_output(
			ctx,
			"ai communication export",
			code="COMMUNICATION_PLAN_FAILED",
			message=str(exc),
			recoverable=True,
			recovery_action="Retry with --mode rules --no-rag, or inspect the input workbook.",
		)
		return
	handle_output(
		ctx,
		"ai communication export",
		payload,
		hints={"next_actions": [boss_command_for_ctx(ctx, f'rag index-companies --input "{output_path}"')]},
	)


def _build_workflow(
	ctx: click.Context,
	*,
	collection: str,
	chroma_url: str | None,
	top_k: int,
	mode: str,
	use_rag: bool,
) -> CommunicationWorkflow | None:
	retriever = None
	if use_rag:
		health = check_chroma_runtime(chroma_url=chroma_url)
		if not health.get("ok"):
			handle_error_output(
				ctx,
				"ai communication",
				code="RAG_CHROMA_UNAVAILABLE",
				message="ChromaDB runtime is unavailable for Communication Agent retrieval.",
				recoverable=True,
				recovery_action="Start/fix ChromaDB, or retry with --no-rag.",
				details={"chroma_runtime": _compact_health(health)},
			)
			return None
		try:
			retriever = build_communication_retriever(
				ctx.obj["data_dir"],
				collection_name=collection,
				chroma_url=chroma_url,
				top_k=top_k,
			)
		except RagDependencyError as exc:
			handle_error_output(
				ctx,
				"ai communication",
				code="RAG_DEPENDENCY_MISSING",
				message=str(exc),
				recoverable=True,
				recovery_action="pip install 'boss-agent-cli[rag]'",
			)
			return None
	ai_service = _create_ai_service(ctx) if mode in {"auto", "ai"} else None
	if mode == "ai" and ai_service is None:
		handle_error_output(
			ctx,
			"ai communication",
			code="AI_NOT_CONFIGURED",
			message="AI service is not configured.",
			recoverable=True,
			recovery_action="boss ai config --provider <provider> --model <model> --api-key <key>",
		)
		return None
	return CommunicationWorkflow(
		retriever=retriever,
		ai_service=ai_service,
		mode=mode,
		memory_store=CommunicationMemoryStore(ctx.obj["data_dir"]),
		outreach_playbook=load_default_outreach_playbook(ctx.obj["data_dir"]),
		use_langgraph=True,
	)


def _create_ai_service(ctx: click.Context) -> AIService | None:
	store = AIConfigStore(ctx.obj["data_dir"])
	if not store.is_configured():
		return None
	config = store.load_config()
	api_key = store.get_api_key()
	base_url = store.get_base_url()
	if not api_key or not base_url:
		return None
	return AIService(
		base_url=base_url,
		api_key=api_key,
		model=config["ai_model"],
		temperature=config.get("ai_temperature", 0.7),
		max_tokens=config.get("ai_max_tokens", 4096),
	)


def _compact_health(health: dict[str, Any]) -> dict[str, Any]:
	compact: dict[str, Any] = {}
	for key, value in health.items():
		if key in {"stdout", "stderr"} and isinstance(value, str):
			compact[key] = value[-4000:]
		else:
			compact[key] = value
	return compact
