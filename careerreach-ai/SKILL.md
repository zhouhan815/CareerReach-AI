---
name: careerreach-ai
description: Run and interpret the CareerReach AI evidence-grounded job-search communication agent in this repository. Use when a user asks Codex to analyze a company or job, match resume evidence to a JD, generate recruiter outreach or follow-up drafts, demonstrate the Boss Data Agent and Communication Agent workflow, run the fixture or boss backend, inspect evidence_ids/confidence/risk_flags, or explain the CareerReach AI architecture. Default to synthetic data and human review; do not use for autonomous applications, automatic messaging, or bypassing recruitment-platform controls.
---

# CareerReach AI

Operate CareerReach AI as a repository-scoped Codex workflow. Treat Codex as the Supervisor and this repository's CLI as the tool layer. Produce evidence-grounded communication plans while keeping all recruitment-platform writes behind explicit user confirmation.

## Establish the repository context

1. Locate the repository root containing `pyproject.toml` with `name = "careerreach-ai"`.
2. Run commands from that repository root.
3. Read `examples/mock_opportunity.json` for the public input contract and `examples/mock_agent_output.json` for the output contract when needed.
4. Use synthetic data by default. Put any user-specific temporary input or output under `.tmp-demo-data/`; never overwrite public examples with private data.

Do not describe `boss-agent-cli` as the model. Codex is the natural-language Supervisor. The third-party CLI is the local tool and data layer. Do not claim that the CLI calls Codex through an OpenAI-compatible API.

## Select the execution path

Choose one path based on the user's request.

### Public or HR-facing demo

Use the Fixture backend when the user wants a quick demonstration, repository verification, architecture walkthrough, or output example.

Run the platform-appropriate script:

```powershell
.\scripts\run-demo.ps1
```

```bash
./scripts/run-demo.sh
```

If the package is installed, this equivalent command is valid:

```bash
python -m careerreach_ai --backend fixture --input examples/mock_opportunity.json --pretty
```

Explain that Fixture mode:

- uses synthetic company, job, and resume evidence;
- does not require a BOSS login, Cookie, ChromaDB, or external model provider;
- simulates the public contract of the dual-Agent workflow rather than contacting a recruitment platform;
- is the recommended path for interviews and GitHub review.

### Local `boss-agent-cli` workflow

Use the `boss` backend only when the user explicitly wants to exercise the installed third-party workflow or verify local integration.

```bash
python -m careerreach_ai \
  --backend boss \
  --data-dir .tmp-demo-data \
  --input examples/mock_opportunity.json \
  --pretty
```

Preserve the defaults `--mode rules --no-rag --no-save` unless the user asks for another mode. These defaults allow the communication workflow to run without an external model provider and without persisting private context.

If the executable is not installed, report that clearly. The optional repository dependency is:

```bash
python -m pip install -e ".[boss]"
```

Do not install dependencies when the user only asked for an explanation or review.

### RAG-enabled workflow

Add `--use-rag` only when the user asks for evidence retrieval and a compatible local ChromaDB service is configured.

```bash
python -m careerreach_ai \
  --backend boss \
  --use-rag \
  --data-dir .tmp-demo-data \
  --input examples/mock_opportunity.json \
  --pretty
```

If ChromaDB is unavailable, fall back to `--no-rag` and state that the result uses direct context only. Do not present Fixture evidence as proof that a live vector search occurred.

## Build the opportunity context

Collect or confirm these fields before generating a personalized plan:

- `company`: target company;
- `job_title`: target role;
- `goal`: for example `initial_outreach`, `reply`, or `follow_up`;
- `latest_message`: the recruiter's latest message when relevant;
- `facts.company_business`: verified company or product information;
- `facts.job_requirement_judgment`: important JD requirements;
- `facts.resume_evidence`: candidate experience that directly supports the match;
- `facts.match_reasons`: concise mapping between the JD and candidate evidence.

When material facts are missing, do not invent them. Surface the gap in `missing_info` or the user-facing summary and prefer `manual_review`.

## Apply the Agent routing contract

Keep the three roles distinct:

1. **Codex Supervisor**: understand intent, choose commands, inspect JSON, compare drafts, explain uncertainty, and retain final risk judgment.
2. **Boss Data Agent**: normalize direct facts, retrieve optional RAG evidence, assign evidence identifiers, and flag missing information.
3. **Communication Agent**: generate recommended action, draft variants, follow-up plan, confidence, evidence references, and risk flags.

The real dual-Agent implementation belongs to `boss-agent-cli`. The Fixture backend only provides a compatible synthetic result for public demonstration.

## Inspect every result

Parse the JSON result and check these fields before presenting a recommendation:

1. `ok` must be `true` for a successful run.
2. `data.context.evidence` must contain the facts available to the workflow.
3. `data.context.missing_info` must be surfaced when non-empty.
4. `data.plan.recommended_action` must be `send`, `manual_review`, or `skip`.
5. `data.plan.drafts` must contain at least one non-empty message.
6. Every `drafts[].evidence_ids` value should map to an item in `context.evidence`.
7. `data.plan.risk_flags` must be shown to the user rather than hidden.
8. Treat `confidence` as a workflow signal, not a calibrated probability of hiring or reply success.

Do not recommend direct use when the action is `manual_review` or `skip`. If the action is `send`, describe it as a candidate draft that still requires the user's decision, not as permission to send automatically.

## Present the result

Return a concise, decision-oriented response with:

1. **Opportunity summary**: company, role, goal, and any missing facts.
2. **Evidence map**: company, job, and resume evidence with their `evidence_ids`.
3. **Recommended action**: action, confidence, and the reason for the recommendation.
4. **Draft options**: preserve the differences between draft styles and identify which evidence each uses.
5. **Risks and next step**: show risk flags and state what the user should verify or do next.

Avoid pasting an unexplained raw JSON dump unless the user asks for it.

## Enforce privacy and platform boundaries

- Never commit or expose real cookies, tokens, encrypted sessions, browser profiles, resumes, recruiter chats, contact details, job IDs, security IDs, or local ChromaDB persistence.
- Keep real temporary files under ignored local directories such as `.tmp-demo-data/`.
- Do not automatically send messages, apply for jobs, exchange contact information, or perform other recruitment-platform writes.
- Require explicit user confirmation before any supported platform write action.
- Stop on platform verification, account risk, login expiry, abnormal-environment warnings, or unsupported actions; report the exact recovery step.
- Never bypass QR login, verification, rate limits, account restrictions, or platform risk controls.
- Preserve visible attribution to the MIT-licensed third-party `boss-agent-cli` project.

## Validate changes and demonstrations

After code, contract, example, or Skill changes, run:

```bash
python -m pytest -q
```

The expected repository baseline is:

```text
3 passed
```

Also verify that public examples contain only synthetic data and that no generated `.tmp-demo-data/`, authentication material, exports, or vector-store files are staged for Git.

## Example invocations

- `$careerreach-ai 用公开样例运行一次 Demo，并解释每个 evidence_id 如何影响沟通草稿。`
- `$careerreach-ai 根据这个 AI 产品经理 JD 和我的三条项目经历生成两版首次沟通话术；证据不足时标记 manual_review。`
- `$careerreach-ai 检查当前输出的 confidence、risk_flags 和 evidence_ids，判断是否适合采用。`
- `$careerreach-ai 说明 Codex Supervisor、Boss Data Agent、Communication Agent 和 ChromaDB 之间如何协作。`
