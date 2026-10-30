# Master Build Prompt

Open the `Context-OS` folder as the coding-agent workspace and submit:

> Build Context OS according to `AGENTS.md` and the approved `docs/MASTER_IMPLEMENTATION_PLAN.md`.
>
> Begin by reading `docs/IMPLEMENTATION_STATUS.md`. If Phase 0 is not approved/complete, work only on its next bounded specification task and record progress; do not make a breaking architecture rewrite. If Phase 0 is complete, resume from the first incomplete task ID in the status file. Preserve unrelated work and never discard the existing MVP without equivalent tested replacements.
>
> Implement one phase/task at a time. Use modular-monolith boundaries, PostgreSQL, LangGraph durable workflows, LangChain's Gemini integration, and the frontend specified in the plan. Use other agents only for independent bounded reviews/research; do not parallel-edit shared code. Personally integrate and verify all delegated findings. A plan or subagent answer is not proof that code works.
>
> For each task, add tests before declaring it complete, run its exact acceptance checks, and update `docs/IMPLEMENTATION_STATUS.md` with task ID, changed files, commands/results, remaining risks, and the next step. Do not claim unrun checks passed. Do not promise zero bugs; surface uncertainty and failures honestly. Never expose or package `.env` or API keys. Never execute model-generated code/commands or deploy publicly without explicit owner approval.

This prompt starts/resumes implementation. It does not replace the plan, acceptance criteria, or human approval gates.
