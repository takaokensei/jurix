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

Next action: Continue the broader root-route interaction audit.

## Cycle 4 — 2026-09-29

Area: Norm version comparison, responsive evidence presentation, and broader
norm-route review.

Observed problems: At a 390px viewport, `/normas/3/compare/` used a five-column
line-diff grid with a 680px minimum width. The consolidated text could sit
outside the visible viewport, with no mobile labels to identify either version.
On desktop, the compact side-by-side diff remains appropriate. During broader
route inspection, `/normas/3/tree/` was also found to repeat `Confiança: 1,00`
for every extracted device; this reflects current segmentation values, but is
low-information UI and remains a candidate for a separate semantics review.

Changes made: At widths up to 720px, each diff row now stacks the original and
consolidated text in separately labelled blocks; line numbers and the desktop
marker are hidden, blank sides explicitly say “Sem linha correspondente”, and
the row no longer enforces the desktop minimum width. Desktop retains the
five-column comparison. Added template/CSS assertions and a Puppeteer test for
both mobile and desktop layouts. The browser test now waits for responsive CSS
to settle before asserting computed layout, avoiding a stylesheet timing race.

Browser validation: Inspected `/normas/`, `/normas/3/tree/`, `/normas/3/`
and `/normas/3/compare/` using the running Django app. The accessibility tree
confirmed the common shell, links and labelled tree hierarchy. At 390×844,
the comparison shows both labelled texts in sequence with no document
horizontal overflow; desktop retains the side-by-side five-column diff. This
browser surface does not support saving screenshots to files.

Tests: `npm test` passed (all JS suites, including 10 real-browser tests).
Targeted Python route/UI tests passed (24 tests). Ruff, design-token guard,
architecture budget, `manage.py check` and `git diff --check` passed. A prior
full JS run exposed a timing-sensitive assertion in the comparison browser
test; it was reproduced, fixed by waiting for the responsive stylesheet state,
and the subsequent complete run passed. Another run of the established stream
drawer test also passed, confirming its earlier intermittent failure did not
recur.

Console: No new app console issue was observed while reviewing the listed
routes. Simulated storage-quota warnings in the JS suite are intentional test
cases.

Responsive validation: Verified the mobile labels, stacked version text, and
absence of horizontal document overflow at 390px; verified the desktop header
and five-column layout at 1280px through the real-browser test.

Visual score: Norm version comparison 8/10 mobile and 8/10 desktop after the
change. The overall product remains in active visual iteration.

Regressions: No regressions in the full JS suite, targeted Python tests, lint,
design-token/architecture checks, or Django system check. Existing project
environment lacks global `ruff`, `pytest`, and Django commands; checks were
rerun successfully using the repository `.venv`.

Next action: Continue manual interaction and accessibility review across the
norm detail, compare, tree, history and collection routes; assess whether
segmentation confidence adds trustworthy, interpretable value to the tree UI.

## Cycle 5 — 2026-09-29

Area: Norma tree disclosure and mobile review of remaining workspace pages.

Goal: Remove low-value internal metadata from the public-facing legal structure
view and check consistency across collections, history, settings and search.

Observed problems: The device tree repeated a technical segmentation score of
`1.00` and an internal ordering index in every node. The label “Confiança” was
unqualified and could be read as legal confidence rather than regex extraction
confidence. Mobile screenshots also showed this metadata as repetitive noise.

Changes made: Simplified recursive tree-node metadata to show only the legal
device type. Kept extraction internals in the data/model layer unchanged; this
is a presentation-only change. Added a regression assertion preventing the
public template from rendering the internal confidence or ordinal index.

Browser validation: At 390px, re-opened `/normas/3/tree/` and confirmed the
node cards now show only “Artigo” or “Inciso” metadata, reducing noise and
improving space for the legal text. Visually reviewed `/colecoes/`,
`/historico/`, `/configuracoes/`, and `/pesquisa/` at the same viewport. The
collection empty state has distinct empty/account/public-exploration sections;
history clearly distinguishes an anonymous browser session; settings controls
fit the viewport and the model selector chevron is visible; search filters
remain readable and within their panel.

Tests: Norma UI test file passed (11 tests), workspace route tests passed (18),
Ruff passed, and `git diff --check` passed. Full `npm test` passed after this
cycle’s final edits, including all 10 real-browser tests. The streaming/drawer
test intermittently failed in an earlier complete run, so it now captures
post-click diagnostics (drawer invocation count, hit target, and panel content)
if it fails again; subsequent isolated and full runs passed.

Console: No visible app error observed on the manually reviewed routes.

Responsive validation: Collection, history, settings, search, and tree pages
were inspected in the live browser at 390px without horizontal overflow or
clipped controls in the visible areas.

Visual score: Tree readability 8.5/10 mobile; collections 8/10; history 8/10;
settings 8/10; search 7.5/10. The search empty-state card is text-heavy and the
below-fold guidance could be more compact; keep it on the audit backlog.

Regressions: None found. Frontend-only markup change; no backend contract or
stored data was changed.

Next action: Continue detailed assistant interaction review (composer, answer
actions, retry/error handling) and check keyboard/focus behavior across routes.

