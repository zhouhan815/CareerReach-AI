import json

from click.testing import CliRunner

from boss_agent_cli.communication.export_excel import seed_from_row
from boss_agent_cli.communication.models import EvidenceItem, OpportunitySeed
from boss_agent_cli.communication.planner import build_rule_based_plan
from boss_agent_cli.communication.retrieval import CommunicationRetriever
from boss_agent_cli.communication.workflow import CommunicationWorkflow
from boss_agent_cli.main import cli
from boss_agent_cli.rag.models import RagSearchResult
from boss_agent_cli.rag.resume_memory import chunks_from_resume
from boss_agent_cli.resume.models import ResumeData, ResumeModule


class FakeCommunicationRetriever:
	def retrieve(self, seed):
		return [
			EvidenceItem(
				evidence_id="company:1",
				text="公司主要业务: 企业 AI 客服和 Agent 平台",
				doc_type="company",
				chunk_kind="company_profile",
				company=seed.company,
			),
			EvidenceItem(
				evidence_id="job:1",
				text="岗位需求: RAG、Dify、Agent 工作流、ToB 需求分析",
				doc_type="job",
				chunk_kind="job_requirement",
				job_title=seed.job_title,
			),
			EvidenceItem(
				evidence_id="resume:1",
				text="简历证据: 做过 AI 客服方案、Dify 工作流和 RAG 求职 Agent",
				doc_type="resume",
			),
		]


class FakeScopedStore:
	def __init__(self):
		self.where_values = []

	def search(self, query, *, top_k, where=None):
		self.where_values.append(where)
		if where == {"$and": [{"doc_type": "message_template"}, {"source": "outreach_playbook"}]}:
			return []
		if where == {"doc_type": "resume"}:
			return []
		if where == {"company": "Target Co"}:
			return [
				RagSearchResult(
					chunk_id="target:1",
					text="Target company evidence",
					metadata={"company": "Target Co", "doc_type": "company"},
				)
			]
		return [
			RagSearchResult(
				chunk_id="other:1",
				text="Other company evidence",
				metadata={"company": "Other Co", "doc_type": "company"},
			)
		]


def test_communication_retriever_does_not_fill_scoped_results_from_other_companies():
	store = FakeScopedStore()
	retriever = CommunicationRetriever(store, top_k=8)

	evidence = retriever.retrieve(OpportunitySeed(company="Target Co", job_title="AI PM"))

	assert [item.evidence_id for item in evidence] == ["target:1"]
	assert store.where_values == [
		{"$and": [{"doc_type": "message_template"}, {"source": "outreach_playbook"}]},
		{"doc_type": "resume"},
		{"company": "Target Co"},
	]


def test_rule_plan_uses_structured_rag_facts_instead_of_chat_status():
	context = OpportunitySeed(company="Target Co", job_title="AI PM")
	workflow = CommunicationWorkflow(
		retriever=type(
			"StructuredRetriever",
			(),
			{
				"retrieve": lambda self, seed: [
					EvidenceItem(
						evidence_id="chat:1",
						text="Company: Target Co\nChat match status: no match",
						doc_type="chat_status",
						chunk_kind="chat_coverage_status",
					),
					EvidenceItem(
						evidence_id="outreach:1",
						text="我的优势主要有：\n1. AI 客服经验: built a production CCaaS workflow",
						doc_type="message_template",
						chunk_kind="outreach_context",
					),
					EvidenceItem(
						evidence_id="job:1",
						text="岗位需求判断: B端产品、AI产品、智能客服",
						doc_type="job",
						chunk_kind="job_requirement",
					),
					EvidenceItem(
						evidence_id="company:1",
						text="公司主要业务: AI 客服/智能客服、企业服务/SaaS",
						doc_type="company",
						chunk_kind="company_profile",
					),
				]
			},
		)(),
		mode="rules",
		use_langgraph=False,
	)

	result = workflow.run(context, save=False)
	messages = "\n".join(draft["message"] for draft in result["plan"]["drafts"])

	assert "AI 客服/智能客服" in messages
	assert "B端产品、AI产品、智能客服" in messages
	assert "built a production CCaaS workflow" in messages
	assert "Chat match status" not in messages


