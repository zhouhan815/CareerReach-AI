from __future__ import annotations

import time
from pathlib import Path

import click

from boss_agent_cli.auth.manager import AuthManager
from boss_agent_cli.cache.store import CacheStore
from boss_agent_cli.compliance import require_compliance_allowed
from boss_agent_cli.commands._platform import get_platform_instance
from boss_agent_cli.commands.search import _check_live_auth_before_search
from boss_agent_cli.display import (
	boss_command_for_ctx,
	error_contract_for_code,
	handle_auth_errors,
	handle_error_output,
	handle_output,
	render_simple_list,
)
from boss_agent_cli.opportunity.constraints import assess_fit_constraints
from boss_agent_cli.opportunity.export_excel import export_opportunities_xlsx
from boss_agent_cli.opportunity.filters import detect_company_too_large, detect_internship_like
from boss_agent_cli.opportunity.models import OpportunityCandidate
from boss_agent_cli.opportunity.pipeline import analyze_candidate, collect_opportunities
from boss_agent_cli.resume.models import resume_to_text
from boss_agent_cli.resume.store import ResumeStore
from boss_agent_cli.search_filters import SearchPipelinePlatformError


def _parse_csv(value: str) -> list[str]:
	return [part.strip() for part in value.split(",") if part.strip()]


def _load_resume_text(ctx: click.Context, resume_name: str) -> str | None:
	store = ResumeStore(ctx.obj["data_dir"] / "resumes")
	resume = store.get(resume_name)
	if resume is None:
		handle_error_output(
			ctx,
			"opportunity",
			code="RESUME_NOT_FOUND",
			message=f"未找到简历: {resume_name}",
			recoverable=True,
			recovery_action=boss_command_for_ctx(ctx, "resume list"),
		)
		return None
	return resume_to_text(resume)


def _cache_path(ctx: click.Context) -> Path:
	return ctx.obj["data_dir"] / "cache" / "boss_agent.db"


def _review_columns() -> list[tuple[str, str, str]]:
	return [
		("candidate_id", "id", "dim"),
		("company", "company", "green"),
		("title", "title", "cyan"),
		("city", "city", "yellow"),
		("salary", "salary", "magenta"),
		("resume_match_score", "match", "bold"),
		("internship_acceptance_score", "intern", "bold"),
		("recommendation_level", "level", "blue"),
		("status", "status", "white"),
	]


def _compact_review_item(item: dict) -> dict:
	fields = [
		"candidate_id",
		"run_id",
		"status",
		"query",
		"city",
		"company",
		"title",
		"salary",
		"location",
		"company_scale",
		"company_stage",
		"industry",
		"experience",
		"education",
		"boss_name",
		"boss_title",
		"company_business",
		"job_requirement_judgment",
		"weekly_days",
		"internship_duration",
		"resume_match_score",
		"internship_acceptance_score",
		"recommendation_level",
		"match_reasons",
		"acceptance_reasons",
		"risk_reasons",
		"greeting_message",
		"excluded_reason",
		"job_id",
	]
	return {field: item.get(field, "") for field in fields if field in item}


@click.group("opportunity")
def opportunity_group() -> None:
	"""AI 产品经理机会筛选、分析、导出和确认后触达。"""


