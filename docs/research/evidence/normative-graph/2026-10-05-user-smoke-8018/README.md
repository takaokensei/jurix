# Tentativa incompleta de smoke — 05/10/2026

O diretório tem duas capturas preliminares produzidas quando `JURIX_BASE_URL`
apontava de fato para `http://127.0.0.1:8019` (o nome `8018` no diretório está
incorreto). A execução parou no cenário de norma sem documento-base porque o
mapfile QA existente era antigo e não continha `edge_case_fixtures.missing_original`.

Estas imagens não são evidência de execução aprovada nem cobrem o restante do
smoke. O seed idempotente gerou um mapfile novo e a execução completa está
registrada em `../2026-10-05-user-smoke-8019-r1/`.