def test_rule_based_plan_uses_distinct_company_job_and_resume_evidence():
	workflow = CommunicationWorkflow(
		retriever=FakeCommunicationRetriever(),
		mode="rules",
		use_langgraph=False,
	)
	result = workflow.run(
		OpportunitySeed(company="未来智能", job_title="AI 产品经理"),
		save=False,
	)

	plan = result["plan"]
	assert plan["recommended_action"] == "send"
	assert plan["evidence_ids"] == ["company:1", "job:1", "resume:1"]
	message = plan["drafts"][0]["message"]
	assert "企业 AI 客服" in message
	assert "RAG、Dify" in message
	assert "做过 AI 客服方案" in message
	assert "公司主要业务:" not in message


def test_sparse_context_moves_plan_to_manual_review():
	context_result = CommunicationWorkflow(mode="rules", use_langgraph=False).run(
		OpportunitySeed(company="未来智能", job_title="AI 产品经理"),
		save=False,
	)
	plan = context_result["plan"]
	assert plan["recommended_action"] == "manual_review"
	assert "rag_evidence" in context_result["context"]["missing_info"]


def test_ai_communication_plan_cli_runs_without_rag(tmp_path):
	runner = CliRunner()
	result = runner.invoke(
		cli,
		[
			"--data-dir",
			str(tmp_path),
			"--json",
			"ai",
			"communication",
			"plan",
			"--company",
			"未来智能",
			"--job-title",
			"AI 产品经理",
			"--context",
			"公司主要业务: 企业 AI 客服和 Agent 平台",
			"--context",
			"岗位需求: RAG、Dify、Agent 工作流、ToB 需求分析",
			"--context",
			"简历证据: 做过 AI 客服方案、Dify 工作流和 RAG 求职 Agent",
			"--mode",
			"rules",
			"--no-rag",
			"--no-save",
		],
	)
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["command"] == "ai communication plan"
	assert parsed["data"]["plan"]["drafts"]
	assert parsed["data"]["runtime"]["orchestrator"] in {"langgraph", "sequential_fallback"}


def test_ai_communication_export_adds_draft_columns(tmp_path):
	openpyxl = __import__("openpyxl")
	input_path = tmp_path / "opportunities.xlsx"
	workbook = openpyxl.Workbook()
	sheet = workbook.active
	sheet.title = "候选公司总表"
	sheet.append(["公司名称", "岗位名称", "公司主要业务", "岗位需求判断", "匹配理由"])
	sheet.append(["未来智能", "AI 产品经理", "企业 AI 客服和 Agent 平台", "RAG、Dify、Agent 工作流", "AI 客服方案经验"])
	workbook.save(input_path)

	output_path = tmp_path / "communication.xlsx"
	runner = CliRunner()
	result = runner.invoke(
		cli,
		[
			"--data-dir",
			str(tmp_path),
			"--json",
			"ai",
			"communication",
			"export",
			"--input",
			str(input_path),
			"--output",
			str(output_path),
			"--mode",
			"rules",
			"--no-rag",
		],
	)
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["count"] == 1
	assert output_path.exists()

	exported = openpyxl.load_workbook(output_path, read_only=True)
	headers = [cell.value for cell in next(exported.active.iter_rows(min_row=1, max_row=1))]
	assert "draft_steady" in headers
	assert "recommended_action" in headers


def test_ai_communication_export_updates_input_workbook_by_default(tmp_path):
	openpyxl = __import__("openpyxl")
	input_path = tmp_path / "opportunities.xlsx"
	workbook = openpyxl.Workbook()
	sheet = workbook.active
	sheet.title = "候选公司总表"
	sheet.append(["公司名", "岗位名称", "公司主要业务", "岗位需求判断", "匹配理由"])
	sheet.append(["未来智能", "AI 产品经理", "企业 AI 客服和 Agent 平台", "RAG、Dify、Agent 工作流", "AI 客服方案经验"])
	workbook.save(input_path)

	runner = CliRunner()
	result = runner.invoke(
		cli,
		[
			"--data-dir",
			str(tmp_path),
			"--json",
			"ai",
			"communication",
			"export",
			"--input",
			str(input_path),
			"--mode",
			"rules",
			"--no-rag",
		],
	)
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["output"] == str(input_path.resolve())

	exported = openpyxl.load_workbook(input_path, read_only=True)
	assert exported.sheetnames == ["候选公司总表"]
	headers = [cell.value for cell in next(exported["候选公司总表"].iter_rows(min_row=1, max_row=1))]
	assert "draft_steady" in headers
	assert "recommended_action" in headers


