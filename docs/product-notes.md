# Product Notes

## Problem

Job search communication is repetitive, but fully automated outreach is risky.
The useful product surface is not "send everything automatically"; it is "help
me understand the opportunity, prepare a grounded message, and know when I
should review it myself."

## User Value

- Saves time on company/JD reading.
- Makes outreach more specific by using evidence instead of generic templates.
- Converts messy job-search notes into structured follow-up actions.
- Preserves user control for sensitive platform actions.

## PM Decisions

- Keep the first screen as conversation, not a heavy dashboard.
- Use RAG only as evidence, not as a source of unchecked claims.
- Make `manual_review` a first-class outcome.
- Prefer JSON contracts so the workflow can be reused by Codex, CLI, MCP, or a
  future web interface.

## Success Metrics

- Percentage of drafts with at least one company, job, and resume evidence ID.
- Manual review rate when evidence is sparse.
- Time from opportunity input to first usable draft.
- User acceptance/edit rate of suggested outreach.
