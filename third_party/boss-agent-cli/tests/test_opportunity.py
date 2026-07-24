import json

import pytest
from click.testing import CliRunner
from openpyxl import load_workbook

from boss_agent_cli.api.client import AccountRiskError
from boss_agent_cli.cache.store import CacheStore
from boss_agent_cli.main import cli
from boss_agent_cli.opportunity.constraints import assess_fit_constraints
from boss_agent_cli.opportunity.drafts import build_greeting_message
from boss_agent_cli.opportunity.export_excel import export_opportunities_xlsx
from boss_agent_cli.opportunity.filters import (
	detect_actual_location_mismatch,
	detect_anonymous_or_headhunter,
	detect_company_too_large,
	detect_internship_like,
	detect_job_closed,
	parse_work_arrangement,
	resolve_work_arrangement,
)
from boss_agent_cli.opportunity.pipeline import _fetch_detail_card, analyze_candidate, collect_opportunities
from boss_agent_cli.opportunity.scoring import score_opportunity
from boss_agent_cli.output import Logger
from boss_agent_cli.search_filters import SearchPipelinePlatformError


class FakeOpportunityPlatform:
	def is_success(self, response):
		return response.get("code") == 0

	def parse_error(self, response):
		return "UNKNOWN", response.get("message", "")

	def unwrap_data(self, response):
		return response.get("zpData", {})

	def search_jobs(self, query, **filters):
		return {
			"code": 0,
			"zpData": {
				"hasMore": False,
				"jobList": [
					{
						"encryptJobId": "job_formal",
						"securityId": "sec_formal",
						"lid": "lid_formal",
						"jobName": "AI产品经理",
						"brandName": "未来智能",
						"salaryDesc": "20-30K",
						"cityName": filters.get("city", "上海"),
						"areaDistrict": "徐汇区",
						"jobExperience": "1-3年",
						"jobDegree": "本科",
						"skills": ["AI产品", "Dify", "需求分析"],
						"welfareList": ["双休"],
						"brandIndustry": "企业服务",
						"brandScaleName": "100-499人",
						"brandStageName": "A轮",
						"bossName": "李经理",
						"bossTitle": "产品负责人",
					},
					{
						"encryptJobId": "job_intern",
						"securityId": "sec_intern",
						"lid": "lid_intern",
						"jobName": "AI产品经理实习生",
						"brandName": "实习公司",
						"salaryDesc": "200-300元/天",
						"cityName": filters.get("city", "上海"),
						"jobExperience": "经验不限",
						"jobDegree": "本科",
					},
				],
			},
		}

	def job_card(self, security_id, lid=""):
		return {
			"code": 0,
			"zpData": {
				"jobCard": {
					"encryptJobId": "job_formal",
					"jobName": "AI产品经理",
					"brandName": "未来智能",
					"salaryDesc": "20-30K",
					"cityName": "上海",
					"address": "上海市徐汇区",
					"experienceName": "1-3年",
					"degreeName": "本科",
					"postDescription": "负责大模型 Agent 产品、Dify 工作流、AI 客服场景和 ToB 需求分析，团队快速成长。",
					"jobLabels": ["AI产品", "Dify", "Agent", "需求分析"],
					"bossName": "李经理",
					"bossTitle": "产品负责人",
				}
			},
		}


