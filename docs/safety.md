# Safety and Privacy

This demo is intentionally scoped to public, synthetic data.

Do not commit:

- BOSS Zhipin cookies, encrypted sessions, auth salts, or browser profiles
- real recruiter messages
- real resumes
- real job IDs, security IDs, contact IDs, or Excel exports
- ChromaDB local persistence directories

The product boundary is also explicit:

- The agent may generate drafts.
- The agent may recommend a follow-up plan.
- The agent may mark `manual_review`.
- The agent should not automatically send messages, apply to jobs, exchange
  contact information, or bypass platform verification.

For an HR-facing demo, synthetic data is enough to show the architecture and
product judgment without exposing private job-search activity.
