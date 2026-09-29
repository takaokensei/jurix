# Frontend Polish Log

## Baseline — 2026-09-29

Environment: Windows 11, Python 3.12.10 virtual environment, local Django server
using the repository's SQLite database; Chromium through the Codex in-app
browser. Docker Desktop's Linux engine was unavailable, so PostgreSQL-backed
tests and a Compose server could not be used in this session. The local database
does contain ten recent norms, allowing the main legislation views to render.

- Python: `652 passed, 6 skipped, 7 warnings` (`pytest -q`, local SQLite).
- JavaScript: initial run `63 passed, 2 failed`. The authenticated history
  pagination browser test failed its exact scroll-position invariant (actual
  3172, expected 3204); a second failure was not isolated in the truncated
  initial output. Repeated focused runs later confirmed the pagination issue.
- Ruff: passed.
- Design token guard: passed; zero legacy hex values outside the token baseline.
- Architecture budget: passed.
- Django system check: passed.
- Browser: Chromium, screenshots visually inspected at 1440×900, 1280×800 and
  390×844. The `cua_repl` browser exposes screenshots for inspection but does
  not expose a filesystem save operation; screenshots are therefore recorded
  as visual evidence in the audit trail rather than files under `docs/ui-audit`.
- Routes confirmed from Django URL configuration and opened locally:
  `/assistente/`, `/pesquisa/`, `/normas/`, `/normas/3/`,
  `/normas/3/compare/`, `/normas/3/tree/`, `/colecoes/`, `/historico/`,
  `/configuracoes/`. `/colecoes/1/` redirects to `/colecoes/` because the local
  database has no collection with that id.
- Responsive check at 390px: all nine main routes had `scrollWidth = 390px`.

## Cycle 1 — 2026-09-29

Area: Global shell geometry and chat history navigation.

Goal: Keep navigation backgrounds inside their shells and preserve the visible
chat position while older history pages are inserted.

Observed problems: `.figma-sidebar-item` and `.workspace-nav-item` used
`width: 100%` with padding under content-box sizing. At 390px the active chat
link extended 23px beyond the translated sidebar, leaving a blue strip over the
page. On desktop the navigation backgrounds crossed their sidebar borders.
The chat's history pager also competed with browser scroll anchoring and
font-loading layout changes, causing inconsistent position restoration.

Changes made: Apply `box-sizing: border-box` to both sidebar item types. Disable
native anchoring on the chat scroll container and use an instant, measured
scroll-height correction during pagination. The browser test now waits for
fonts to settle and checks that the previous first message remains within 8px
of its original visual position. Add a real-browser sidebar-boundary test for
390px and desktop.

Browser validation: In Chromium, `/normas/` at 1280×800 has sidebar right edge
at 240px and every navigation item ends at 225px. On `/assistente/` at 390×844,
the closed sidebar ends at x=0 and its active item at x=-17; document width is
390px. Screenshots were visually inspected before and after. Console error and
warning collection on both routes returned an empty list.

Tests: Focused pagination browser test passed five consecutive runs. Full
JavaScript suite: `66 passed, 0 failed`. Ruff passed; design-token guard reports
zero legacy hex occurrences; architecture budget passed; `git diff --check`
passed. Python baseline remains `652 passed, 6 skipped` on local SQLite; no
Python files changed in this cycle.

Console: No browser error or warning during the verified workspace and assistant
routes. The suite emits expected console messages in tests that deliberately
simulate storage quota failures.

Responsive validation: Before change, all nine main routes reported no document
horizontal overflow at 390px, although the chat sidebar child leaked visually.
After the change the assistant screenshot confirms the leak is gone; the
workspace desktop geometry also stays inside its 240px track.

Visual score: Navigation/shell 8.5/10 after the geometry fix; norms and
workspace hierarchy 8/10; mobile assistant composition 7.5/10. The assistant
composition and remaining pages still need additional visual iterations.

Regressions: None found in the full JavaScript suite or the route smoke audit.

Next action: Fix the command palette's oversized SVG result icon, then audit the
other interactive and empty states for similar omissions from the canonical
workspace stylesheet.