class FakeBalancedOpportunityPlatform:
	def is_success(self, response):
		return response.get("code") == 0

	def parse_error(self, response):
		return "UNKNOWN", response.get("message", "")

	def unwrap_data(self, response):
		return response.get("zpData", {})

	def search_jobs(self, query, **filters):
		city = filters.get("city", "上海")
		return {
			"code": 0,
			"zpData": {
				"hasMore": False,
				"jobList": [
					{
						"encryptJobId": f"job_formal_{city}",
						"securityId": f"sec_formal_{city}",
						"lid": f"lid_formal_{city}",
						"jobName": "AI产品经理",
						"brandName": f"未来智能{city}",
						"salaryDesc": "20-30K",
						"cityName": city,
						"areaDistrict": "核心区",
						"jobExperience": "1-3年",
						"jobDegree": "本科",
						"skills": ["AI产品", "Dify", "需求分析"],
						"welfareList": ["双休"],
						"brandIndustry": "企业服务",
						"brandScaleName": "100-499人",
						"brandStageName": "A轮",
						"bossName": "李经理",
						"bossTitle": "产品负责人",
					}
				],
			},
		}

	def job_card(self, security_id, lid=""):
		city = security_id.rsplit("_", 1)[-1]
		return {
			"code": 0,
			"zpData": {
				"jobCard": {
					"encryptJobId": f"job_formal_{city}",
					"jobName": "AI产品经理",
					"brandName": f"未来智能{city}",
					"salaryDesc": "20-30K",
					"cityName": city,
					"address": f"{city}市核心区",
					"experienceName": "1-3年",
					"degreeName": "本科",
					"postDescription": "负责大模型 Agent 产品、Dify 工作流、AI 客服场景和 ToB 需求分析，团队快速成长。",
					"jobLabels": ["AI产品", "Dify", "Agent", "需求分析"],
					"bossName": "李经理",
					"bossTitle": "产品负责人",
				}
			},
		}


class FakeDetailFailurePlatform(FakeOpportunityPlatform):
	def job_card(self, security_id, lid=""):
		raise RuntimeError("playwright sync fallback failed")


class FakeHttpxDetailPlatform(FakeDetailFailurePlatform):
	def job_detail(self, job_id):
		return {
			"code": 0,
			"zpData": {
				"jobInfo": {
					"encryptJobId": job_id,
					"jobName": "AI产品经理",
					"salaryDesc": "20-30K",
					"cityName": "上海",
					"address": "上海市徐汇区",
					"experienceName": "1-3年",
					"degreeName": "本科",
					"postDescription": "负责大模型 Agent 产品、Dify 工作流和 AI 客服场景。",
					"jobLabels": ["AI产品", "Dify", "Agent"],
				},
				"bossInfo": {"name": "李经理", "title": "产品负责人"},
				"brandComInfo": {"brandName": "未来智能"},
			},
		}


def _resume_text():
	return (
		"AI产品经理 实习 简历：参与保险 AI 客服项目，负责场景定位、竞品分析和解决方案设计；"
		"搭建 Dify 工作流，进行 prompt 优化；熟悉 Cursor Codex Agent；有 Transformer 论文经历和英语背景。"
	)


def _candidate_dict():
	return {
		"candidate_id": "cand_1",
		"run_id": "run_1",
		"status": "pending",
		"query": "AI产品经理",
		"city": "上海",
		"title": "AI产品经理",
		"company": "未来智能",
		"salary": "20-30K",
		"location": "上海市徐汇区",
		"company_scale": "100-499人",
		"company_stage": "A轮",
		"industry": "企业服务",
		"experience": "1-3年",
		"education": "本科",
		"security_id": "sec_1",
		"job_id": "job_1",
		"lid": "lid_1",
		"description": "负责大模型 Agent 产品、Dify 工作流和 AI 客服场景。",
		"skills": ["AI产品", "Dify"],
		"welfare": ["双休"],
		"company_business": "大模型应用/智能体、企业服务/SaaS",
		"job_requirement_judgment": "JD 指向：大模型应用/智能体",
		"resume_match_score": 88,
		"internship_acceptance_score": 90,
		"recommendation_level": "A",
		"match_reasons": ["JD 与简历都覆盖工作流"],
		"acceptance_reasons": ["公司规模处于 20-500 人"],
		"risk_reasons": [],
		"greeting_message": "您好，我的求职 Agent 基于贵公司岗位做了匹配分析。",
		"payload": {},
	}


