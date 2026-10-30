# Security and Privacy Requirements

> **Scope note:** These are the minimum protections for the existing local MVP. The target privacy lifecycle and release boundary are specified in `MASTER_IMPLEMENTATION_PLAN.md`; stronger controls must not be weakened during migration.

## Data handling

- Tell the user before any idea or answer is sent to the configured external AI provider.
- Do not send data to a provider until the user explicitly continues after seeing that notice.
- Use only the configured provider and endpoint. Do not fetch URLs mentioned in the idea.
- Do not persist user content by default; disclose any necessary short-lived session storage and expiry.
- Do not add analytics, telemetry, or third-party scripts in the MVP.
- Provide a clear way to restart or discard the current idea.

## Secrets

- Read Gemini API credentials only from the local `.env` or environment variables, outside the ZIP.
- Never expose credentials to client-side HTML, browser storage, logs, generated documents, or archives.
- Do not ask the user to paste credentials into the idea field.
- Redact authorization headers and credential values from errors.

## Untrusted inputs and model output

- Treat user input and AI output as untrusted content.
- Do not execute generated text, code, shell commands, or URLs.
- Escape user/model text when rendering HTML.
- Use fixed output path templates; reject traversal, absolute paths, and unsafe archive names.
- Validate structured output against typed models and JSON Schema before rendering or packaging.
- Keep instructions embedded in an idea from overriding system behavior, disclosing secrets, or changing the package layout.
- Bound idea length, number of questions, model output size, and generation time.

## Local web application

- Bind to `127.0.0.1` by default.
- Reject non-loopback host configuration in the local-only release; a deployment on a LAN/public interface is not supported.
- Apply normal web protections appropriate to the chosen server-rendered framework, including CSRF protection for state-changing form submissions.
- Do not claim the MVP is safe for public hosting or multi-user deployment.
- Return safe errors to the browser; do not expose stack traces or provider response headers.

## Output safeguards

- Run the generation contract checks before enabling ZIP download.
- Include only the generated project files and manifest.
- Scan for common credential patterns and configured secret values; block and explain a match.
- State in the UI that automated secret detection is not exhaustive and the user should inspect the ZIP.

## Human control

- The user reviews confirmed facts, accepted proposals, assumptions, and open questions before generation.
- The app must not autonomously create repositories, run a coding agent, execute code, commit, deploy, or alter production data.
