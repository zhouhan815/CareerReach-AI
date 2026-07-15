# Agent Instructions

This repository is a public demo wrapper for a job-search communication agent.

- Use synthetic data in `examples/` by default.
- Do not commit real BOSS Zhipin session files, cookies, Excel exports, recruiter chats, resumes, or platform IDs.
- Keep third-party attribution visible. The low-level job-search CLI is `boss-agent-cli`; this repo demonstrates productized orchestration around it.
- Before handing off changes, run `python -m pytest`.
- Treat `send`, `apply`, `exchange contact`, and platform messaging as human-review actions, not automatic demo actions.