## Cycle 6 — 2026-09-29

Area: Assistant welcome-state suggestion motion and layout stability.

Goal: Verify that dynamic corpus suggestions arrive quickly and present complete
questions without an artificial typewriter or progressive layout shift.

Observed problems: On the live mobile assistant, the suggestion title revealed
character-by-character after API load, including a blinking block cursor. This
made a navigation prompt look like a streaming legal answer and changed the
card height while its text wrapped. In the in-app browser the reveal took
several seconds, even though a direct same-origin API check returned HTTP 200
in about 144ms; animation cadence depends on browser frame scheduling and
should not delay access to the prompt.

Changes made: Removed the JavaScript typewriter and cursor from suggestion
cards. The complete question is now rendered immediately, while the card uses
a single 160ms opacity/translate entrance animation (the design token already
defined by the design system). The existing global `prefers-reduced-motion`
rule disables that motion. Expanded the dynamic suggestions regression test to
require the full visible question and prevent reintroduction of the typewriter.

Browser validation: On `/assistente/` at 390×844, reloaded the page and verified
the suggestion appeared as complete text after the corpus response, without a
blinking cursor or character reveal. Accessibility tree exposes the same full
question as the button label and visible content. The card now reaches its final
height in one short entrance instead of growing line-by-line.

Tests: Dynamic suggestion tests passed (2); full `npm test` passed, including
all 10 real-browser tests. Ruff, design-token guard, architecture budget, and
`git diff --check` passed. Quota errors logged by storage-failure tests are
intentional fixtures.

Console: No new runtime error observed. Dynamic suggestion endpoint responded
successfully; no failed requests were observed in this interaction.

Responsive validation: Mobile 390px screen inspected; full title wraps to its
final 3-line layout without progressive vertical movement. Reduced motion is
covered by the global Figma-theme motion rule.

Visual score: Welcome suggestion clarity 8.5/10 mobile. The composer still
shows four separate dropdown/actions in a tall stack at 390px; this is usable
but remains a density/priority opportunity for a later assistant pass.

Regressions: None found in the complete JavaScript suite. Streaming typewriter
behavior for assistant answers was not changed; only home-page suggestion
animation was simplified.

Next action: Audit real assistant answer actions and keyboard reachability,
then review composer controls/overflow at tablet and desktop widths.

## Cycle 7 — 2026-09-29

Area: Active assistant composer, evidence access, and answer-copy feedback.

Goal: Exercise an end-to-end legal question on the running app and fix concrete
mobile interaction failures found after the first response.

Observed problems: At 390px, the active fixed composer retained the desktop
sidebar offset (`left: 240px`), leaving only a narrow vertical strip and
covering the source affordance beneath it. The 120px message bottom padding was
also insufficient for the mobile composer’s height. The answer-copy action
depended solely on the Clipboard API, gave no failure feedback when unavailable,
and did not consistently announce success across its duplicated handlers.

Changes made: On mobile, the active composer now spans the viewport, uses
box-sizing-safe gutters plus the device safe-area inset, and its form remains
full-width. Increased mobile conversation tail space so the sources pill stays
above the fixed composer when scrolled to the end. Centralized copy handling
through `JurixChatRenderer`; it now falls back to a temporary, offscreen
textarea and `execCommand('copy')`, preserves focus, swaps to a check icon,
updates the accessible label/title on success, and reports failure accessibly.
Added browser geometry assertions for composer and sources at 390px and a
renderer fallback test.

Browser validation: Submitted “O que prevê o art. 8º da Lei nº 8206/2026?” in
the actual local assistant. It returned the publication-date rule with two
sources. Before the CSS fix, the composer rendered vertically at the right and
obscured “Ver fontes”; after reload it spans the bottom of the viewport and the
source button is fully exposed above it. Opened the source drawer, confirmed
both Art. 8º and Art. 7º records and SAPL links, closed via Escape and verified
focus returned to “Ver fontes”. Clicked “Copiar resposta” and observed the
accessible label change to “Resposta copiada”.

Tests: Full `npm test` passed, including all 10 real-browser tests. The added
mobile browser assertions verify composer width, visible sources affordance,
sidebar geometry, and desktop viewport containment. The copy fallback unit
test passed (including focus retention). Ruff, design-token guard, architecture
budget, Django `manage.py check`, and `git diff --check` passed. Existing
storage-quota console output in one unit test is intentional.

Console: No browser warning/error entries after the real question, drawer open/
Escape cycle, reload, and copy interaction.

Responsive validation: The actual 390×844 conversation now has a full-width
composer and an independently clickable sources pill. The real-browser suite
also checks the desktop viewport does not overflow; its exact left edge adapts
to whether the sidebar is collapsed.

Visual score: Active chat composition 8/10 mobile after correction; evidence
access 8.5/10; copy affordance/feedback 8/10. More answer-side actions and
composer-state cases remain for the assistant audit.

Regressions: None in the completed full JavaScript suite or static/Django
checks. Only assistant presentation and clipboard interaction code changed;
no API or persistence contract changed.

Next action: Continue assistant interactions (new conversation, retry/error,
input limits, keyboard order), then test the same active chat at tablet and
desktop sizes.