def test_detect_internship_like_excludes_daily_rate_and_title():
	is_intern, reasons = detect_internship_like({"title": "AI产品经理实习生", "salary": "200-300元/天"})
	assert is_intern is True
	assert reasons
	is_intern, reasons = detect_internship_like({"title": "AI产品经理", "salary": "20-30K"})
	assert is_intern is False


def test_detect_company_too_large_excludes_thousand_plus():
	excluded, reasons = detect_company_too_large({"company_scale": "1000-9999人"})
	assert excluded is True
	assert "1000-9999人" in reasons[0]
	excluded, reasons = detect_company_too_large({"company_scale": "10000人以上"})
	assert excluded is True
	assert "10000人以上" in reasons[0]
	excluded, reasons = detect_company_too_large({"company_scale": "500-999人"})
	assert excluded is False


def test_detects_anonymous_headhunter_and_closed_roles():
	excluded, reasons = detect_anonymous_or_headhunter({"company": "某大型互联网金融公司"})
	assert excluded is True
	assert "匿名" in reasons[0]
	excluded, _ = detect_anonymous_or_headhunter({"company": "上海某小型人工智能增长智能Pre-A轮融资公司"})
	assert excluded is True
	excluded, reasons = detect_anonymous_or_headhunter({"company": "真实科技", "boss_title": "猎头顾问"})
	assert excluded is True
	closed, reasons = detect_job_closed({"description": "该职位已关闭"})
	assert closed is True
	assert "关闭" in reasons[0]


def test_detects_jd_actual_location_mismatch():
	excluded, reasons = detect_actual_location_mismatch({
		"city": "上海",
		"description": "岗位由上海团队发布。实际工作地点：义乌市，公司可提供住宿。",
	})
	assert excluded is True
	assert "义乌" in reasons[0]
	excluded, _ = detect_actual_location_mismatch({
		"city": "上海",
		"description": "办公地点：上海市浦东新区。",
	})
	assert excluded is False
	excluded, reasons = detect_actual_location_mismatch({
		"city": "深圳",
		"title": "AI产品经理（跨境品牌独立站 base 郑州）",
		"description": "负责 AI 产品规划。",
	})
	assert excluded is True
	assert "郑州" in reasons[0]


def test_parse_work_arrangement_from_jd_text():
	weekly_days, duration = parse_work_arrangement("岗位要求：每周到岗4天，实习期不少于3个月。")
	assert weekly_days == "每周4天"
	assert duration == "3个月以上"


def test_resolve_work_arrangement_does_not_use_long_jd_as_value():
	weekly_days, duration = resolve_work_arrangement(
		"今天想到一个提效场景，这周就能搭出智能体让同事用上；下个月验证有效，再交给开发团队工程化。"
	)
	assert weekly_days == "待沟通"
	assert duration == "待沟通"


def test_resolve_work_arrangement_ignores_business_month_in_long_jd():
	weekly_days, duration = resolve_work_arrangement(
		"我们希望你重度使用 Claude / ChatGPT / Cursor 等工具，"
		"以用 AI 把过去一个月的产研工作量压缩到一周为乐趣。"
		"岗位负责 AI 产品需求分析、原型设计和跨团队推进。"
	)
	assert weekly_days == "待沟通"
	assert duration == "待沟通"


def test_score_and_draft_include_agent_and_score():
	candidate = _candidate_dict()
	score = score_opportunity(candidate, _resume_text())
	assert score.resume_match_score >= 80
	assert score.internship_acceptance_score >= 70
	message = build_greeting_message({
		**candidate,
		**score.to_dict(),
		"description": "负责 AI 客服、Dify Agent 工作流和数据指标分析",
	})
	assert "由我自己搭建的求职 Agent" in message
	assert "匹配度：" in message
	assert "Dify" in message
	assert "日均 4 万次咨询" in message
	assert "岗位方向与 AI 产品经理目标一致" not in message