@opportunity_group.command("collect")
@click.option("--query", default="AI产品经理", help="搜索关键词")
@click.option("--cities", default="上海,深圳", help="城市列表，逗号分隔")
@click.option("--resume", "resume_name", default="ai_pm_intern", help="用于匹配分析的本地简历名称")
@click.option("--pages", default=1, type=int, help="每个城市扫描页数")
@click.option("--limit", default=10, type=int, help="目标候选数量")
@click.option("--min-match", default=70, type=int, help="简历匹配度下限")
@click.option("--min-acceptance", default=58, type=int, help="正式岗接受实习可能性下限")
@click.option("--web-research/--no-web-research", default=False, help="是否进行公开网页业务摘要")
@click.pass_context
@handle_auth_errors("opportunity")
def collect_cmd(
	ctx: click.Context,
	query: str,
	cities: str,
	resume_name: str,
	pages: int,
	limit: int,
	min_match: int,
	min_acceptance: int,
	web_research: bool,
) -> None:
	"""搜索正式 AI PM 岗位，结合简历评分并写入机会池。"""
	resume_text = _load_resume_text(ctx, resume_name)
	if resume_text is None:
		return
	city_list = _parse_csv(cities)
	if not city_list:
		handle_error_output(ctx, "opportunity", code="INVALID_PARAM", message="cities 不能为空")
		return

	data_dir = ctx.obj["data_dir"]
	logger = ctx.obj["logger"]
	auth = AuthManager(data_dir, logger=logger, platform=ctx.obj.get("platform", "zhipin"))
	with CacheStore(_cache_path(ctx)) as cache:
		with get_platform_instance(ctx, auth) as platform:
			if not _check_live_auth_before_search(ctx, platform):
				return
			try:
				result = collect_opportunities(
					platform,
					cache,
					logger,
					resume_text=resume_text,
					query=query,
					cities=city_list,
					pages=max(1, pages),
					limit=max(1, limit),
					min_match=min_match,
					min_acceptance=min_acceptance,
					include_web_research=web_research,
				)
			except SearchPipelinePlatformError as exc:
				recoverable, recovery_action = error_contract_for_code(exc.code)
				handle_error_output(
					ctx,
					"opportunity",
					code=exc.code,
					message=exc.message or "机会搜索失败",
					recoverable=recoverable,
					recovery_action=recovery_action,
					details=exc.details,
				)
				return

	items = result["items"]
	handle_output(
		ctx,
		"opportunity",
		result,
		render=lambda data: render_simple_list(
			[item for item in items if item.get("status") == "pending"],
			"opportunity collect",
			_review_columns(),
		),
		hints={
			"next_actions": [
				boss_command_for_ctx(ctx, "opportunity review --status pending"),
				boss_command_for_ctx(ctx, "opportunity export"),
				boss_command_for_ctx(ctx, "opportunity confirm <candidate_id>"),
			]
		},
	)


@opportunity_group.command("review")
@click.option("--status", default=None, help="按状态筛选：pending/confirmed/rejected/sent/filtered/excluded")
@click.option("--limit", default=20, type=int, help="显示数量")
@click.option("--run-id", default=None, help="仅查看某次 collect 运行")
@click.option("--full/--compact", default=False, help="Include full JD and raw payload in JSON output")
@click.pass_context
def review_cmd(ctx: click.Context, status: str | None, limit: int, run_id: str | None, full: bool) -> None:
	"""查看机会池候选岗位。"""
	with CacheStore(_cache_path(ctx)) as cache:
		items = cache.list_opportunity_candidates(status=status, limit=limit, run_id=run_id)
	if not full:
		items = [_compact_review_item(item) for item in items]
	handle_output(
		ctx,
		"opportunity",
		{"status": status, "run_id": run_id, "count": len(items), "items": items},
		render=lambda data: render_simple_list(data["items"], "opportunity review", _review_columns()),
		hints={"next_actions": [boss_command_for_ctx(ctx, "opportunity export")]},
	)


