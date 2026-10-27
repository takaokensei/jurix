# Jurix Security Threat Model v2

## Assets

The protected assets include:

- legal corpus text;
- object-storage attachments;
- user chat sessions;
- generated RAG responses;
- database credentials;
- Ollama access;
- Celery broker state;
- cache contents;
- operational logs.

## Threat classes

### T1 — Upload abuse

A malicious PDF/DOCX can attempt parser exploitation, decompression bombs,
resource exhaustion or path traversal.

Primary controls:

- file signature validation;
- page/size limits;
- isolated processing;
- explicit storage keys;
- resource limits.

### T2 — Prompt injection

A legal document can contain instructions intended for the model instead of
legal content.

Primary controls:

- prompt separates evidence from user question;
- answer policy only accepts source-grounded claims;
- citations and numbers must match evidence;
- benchmark contains adversarial cases.

### T3 — Data leakage

A chat session must not expose another user's messages or attachments.

Primary controls:

- authenticated session ownership filters;
- browser-local guest history;
- explicit object-storage keys;
- no client-controlled direct record identifiers without ownership checks.

### T4 — Configuration drift

A valid development configuration may be unsafe in production.

Primary controls:

- production preflight;
- mandatory secrets;
- non-development cache;
- explicit host configuration;
- storage checks.

### T5 — Dependency and supply-chain risk

Static scanners and lock/version review should detect accidental changes in the
dependency graph.

### T6 — Operational compromise

An attacker may not need a memory corruption bug if credentials, backup files or
logs expose enough information.

Primary controls:

- secret management outside source control;
- minimal file permissions;
- backup artifact handling;
- log redaction.

## Exceptions

Every security exception must include:

- rule;
- file;
- justification;
- reviewer;
- expiration date.

Temporary exceptions should not be silently converted into permanent policy.
