# CI Gates v2

## Pull request

Run fast, deterministic checks:

- Ruff;
- focused hardening tests;
- service contract scan;
- security regression scan;
- architecture budget.

## Main branch

Add:

- full pytest;
- Django system checks;
- production preflight;
- release artifact aggregation.

## Nightly

Run:

- full security audit;
- benchmark contract validation;
- staging HTTP smoke where infrastructure exists;
- vector health against a disposable database.

## Why separate the jobs?

A single all-in-one job produces poor diagnostics. Independent gates let the
team identify whether a regression belongs to code, configuration, data,
security or infrastructure.
