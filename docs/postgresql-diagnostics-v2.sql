-- Read-only PostgreSQL diagnostics for Jurix.
-- Run in a maintenance session; these statements do not mutate data.

SELECT version();

SELECT extname, extversion
FROM pg_extension
WHERE extname = 'vector';

SELECT relname, indexrelname, indexdef
FROM pg_indexes
WHERE schemaname = current_schema()
  AND relname IN ('legislation_dispositivo', 'legislation_norma')
ORDER BY relname, indexrelname;

SELECT
    schemaname,
    relname,
    n_live_tup,
    n_dead_tup,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
WHERE relname IN ('legislation_dispositivo', 'legislation_norma')
ORDER BY relname;

SELECT
    datname,
    numbackends,
    xact_commit,
    xact_rollback,
    blks_read,
    blks_hit
FROM pg_stat_database
WHERE datname = current_database();
