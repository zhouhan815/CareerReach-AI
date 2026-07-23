<div align="center">

# CareerReach AI

### 面向求职沟通场景的证据驱动型双 Agent 原型

把岗位信息、个人经历与历史沟通整理成可核验的证据，再生成可供用户审核的沟通策略。

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Workflow](https://img.shields.io/badge/Workflow-LangGraph-1F6FEB?style=flat-square)
![RAG](https://img.shields.io/badge/RAG-ChromaDB-0F8B8D?style=flat-square)
![Interface](https://img.shields.io/badge/Interface-CLI%20%2B%20JSON-475569?style=flat-square)
![Review](https://img.shields.io/badge/Safety-Human--in--the--loop-D97706?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-16A34A?style=flat-square)

[查看演示](#完整演示从-prompt-到-excel) · [系统架构](#系统架构) · [工作流程](#端到端工作流程) · [技术实现](#技术实现) · [快速运行](#快速运行) · [Codex 交互](#在-codex-中使用) · [安全边界](#安全与隐私边界)

</div>

---

## 项目简介

CareerReach AI 是一个求职沟通 Agent 产品原型。系统先整理公司、岗位、简历和历史沟通中的事实，再基于证据生成沟通建议，并把信息缺口、引用依据和风险提示一起交给用户审核。

它关注的不是自动批量投递，而是三个更具体的问题：

- 如何把分散的岗位信息和个人经历整理成清晰的匹配依据；
- 如何让事实整理与话术生成由不同 Agent 分工完成；
- 如何在证据不足或动作敏感时停下来，请用户确认。

> **开源说明：** 本仓库是产品化展示与应用适配层。招聘平台本地工具、真实双 Agent 工作流、LangGraph 编排和 ChromaDB RAG 能力来自 MIT License 的第三方项目 [`boss-agent-cli`](https://github.com/can4hou6joeng4/boss-agent-cli)。本仓库不把第三方能力表述为完全自研。

## 完整演示：从 Prompt 到 Excel

下面展示一次完整的 Opportunity 工作流：用户用自然语言定义搜索城市、硬性筛选、RAG 匹配门槛、输出字段与沟通话术规则，Agent 将任务转化为结构化机会表。为保护隐私，公开版使用 20 条合成候选岗位；字段、筛选门槛和输出逻辑与 Prompt 对齐。

| 演示材料 | 内容 | 链接 |
| --- | --- | --- |
| 完整输入 | 可复用的 Opportunity 工作流 Prompt | [查看独立 Prompt 页面](examples/showcase/demo_input_prompt.md) |
| 浏览器预览 | 20 条合成候选结果与完整字段说明 | [查看输出预览](examples/showcase/demo_output_preview.md) |
| Excel 工作簿 | 19 个指定字段，可筛选、可继续编辑 | [下载公开演示 Excel](examples/showcase/careerreach_agent_output_public.xlsx) |

<details open>
<summary><strong>输入：AI 产品经理 Opportunity 工作流 Prompt</strong></summary>

```text
$boss-job-agent

请使用 boss-job-agent 的 opportunity 工作流，帮我生成一份 AI 产品经理机会表。

目标：
1. 在 BOSS 直聘搜索「AI产品经理」相关正式岗位，城市限定为上海和深圳。
2. 目标数量：20 个合格候选岗位。
3. 岗位本身可以是正式岗，但需要判断公司是否可能接受我以 AI 产品经理实习生身份先参与。

硬性筛选：
1. 排除实习岗：岗位名包含“实习/Intern/校招实习”等，或薪资为 100-500 元/天这类日薪。
2. 排除 1000 人以上公司；20-499 人优先；500-999 人可保留但降权。
3. 排除猎头、匿名公司及无法判断真实主体的岗位。
4. 排除已关闭岗位。
5. 排除实际工作地点不在上海或深圳的岗位。
6. 若 JD 将某项能力或工具列为硬性要求，而 RAG 记忆库中没有相关证据，则一票否决或进入待确认。
7. 对机器人/运动控制/ROS/机械臂、金融/投资/资金/对账、审美/视觉设计等缺少背景的方向明显降权。

匹配分析：
1. 调用本地 ChromaDB/RAG 记忆库，结合简历、项目经历、CareerReach Agent 搭建经历和历史补充记忆进行判断。
2. 重点匹配 AI 客服/ToB 场景、Dify 工作流、Agent 搭建和英语能力。
3. 简历匹配度低于 75，或实习接收可能性低于 48 的，不进入最终候选表。

输出 Excel：
字段必须包括：公司名、公司主要业务、公司规模、岗位名称、岗位需求判断、工作地点、薪资、一周实习几天、实习时长、简历匹配度、实习接收可能性、推荐等级、状态、匹配理由、风险/待确认、生成的打招呼话术、security_id、job_id、岗位网址。

话术要求：
1. 每个候选公司生成一段独立打招呼话术。
2. 说明话术由我自己搭建的 CareerReach Agent 基于 JD 和我的 RAG 记忆库生成。
3. 保持 bullet points、简洁、专业。
4. 如果匹配度低于 80，不显示具体分数，只说“匹配度较高”。
```

</details>

### 输出结果预览

| 公司名 | 城市 | 岗位名称 | 简历匹配度 | 实习接收可能性 | 推荐等级 | 状态 |
| --- | --- | --- | ---: | ---: | --- | --- |
| 星云智能（合成） | 上海 | AI 产品经理 | 92 | 82 | A | 合格候选 |
| 知序科技（合成） | 上海 | Agent 产品经理 | 90 | 80 | A | 合格候选 |
| 海拓智联（合成） | 深圳 | AI 客服产品经理 | 91 | 80 | A | 合格候选 |
| 深蓝云策（合成） | 深圳 | ToB AI 产品经理 | 88 | 74 | B | 合格候选 |
| 前海知链（合成） | 深圳 | RAG 产品经理 | 87 | 70 | B | 合格候选 |

完整工作簿包含 20 条候选记录与 Prompt 指定的全部 19 个字段。公开文件保留 `security_id`、`job_id` 和岗位网址的字段形态，但值统一使用 `demo-*` 与 `example.com` 合成占位符；不包含真实公司、真实平台标识、Cookie、会话信息或个人隐私数据。

## 核心能力

| 能力 | 系统做什么 | 用户得到什么 |
| --- | --- | --- |
| 岗位信息整理 | 汇总公司、JD、沟通目标和补充信息 | 一份结构清晰的岗位上下文 |
| 双 Agent 协作 | Data Agent 整理事实，Communication Agent 生成策略 | 事实与表达分开，便于检查 |
| RAG 证据检索 | 从公司、岗位、简历和沟通记录中召回相关内容 | 建议可以追溯到依据 |
| 多版本沟通建议 | 生成候选话术、跟进思路和行动建议 | 用户可以比较后再选择 |
| 信息缺口识别 | 主动标记缺失事实和不确定内容 | 避免把推测包装成事实 |
| 人工审核 | 敏感动作停在用户确认之前 | 用户保留最终决定权 |
| 双 Backend | 公开演示模式与本地真实工作流使用同一输出规范 | 陌生环境可演示，本地环境可扩展 |

## 系统架构

下面的图只表达模块职责。技术实现和数据字段放在后文，避免把架构图变成代码清单。

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"16px","fontFamily":"Arial, sans-serif","primaryTextColor":"#172033","lineColor":"#64748B"}}}%%
flowchart TB
    USER["用户<br/>描述岗位与沟通目标"]
    ENTRY["交互入口<br/>Codex 或命令行"]
    APP["CareerReach 应用后端<br/>选择运行模式并检查结果"]
    FLOW["LangGraph 双 Agent 工作流<br/>控制处理顺序与状态传递"]
    DATA["Data Agent<br/>整理事实并查找证据"]
    COMM["Communication Agent<br/>生成策略与候选话术"]
    REVIEW["人工审核<br/>确认、修改或放弃"]

    TOOL["本地工具与数据能力<br/>boss-agent-cli"]
    RAG["知识库<br/>ChromaDB RAG"]

    USER --> ENTRY --> APP --> FLOW
    FLOW --> DATA --> COMM --> REVIEW
    TOOL --> APP
    RAG --> DATA

    classDef person fill:#FFF7ED,stroke:#D97706,color:#7C2D12,stroke-width:1.5px;
    classDef app fill:#EFF6FF,stroke:#2563EB,color:#172554,stroke-width:1.5px;
    classDef agent fill:#ECFDF5,stroke:#0F8B8D,color:#134E4A,stroke-width:1.5px;
    classDef support fill:#F8FAFC,stroke:#64748B,color:#334155,stroke-width:1.2px;

    class USER,REVIEW person;
    class ENTRY,APP,FLOW app;
    class DATA,COMM agent;
    class TOOL,RAG support;
```

### 模块职责

| 模块 | 职责 |
| --- | --- |
| 交互入口 | 接收自然语言或结构化输入；Codex 是可选的自然语言客户端，不是系统内部的 Supervisor 节点 |
| CareerReach 应用后端 | 解析参数、选择 Fixture 或本地 Backend、调用工具并校验返回结果 |
| LangGraph 工作流 | 按固定顺序执行 Data Agent 和 Communication Agent，并传递工作流状态 |
| Data Agent | 整理公司、岗位、个人经历和历史沟通，检索证据并标记缺失信息 |
| Communication Agent | 依据已整理的上下文生成候选话术、跟进建议、置信度和风险提示 |
| ChromaDB RAG | 在本地保存并检索公司、岗位、简历和沟通上下文 |
| 人工审核 | 在采用话术或执行平台动作前保留用户确认 |

### 关于 Supervisor 与 Codex

当前版本**没有实现 Supervisor Agent**。

- 在 LangChain 的多 Agent 设计中，Supervisor 通常指一个能够根据对话状态动态选择和调用子 Agent 的中心 Agent。
- 当前真实工作流是由 LangGraph `StateGraph` 编排的固定双节点流程：Data Agent 完成事实整理后，再交给 Communication Agent。
- Codex 可以作为仓库外部的自然语言交互环境，通过 Skill 或 CLI 调用 CareerReach AI，并解释返回结果；它不是本项目 LangGraph 图中的 Supervisor，也不是被本地 CLI 直接调用的模型 API。

如果未来加入动态任务分派、循环重写或多个专业 Agent，再引入 Supervisor 模式会更合适。

## Agent 分工

### Data Agent

负责“把事实准备好”：

- 整理公司、岗位、沟通目标和用户补充信息；
- 从 ChromaDB 中检索相关公司、JD、简历和历史沟通证据；
- 为证据保留可追踪标识；
- 明确信息是否缺失；
- 不直接撰写沟通话术。

### Communication Agent

负责“基于事实给出沟通方案”：

- 生成不同表达风格的候选话术；
- 说明每个版本使用了哪些证据；
- 给出跟进建议、置信度和风险提示；
- 在信息不足时建议人工检查；
- 不直接在招聘平台发送消息。

### Human Review Gate

它不是生成式 Agent，而是一条产品安全边界：

- **可采用**：证据相对完整，用户可以选择使用候选草稿；
- **需检查**：信息不足或存在风险，需要用户补充或修改；
- **不建议继续**：当前条件下不建议触达。

无论系统给出哪一种建议，最终采用、发送或放弃都由用户决定。

## 端到端工作流程

这张图从用户视角说明一次任务如何完成，不展示内部字段名。

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontSize":"16px","fontFamily":"Arial, sans-serif","primaryTextColor":"#172033","lineColor":"#64748B"}}}%%
flowchart LR
    A["1. 描述目标<br/>提供岗位和沟通需求"]
    B["2. 整理信息<br/>统一岗位与个人经历"]
    C["3. 查找证据<br/>检索相关事实与历史上下文"]
    D["4. 生成策略<br/>形成候选话术与跟进建议"]
    E{"5. 信息是否充分？"}
    F["6A. 用户审核<br/>比较、修改并决定是否采用"]
    G["6B. 补充信息<br/>说明缺口后重新分析"]

    A --> B --> C --> D --> E
    E -- "是" --> F
    E -- "否" --> G
    G -. "补充后返回" .-> B

    classDef step fill:#EFF6FF,stroke:#2563EB,color:#172554,stroke-width:1.5px;
    classDef decision fill:#FFF7ED,stroke:#D97706,color:#7C2D12,stroke-width:1.5px;
    classDef finish fill:#ECFDF5,stroke:#0F8B8D,color:#134E4A,stroke-width:1.5px;

    class A,B,C,D step;
    class E decision;
    class F,G finish;
```

真实 Backend 的核心执行顺序是：

```text
START → Data Agent → Communication Agent → END
```

当 LangGraph 不可用时，上游工作流可以按相同顺序降级执行，并保持一致的输出结构。

## RAG 与证据链

RAG 的作用不是单纯增加上下文，而是让关键建议能够回到原始依据。

| 知识类型 | 典型内容 | 使用目的 |
| --- | --- | --- |
| 公司 | 业务方向、产品与行业信息 | 避免生成与公司无关的通用表达 |
| 岗位 | JD 职责、技能要求和岗位重点 | 判断岗位真正关注什么 |
| 简历 | 项目经历、职责、成果和技能 | 找到可以支撑沟通内容的个人证据 |
| 沟通 | 历史问题、回复和跟进状态 | 避免重复提问，保持对话连续 |

真实 Backend 可以使用 ChromaDB 的 `career_rag` collection 管理这些内容。召回的证据会进入 Agent 上下文，生成结果需要声明使用了哪些依据；当证据不足时，系统会优先提示人工补充。

公开 Fixture 模式只模拟相同的数据结构，不会声称真实启动了向量检索。

## 技术实现

### 技术栈

| 模块 | 技术 | 在项目中的作用 |
| --- | --- | --- |
| 应用后端 | Python 3.10+ | CLI、Backend 适配、结果校验和测试 |
| 命令入口 | `argparse` | 提供轻量、可复现的本地运行入口 |
| 本地工具层 | `boss-agent-cli` | 提供招聘场景数据能力与真实双 Agent 工作流 |
| Agent 编排 | LangGraph `StateGraph` | 串联 Data Agent 与 Communication Agent |
| RAG 数据库 | ChromaDB | 保存和检索公司、岗位、简历与沟通上下文 |
| 数据交换 | JSON | 统一输入输出协议，便于 CLI、Codex、MCP 或未来 Web 层接入 |
| 进程适配 | Python `subprocess` | 调用本地 CLI，并处理 Windows 中文编码兼容 |
| 输出校验 | Contract validator | 检查行动建议、草稿完整性和证据引用 |
| 隐私检查 | Redaction scan | 识别 Cookie、Token、会话和平台标识等敏感内容 |
| 测试与构建 | Pytest、Hatchling | 验证公开样例、输出契约和Python包构建 |
| 可选交互环境 | Codex + 仓库 Skill | 用自然语言调用CLI、阅读结果并协助用户判断 |

### 双 Backend

| Backend | 适用场景 | 是否需要外部依赖 | 数据 |
| --- | --- | --- | --- |
| `fixture`（默认） | GitHub 展示、快速体验和自动测试 | 不需要登录、模型服务或 ChromaDB | 合成数据 |
| `boss` | 本地集成验证与真实双 Agent 工作流 | 需要安装 `boss-agent-cli`；RAG 可选 | 用户本地上下文或本地知识库 |

两种模式返回相同的核心结构，让公开演示和本地工作流能够复用同一套上层处理逻辑。

## 输入与输出

### 输入示例

```json
{
  "company": "未来智能",
  "job_title": "AI 产品经理",
  "goal": "initial_outreach",
  "facts": {
    "company_business": "企业 AI 客服和 Agent 平台",
    "job_requirement_judgment": "RAG、Agent 工作流、ToB 需求分析",
    "resume_evidence": "AI 客服方案、Dify 工作流和 RAG Agent 实践"
  }
}
```

### 输出内容

系统返回的不是单独一句话，而是一份可审核的沟通决策结果，主要包括：

- 整理后的岗位上下文与可用证据；
- 当前缺失的信息；
- 多个候选沟通版本；
- 每个版本使用的证据；
- 跟进建议、置信度与风险提示；
- 建议采用、人工检查或停止的状态。

完整结构化样例见 [`examples/mock_agent_output.json`](examples/mock_agent_output.json)。

## 快速运行

默认运行 Fixture Backend。它只使用合成数据，不需要招聘平台登录、Cookie、外部模型或 ChromaDB。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
.\scripts\run-demo.ps1
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
./scripts/run-demo.sh
```

也可以直接运行：

```bash
python -m careerreach_ai --input examples/mock_opportunity.json --pretty
```

### 使用本地真实 Backend

```bash
python -m pip install -e ".[boss]"
python -m careerreach_ai \
  --backend boss \
  --data-dir .tmp-demo-data \
  --input examples/mock_opportunity.json \
  --pretty
```

默认参数为 `rules + no-rag + no-save`，用于验证工作流与输出，不自动投递或发送消息。

本地 ChromaDB 配置完成后，可以显式开启 RAG：

```bash
python -m careerreach_ai \
  --backend boss \
  --use-rag \
  --data-dir .tmp-demo-data \
  --input examples/mock_opportunity.json \
  --pretty
```

## 在 Codex 中使用

Codex 是本仓库的一种可选交互方式。它可以读取自然语言任务，通过项目级 Skill 调用 CareerReach CLI，并把结构化结果解释给用户；核心双 Agent 工作流仍由本地 Backend 执行。

仓库 Skill 位于：

```text
.agents/skills/careerreach-ai/
├── SKILL.md
└── agents/
    └── openai.yaml
```

示例：

```text
$careerreach-ai 用公开样例运行一次 Demo，说明系统使用了哪些证据，
并在任何发送动作前停下来让我确认。
```

也可以查看 [`examples/codex_conversation_prompt.md`](examples/codex_conversation_prompt.md)。

## 测试

```bash
python -m pytest -q
```

测试覆盖：

- Fixture Backend 是否符合统一输出契约；
- 本地 Backend 是否使用安全默认参数；
- 证据引用能否映射回上下文；
- 公开样例是否包含敏感标记；
- README、Skill、架构说明与运行时术语是否保持一致。

## 仓库结构

```text
careerreach-ai/
├── .agents/skills/careerreach-ai/   # Codex 项目级 Skill
├── src/careerreach_ai/              # 应用后端与 Backend 适配
├── examples/
│   ├── mock_opportunity.json        # 合成输入
│   ├── mock_agent_output.json       # 结构化输出
│   └── showcase/                    # 可点击的 Prompt 与表格展示
├── docs/                            # 架构、产品和安全补充说明
├── scripts/                         # Windows / macOS / Linux 运行脚本
├── tests/                           # 契约与安全测试
├── pyproject.toml
├── THIRD_PARTY_NOTICES.md
└── README.md
```

## 当前实现边界

### 本仓库已实现

- 可直接运行的 Fixture Backend；
- `boss-agent-cli` Backend 适配器；
- 统一输入输出契约与结果校验；
- Windows 中文输出兼容；
- 敏感标记扫描、测试和跨平台脚本；
- 公开演示文档、Codex Skill 与脱敏展示材料。

### 依赖第三方 `boss-agent-cli`

- Data Agent 与 Communication Agent 的真实工作流；
- LangGraph 编排与顺序降级；
- ChromaDB RAG 读写和求职上下文管理；
- 招聘平台本地数据与相关 CLI 能力。

### 当前不包含

- 独立 Web 前端或在线托管服务；
- 当前版本的 Supervisor Agent；
- 自动投递、自动发送消息或自动交换联系方式；
- 真实账号凭证、简历、聊天记录、岗位标识或向量数据库；
- 面向生产环境的多租户、权限、监控和云部署能力。

## 安全与隐私边界

公开仓库只允许合成或充分脱敏的数据。以下内容不得提交：

- Cookie、Token、加密 Session、登录二维码或浏览器用户目录；
- 真实简历、招聘者消息、联系方式和沟通记录；
- 真实 `job_id`、`security_id`、`contact_id` 或含这些字段的平台导出表；
- 本地 ChromaDB 持久化目录和真实向量数据；
- `.env`、私钥或模型 Provider 密钥。

Agent 可以整理事实、检索证据和生成建议，但任何平台写操作、投递、回复、联系方式交换或验证流程都需要用户明确确认。系统不会尝试绕过平台登录、验证、风控或账号限制。

## 第三方开源说明

本项目的本地招聘工具层与真实双 Agent 工作流基于 MIT License 的开源项目 [`boss-agent-cli`](https://github.com/can4hou6joeng4/boss-agent-cli)。详细归属与许可证说明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## License

本展示仓库采用 [MIT License](LICENSE)。第三方组件继续遵循其各自许可证。

---

<div align="center">

**CareerReach AI — 用可核验的证据支持每一次求职沟通。**

</div>
