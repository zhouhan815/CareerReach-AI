# Architecture

CareerReach AI separates the user-facing interaction, the public application
adapter, the upstream two-agent workflow, and the human review boundary.

## 1. Interaction client

Users can run the repository through the CLI or use Codex as an optional
natural-language client. Codex may invoke the repository Skill and CLI, then
explain the structured result. It is external to the LangGraph runtime and is
not implemented as the workflow supervisor.

## 2. CareerReach application layer

The public repository implements:

- CLI argument parsing and backend selection
- a Fixture backend for reproducible public demonstrations
- an adapter for the third-party `boss-agent-cli`
- JSON output validation
- privacy-marker scanning and tests

The application layer does not pretend to contain the upstream agents or vector
database.

## 3. Upstream two-agent workflow

The real workflow is provided by `boss-agent-cli` and can run through a
LangGraph `StateGraph`:

```text
START -> boss_data_agent -> communication_agent -> END
```

### Boss Data Agent

The data agent prepares the opportunity context:

- normalizes company, role, goal, and direct facts
- retrieves optional RAG evidence from ChromaDB
- records missing information
- preserves traceable evidence identifiers

It collects facts and does not draft outreach.

### Communication Agent

The communication agent turns the prepared context into:

- candidate communication drafts
- follow-up guidance
- confidence and risk signals
- evidence references
- a recommended review state

## 4. Human review

Human review is a product boundary rather than another generative agent.
Candidate drafts can be reviewed, edited, accepted, or discarded by the user.
The demo does not automatically send platform messages.

## Supervisor terminology

The current version does not implement a Supervisor Agent. In a supervisor
architecture, a central agent dynamically chooses and calls subagents based on
the evolving conversation. CareerReach currently uses a fixed two-step
LangGraph workflow. A supervisor can be added later if the product introduces
dynamic routing, additional specialist agents, or iterative rewrite loops.

If LangGraph is unavailable, the upstream workflow falls back to the same
two-step sequential execution and preserves the output structure.