def test_score_penalizes_missing_robotics_domain_background():
	candidate = {
		**_candidate_dict(),
		"description": "负责机器人 AI 产品、机械臂运动控制、ROS 导航控制和控制算法相关需求。",
	}
	score = score_opportunity(candidate, _resume_text())
	assert score.resume_match_score < 80
	assert any("机器人/运动控制" in reason for reason in score.risk_reasons)


def test_score_penalizes_missing_finance_and_aesthetic_background():
	candidate = {
		**_candidate_dict(),
		"description": "负责基金投顾产品，需要金融行业知识与良好的美学修养、视觉设计能力。",
	}
	score = score_opportunity(candidate, _resume_text())
	assert score.resume_match_score < 70
	assert any("金融/投资" in reason for reason in score.risk_reasons)
	assert any("审美/视觉" in reason for reason in score.risk_reasons)


def test_draft_hides_numeric_score_below_ninety_and_keeps_six_bullets():
	message = build_greeting_message({
		**_candidate_dict(),
		"resume_match_score": 88,
		"description": "负责 AI 客服产品与企业客户解决方案。",
	})
	assert "匹配度较高" in message
	assert "88/100" not in message
	assert "岗位 JD（AI 客服）" in message
	assert all(f"{index}. " in message for index in range(1, 7))


def test_draft_does_not_mislabel_generic_b2b_agent_role_as_customer_service():
	message = build_greeting_message({
		**_candidate_dict(),
		"resume_match_score": 88,
		"description": "负责 B 端 SaaS Agent、RAG 工作流和海外营销产品。",
		"company_business": "企业服务/SaaS、营销增长",
	})
	assert "岗位 JD（Agent / 工作流）" in message
	assert "岗位 JD（AI 客服）" not in message


def test_mandatory_tool_gap_is_hard_exclusion():
	candidate = {
		**_candidate_dict(),
		"description": "数字员工、WorkBuddy、Genspark、Hermes 工具应用为必须项，如果没有这两项能力，不匹配。",
	}
	constraints = assess_fit_constraints(candidate, _resume_text())
	assert constraints.hard_exclusion_reasons
	analyzed = analyze_candidate(candidate, _resume_text())
	assert analyzed["resume_match_score"] < 80
	assert any("WorkBuddy" in reason for reason in analyzed["risk_reasons"])


def test_analyze_candidate_recomputes_stale_work_arrangement():
	candidate = {
		**_candidate_dict(),
		"weekly_days": "待沟通",
		"internship_duration": "1个月",
		"payload": {"raw": {}, "job_card": {}},
		"description": "负责 AI Agent 产品设计和业务指标分析。",
	}
	analyzed = analyze_candidate(candidate, _resume_text())
	assert analyzed["weekly_days"] == "待沟通"
	assert analyzed["internship_duration"] == "待沟通"


def test_collect_opportunities_stores_pending_and_excluded(tmp_path):
	with CacheStore(tmp_path / "boss_agent.db") as cache:
		result = collect_opportunities(
			FakeOpportunityPlatform(),
			cache,
			Logger("error"),
			resume_text=_resume_text(),
			query="AI产品经理",
			cities=["上海"],
			pages=1,
			limit=10,
		)
		assert result["stats"]["pending"] == 1
		assert result["stats"]["excluded_internship"] == 1
		pending = cache.list_opportunity_candidates(status="pending")
		excluded = cache.list_opportunity_candidates(status="excluded")
	assert pending[0]["company"] == "未来智能"
	assert pending[0]["resume_match_score"] >= 80
	assert excluded[0]["excluded_reason"]


