# Architecture

This demo uses a three-layer agent design.

## 1. Codex Supervisor

Codex is the top-level supervisor. It converts the user's natural-language
request into a bounded workflow, selects the backend, validates the output, and
keeps sensitive actions behind human review.

## 2. Boss Data Agent

The data agent prepares `OpportunityContext`:

- company and job title
- direct facts from an opportunity sheet
- RAG evidence from ChromaDB when available
- missing information flags
- traceable evidence IDs

The upstream implementation keeps the data agent deliberately narrow: it
collects facts and does not draft outreach on its own.

## 3. Communication Agent

The communication agent turns structured context into:

- recommended action: `send`, `manual_review`, or `skip`
- multiple draft styles
- follow-up plan
- confidence score
- evidence IDs used by each draft
- risk flags

In the upstream CLI, the workflow can run through LangGraph:

```text
START -> boss_data_agent -> communication_agent -> END
```

If LangGraph is unavailable, it falls back to a sequential runtime. This keeps
the product demo stable while preserving a clean migration path to graph-based
multi-agent orchestration.