@opportunity_group.command("refresh")
@click.option("--resume", "resume_name", default="ai_pm_intern", help="用于重新匹配分析的本地简历名称")
@click.option("--status", default=None, help="仅刷新某个状态的候选：pending/filtered/excluded/confirmed")
@click.option("--run-id", default=None, help="仅刷新某次 collect 运行")
@click.option("--min-match", default=70, type=int, help="简历匹配度下限")
@click.option("--min-acceptance", default=58, type=int, help="正式岗接受实习可能性下限")
@click.pass_context
def refresh_cmd(
	ctx: click.Context,
	resume_name: str,
	status: str | None,
	run_id: str | None,
	min_match: int,
	min_acceptance: int,
) -> None:
	"""用当前筛选、评分和话术规则重新刷新本地机会池。"""
	resume_text = _load_resume_text(ctx, resume_name)
	if resume_text is None:
		return
	stats = {"seen": 0, "pending": 0, "filtered": 0, "excluded": 0, "skipped_sent": 0}
	refreshed: list[dict] = []
	with CacheStore(_cache_path(ctx)) as cache:
		items = cache.list_opportunity_candidates(status=status, run_id=run_id)
		for item in items:
			stats["seen"] += 1
			if item.get("status") == "sent":
				stats["skipped_sent"] += 1
				continue
			internship_like, reasons = detect_internship_like(item)
			company_too_large, scale_reasons = detect_company_too_large(item)
			if internship_like or company_too_large:
				item["status"] = "excluded"
				item["excluded_reason"] = "；".join([*reasons, *scale_reasons])
				stats["excluded"] += 1
			else:
				item = analyze_candidate(item, resume_text, include_web_research=False)
				constraints = assess_fit_constraints(item, resume_text)
				if constraints.hard_exclusion_reasons:
					item["status"] = "excluded"
					item["excluded_reason"] = "；".join(constraints.hard_exclusion_reasons)
					stats["excluded"] += 1
				elif (
					int(item.get("resume_match_score") or 0) >= min_match
					and int(item.get("internship_acceptance_score") or 0) >= min_acceptance
				):
					item["status"] = "pending"
					item["excluded_reason"] = ""
					stats["pending"] += 1
				else:
					item["status"] = "filtered"
					item["excluded_reason"] = ""
					stats["filtered"] += 1
			cache.upsert_opportunity_candidate(OpportunityCandidate.from_dict(item).to_dict())
			refreshed.append(item)

	handle_output(
		ctx,
		"opportunity",
		{"status": status, "run_id": run_id, "stats": stats, "items": [_compact_review_item(item) for item in refreshed]},
		render=lambda data: render_simple_list(data["items"], "opportunity refresh", _review_columns()),
		hints={"next_actions": [boss_command_for_ctx(ctx, "opportunity review --status pending"), boss_command_for_ctx(ctx, "opportunity export --status pending")]},
	)


@opportunity_group.command("confirm")
@click.argument("candidate_id")
@click.pass_context
def confirm_cmd(ctx: click.Context, candidate_id: str) -> None:
	"""确认某个候选岗位可进入发送队列。"""
	with CacheStore(_cache_path(ctx)) as cache:
		updated = cache.update_opportunity_status(candidate_id, "confirmed")
		item = cache.get_opportunity_candidate(candidate_id) if updated else None
	handle_output(
		ctx,
		"opportunity",
		{"action": "confirm", "candidate_id": candidate_id, "updated": updated, "item": item},
		hints={"next_actions": [boss_command_for_ctx(ctx, "opportunity send --dry-run")]},
	)


@opportunity_group.command("reject")
@click.argument("candidate_id")
@click.pass_context
def reject_cmd(ctx: click.Context, candidate_id: str) -> None:
	"""拒绝某个候选岗位，避免发送。"""
	with CacheStore(_cache_path(ctx)) as cache:
		updated = cache.update_opportunity_status(candidate_id, "rejected")
	handle_output(
		ctx,
		"opportunity",
		{"action": "reject", "candidate_id": candidate_id, "updated": updated},
		hints={"next_actions": [boss_command_for_ctx(ctx, "opportunity review --status pending")]},
	)


