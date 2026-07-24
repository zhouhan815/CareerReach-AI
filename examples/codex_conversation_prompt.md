# Codex Conversation Demo Prompt

下面是一段可以在 Codex 中演示的自然语言交互。Codex 在这里是调用仓库
Skill 与 CLI 的外部交互环境，不是 LangGraph 工作流中的 Supervisor：

```text
我在看一个 AI 产品经理岗位。请你用 Boss Data Agent 先整理公司、岗位、简历证据，
再让 Communication Agent 生成 2 个初次沟通版本。

要求：
- 只使用已有证据，不要编造公司业务；
- 输出 recommended_action、confidence、risk_flags 和 evidence_ids；
- 如果证据不足，停在 manual_review；
- 不要自动发送消息。
```

可以配合 `examples/mock_opportunity.json` 运行本仓库的 fixture demo，或者在本机安装
`boss-agent-cli` 后切换到真实 CLI backend。
