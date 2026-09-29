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

## Cycle 2 — 2026-09-29

Area: Command palette result rendering and mobile usability.

Goal: Make the global Ctrl+K navigation palette usable in the Figma chat shell,
including on a narrow mobile viewport.

Observed problems: On `/assistente/` the palette appeared with enormous SVGs
covering its first result. The SVG markup itself was valid and sanitized; the
chat shell's `workspace.css` defined the palette container but omitted styles
for result rows, icon wrappers, titles and descriptions. The icon wrapper
therefore expanded to the SVG's intrinsic size (roughly 341px square).

Changes made: Added compact flex result rows, fixed 20px icon slots and 18px
SVGs, readable title/description hierarchy, command-specific icon colors and a
clear empty-search state in `workspace.css`. Added a Puppeteer real-browser
regression test that opens the palette at 390×844, verifies focus, item count,
icon and row bounds, markup visibility, and Escape dismissal.

Browser validation: Opened the palette in Chromium at the 390px in-app viewport.
All results remain readable, the icon marks are compact and the panel fits the
screen; opening focuses the search field and Escape dismisses the overlay.
Visually inspected the screenshot. The normal in-app keyboard shortcut did not
open reliably through CUA's keyboard bridge, so the palette was opened through
its visible toolbar button; the real-browser regression test exercises Ctrl+K.

Tests: Full JavaScript test suite passed, including all 9 real-browser tests and
the new palette regression. Ruff passed; design-token guard passed with zero
legacy hex values; architecture budget passed with no findings; Django system
check passed; `git diff --check` passed. The targeted palette browser test also
passed independently.

Console: No palette-specific console errors were observed in Chromium. The JS
suite emitted only the expected simulated storage quota warnings from tests.

Responsive validation: Palette test uses 390×844 and asserts it stays within the
viewport, SVGs are at most 20px, and result rows remain below 80px. The manual
Chromium viewport was the existing 390px mobile viewport.

Visual score: Command palette 8.5/10 after correction; full assistant mobile
workspace remains 7.5/10 and requires broader interaction and visual passes.

Regressions: None found in the full JavaScript suite or static guards.

Next action: Continue auditing the remaining root routes and interactive
components for shell-specific style omissions and inconsistent hierarchy.

## Cycle 3 — 2026-09-29

Area: Workspace parity, responsive navigation, empty states and form geometry.

Goal: Address confirmed remaining items from the supplied UI audit and inspect
related mobile behavior in the running application.

Observed problems: `/normas/` already extends the shared workspace base in the
current checkout, with the global sidebar, mobile topbar and command palette;
the dedicated page CSS only styles its content. The norma cards already give
their title more weight than publication/vigency metadata (18–22px title vs
9px labels and 12px values), so the old screenshot issue was already addressed.
The chat shell still lacked the workspace's sidebar quick-search shortcut. More
importantly, its hamburger toggled only the desktop `collapsed` state, while
mobile CSS required `is-open`, making navigation unreachable from that button.
The shared workspace hamburger also changed the CSS class without updating its
ARIA state or supporting Escape-to-close, and its `aria-controls` target did not
exist on workspace pages.
The search field forced autofocus on mobile, its 100%-width form controls could
overflow due to content-box sizing, and the collections empty state invited a
login despite no user-facing login route being available.

Changes made: Added the quick-search trigger to the chat sidebar footer and
aligned its keyboard hint. Implemented distinct mobile-open and desktop-collapse
sidebar states, accessible `aria-expanded`/`aria-controls` labels, Escape and
outside-click closure, and a real backdrop button. Revised collections copy to
separate the empty state, account limitation and public-norms action without a
dead login promise. Removed forced search autofocus, tightened the search empty
state, emphasized select chevrons, and applied border-box sizing to workspace
search/settings/dialog controls. Gave the shared sidebar a stable `id` and
updated workspace menu state, Escape handling, focus return, and resize cleanup.

Browser validation: On the live Django app at 390×844, opened `/assistente/`,
verified the hamburger exposes settings and quick search, the palette opens
from the footer button and focus enters the search field. Verified the backdrop
and Escape close the mobile sidebar. Inspected `/colecoes/`, `/pesquisa/` and
`/configuracoes/`: the revised empty-state hierarchy is legible, search inputs
stay within their panel, and the model select chevron is clearly visible.
The workspace sidebar also opens on mobile and closes with Escape.
`/normas/` already uses the common sidebar/topbar shell; list content remains
purposefully specialized. Desktop/mobile screenshots were inspected in
Chromium; this browser surface does not support saving screenshots to files.

Tests: Full Python suite: `652 passed, 6 skipped, 7 warnings` (SQLite; baseline
count unchanged). Ruff, design-token guard, architecture budget and `manage.py
check` passed. The real-browser sidebar test now covers open, Escape close,
backdrop close, ARIA state, and desktop geometry. One unrelated drawer/streaming
browser test failed once in the full JS run, then passed isolated and in the
fresh complete rerun. The full JS suite passed, including all 9 real-browser
tests. `git diff --check` passed before final edits and will be repeated.

Console: No visible app errors on the manually inspected pages. A missing
`matchMedia` API in JSDOM was found by existing JS tests after the responsive
logic was added; production now falls back to viewport width and this was fixed
before rerunning.

Responsive validation: 390×844 mobile menu is fully off-canvas when closed,
opens to the 240px rail with a dimmed backdrop, and closes through Escape or an
outside click. Workspace forms stay within their panels. Existing browser test
also rechecks sidebar item geometry at 1280×800.

Visual score: Chat navigation 8.5/10; search/settings controls 8/10; collections
empty state 8/10. The complete app remains in active visual iteration.

Regressions: No Python, static-check, or final JavaScript regressions. One
JavaScript real-browser timing failure was not reproducible in isolation or in
the subsequent full rerun. Simulated quota warnings are expected test cases.

Next action: Check the updated source/diff and browser console across routes,
then continue the broader root-route interaction audit.