def test_seed_from_row_supports_phase4_workbook_headers():
	seed = seed_from_row(
		{
			"公司名": "云咨科技",
			"岗位名称": "AI产品经理",
			"公司主要业务": "AI 客服/智能客服、企业服务/SaaS",
			"公司规模": "20-99人",
			"工作地点": "上海黄浦区",
			"薪资": "25-35K",
			"岗位需求判断": "技能标签：B端产品、AI产品、智能客服",
			"匹配理由": "岗位关键词与 AI 产品经理经历相关",
			"风险/待确认": "经验要求偏高",
			"生成的打招呼话术": "已有初稿",
			"security_id": "security-1",
			"job_id": "job-1",
			"岗位网址": "https://www.zhipin.com/job_detail/job-1.html",
		}
	)

	assert seed.company == "云咨科技"
	assert seed.job_title == "AI产品经理"
	assert seed.job_id == "job-1"
	assert seed.security_id == "security-1"
	assert seed.facts["company_size"] == "20-99人"
	assert seed.facts["location"] == "上海黄浦区"
	assert seed.facts["risk_to_confirm"] == "经验要求偏高"
	assert any("existing greeting: 已有初稿" == item for item in seed.extra_context)
	assert not any(item.startswith("resume_match_score:") for item in seed.extra_context)


def test_score_fields_are_not_used_as_resume_phrase():
	seed = seed_from_row(
		{
			"公司名": "云咨科技",
			"岗位名称": "AI产品经理",
			"公司主要业务": "AI 客服/智能客服、企业服务/SaaS",
			"岗位需求判断": "技能标签：B端产品、AI产品、智能客服",
			"简历匹配度": "92",
			"匹配理由": "岗位关键词与 AI 产品经理经历相关",
		}
	)
	result = CommunicationWorkflow(mode="rules", use_langgraph=False).run(seed, save=False)
	messages = "\n".join(draft["message"] for draft in result["plan"]["drafts"])

	assert "92" not in messages
	assert "岗位关键词与 AI 产品经理经历相关" in messages


def test_direct_match_reasons_label_is_stripped_from_drafts():
	result = CommunicationWorkflow(mode="rules", use_langgraph=False).run(
		OpportunitySeed(
			company="Future AI",
			job_title="AI Product Manager",
			extra_context=[
				"company_business: Enterprise AI customer service and agent platform",
				"job_requirement: RAG workflow and agent product design",
				"match_reasons: Built AI customer service solution and RAG job-search agent",
			],
		),
		save=False,
	)
	messages = "\n".join(draft["message"] for draft in result["plan"]["drafts"])

	assert "match_reasons:" not in messages
	assert "Built AI customer service solution" in messages


def test_excel_seed_direct_context_is_enough_for_rule_plan_without_rag():
	seed = seed_from_row(
		{
			"company": "Future AI",
			"title": "AI Product Manager",
			"company_business": "Enterprise AI customer service and agent platform",
			"job_requirement_judgment": "RAG workflow and agent product design",
			"match_reasons": "Built AI customer service solution and job-search agent",
		}
	)
	result = CommunicationWorkflow(mode="rules", use_langgraph=False).run(seed, save=False)
	plan = result["plan"]
	messages = "\n".join(draft["message"] for draft in plan["drafts"])

	assert any(item.startswith("company business: Enterprise AI customer service") for item in seed.extra_context)
	assert any(item.startswith("job requirement: RAG workflow") for item in seed.extra_context)
	assert plan["recommended_action"] == "send"
	assert "Missing company/business evidence." not in plan["risk_flags"]
	assert "Missing JD/job requirement evidence." not in plan["risk_flags"]
	assert "Enterprise AI customer service" in messages
	assert "RAG workflow" in messages