def test_collect_opportunities_excludes_large_companies(tmp_path):
	class LargeCompanyPlatform(FakeOpportunityPlatform):
		def search_jobs(self, query, **filters):
			data = super().search_jobs(query, **filters)
			data["zpData"]["jobList"][0]["brandScaleName"] = "10000人以上"
			return data

	with CacheStore(tmp_path / "boss_agent.db") as cache:
		result = collect_opportunities(
			LargeCompanyPlatform(),
			cache,
			Logger("error"),
			resume_text=_resume_text(),
			query="AI产品经理",
			cities=["上海"],
			pages=1,
			limit=10,
		)
		excluded = cache.list_opportunity_candidates(status="excluded")

	assert result["stats"]["excluded_company_scale"] == 1
	assert any("10000人以上" in item["excluded_reason"] for item in excluded)


def test_collect_opportunities_balances_city_targets(tmp_path):
	with CacheStore(tmp_path / "boss_agent.db") as cache:
		result = collect_opportunities(
			FakeBalancedOpportunityPlatform(),
			cache,
			Logger("error"),
			resume_text=_resume_text(),
			query="AI产品经理",
			cities=["上海", "深圳"],
			pages=1,
			limit=2,
		)
		pending = cache.list_opportunity_candidates(status="pending", run_id=result["run_id"])

	assert result["stats"]["pending_by_city"] == {"上海": 1, "深圳": 1}
	assert {item["city"] for item in pending} == {"上海", "深圳"}


def test_collect_opportunities_tolerates_detail_runtime_error(tmp_path):
	with CacheStore(tmp_path / "boss_agent.db") as cache:
		result = collect_opportunities(
			FakeDetailFailurePlatform(),
			cache,
			Logger("error"),
			resume_text=_resume_text(),
			query="AI产品经理",
			cities=["上海"],
			pages=1,
			limit=10,
			min_match=0,
			min_acceptance=0,
		)

	assert result["stats"]["detail_failures"] == 1
	assert result["stats"]["pending"] == 1


def test_collect_opportunities_prefers_httpx_detail_over_job_card(tmp_path):
	with CacheStore(tmp_path / "boss_agent.db") as cache:
		result = collect_opportunities(
			FakeHttpxDetailPlatform(),
			cache,
			Logger("error"),
			resume_text=_resume_text(),
			query="AI产品经理",
			cities=["上海"],
			pages=1,
			limit=10,
		)
		pending = cache.list_opportunity_candidates(status="pending", run_id=result["run_id"])

	assert result["stats"]["detail_failures"] == 0
	assert "大模型 Agent" in pending[0]["description"]


def test_detail_account_risk_stops_before_job_card_fallback():
	class RiskPlatform(FakeOpportunityPlatform):
		def __init__(self):
			self.job_card_called = False

		def job_detail(self, job_id):
			raise AccountRiskError("environment abnormal")

		def job_card(self, security_id, lid=""):
			self.job_card_called = True
			return super().job_card(security_id, lid)

	platform = RiskPlatform()
	with pytest.raises(AccountRiskError, match="environment abnormal"):
		_fetch_detail_card(
			platform,
			{"job_id": "job-1", "security_id": "security-1", "lid": "lid-1"},
		)

	assert platform.job_card_called is False


def test_failed_detail_response_does_not_call_job_card_fallback():
	class FailedDetailPlatform(FakeOpportunityPlatform):
		def __init__(self):
			self.job_card_called = False

		def job_detail(self, job_id):
			return {"code": 429, "message": "rate limited"}

		def parse_error(self, response):
			return "RATE_LIMITED", response.get("message", "")

		def job_card(self, security_id, lid=""):
			self.job_card_called = True
			return super().job_card(security_id, lid)

	platform = FailedDetailPlatform()
	with pytest.raises(SearchPipelinePlatformError) as exc_info:
		_fetch_detail_card(
			platform,
			{"job_id": "job-1", "security_id": "security-1", "lid": "lid-1"},
		)

	assert exc_info.value.code == "RATE_LIMITED"
	assert platform.job_card_called is False


