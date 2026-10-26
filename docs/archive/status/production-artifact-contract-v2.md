# Production Artifact Contract v2

Every release gate should emit JSON rather than relying solely on human-readable
stdout. This allows CI artifacts, dashboards and post-mortem tooling to consume
the same information.

Required top-level fields:

```json
{
  "schema_version": 2,
  "passed": true,
  "generated_at": "ISO-8601 timestamp",
  "commit": "git SHA",
  "environment": "staging|production|ci",
  "checks": [],
  "warnings": [],
  "failures": []
}
```

Each check should include:

- name;
- start time;
- duration;
- return code;
- summary;
- artifact path if one exists.

The contract must not include secrets, full user questions, uploaded document
bytes or full generated legal answers.

Logs should be summarized at artifact boundaries. Sensitive raw content remains
inside the application logs subject to the existing redaction policy.
