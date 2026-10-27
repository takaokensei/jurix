# Migration Gate v2

A migration is a production event, not just a code change.

## Pre-merge

- `makemigrations --check`;
- migration graph inspection;
- test database migration from zero;
- migration on the current production schema snapshot.

## Release

- no unexpected destructive operation;
- lock duration considered;
- large table operations planned;
- index build strategy reviewed;
- rollback/forward-only behavior documented.

## Post-release

- migration status clean;
- health endpoint healthy;
- background workers restarted if task signatures changed;
- vector health verified if embedding schema changes.
