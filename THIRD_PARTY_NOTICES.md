# Third-Party Notices

This repository is a public demo wrapper and orchestration showcase. It does
not claim authorship of the underlying job-search CLI.

## boss-agent-cli

- Project: `boss-agent-cli`
- Repository: https://github.com/can4hou6joeng4/boss-agent-cli
- License: MIT
- Role in this demo: local tool/data layer for BOSS Zhipin-style job discovery,
  structured JSON command output, RAG storage, and communication-agent planning.
- Vendored path in this distribution: `third_party/boss-agent-cli`

The demo code in this repository focuses on application-layer adaptation,
sample inputs, output validation, safety boundaries, documentation, optional
Codex interaction, and reproducible demo packaging around the upstream CLI.

If you publish this repository, keep `third_party/boss-agent-cli/LICENSE` and
this notice. Do not publish local runtime data, login sessions, cookies, chat
history, or private resume data.