def test_collect_stops_batch_on_terminal_detail_error(tmp_path):
	class RateLimitedPlatform(FakeOpportunityPlatform):
		def job_detail(self, job_id):
			return {"code": 429, "message": "rate limited"}

		def parse_error(self, response):
			return "RATE_LIMITED", response.get("message", "")

	with CacheStore(tmp_path / "boss_agent.db") as cache:
		with pytest.raises(SearchPipelinePlatformError) as exc_info:
			collect_opportunities(
				RateLimitedPlatform(),
				cache,
				Logger("error"),
				resume_text=_resume_text(),
				query="AI product manager",
				cities=["Shanghai"],
				pages=1,
				limit=10,
			)

	assert exc_info.value.code == "RATE_LIMITED"


def test_export_opportunities_xlsx_creates_workbook(tmp_path):
	output = export_opportunities_xlsx([_candidate_dict()], tmp_path / "opportunities.xlsx")
	assert output.exists()
	workbook = load_workbook(output)
	assert workbook.sheetnames == ["候选公司总表", "高优先级联系名单", "已排除岗位"]
	sheet = workbook["候选公司总表"]
	headers = [cell.value for cell in sheet[1]]
	url_column = headers.index("岗位网址") + 1
	greeting_column = headers.index("生成的打招呼话术") + 1
	assert sheet.cell(row=2, column=url_column).value == "https://www.zhipin.com/job_detail/job_1.html?securityId=sec_1&lid=lid_1"
	assert "由我自己搭建的求职 Agent" in sheet.cell(row=2, column=greeting_column).value
	assert all(f"{index}. " in sheet.cell(row=2, column=greeting_column).value for index in range(1, 7))


def test_export_opportunities_xlsx_updates_existing_tracking_workbook(tmp_path):
	output = export_opportunities_xlsx([_candidate_dict()], tmp_path / "opportunities.xlsx")
	workbook = load_workbook(output)
	sheet = workbook["候选公司总表"]
	headers = [cell.value for cell in sheet[1]]
	status_column = headers.index("状态") + 1
	greeting_column = headers.index("生成的打招呼话术") + 1
	manual_column = len(headers) + 1
	sheet.cell(row=1, column=manual_column).value = "我的跟进备注"
	sheet.cell(row=2, column=status_column).value = "confirmed"
	sheet.cell(row=2, column=greeting_column).value = "旧版错误话术"
	sheet.cell(row=2, column=manual_column).value = "用户手工确认过"
	workbook.save(output)

	updated_candidate = {
		**_candidate_dict(),
		"salary": "22-30K",
		"resume_match_score": 92,
		"description": "负责 AI 客服产品、Dify 工作流和数据指标分析",
		"greeting_message": "",
	}
	export_opportunities_xlsx([updated_candidate], output)

	updated = load_workbook(output)
	sheet = updated["候选公司总表"]
	headers = [cell.value for cell in sheet[1]]
	status_column = headers.index("状态") + 1
	salary_column = headers.index("薪资") + 1
	greeting_column = headers.index("生成的打招呼话术") + 1
	manual_column = headers.index("我的跟进备注") + 1
	assert sheet.cell(row=2, column=status_column).value == "confirmed"
	assert sheet.cell(row=2, column=salary_column).value == "22-30K"
	assert sheet.cell(row=2, column=manual_column).value == "用户手工确认过"
	greeting = sheet.cell(row=2, column=greeting_column).value
	assert "旧版错误话术" not in greeting
	assert "岗位 JD（AI 客服）" in greeting
	assert "匹配度：92/100" in greeting
	assert all(f"{index}. " in greeting for index in range(1, 7))