@opportunity_group.command("export")
@click.option("--output", default=None, help="输出 xlsx 路径")
@click.option("--base-workbook", default=None, help="基于已有岗位追踪表合并更新；未指定 output 时会原地更新该表")
@click.option("--status", default=None, help="仅导出某个状态")
@click.option("--run-id", default=None, help="仅导出某次 collect 运行")
@click.option("--limit", default=None, type=int, help="最多导出多少条候选")
@click.pass_context
def export_cmd(
	ctx: click.Context,
	output: str | None,
	base_workbook: str | None,
	status: str | None,
	run_id: str | None,
	limit: int | None,
) -> None:
	"""导出机会池为 Excel 工作簿。"""
	with CacheStore(_cache_path(ctx)) as cache:
		items = cache.list_opportunity_candidates(status=status, run_id=run_id, limit=limit)
	base_path = Path(base_workbook) if base_workbook else None
	if output:
		output_path = Path(output)
	elif base_path is not None:
		output_path = base_path
	else:
		output_path = ctx.obj["data_dir"] / "exports" / f"opportunities-{time.strftime('%Y%m%d-%H%M%S')}.xlsx"
	exported = export_opportunities_xlsx(items, output_path, existing_path=base_path)
	handle_output(
		ctx,
		"opportunity",
		{
			"output": str(exported),
			"base_workbook": str(base_path) if base_path else None,
			"count": len(items),
			"status": status,
			"run_id": run_id,
			"limit": limit,
		},
		hints={"next_actions": [boss_command_for_ctx(ctx, "opportunity review --status pending")]},
	)


@opportunity_group.command("send")
@click.argument("candidate_ids", nargs=-1)
@click.option("--dry-run", is_flag=True, default=False, help="只预览，不发送")
@click.option("--limit", default=10, type=int, help="最多发送数量")
@click.pass_context
@handle_auth_errors("opportunity")
def send_cmd(ctx: click.Context, candidate_ids: tuple[str, ...], dry_run: bool, limit: int) -> None:
	"""仅向 confirmed 状态的候选岗位发送已生成话术。"""
	if not dry_run and not require_compliance_allowed(ctx, "greet"):
		return

	with CacheStore(_cache_path(ctx)) as cache:
		if candidate_ids:
			items = [cache.get_opportunity_candidate(candidate_id) for candidate_id in candidate_ids]
			items = [item for item in items if item is not None]
		else:
			items = cache.list_opportunity_candidates(status="confirmed", limit=limit)
		items = [item for item in items if item.get("status") == "confirmed"]

		if dry_run:
			handle_output(
				ctx,
				"opportunity",
				{"dry_run": True, "count": len(items), "items": items},
				render=lambda data: render_simple_list(data["items"], "opportunity send dry-run", _review_columns()),
				hints={"next_actions": [boss_command_for_ctx(ctx, "opportunity send")]},
			)
			return

		data_dir = ctx.obj["data_dir"]
		logger = ctx.obj["logger"]
		auth = AuthManager(data_dir, logger=logger, platform=ctx.obj.get("platform", "zhipin"))
		results = []
		with get_platform_instance(ctx, auth) as platform:
			for item in items[: max(1, limit)]:
				security_id = item.get("security_id", "")
				job_id = item.get("job_id", "")
				message = item.get("greeting_message", "")
				if not security_id or not job_id or not message:
					cache.record_opportunity_send(item["candidate_id"], security_id, job_id, "failed", "missing send fields")
					results.append({"candidate_id": item["candidate_id"], "ok": False, "error": "missing send fields"})
					continue
				if cache.is_greeted(security_id):
					cache.update_opportunity_status(item["candidate_id"], "sent")
					results.append({"candidate_id": item["candidate_id"], "ok": True, "skipped": "already greeted"})
					continue
				resp = platform.greet(security_id, job_id, message)
				if platform.is_success(resp):
					cache.record_greet(security_id, job_id)
					cache.update_opportunity_status(item["candidate_id"], "sent")
					cache.record_opportunity_send(item["candidate_id"], security_id, job_id, "sent")
					results.append({"candidate_id": item["candidate_id"], "ok": True})
				else:
					code, platform_message = platform.parse_error(resp)
					cache.record_opportunity_send(item["candidate_id"], security_id, job_id, "failed", platform_message)
					cache.update_opportunity_status(item["candidate_id"], "failed")
					results.append({"candidate_id": item["candidate_id"], "ok": False, "error": code, "message": platform_message})

	handle_output(
		ctx,
		"opportunity",
		{"sent": sum(1 for item in results if item.get("ok")), "results": results},
		hints={"next_actions": [boss_command_for_ctx(ctx, "opportunity review --status sent")]},
	)