def test_resume_is_split_into_traceable_rag_chunks():
	resume = ResumeData(
		name="test-resume",
		title="AI Product Manager Intern",
		modules=[
			ResumeModule(
				id="projects",
				title="Projects",
				rows=[
					{"type": "tags", "tags": ["AI customer service", "Dify", "RAG"]},
					{"type": "richtext", "content": ["Built a CareerReach Agent with LangGraph, MCP, and ChromaDB."]},
				],
			)
		],
	)

	chunks = chunks_from_resume(resume)

	assert {chunk.metadata["doc_type"] for chunk in chunks} == {"resume"}
	assert {chunk.metadata["chunk_kind"] for chunk in chunks} >= {"resume_profile", "resume_module", "resume_experience"}
	assert any("CareerReach Agent" in chunk.text for chunk in chunks)


def test_communication_retriever_adds_resume_evidence_before_scoped_company_evidence():
	class ResumeAwareStore:
		def __init__(self):
			self.where_values = []

		def search(self, query, *, top_k, where=None):
			self.where_values.append(where)
			if where == {"$and": [{"doc_type": "message_template"}, {"source": "outreach_playbook"}]}:
				return []
			if where == {"doc_type": "resume"}:
				return [
					RagSearchResult(
						chunk_id="resume:test:row:1",
						text="experience: Built AI customer service and Dify workflow.",
						metadata={"doc_type": "resume", "chunk_kind": "resume_experience", "resume_name": "test"},
					)
				]
			if where == {"company": "Target Co"}:
				return [
					RagSearchResult(
						chunk_id="company:target:job_requirement",
						text="job_requirement: AI customer service product manager.",
						metadata={"doc_type": "job", "chunk_kind": "job_requirement", "company": "Target Co"},
					)
				]
			return []

	retriever = CommunicationRetriever(ResumeAwareStore(), top_k=8)
	evidence = retriever.retrieve(OpportunitySeed(company="Target Co", job_title="AI PM"))

	assert [item.evidence_id for item in evidence] == ["resume:test:row:1", "company:target:job_requirement"]
	assert evidence[0].doc_type == "resume"


def test_playbook_supplemental_match_is_triggered_by_jd_not_resume_only():
	playbook = {
		"outreach_rules": {
			"agent_name": "CareerReach Agent",
			"opening_template": "{agent_name}: {focus_label}; {score_phrase}",
			"internship_intro": "intro",
			"closing": "closing",
		},
		"core_points": [
			{
				"id": "agent",
				"label": "Agent",
				"default_text": "default agent",
				"expanded_text": "expanded agent",
				"jd_focus_terms": ["Agent"],
				"keywords": ["Agent"],
			}
		],
		"supplemental_points": [
			{
				"id": "psychology",
				"label": "Psychology",
				"default_text": "psychology special match",
				"keywords": ["psychology"],
			}
		],
	}
	resume_only_context = CommunicationWorkflow(
		retriever=type(
			"ResumeOnlyRetriever",
			(),
			{
				"retrieve": lambda self, seed: [
					EvidenceItem(
						evidence_id="resume:psychology",
						text="experience: psychology and user emotion observation",
						doc_type="resume",
					)
				]
			},
		)(),
		mode="rules",
		outreach_playbook=playbook,
		use_langgraph=False,
	).run(OpportunitySeed(company="Target", job_title="AI PM"), save=False)
	resume_only_message = resume_only_context["plan"]["drafts"][0]["message"]
	assert "psychology special match" not in resume_only_message

	jd_context = CommunicationWorkflow(
		retriever=type(
			"JdRetriever",
			(),
			{
				"retrieve": lambda self, seed: [
					EvidenceItem(
						evidence_id="job:psychology",
						text="job_requirement: psychology based companion product",
						doc_type="job",
						chunk_kind="job_requirement",
					)
				]
			},
		)(),
		mode="rules",
		outreach_playbook=playbook,
		use_langgraph=False,
	).run(OpportunitySeed(company="Target", job_title="AI PM"), save=False)
	jd_message = jd_context["plan"]["drafts"][0]["message"]
	assert "psychology special match" in jd_message