def test_opportunity_review_defaults_to_compact_output(tmp_path):
	candidate = _candidate_dict()
	candidate["description"] = "full jd text"
	candidate["payload"] = {"raw": {"heavy": True}}
	with CacheStore(tmp_path / "cache" / "boss_agent.db") as cache:
		cache.upsert_opportunity_candidate(candidate)

	runner = CliRunner()
	result = runner.invoke(
		cli,
		["--data-dir", str(tmp_path), "--json", "opportunity", "review", "--status", "pending"],
	)
	assert result.exit_code == 0, result.output
	parsed = json.loads(result.output)
	item = parsed["data"]["items"][0]
	assert item["candidate_id"] == "cand_1"
	assert "greeting_message" in item
	assert "payload" not in item
	assert "description" not in item


def test_opportunity_review_filters_by_run_id(tmp_path):
	candidate_1 = _candidate_dict()
	candidate_2 = {**_candidate_dict(), "candidate_id": "cand_2", "run_id": "run_2", "company": "第二批公司"}
	with CacheStore(tmp_path / "cache" / "boss_agent.db") as cache:
		cache.upsert_opportunity_candidate(candidate_1)
		cache.upsert_opportunity_candidate(candidate_2)

	runner = CliRunner()
	result = runner.invoke(
		cli,
		[
			"--data-dir",
			str(tmp_path),
			"--json",
			"opportunity",
			"review",
			"--status",
			"pending",
			"--run-id",
			"run_2",
		],
	)
	assert result.exit_code == 0, result.output
	parsed = json.loads(result.output)
	assert parsed["data"]["count"] == 1
	assert parsed["data"]["items"][0]["candidate_id"] == "cand_2"


def test_opportunity_refresh_reanalyzes_cached_candidates(tmp_path):
	resume_dir = tmp_path / "resumes"
	resume_dir.mkdir(parents=True)
	(resume_dir / "ai_pm_intern.json").write_text(
		json.dumps({
			"name": "ai_pm_intern",
			"title": "AI PM Intern",
			"modules": [
				{"id": "m1", "title": "经历", "rows": [{"type": "richtext", "content": [_resume_text()]}]},
			],
		}, ensure_ascii=False),
		encoding="utf-8",
	)
	candidate = {**_candidate_dict(), "company_scale": "10000人以上"}
	with CacheStore(tmp_path / "cache" / "boss_agent.db") as cache:
		cache.upsert_opportunity_candidate(candidate)

	runner = CliRunner()
	result = runner.invoke(cli, ["--data-dir", str(tmp_path), "--json", "opportunity", "refresh", "--status", "pending"])
	assert result.exit_code == 0, result.output
	parsed = json.loads(result.output)
	assert parsed["data"]["stats"]["excluded"] == 1
	with CacheStore(tmp_path / "cache" / "boss_agent.db") as cache:
		item = cache.get_opportunity_candidate("cand_1")
	assert item["status"] == "excluded"
	assert "10000人以上" in item["excluded_reason"]


def test_opportunity_cli_confirm_and_schema(tmp_path):
	with CacheStore(tmp_path / "cache" / "boss_agent.db") as cache:
		cache.upsert_opportunity_candidate(_candidate_dict())

	runner = CliRunner()
	result = runner.invoke(cli, ["--data-dir", str(tmp_path), "--json", "opportunity", "confirm", "cand_1"])
	assert result.exit_code == 0, result.output
	parsed = json.loads(result.output)
	assert parsed["data"]["updated"] is True
	assert parsed["data"]["item"]["status"] == "confirmed"

	schema_result = runner.invoke(cli, ["schema"])
	assert schema_result.exit_code == 0
	schema = json.loads(schema_result.output)
	assert "opportunity" in schema["data"]["commands"]
	assert "collect" in schema["data"]["commands"]["opportunity"]["subcommands"]
	assert "refresh" in schema["data"]["commands"]["opportunity"]["subcommands"]
	opportunity_options = schema["data"]["commands"]["opportunity"]["options"]
	assert "--run-id" in opportunity_options["review"]
	assert "--full" in opportunity_options["review"]
	assert "--run-id" in opportunity_options["export"]
	assert "--limit" in opportunity_options["export"]
	assert "--run-id" in opportunity_options["refresh"]
