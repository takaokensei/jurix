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

## Cycle 8 — 2026-09-29

Area: Assistant interruption and retry behavior for anonymous conversations.

Observed problem: The interruption card's “Tentar novamente” action only copied
the failed question back into the composer. It did not launch a new request.
Retrying through the normal submit flow would also append a duplicate user
message and preserve the interrupted assistant fragment in local history.

Changes made: Retry now resubmits immediately, removes the interrupted bubble,
does not add a second user bubble/session card, and marks the callback so the
anonymous-history layer replaces the partial assistant record while preserving
the original question. Existing authenticated sessions continue through the
session regeneration endpoint. Added unit and real Chromium coverage asserting
that retry makes a second streaming request and leaves exactly one user message
and one completed assistant message both in the DOM and local history.

Tests: All 10 real-browser tests passed in a sequential full JavaScript run; the
retry browser test also passed in isolation. One earlier full JavaScript run
timed out waiting for the recovered answer while the 652-test Python suite was
running concurrently; a sequential rerun passed. Full Python suite: 652 passed,
6 skipped. Ruff, design-token guard, architecture budget, Django system check,
JavaScript syntax checks, and `git diff --check` passed.

Regressions: None observed. No API or backend changes; authenticated retry
continues to use its existing regeneration contract.

Next action: Continue auditing the assistant's error, retry and composer states
across authenticated/anonymous and narrow/wide layouts, then inspect another
high-impact interaction in the workspace.

## Cycle 9 — 2026-09-29

Area: Mobile evidence affordance in the assistant response.

Observed problem: At 390px, the source-count label, semantic correspondence
badge, and “Ver fontes” action competed on one compressed flex row; all three
labels wrapped, making the control visually noisy and harder to scan.

Changes made: On narrow screens, the source count and action now remain on the
first line while the full correspondence badge moves to a second line. The
source control uses the available message width and preserves the existing
button semantics and click target. The real Chromium streaming test now runs at
390px with a scored source and asserts that all three labels fit on one line.

Tests: Full `npm test` passed, including all 10 real-browser tests and the new
390px geometry assertions. Ruff, design-token guard, architecture budget,
Django system check, JavaScript syntax check, and `git diff --check` passed.

Regressions: None observed; the change is restricted to the source affordance
below 481px.

Next action: Continue the keyboard and narrow-screen audit of assistant
composer controls, then verify the same flow at tablet and desktop widths.

## Cycle 10 — 2026-09-29

Area: Welcome-search controls and keyboard interaction.

Observed problems: On a phone viewport the four search filters wrapped into an
unbalanced stack with inconsistent widths. In live interaction, opening the
scope menu and pressing Escape did not close it; clicking the active control
again also left the menu open. The menu exposed no expanded state or radio-item
semantics to assistive technology.

Changes made: The welcome filters now form a two-column grid below 641px with
bounded text and stable hit targets. Search menus now toggle on the active
control, close on Escape, return focus to their trigger, and publish
`aria-haspopup`, `aria-expanded`, `aria-controls`, and checked menu-item state.
Added unit coverage for keyboard open/Escape/focus/toggle and Chromium mobile
coverage for filter geometry plus the complete Escape-and-toggle flow.

Tests: Full `npm test` passed (including all 10 real-browser cases and the new
search-controls unit test). Ruff, design-token guard, architecture budget,
Django system check, JavaScript syntax checks, and `git diff --check` passed.

Regressions: None observed; filters keep the existing option values and event
contract, with no backend changes.

Next action: Exercise selecting each search option and check that focus,
announcements, persisted preferences, and composer-vs-home control state stay
consistent; then inspect file-attachment UX without uploading user documents.

## Cycle 11 — 2026-09-29

Area: Search-filter selection and state synchronization.

Observed problems: Selecting a menu option bubbled the click back to its trigger,
which immediately reopened the menu. The welcome controls also lacked the
`data-control-label` hooks used by the controller, so their visible captions
could not follow the persisted selection. Finally, changing the shared source
scope updated only the clicked control, leaving the composer caption stale.

Changes made: Menu option clicks now stop propagation and restore focus after
selection. Added label hooks to the four welcome controls, preserved the
descriptive default label, and made the controller update every matching
control instance. Unit and real-browser tests select “Todas as fontes” and
verify both home and composer labels, stored preference, collapsed menu, and
focus return.

Tests: Full `npm test` passed (all 10 browser tests, search control and streaming
unit coverage). The route suite passed (18 tests). Ruff, design-token guard,
architecture budget, Django system check, JavaScript syntax checks, and
`git diff --check` passed.

Regressions: None observed; option keys, payload shape, and backend remain
unchanged.

Next action: Audit attachment selection, removal, and conversation-reset states
using disposable test fixtures only, then test keyboard traversal at phone and
desktop widths.

## Cycle 12 — 2026-09-29

Area: Popover placement and attachment-control clarity.

Observed problems: The active composer sits at the viewport bottom, but its
search-mode menu opened downward and was clipped on phones. Right-side filters
could also open menus past the viewport edge. The composer labelled its
attachment control “Anexar PDF” even though the picker accepts PDF, TXT, MD,
CSV, JSON, and DOCX. The retry browser diagnostic additionally exposed a real
race: a just-rendered retry button could be clicked before chat state became
idle, causing the request to be ignored.

Changes made: Menus now measure available space, open upward when needed, align
to the trigger's right edge when needed, and constrain their dimensions to the
viewport. The selected radio item retains its visible highlight with the new
ARIA state. Attachment copy now says “Anexar documento” and the picker contract
is covered without selecting or uploading a file. Retry explicitly releases
the terminal busy state before invoking regeneration/resubmission.

Tests: Full `npm test` passed, including the browser retry race and mobile menu
geometry. Route tests: 18 passed. Ruff, design-token guard, architecture budget,
Django system check, JavaScript syntax checks, and `git diff --check` passed.

Regressions: None observed; attachment selection remains user-initiated and no
file was uploaded during validation. No API changes.

Next action: Continue end-to-end testing of attachment removal/reset with fake
in-memory records, then verify menu placement and keyboard order at tablet and
desktop widths.

## Cycle 13 — 2026-09-29

Area: Attachment limits, partial failure recovery, and conversation lifecycle.

Observed problems: The picker accepted multiple formats, but selecting more
than the five-file limit silently uploaded only the first five. A later upload
failure could leave earlier files on the server without a visible local
reference; if cleanup also failed, those files disappeared from the UI and
could not be removed by the user.

Changes made: The controller now rejects over-limit selections before issuing
any upload, cleans up successful earlier uploads when a subsequent upload
fails, and keeps any unremovable partial uploads visible with a recoverable
remove action and an explicit error. Added isolated API-mock tests for
over-limit rejection, successful rollback, failed rollback recovery, removal,
and new-conversation cleanup. No real file chooser was submitted and no user
document was uploaded.

Tests: Full `npm test` passed, including all 10 Chromium scenarios. Attachment
storage and workspace route tests: 21 passed. Ruff, design-token guard,
architecture budget, Django system check, JavaScript syntax, and `git diff
--check` passed.

Regressions: None observed; backend interfaces are unchanged.

Next action: Continue responsive and keyboard traversal through the command
palette, sidebar, active composer, and legal-search screens at phone, tablet,
and desktop widths; then investigate another high-impact usability issue.

## Cycle 14 — 2026-09-29

Area: Regression audit of the seven reported UI findings across assistant,
workspace routes, settings, collections, legal search, and norm catalog.

Observed: The current implementation already prevents SVG source from leaking
into the command palette and its browser test verifies rendered icon bounds and
absence of visible SVG markup. The norm catalog inherits the shared workspace
shell. The active assistant template retains both Settings and Quick Search in
its sidebar. Norm metadata is visually subordinate to titles; collections
separate the empty state, account limitation, and public catalog CTA; settings
show a visible blue select chevron; legal search has a compact empty state.
Manual mobile checks confirmed the palette opens/closes with Escape, the
settings chevron is visible, and `/normas/` uses the same sidebar/topbar shell.

Changes made: Added explicit regression assertions that the norm catalog must
inherit the workspace base and that the assistant sidebar retains its settings
route and shared navigation shell. No production UI code needed alteration for
these seven findings because they were already fixed in the current tree.

Tests: `node --test tests/js/norma_ui_v3.test.mjs` passed (12/12). Full
`npm test` passed from `tests/js`, including 10 real Chromium browser scenarios
and the command-palette check that visible SVG source markup is absent.

Regressions: None observed. No backend/API changes.

Next action: Continue end-to-end checks on actual conversation routes and
keyboard navigation across viewport sizes, then fix the next reproducible UI
or usability issue.

## Cycle 15 — 2026-09-29

Area: Source drawer information hierarchy, evidence grouping, relevance
indicator accuracy, and static asset freshness.

Goal: Make repeated evidence from one law easier to audit without collapsing
article-level citations or implying that retrieval similarity is legal
certainty.

Observed problems: The live persisted conversation rendered two cards with the
same law title, forcing users to rediscover the shared instrument. The drawer
subtitle described every source as a “dispositivo” and did not state the number
of represented norms. Its similarity meter rendered coarse fixed widths by
band instead of the actual score; the drawer showed relevance labels wrapped
onto two lines in the 480px panel. After the initial edit, the long-running
browser retained old static URLs and continued rendering the previous version.

Changes made: Group evidence by normalized norm title while preserving each
article card, rank, source link, and citation target. Unknown norm names remain
separate to avoid asserting a relationship without evidence. The drawer now
reports evidence and norm counts and renders a single norm heading per group.
Replaced the coarse CSS meter with a native progress element driven by the
actual bounded recovery score; the screen-reader description continues to
identify it as a technical retrieval score. Added cache-busting versions to
the shared visual CSS, RAG CSS, and RAG script URLs so open clients fetch the
updated components. No backend, API, or corpus changes.

Browser validation: On the real local assistant conversation, confirmed the
drawer displays one “Lei nº 8206/2026” group with two distinct article cards,
individual excerpts and SAPL links, plus “2 evidências em 1 norma”. The
relevance label is now a single line and its meter reflects the actual 98% and
97% values. At 390×844 and 1440×900, the real-Chromium test checks group bounds,
article ranks, score values, and focus return after close. The in-app browser
reloaded the versioned assets and visually confirmed the revised drawer.

Tests: Focused source drawer tests passed (14/14). New real-browser source
drawer test passed, with no page or console errors after stubbing the unrelated
fixture-only suggestions module. Full `npm test` passed, including all 11 real
Chromium scenarios. Ruff, Django system check, design token guard, architecture
budget, JavaScript syntax, and `git diff --check` passed.

Console: No page errors or console errors in the focused Chromium interaction.
The fixture emits an expected missing-suggestions error without the explicit
stub; the test isolates that unrelated fixture condition instead of hiding
application errors.

Responsive validation: Evidence groups remain fully inside the drawer at
390px and 1440px. Relevance labels remain single-line; article order and
citation ranks stay unchanged.

Visual score: Evidence drawer 8.8/10 after this cycle; remaining concerns are
the model-provided answer's redundant introduction/conclusion and the second
retrieved source (Art. 7º) appearing alongside a question specifically about
Art. 8º. The latter may be retrieval relevance rather than a UI defect and is
not changed because this frontend goal explicitly excludes backend/RAG edits.

Regressions: None observed; all evidence remains individually navigable and
the keyboard close/focus-return behavior is preserved.

Screenshots: The app was visually inspected in the in-app browser and captured
by the test runner's live DOM measurements. Persistent before/after screenshot
files are still absent; the current in-app screenshot API does not save to the
repository. Establish a reproducible capture path during the final audit.

Next action: Continue the full route and keyboard audit, focusing on the
assistant answer reading hierarchy and the active-conversation shell; then
establish saved screenshot evidence for the final route matrix.

## Cycle 16 — 2026-09-29

Area: Timestamp fidelity when restoring anonymous and authenticated chat history.

Goal: Keep message metadata stable across refresh, direct URL navigation, and
loading older pages; show the current time only for newly created messages.

Observed problems: Both the shared user-message renderer and the assistant
message restoration path generated `new Date()` during rendering, ignoring the
persisted `created_at`. A reload therefore made an old user/assistant exchange
appear to have happened at the current time. The issue reproduced on the local
conversation: before the fix, repeated reloads showed changing time; after it,
both messages remain at their stored time.

Changes made: The shared renderer now formats a validated stored timestamp and
falls back to current time only when it is missing/invalid. Session restoration
and history pagination pass `created_at` for user and assistant messages. Live
messages continue to use the current time. Updated cache-busting URLs for the
changed renderer and chat script. No API, model, or backend changes.

Browser validation: The real Chromium anonymous-history test now seeds a fixed
historical timestamp, performs F5, and opens the direct conversation URL in a
second tab; both user and assistant times remain unchanged. The authenticated
multi-page-history browser test verifies the first restored message uses its
API `created_at` after loading older pages. Repeated F5 in the actual local
conversation kept both timestamps at 13:39 while the previous implementation
changed them to the current time.

Tests: Full `npm test` passed (exit code 0), including all 11 real Chromium
scenarios, 15 streaming behavior tests, sanitization/CSP, command palette, and
responsive interaction coverage. Focused Python/system, lint and token gates
were green in Cycle 15; this cycle changes only frontend JS/templates/tests.
`node --check` and `git diff --check` passed.

Console: No new console errors; F5 and direct-route assertions completed.
Quota warnings in the unit suite remain intentional fault-injection output.

Responsive validation: No layout changes; message timestamp restoration was
tested on real Chromium. The route matrix already covers assistant and shell
interactions at 390px as well as wide desktop widths; the full evidence drawer
was also checked at 390px and 1440px in Cycle 15.

Visual score: History/message metadata 9/10 after this cycle; old timestamps
are stable and intentionally retain the existing compact time-only treatment.
The conversation's substantive answer hierarchy remains a separate open
presentation concern because changing or suppressing model text at the frontend
could misrepresent the original answer.

Regressions: None found in the complete JS suite or real reload/navigation
flows.

Screenshots: Verified in the live in-app browser; persistent before/after
screenshots for the required full route matrix remain outstanding.

Next action: Continue with the answer reading hierarchy and the complete
desktop/mobile route audit, then close the screenshot artifact gap during the
final pass.

## Cycle 17 — 2026-09-29

Area: Mobile legal-version comparison and repeatable visual evidence.

Goal: Make each side of the mobile line-by-line comparison auditable without
repeating a long placeholder in every unmatched row, and establish persistent
before/after evidence for the actual Django routes.

Observed problems: At 390px, the comparison stacked each source line into two
cards but hid the line numbers. This removed a key citation aid on the smallest
viewport. Unmatched sides repeated “Sem linha correspondente” in every row,
visually competing with the legal text. The audit also had no saved screenshot
files, despite previous visual inspections.

Changes made: Mobile comparison labels now show the source and its original or
consolidated line number. Unmatched sides display the shorter “Sem
correspondente” while retaining the complete accessible name and tooltip. The
empty-side treatment uses a compact token-based visual style. Added an
executable route/viewport screenshot capturer that also reports HTTP failures,
console errors, failed requests, main-content visibility, and horizontal
overflow. No backend, API, model, or diff-generation changes.

Browser validation: On the live Django app, manually executed a legal search
for “servidor educação”; it returned three result cards, highlighted both
terms, and preserved the query and filters in the URL. Inspected the live
comparison accessibility tree and verified the full missing-side name remains
available. Before and after captures cover the same ten views—assistant,
empty/results search, norms, norm detail, comparison, device tree, collections,
history, and settings—at 1440×900, 1280×800, and 390×844. Both manifests report
30/30 HTTP 200, main content visible, zero horizontal overflow, zero console
errors, zero failed requests, and identical screenshot filenames. The
before/after comparison screenshot visibly confirms mobile line references.

Tests: The focused structural and Chromium browser tests passed (24/24); the
full `npm test` suite passed. `manage.py check`, the design-token gate,
JavaScript syntax checks, both screenshot-manifest audits, and `git diff
--check` passed. The screenshot evidence totals about 8.0 MB.

Console: No console errors or failed requests in the 60 captured real-route
views. The full JavaScript suite emitted only its existing intentional storage
quota fault-injection logs.

Responsive validation: All ten route/query variants fit the exact 390px
document width; comparison at 390px now identifies the source line in each
card label. The same route set remains overflow-free at both desktop sizes.

Visual score: Mobile version comparison 8.2/10 after this cycle (estimated
7.6/10 before). The line-reference hierarchy is clearer, but OCR formatting
and alignment remain visible content-quality limitations; they are not
modified because diff generation is outside this frontend-only goal.

Regressions: None in the 24 focused tests or full JavaScript suite. Desktop
five-column comparison and mobile single-column layout are both retained.

Screenshots: `docs/ui-audit/before/` and `docs/ui-audit/after/` now contain
matching 30-image route/viewport sets and manifests. Reproduce with
`node tests/js/capture-ui-audit.mjs before` and `node
tests/js/capture-ui-audit.mjs after` while the local app is running at
`127.0.0.1:8004` (or set `JURIX_UI_AUDIT_URL`).

Next action: Continue the full route interaction audit, prioritizing the norm
detail/timeline and device-tree reading experience; then verify keyboard and
reduced-motion behavior across the shared shell.

## Cycle 18 — 2026-09-29

Area: Accessible device-tree interaction and responsive affordance.

Goal: Make the normative device tree behave like the ARIA tree widget it
advertises, including keyboard operation, visible disclosure state, and
mobile-sized pointer targets.

Observed problems: The real `/normas/3/tree/` accessibility tree exposed
`role=tree` and `role=treeitem`, but all items were `tabindex=-1`; no script
handled arrow keys, expansion, or collapse. This left the main legal
hierarchy unusable from the keyboard and misleading to assistive technology.

Changes made: Added roving focus and Arrow Up/Down/Left/Right plus Home/End
navigation, Enter/Space expansion, and a visible disclosure control for nodes
with children. Parent and control `aria-expanded`/labels remain synchronized;
child groups are hidden when collapsed. Disclosure targets are 44×44px on
mobile, use existing design tokens and global reduced-motion rules, and do
not remove device IDs or deep-link targets. No backend or API changes.

Browser validation: Opened the actual Django tree in Chromium; the AX tree now
reports expandable rows and controls such as “Recolher Art. 2º”. Used Arrow
Down to focus Art. 2º, Enter to collapse it (its child rows disappear from the
AX tree and the control changes to “Expandir”), and Arrow Right to restore its
children. The selected article retains a visible focus ring. The mobile
before/after capture shows the 44px chevron aligned with the article heading.
All 30 after-capture views across ten routes at 1440×900, 1280×800, and
390×844 returned HTTP 200 with visible main content, no horizontal overflow,
no console errors, no failed requests, and matching filenames to `before/`.

Tests: Full JavaScript suite passed, including 12 real Chromium cases. The new
tree interaction test covers keyboard navigation, disclosure state, pointer
activation, mobile target dimensions, reduced-motion duration, and browser
errors. Full Python suite: 652 passed, 6 skipped, 7 existing Django setting
override warnings. `manage.py check`, design-token gate, JavaScript syntax,
route-manifest audit, and `git diff --check` passed.

Console: No application errors on the live route or in the tree interaction
test. Expected quota-failure logging remains in its dedicated fault-injection
JavaScript test.

Responsive validation: Tree route remains within 390px document width; the
disclosure button is 44×44px at 390px and 36×36px on desktop. Nested content
retains indentation and can be progressively hidden to shorten long statutes.

Visual score: Device tree 8.8/10 after this cycle (estimated 7.7/10 before).
The hierarchy now communicates depth, focus and expanded/collapsed state;
copy quality in OCR-derived text remains a corpus limitation rather than a UI
change.

Regressions: None in the full 652-test Python suite, full JavaScript suite, or
the 18 Django workspace-route tests. Existing deep-link IDs and the visual
tree remain intact.

Screenshots: Replaced only the `after/` route images and manifest for this
cycle; `before/` remains the fixed baseline from before the comparison/tree
improvements. The two directories still have matching 30-image sets.

Next action: Audit keyboard traversal, visible focus, Escape behavior and
reduced-motion on the remaining shell controls, then exercise real assistant,
history, collections and settings interactions before the final audit.

## Cycle 19 — 2026-09-29

Area: Revalidation of reported UI regressions U1–U7 against the current checkout.

Result: The supplied screenshots/issues describe an earlier UI state. No new
reproducible defect from U1–U7 remains in the current working tree, so this
verification cycle intentionally makes no application-code changes.

Checks performed: Opened `/assistente/`, `/normas/`, `/colecoes/`,
`/pesquisa/`, and `/configuracoes/` in the local app. Ctrl+K opened the palette;
its navigation icons rendered as SVGs rather than text. `/normas/` and the
workspace routes exposed the same sidebar/topbar structure. The active chat
also exposed Configurações and Busca rápida. Norm cards showed the law title
above secondary 9px labels/12px values. Collections separated the empty state,
account limitation, public exploration CTA, and resource indicators. The
settings model select displayed a visible blue chevron. Legal-search empty
state used the compact 28px/20px padding rule.

Automated validation: `node --test tests/js/norma_ui_v3.test.mjs
tests/js/real.browser.test.mjs` passed all 25 tests, including a real-Chromium
assertion that SVG markup is not visible text and structural checks for U2–U7.

Architecture note: The assistant template retains its chat-specific session
list and CSS shell rather than extending `workspace/base.html`; its sidebar
still includes the shared navigation destinations, settings, quick search,
and the shared topbar partial. This is an implementation difference, but the
reported missing controls and visual split are not present in the live UI.
Replacing the chat shell solely to erase that implementation difference would
risk its session-specific behavior without fixing a reproduced user-facing
failure.

Next action: Continue the full application interaction audit across assistant,
history, collections, search, settings, norms, detail, comparison, and tree;
prioritize reproducible keyboard, responsive, and cross-route state bugs.

## Cycle 20 — 2026-09-29

Area: Norm detail action hierarchy and responsive layout.

Goal: Remove the visually stranded official-source action on `/normas/<id>/`
without changing legal content or application behavior.

Observed problems: At the 1280px browser viewport, the detail header actions
used wrapping flex layout. Five actions occupied the first row while “Abrir
fonte oficial no SAPL” appeared alone in the second row. The CSS file was not
versioned in the template, so browser cache could also retain the previous
layout after deploy.

Changes made: Replaced the wrapping action row with a responsive CSS grid
using existing button colors and surfaces; actions align consistently and
retain centered labels and 44px minimum target height. Added a cache-busting
version to `jurix-legal-detail.css`. Added a structural regression assertion.
No backend, model, API, or legal text changed.

Browser validation: Inspected the real `/normas/3/` route in Chromium and
iterated from an initial 4+2 layout with wrapped primary labels to a balanced
3×2 grid at 1280px. At 1440px it displays as 4+2; at 390px as one column.
Measured six controls at 44px or larger, zero document horizontal overflow,
and no console errors or failed requests at all three widths.

Tests: `npm test` passed, including 12 real Chromium tests and the new
norm-detail action-grid regression test (14 focused UI tests passed).
Updated `docs/ui-audit/after/` captures: 30 views across ten routes and three
viewports, zero views flagged. The before/after manifests still contain
matching route/view filenames; all 60 views report HTTP 200, visible main
content, no horizontal overflow, no console errors, failed requests, or bad
responses. `git diff --check` passed.

Console: No browser console errors on the live norm-detail route at desktop or
mobile widths.

Responsive validation: The grid resolves to four columns at 1440px, three at
1280px, and one at 390px. The page document remains within viewport width at
each size; every action remains reachable and has an adequate hit area.

Visual score: Norm detail action group 8.9/10 after this cycle (estimated
7.8/10 before); standalone wrapping and variable action placement are gone.
This score applies only to the action group, not the entire application.

Regressions: None observed in the full JavaScript suite or the live route.

Screenshots: Refreshed all 30 files in `docs/ui-audit/after/`; the norm detail
captures show balanced actions at desktop widths and stacked actions on mobile.

Next action: Continue remaining UI/UX audit across the norm reading content,
comparison, search filters/results, history and collection interactions; use
new-cycle evidence rather than treating the passing route screenshot gate as
proof that the full product is complete.

## Cycle 21 — 2026-09-29

Area: Command-palette keyboard accessibility across assistant and workspace.

Goal: Make the visually selected command discoverable to assistive technology
while retaining the existing arrow-key, Enter, Escape, and focus behavior.

Observed problems: The palette already handled ArrowUp/ArrowDown and visually
marked the active option, but exposed neither the combobox/listbox relationship
nor the active option to screen readers. The chat template also omitted the
listbox role that the workspace template already had.

Changes made: The shared controller now exposes the input as a combobox,
sets controls/expanded/autocomplete semantics, assigns listbox role, gives each
option a stable in-render ID and synchronized `aria-selected`, and points
`aria-activedescendant` at the active choice. Empty results and closing clear
the active descendant; close collapses the combobox. Added listbox semantics
to the assistant template and cache-busted the shared controller on both
shells. No security policy or navigation behavior changed.

Browser validation: Ran keyboard and pointer interactions against the live
Django `/configuracoes/` and `/assistente/` routes in Chromium. In both,
opening placed focus in the combobox, the first option was announced as
selected, ArrowDown moved both the visual and ARIA selection to option 2,
filtering to no results removed the active descendant, Escape closed the
palette and restored focus to the opening trigger. No page/console errors.

Tests: Full `npm test` passed, including 12 real-Chromium cases. The focused
palette Chromium test now asserts combobox/listbox semantics, active-descendant
movement, empty results and focus restoration; `norma_ui_v3.test.mjs` passed
15/15. JavaScript syntax and `git diff --check` passed.

Console: No palette errors on either live route; no unexpected failed requests
observed during direct Chromium interaction.

Responsive validation: Existing real-Chromium palette test still verifies
390px dialog fit, compact icon bounds, option height and focus. The new ARIA
semantics do not alter the visual layout.

Visual score: Command palette interaction/accessibility 9.0/10 after this
cycle (estimated 8.0/10 before); keyboard users and screen readers now receive
the same active-option state as sighted pointer users.

Regressions: None in the full JavaScript test suite or live assistant and
workspace routes.

Screenshots: Refreshed the 30-view `docs/ui-audit/after/` set after updating
the shared script URLs; all ten routes at 1440×900, 1280×800, and 390×844
captured without issues. Both before/after manifests still contain 30 views,
zero overflow, errors, failed requests, or bad responses.

Next action: Audit the mobile workspace header/composer and norm reading flow
for clipping and awkward density; then continue remaining interaction paths
in history, collections, settings and document comparison.

## Cycle 22 — 2026-09-29

Area: Compact mobile global-search control in shared topbars.

Goal: Preserve clear search affordance on narrow screens without allowing a
label-hidden control to consume the remaining header width.

Observed problems: At widths up to 640px, the shared component hid the search
label and shortcut, but the workspace's `flex: 1` rule still stretched the
header button. It looked like a wide, empty input in the assistant and the
workspace despite retaining an accessible name.

Changes made: Constrained `.workspace-top-search` to a 44×44px icon button at
the compact breakpoint, centered its icon, and preserved the existing
`aria-label`. Versioned `workspace.css` in both shared-workspace and assistant
templates so browsers receive the updated responsive rule. Added a structural
regression test. No interaction or route contract changed.

Browser validation: Tested the real `/assistente/` and `/configuracoes/`
pages in Chromium at 390px, 640px and 641px. At 390/640, the control measured
44×44px and its accessible name remained “Abrir busca rápida (Ctrl K)”; at
641px the visible search label returned and the control expanded to fill the
available header space. All six route/viewport checks had zero overflow and
zero page/console errors. Refreshed captures visibly confirm the compact icon
button in all mobile routes and readable page headings.

Tests: `norma_ui_v3.test.mjs` passed 16/16; `git diff --check` passed. Both
before and after manifests contain 30 screenshots with zero HTTP, visibility,
overflow, console, failed-request, or bad-response issues.

Console: No browser errors on either live route at any of the tested widths.

Responsive validation: Breakpoint edge explicitly tested at 640px and 641px;
390px mobile document width remains exact. Search control stays above the
44px touch-target minimum.

Visual score: Mobile shared header 8.9/10 after this cycle (estimated 7.3/10
before); the icon affordance is compact rather than resembling an empty text
field, and the route label retains its own space.

Regressions: None observed in route tests or capture manifests.

Screenshots: Refreshed `docs/ui-audit/after/` (30 route/viewport images); all
mobile topbars show the same compact control while desktop captures remain
unchanged apart from dynamic chat content.

Next action: Review the assistant composer and long legal-text reading on
mobile for clipping, overly tall controls, and keyboard/focus inconsistencies;
then move on to document comparison, history and collection action flows.

## Cycle 23 — 2026-09-29

Area: Mobile norm-detail information density.

Goal: Reduce scroll consumed by secondary count cards before the legal device
hierarchy, without making metric labels too narrow to read.

Observed problems: At 390px, all three detail metrics were stacked at full
width even though their labels and values were short; this added roughly one
card row of unnecessary scrolling before the article tree.

Changes made: At widths up to 640px, the metric grid now uses two columns and
the final metric spans the full row. Desktop remains three columns. Bumped the
detail stylesheet cache key and added a regression test. No legal content or
backend logic changed.

Browser validation: Measured the actual `/normas/3/` page in Chromium at
320px, 390px, 640px, and 641px. It resolves to two columns through 640px and
three columns above the breakpoint; at 390px the third card spans the row.
At 320px, the longer “Eventos de Alteração” label wraps but remains readable.
All widths had zero horizontal overflow, page errors, or console errors. The
390px after-capture shows the three metrics using two rows rather than three.

Tests: Focused `norma_ui_v3.test.mjs` passed 17/17; `git diff --check` passed.
Both screenshot manifests still have 30 views and zero issues.

Console: No errors on the real route at all four widths.

Responsive validation: Explicitly checked 320, 390, 640, and 641px, including
the breakpoint transition and label wrapping at the narrowest width.

Visual score: Mobile metric block 8.8/10 after this cycle (estimated 7.4/10
before); secondary information takes less vertical space and retains readable
labels.

Regressions: A structural assertion still expected the prior stylesheet
cache-key string; it failed during validation, was updated to the new key, and
the complete focused suite then passed.

Screenshots: Refreshed all 30 `after/` images. The mobile norm-detail image
confirms the compact 2+1 layout; baseline and after manifests retain identical
route/viewport coverage.

Next action: Continue testing the assistant's mobile composer and keyboard
submission, then inspect reading density and focus behavior in comparison,
history, and collection flows.

## Cycle 24 — 2026-09-29

Area: Assistant welcome-composer prompt clarity on narrow screens.

Goal: Prevent the hero-search placeholder from ending abruptly behind the
send control on phones while preserving a fuller accessible description.

Observed problems: The mobile hero input had 185px of width at 320px, while
the placeholder “Pergunte sobre normas, artigos ou jurisprudência...” measured
364px at its rendered font. The visible hint stopped at “ou” on 390px, hiding
the rest of its instruction.

Changes made: Shortened the visible placeholder to “Pergunte sobre leis…” in
the assistant template and both browser fixtures. Retained the full
`aria-label` (“Pergunte sobre normas, artigos ou jurisprudência”) so the
shorter visual hint does not reduce the accessible name. Added a Chromium
measurement asserting the placeholder fits the available input width.

Browser validation: At 320px on the real local assistant, the new hint
measures 150px against 181px of available text width; `aria-label` remains
complete and there is no horizontal overflow. The 390px after screenshot
shows the complete placeholder and send button with clear separation. Existing
mobile test also verifies composer controls and 44px target dimensions.

Tests: The focused real-Chromium assistant test and all 17 structural UI tests
passed. `git diff --check` passed. Refreshed the 30-view after set; manifests
report zero issues.

Console: No browser errors on the real mobile assistant route or focused test.

Responsive validation: Measured the real route at 320px and visually reviewed
the 390px capture; placeholder fits at the minimum supported mobile viewport.

Visual score: Mobile welcome composer 8.9/10 after this cycle (estimated
7.8/10 before); the input prompt is now fully visible rather than clipped.

Regressions: None in the focused browser test or UI structural suite.

Screenshots: Updated all `after/` route captures; the 390px assistant image
shows the full “Pergunte sobre leis…” hint.

Next action: Continue the remaining mobile assistant composer interaction
states, then exercise comparison, history, collections, settings, and reading
flow focus/keyboard behavior.

## Cycle 25 — 2026-09-29

Area: Active assistant composer controls and mobile menu positioning.

Goal: Keep the composer filters readable and their menus usable on narrow
screens, especially when the composer is fixed to the bottom of the viewport.

Observed problems: At 320–390px, three composer controls shared one row and
their labels were clipped. Opening the mode menu at 390px then showed a second
issue: the menu opened below the fixed composer and extended outside the left
viewport edge.

Changes made: Mobile composer filters now use a two-column grid, with the
attachment action on a full-width second row; controls retain 44px targets and
labels truncate explicitly. Menus belonging to the fixed composer open above
it and calculate a viewport-safe horizontal offset. Updated cache keys for
both changed assets. No backend behavior changed.

Browser validation: Tested the real Django `/assistente/` page at 320, 390,
640, and 641px. At <=640px, controls form a 2+1 layout, all hit areas are at
least 44px, document width equals viewport, and the menu at 390px stays within
the viewport and above its trigger. At 641px, the desktop layout is preserved.
No console or page errors occurred.

Tests: Full `npm test` passed, including all 12 real-Chromium browser tests;
the search-control unit test passed. `git diff --check` passed. The first full
run surfaced the menu-placement bug, which was fixed and then revalidated by
the focused browser test and second complete run.

Screenshots: Refreshed the 30-view `after/` set. Before and after manifests
both have 30 views and zero flagged route, overflow, console, request, or
visibility issues.

Next action: Continue the outstanding keyboard/focus and mobile reading-flow
checks across comparison, history, collections, and settings; fix the next
demonstrable issue rather than assuming these routes are complete.

## Cycle 26 — 2026-09-29

Area: Shared workspace mobile navigation accessibility.

Goal: Ensure the off-canvas sidebar does not expose invisible links to keyboard
users and that opening/closing it gives predictable focus feedback.

Observed problems: On the actual `/historico/` and `/colecoes/` pages at 390px,
Tab moved focus through sidebar links whose right edge was at -15px. They were
outside the viewport but remained in the keyboard order.

Changes made: `workspace.js` now marks a closed mobile sidebar `inert` and
`aria-hidden`, clears those states while open, moves focus to its first link
when opened, returns focus to the menu toggle on Escape, and restores normal
desktop navigation after resizing above 900px. Added a cache key for the
shared script and a real-Chromium regression test for mobile closed/open,
Escape, and desktop resize states. No backend changes.

Browser validation: Reproduced on both real workspace routes. Added isolated
Chromium coverage proving Tab skips the offscreen links, opening enters the
menu, subsequent Tab reaches the next item, Escape restores the trigger, and
desktop resize removes inert/hidden state. Full frontend suite passed: 13/13
real-Chromium browser tests plus all structural, security, persistence, and
streaming test groups. `git diff --check` passed.

Screenshots: This is an accessibility-state-only change with no intended
visual delta; the verified 30-view before/after set from Cycle 25 remains the
current visual baseline.

Next action: Audit the comparison and norm-reading routes for keyboard access
to dense legal text, then exercise the history and collection controls at
mobile widths and in reduced-motion mode.

## Cycle 27 — 2026-09-29

Area: Assistant conversation sidebar keyboard access.

Goal: Apply the same mobile focus contract to the assistant shell, which is a
separate template and JavaScript path from the workspace shell.

Observed problems: The workspace fix did not cover `/assistente/`. At 390px,
the chatbot sidebar links, settings action, and quick-search action were still
reachable by Tab while translated to x=-224..-17px.

Changes made: The chat sidebar now toggles `inert` and `aria-hidden` with its
mobile open state, moves focus into the visible sidebar on open, and restores
the normal focusable state when crossing the 768px breakpoint. Escape already
returned focus to the trigger and continues to do so. Updated the chat script
cache key and strengthened the real-Chromium test to assert focus exclusion,
open focus visibility, Escape restoration, and desktop reactivation.

Browser validation: Reproduced the invisible Tab stops on the actual Django
assistant page. After the change, Tab skips the closed sidebar; opening moves
focus to the visible brand link, Escape returns focus to the menu toggle, and
the sidebar is no longer inert on desktop. Focused Chromium test passed.

Tests: One full-suite run had a transient failure in the pre-existing stream
interruption/retry browser scenario (first attempt was preserved, but retry
did not dispatch in that run); the isolated scenario passed on retry, and a
second complete `npm test` passed, including 13/13 browser tests. No failure
was observed in the navigation test. `git diff --check` passed.

Screenshots: No intended visual change; Cycle 25's 30-route visual captures
remain applicable.

Next action: Keep auditing actual routes for keyboard/reduced-motion issues,
then add accessibility checks for collection dialogs and comparison reading.

## Cycle 28 — 2026-09-29

Area: Assistant navigation focus parity and production dark-text contrast.

Goal: Check the assistant's separate sidebar implementation and verify the
small, secondary text used on legal evidence surfaces against measurable
contrast requirements.

Observed problems: The assistant shell had the same hidden-tab-stop issue as
the workspace shell: its collapsed sidebar items were at x=-224..-17px but
still keyboard reachable. Separately, `--figma-text-dim` measured 3.73:1 on
the main graphite surface, below WCAG AA for normal-sized text; the token is
used by the source-drawer subtitle and legal comparison metadata.

Changes made: Applied inert/aria-hidden and focus-entry behavior to the
assistant sidebar, with breakpoint restoration and real-browser assertions.
Raised the dim-text token to `#7788A0`, which preserves its secondary role
while exceeding 4.5:1 on the root, card, and control surfaces. Added a
contrast-contract test and bumped the shared stylesheet cache key.

Browser validation: Reproduced invisible focus stops on the real Django
assistant route. The strengthened Chromium scenario passes. Updated the 30
`after/` screenshots and confirmed both before/after manifests have zero
flagged routes, errors, failed requests, or overflows.

Tests: Contrast contract passed; full frontend suite passed once after the
assistant-sidebar changes, including 13/13 browser tests. One unrelated
stream-interruption/retry browser case intermittently times out while its
submit event is being processed; it passes on isolated reruns, so it remains
on the investigation list rather than being hidden by a larger timeout.
`git diff --check` passed.

Next action: Audit the retry race with deterministic instrumentation, then
continue mobile dialog and comparison-reading accessibility checks.

## Cycle 29 — 2026-09-29

Area: Primary-action contrast on dark surfaces.

Goal: Extend the measurable contrast audit beyond muted metadata to the main
actions that carry the core legal research workflows.

Observed problems: The white text on the existing primary blue (`#3B82F6`)
measured only 3.52:1 with the interface's actual near-white text, below the
4.5:1 AA requirement for normal button labels. This affected prominent actions
such as “Perguntar sobre esta norma” and the workspace primary CTAs.

Changes made: Darkened the shared primary action color to `#2563EB`, preserving
the blue visual identity while measuring 4.94:1 against `#F8FAFC`. Added a
regression check for both the numeric ratio and the workspace button token
mapping. Cache-busted the common stylesheet for assistant and workspace pages.

Browser validation: Refreshed all 30 after captures and visually compared the
mobile norm detail: the primary action remains clear, still visually primary,
and has stronger label contrast. Both before/after manifests remain at 30
views with zero flagged issues.

Tests: Both automated contrast contracts pass; `git diff --check` passes. The
broader browser suite still has an intermittent pre-existing retry-stream
failure under investigation; no test was skipped or weakened.

Next action: Continue the independent retry investigation and the planned
dialog/comparison keyboard flow checks; keep the full suite green as a release
gate rather than treating capture success as completion.

## Cycle 30 — 2026-09-29

Area: Streaming error recovery and retry action reachability.

Goal: Resolve the intermittent browser retry failure without widening timeouts
or weakening the expected recovery behavior.

Observed problems: On intermittent runs, the first partial answer remained
intact but the retry did not produce a second stream request (`streamAttempts`
stayed at 1). The retry control is appended after the streaming answer while a
fixed composer occupies the viewport bottom, so the UI did not guarantee the
recovery action was brought into the visible interaction area.

Changes made: After rendering the retryable error state, the assistant now
scrolls its message viewport to the newest content on the next animation
frame. The real-browser test checks that the retry button is fully inside the
viewport and receives the pointer at its center before clicking; it still
asserts successful retry and no duplicate user message.

Browser validation: The strengthened streaming-interruption test passed
three consecutive isolated Chromium runs. Each verified the visible/uncovered
retry hit target, second stream response, preserved question, and no duplicate
messages. This replaces the earlier intermittent retry failure with an
explicitly tested visibility contract.

Tests: Focused retry scenario passed 3/3. The complete frontend suite then
passed, including all 13 real-Chromium browser scenarios and both contrast
contracts. No timeout increase, skip, or weakened assertion was used.

Next action: Run the full suite, then finish the collection-dialog and legal
comparison keyboard/reduced-motion checks before selecting the next remaining
product issue.

## Cycle 31 — 2026-09-29

Area: Authenticated collection creation dialog accessibility.

Goal: Exercise the modal workflow that anonymous navigation cannot reach,
without changing account flows or server behavior.

Observed problems: The existing collection dialog used native `<dialog>` and
had close/focus-return code, but no browser regression covered keyboard
opening, Escape, Cancelar, or phone-sized bounds.

Changes made: Added a real-Chromium test page that loads the project's actual
`workspace.css` and `jurix-collections.js`, then exercises the production
dialog structure. No production change was needed.

Browser validation: At 390×844, opening focuses the name field, the dialog
stays within the viewport with no document overflow, Escape closes it and
returns focus to the opener, and Cancelar closes it with the same focus return.

Tests: Focused dialog test passed. Full `npm test` passed, including all 14
real-Chromium scenarios and both contrast contracts. `git diff --check`
passed.

Screenshots: No visual delta; Cycle 29's 30-route before/after capture set
remains current.

Next action: Continue verifying legal comparison keyboard reading and reduced
motion, then re-audit settings and history interaction states.

## Cycle 32 — 2026-09-29

Area: Mobile readability in the normative version comparison.

Observed problem: The stacked mobile comparison reduced legal body text to
12px and the generated version/line labels to 9px. That made side-by-side
reading technically fit the viewport but unnecessarily difficult for long
legal excerpts.

Changes made: Raised mobile comparison text to 14px with 1.65 line-height and
labels to 10px/1.4, keeping the existing 12px desktop density. Updated the
stylesheet cache key and extended the real-browser test to assert both mobile
and desktop typography contracts.

Browser validation: The focused Chromium comparison test passed at 390px and
1280px. It continues to verify stacked labelled versions and no horizontal
overflow. The refreshed route capture contains 30/30 successful views; both
before/after manifests report zero flagged issues.

Tests: Focused comparison test passed. Complete `npm test` passed with all 14
real-Chromium scenarios, 17 structural tests, 15 streaming/persistence tests,
and contrast contracts green. `git diff --check` passed.

Next action: Continue with settings and history interaction states, then
revisit remaining route-level usability gaps.

## Cycle 33 — 2026-09-29

Area: Honest feedback when saving workspace preferences fails.

Observed problem: If browser storage rejects `localStorage.setItem` (privacy
settings, disabled storage, or quota), the chosen appearance is applied in the
current document but the UI still claimed it had been saved. A reload then
discarded the change without warning.

Changes made: Settings now distinguish durable save success from a current-page
appearance change that could not be persisted. The latter receives an explicit
warning style and accurate live-region message. Updated JS/CSS cache keys and
added a real-Chromium test that forces `QuotaExceededError` at 390px.

Browser validation: On the actual local Django app, `/configuracoes/` loaded
successfully at 390px and 1280px without horizontal overflow. Changing theme
and density applied immediately and survived reload. The new failure-path
browser test confirms the theme still applies but reports the inability to
save instead of claiming persistence. `/historico/` also loaded successfully.

Tests: Focused storage-failure Chromium test passed. The full frontend suite
passed with 15 real-Chromium scenarios, 17 structural tests, 15
streaming/persistence tests, and contrast contracts. The cache-key contract was
updated to follow the intentional stylesheet version bump; `git diff --check`
passed.

Next action: Continue testing settings reset and history interactions, then
inspect the remaining primary routes for concrete usability regressions.

## Cycle 34 — 2026-09-29

Area: Applying assistant preferences to the actual streaming request.

Observed problem: Browser inspection of the live SSE request showed that the
saved model and source count never reached the API, and temperature was also
absent. The settings UI persisted these values, but chat requests silently
used retrieval/generation defaults. The API already accepts these fields, so
this was a client integration gap rather than a backend contract change.

Changes made: The shared chat API now reads and validates the browser preference
object at request time, maps `sources` to `max_sources`, and sends model and
temperature with bounded numeric fallbacks. The chat page no longer duplicates
preference mapping. Malformed or non-object stored JSON safely falls back.

Browser validation: Extended the real-Chromium streaming scenario to set model,
3 sources, and temperature 0.7 in local storage, then inspect the request body
received by the mock SSE endpoint. All three values arrive as expected while
existing stream/source timing checks remain active.

Tests: Focused request-payload Chromium test passed. The complete frontend
suite passed, including 15 real-Chromium scenarios, 17 structural tests, 15
streaming/persistence tests, and contrast checks. `git diff --check` passed.

Next action: Continue examining history/session state and settings reset for
additional behavior that diverges from what the interface promises.

## Cycle 35 — 2026-09-29

Area: Settings reset behavior when local storage is unavailable.

Observed problem: “Restaurar padrão” ignored `removeItem` failures and reloaded
the page. When storage was blocked, the original preferences remained saved and
were reapplied, with no feedback to explain why reset did not stick.

Changes made: Reset now updates all controls and appearance to defaults in the
current document. It reloads only after successful removal; on failure it
preserves the page and announces that stored preferences may return after a
reload. Added a real-browser failure-path assertion, including proof that the
old stored value was not falsely reported as cleared.

Browser validation: Exercised the actual `/configuracoes/` route at 390px.
Normal save/reload persisted the selected theme/density; normal reset removed
the key and restored dark/comfortable defaults. Chromium also verified blocked
removal keeps the user on the page and announces the limitation.

Tests: Focused storage-failure/reset test passed. The complete frontend suite
passed with 15 real-Chromium scenarios, 17 structural tests, 15
streaming/persistence tests, and contrast checks. `git diff --check` passed.

Next action: Continue auditing authenticated and anonymous history transitions
and the remaining settings controls for mismatches between UI and behavior.

## Cycle 36 — 2026-09-29

Area: Respecting the backend-configured default LLM model.

Observed problem: The view passed `default_model` to the settings template, but
the model `<select>` never used it. Since allowed models are sorted, an
untouched form could save a different model than the server default. Reset
also chose the first option rather than the configured default.

Changes made: The template now marks the configured model as selected, and the
reset path resolves that exact selected option. Added a structural contract
plus a Chromium regression fixture where the default (`llama3`) is deliberately
the second option and a different model was previously saved.

Browser validation: Focused settings browser flow passed, including failure to
clear browser storage while restoring the server default in the visible form.
The production Django route continues to exercise normally after the reset
changes.

Tests: Focused structural and browser settings tests passed. The full frontend
suite passed with 15 real-Chromium scenarios, 18 structural tests, 15
streaming/persistence tests, and contrast checks. `git diff --check` passed.

Next action: Re-audit route navigation and history-to-assistant transitions,
including viewport and focus behavior on mobile.

## Cycle 37 — 2026-09-29

Area: Theme consistency between workspace and assistant/public shells.

Observed problem: `/configuracoes/` stores theme in `jurix-preferences`, while
the assistant's legacy `theme.js` read only `jurix-theme`. A live-browser route
walk reproduced the mismatch: saving Light left `/assistente/` Dark. The legacy
toggle also changed only its old key, so workspace pages could revert it.

Changes made: Theme resolution now prioritizes the shared workspace preference,
supports the `system` mode without converting it into a fixed color, and keeps
the legacy key synchronized for older routes. Workspace appearance application
also updates that compatibility key. Cache keys were bumped on both templates
that load the shared theme controller.

Browser validation: Reproduced the old cross-route mismatch on the local Django
app. Added Chromium coverage for conflicting old/new keys, toggle synchronization,
and system-dark behavior with the system preference preserved. Focused test
passed.

Tests: Focused theme integration Chromium test passed. The full frontend suite
passed with 16 real-Chromium scenarios, 18 structural tests, 15
streaming/persistence tests, and contrast checks. `git diff --check` passed.

Next action: Continue with keyboard and route transitions from History into
conversation pages, including browser back/forward and mobile navigation.

## Cycle 38 — 2026-09-29

Area: Applying density preferences to assistant conversations.

Observed problem: The Compacta preference only had CSS consumers in workspace
cards. The assistant's separate chat shell neither loaded `data-density` from
the shared preference nor changed message spacing, so the setting had no
visible effect where users spend most of their time.

Changes made: The shared theme controller now applies the validated density
preference to legacy shell pages before paint. Added restrained compact rules
for chat message gaps, avatar spacing, body padding and paragraph rhythm, and
bumped the chat-shell stylesheet cache key.

Browser validation: Extended the real-Chromium shared-preference test to assert
computed message padding in Compacta (12px 16px) and Confortável (16px 20px),
while continuing to verify light/dark/system preference synchronization.

Tests: Focused density/theme browser test passed. After the harness port fix in
Cycle 39, the complete suite passed with 16 real-Chromium scenarios, 18
structural tests, 15 streaming/persistence tests, and contrast checks.
`git diff --check` passed.

Next action: Continue testing history-to-chat navigation and responsive message
readability with both density modes.

## Cycle 39 — 2026-09-29

Area: Deterministic safe ports for Chromium test servers.

Observed problem: The real-browser harness bound fixtures to OS-selected
ephemeral ports. Chromium rejects a small reserved set, so one full suite run
failed nondeterministically when Windows selected port 1719.

Changes made: `createTestServer` now remaps ephemeral requests to a process-local
high port range known to be accepted by Chromium, keeping the test setup and
browser origin otherwise unchanged.

Validation: The rerun passed all 16 real-Chromium scenarios and the complete
frontend suite. The previous Chromium unsafe-port failure did not recur.

Next action: If the complete run stays green, continue with history navigation
and mobile density checks.

## Cycle 40 — 2026-09-29

Area: Keyboard navigation from the anonymous History page into a restored chat.

Observed coverage gap: History persistence and direct assistant reload were
tested separately, but the production anonymous-history renderer had no browser
test for activating a conversation card with the keyboard, restoring the exact
conversation, and returning with browser Back.

Changes made: Added a fixture around the production anonymous history store and
history-page renderer. The Chromium scenario seeds a two-message conversation,
reloads History, opens its card using Enter, checks both messages and mobile
width, then uses Back and verifies the card remains available.

Browser validation: Focused 390px Chromium flow passed end-to-end.

Tests: Focused history transition test passed. The complete suite passed with
17 real-Chromium scenarios, 18 structural tests, 15 streaming/persistence
tests, and contrast checks. `git diff --check` passed.

Next action: Continue route-level keyboard checks for search, collections and
norm detail, preserving the existing capture baseline.

## Cycle 41 — 2026-09-29

Area: Preventing theme flash during initial page render.

Observed problem: `theme.js` contains anti-FOUC logic, but the assistant loaded
it at the end of `<body>` and the workspace shell only applied preferences from
its bottom-loaded controller. With a saved light theme, the document could
paint dark first and then switch after the page content was already present.

Changes made: Moved the shared theme controller into `<head>` before stylesheets
in both the assistant and workspace shells. It now applies theme and density
before the browser paints CSS; the assistant no longer loads it a second time.
Added a structural contract for placement and single loading.

Validation: Focused template-order test passed for both shells.

Tests: The complete frontend suite passed with 17 real-Chromium scenarios, 19
structural tests, 15 streaming/persistence tests, and contrast checks.
`git diff --check` passed.

Next action: Continue with root route keyboard paths and initial-paint checks
across light/dark/system preference states.

## Cycle 42 — 2026-09-29

Area: Recovery path from an empty semantic search to direct norm lookup.

Observed problem: On the actual local database, semantic searches for `7982`
and `7982/2025` returned zero while `Lei 7.982/2025` returned results. The
empty state offered no way to switch to the separate `/normas/` catalog, whose
existing search supports number, type and ementa. The corpus currently has only
10 consolidated norms, so the specific 2025 law may not be present locally.

Changes made: Added a clear direct-catalog CTA to semantic no-result states,
preserving query, type and year in the link. Added structural coverage; no
backend, RAG, model or API contract was changed. Found that the shared
`workspace-button-secondary` class had no explicit design-system rules; added
normal/hover states for the CTA and the existing history pagination links.

Browser validation: Real 390px `/pesquisa/` rendered the CTA without horizontal
overflow and produced `/normas/?q=7982&tipo=1&ano=2025`. The linked route
returned HTTP 200 with those filters. This is a discoverable fallback, not a
claim that a missing norm exists in the local corpus. The CTA's computed hit
target is 46px; hover changes surface, border and text color as intended.

Tests: Focused empty-state contract passed. The full frontend suite passed with
17 real-Chromium scenarios, 19 structural tests, 15 streaming/persistence
tests, and contrast checks. `git diff --check` passed.

Next action: Continue route-level keyboard verification and audit no-results,
empty and error states across the primary product surfaces.

## Cycle 43 — 2026-09-29

Area: Revalidation of reported shell, palette and empty-state defects (U1–U7).

Goal: Reproduce the reported issues against the current checkout before making
further UI changes.

Observed problems: None of U1–U7 reproduced. The current tree already contains
the earlier fixes: the palette renders actual SVG nodes; `/normas/` uses the
shared workspace shell; the active chat sidebar includes Settings and Quick
Search; norm metadata is secondary; the collections empty state distinguishes
empty, account-unavailable and public-catalog actions; the model select has a
visible chevron; and legal-search's initial empty state is compact.

Changes made: No application code changed. This cycle records an evidence-based
recheck rather than reapplying fixes already present.

Browser validation: On the live local app, opened Ctrl+K, searched “normas”
and confirmed accessible results (“Pesquisa Jurídica” and “Normas
Consolidadas”) with rendered icons and visible keyboard focus; no SVG source
markup appeared. Inspected `/normas/`, `/colecoes/`, `/pesquisa/`, and
`/configuracoes/`; each showed the shared sidebar/topbar. The active assistant
conversation retained Configurações and Busca rápida. The settings model
select visibly displays its chevron. Re-captured the 30-view audit set at
1440×900, 1280×800, and 390×844; the capture runner reported zero views needing
review.

Tests: Full `npm test` passed, including 17 real-Chromium scenarios, 19
structural contracts, 15 streaming/persistence tests, one composer lifecycle
test, and contrast checks. `git diff --check` passed. The first capture
invocation used the wrong script path and made no changes; rerun from
`tests/js/capture-ui-audit.mjs` succeeded.

Console: No palette-related browser errors observed during the live interaction.

Responsive validation: Captured all 30 configured route/viewport views with no
review flags; existing browser tests verify mobile palette, shell, collections
dialog, and norm/search interactions.

Visual score: These seven reported items are resolved in the current UI; no
new issue from this list warrants a code change.

Regressions: None observed.

Next action: Continue the final cross-route audit for issues outside U1–U7,
prioritizing functional inconsistencies and accessibility over cosmetic churn.

## Cycle 44 — 2026-09-29

Area: Keyboard and accessibility state of the assistant evidence drawer.

Goal: Ensure a visually closed drawer cannot receive keyboard focus or be
announced as an active modal.

Observed problems: Reproduced on the real assistant conversation: pressing Tab
through the page eventually focused “Fechar painel de fontes” while the drawer
was translated entirely outside the viewport. `aria-hidden="true"` did not
remove its descendants from the browser's sequential focus navigation.

Changes made: The drawer starts with `inert` and `aria-modal="false"`. Opening
removes `inert` and activates modal semantics; closing restores `inert`, hides
the drawer and disables modal semantics before returning focus to the trigger.
Added assertions for initial/open/closed state and the real-Chromium focus path;
updated the static asset cache key.

Browser validation: Repeated Tab navigation on the live `/assistente/<session>/`
page through 40 focus moves; none entered the closed drawer. The Chromium test
also attempts to focus the close control while closed (focus is rejected),
opens the drawer, verifies the content, closes it, checks trigger focus return,
and confirms it is inert again. Re-captured 30 audit views; zero need review.

Tests: Full `npm test` passed: 17 real-Chromium scenarios, 19 structural
contracts, 15 streaming/persistence tests, composer lifecycle and contrast
checks. `git diff --check` passed. An early test run exposed fixture setup and
transition-timing assumptions; the fixture now initializes the dynamic drawer
and the geometry assertion waits for its 300ms transition.

Console: No errors in the drawer browser scenario.

Responsive validation: Drawer browser coverage exercises mobile and desktop
viewport bounds; 390×844 is used for the mobile evidence-card check.

Visual score: No visual change; keyboard behavior and modal semantics are now
consistent with the drawer's visible state.

Regressions: None observed.

Next action: Continue the final accessibility pass across overlays and other
off-canvas controls, then reassess remaining phase-E gaps.

## Cycle 45 — 2026-09-29

Area: Command-palette focus containment on mobile.

Goal: Verify that quick navigation behaves as a modal for keyboard users in the
assistant and shared workspace shell.

Observed problems: No focus escape reproduced. The existing palette handler
wraps both Tab and Shift+Tab to its search combobox, and Escape closes it and
restores the previously focused control. The prior browser scenario checked
open/search/selection/escape but did not explicitly assert both focus-wrap
directions.

Changes made: Strengthened the existing real-Chromium regression test to assert
that Tab and Shift+Tab remain in the palette. No application behavior changed.

Browser validation: Opened Ctrl+K in the live assistant and confirmed the
palette contents and visible focus; then opened the palette from its keyboard
shortcut in the shared Normas shell. The Chromium mobile scenario exercises
Tab, Shift+Tab, keyboard selection, Escape and focus return at 390×844.

Tests: Full `npm test` passed: 17 real-Chromium scenarios (including the added
focus-wrap assertions), 19 structural contracts, 15 streaming/persistence
tests, composer lifecycle and contrast checks. The focused palette test also
passed independently. `git diff --check` passed.

Console: No palette-specific errors observed in the real-browser test.

Responsive validation: Re-captured 30 route/viewport views at 1440×900,
1280×800 and 390×844; zero views need review.

Visual score: Palette layout unchanged; keyboard modal behavior is explicitly
protected from regression.

Regressions: None observed.

Next action: Continue final pass through route-level feedback/error states and
reduced-motion behavior; verify that UI claims match actual actions.

## Cycle 46 — 2026-09-29

Area: Chat-history deletion confirmation accessibility and safety feedback.

Goal: Make the destructive-action confirmation understandable and fully
operable with keyboard without allowing accidental background actions.

Observed problems: The dynamically created “Deletar conversa” confirmation
had no dialog semantics, initial focus, Escape handling, focus containment or
background isolation. Its cancel/backdrop paths only removed a CSS class, so
focus could remain in an invisible overlay.

Changes made: Added labelled/described dialog semantics, `aria-hidden` and
`aria-modal` state, `inert` state for the dialog and underlying app shell,
initial focus on the non-destructive Cancel action, Tab/Shift+Tab wrapping,
Escape/backdrop cancellation and focus restoration. After a successful
deletion, focus moves to “Nova pesquisa” rather than a removed history row.
Updated the chat script cache key.

Browser validation: At 390×844 in real Chromium, opened the modal through the
chat UI API with a fixture trigger, verified its accessible name/description,
background inertness and Cancel initial focus; exercised both Tab directions,
Escape, focus return, reopen and Cancel. The fixture performed no delete
request. Desktop/mobile capture set completed with 30 views and zero review
flags.

Tests: Full `npm test` passed with 18 real-Chromium scenarios, 19 structural
contracts, 15 streaming/persistence tests, composer lifecycle and contrast
checks. `git diff --check` passed.

Console: The focused browser test reported no modal-specific runtime errors.

Responsive validation: Modal keyboard test uses 390×844; screenshot capture
covered 1440×900, 1280×800 and 390×844.

Visual score: No new visual treatment; this closes a critical accessibility
and interaction gap in a destructive flow.

Regressions: None observed; confirmation still requires the explicit
“Deletar” action, and the added test cancels without calling the deletion API.

Next action: Continue auditing error and success announcements, then verify
reduced-motion behavior across assistant and workspace route families.

## Cycle 47 — 2026-09-29

Area: Accessible announcement for failed chat-history deletion.

Goal: Ensure users, including screen-reader users, receive an immediate and
programmatically announced failure when a delete request is rejected.

Observed problems: The visual error toast created after a failed deletion had
no live-region semantics, so assistive technology was not required to announce
the failure. The first test attempt used the anonymous fixture, whose expected
behavior is local deletion and therefore correctly made no HTTP request.

Changes made: Error notifications now use `role="alert"`, assertive live
announcement and atomic message updates. Success notifications use
`role="status"` and polite announcement. Clearing and re-setting the toast text
ensures an identical repeated message still produces a live-region change. The
chat static cache key was updated. The test fixture now uses the authenticated
path and intercepts a simulated 500 response without contacting a real API or
database.

Browser validation: Real Chromium opened the confirmation, cancelled without
request, reopened it, confirmed the test-only operation against a local 500
handler, and verified the resulting announcement role, live priority and exact
message. Captured 30 route/viewport views; zero need review.

Tests: Full `npm test` passed: 18 real-Chromium scenarios, 19 structural
contracts, 15 streaming/persistence tests, composer lifecycle and contrast
checks. `git diff --check` passed.

Console: The deliberate 500 is handled by the app's expected error path; no
uncaught runtime error was reported in the test.

Responsive validation: Failure-feedback scenario runs at 390×844; the full
capture set also covers 1280×800 and 1440×900.

Visual score: Toast appearance is unchanged; status is now accessible to
assistive technology and repeat failures are announced again.

Regressions: None observed. Anonymous history continues to use local deletion;
the failure test explicitly uses the authenticated API path.

Next action: Test reduced-motion computed behavior on actual assistant and
workspace components, then continue the phase-E cross-route audit.

## Cycle 48 — 2026-09-29

Area: Reduced-motion behavior in assistant and shared workspace shell.

Goal: Verify the user preference changes rendered animation/transition values,
not merely that stylesheets contain a media query.

Observed problems: The CSS already supplied global reduced-motion rules, but
the existing checks were largely structural and did not establish the computed
duration of live components in both shell families.

Changes made: Added a real-Chromium scenario emulating
`prefers-reduced-motion: reduce`, creating/closing the actual sources drawer,
and measuring drawer and workspace-sidebar computed transitions/animations.
No styling or runtime behavior changed.

Browser validation: At 390×844, Chromium confirmed the preference matches in
both routes and all computed transition/animation duration values are below
1ms for the assistant evidence drawer and workspace sidebar. The 30-view route
capture reported zero views needing review.

Tests: Full `npm test` passed: 19 real-Chromium scenarios, 19 structural
contracts, 15 streaming/persistence tests, composer lifecycle and contrast
checks. The focused reduced-motion browser test also passed independently.
`git diff --check` passed.

Console: No new browser errors from reduced-motion emulation.

Responsive validation: Runtime check at 390×844; screenshot capture covered
390×844, 1280×800 and 1440×900.

Visual score: No appearance changes; reduced-motion preference is now verified
against computed runtime styles in both product shells.

Regressions: None observed.

Next action: Continue the phase-E pass through route error/empty states and
keyboard paths on Norma detail, comparison, tree and workspace forms; identify
any remaining user-visible failure before considering completion.

## Cycle 49 — 2026-09-29

Area: Norma detail reading hierarchy and full-text disclosure.

Goal: Reduce repeated content on the consolidated norm page without removing
access to its complete source text.

Observed problems: A live Chromium inspection of Lei nº 8206/2026 showed all
24 structured devices followed by a second, full-text rendering of the same
norm, including decorative separator lines and consolidation metadata. This
made the page unusually long and obscured the article-by-article reading path.

Changes made: Kept the full consolidated text but placed it in a native,
keyboard-operable `<details>` disclosure, renamed the section to distinguish
it from the structured devices, provided a 44px summary target and an explicit
visible keyboard focus ring. Updated the stylesheet cache key and added a
regression contract for the disclosure and CSS.

Browser validation: At `/normas/3/`, the live accessibility tree exposed all
24 devices while the duplicate text stayed collapsed. Pressing Enter on the
summary expanded the full text. The disclosure is native HTML, so it retains
standard keyboard and assistive-technology semantics.

Tests: Full `npm test` passed, including 19 real-Chromium scenarios, 20
workspace/norm structural contracts, 15 streaming/persistence checks, composer
lifecycle and contrast checks. `git diff --check` passed.

Console: No new browser errors observed. Route capture completed 30 views with
zero needing review.

Responsive validation: Browser capture covered 390×844, 1280×800 and
1440×900; no overflow or navigation failures were reported.

Visual score: The initial legal reading path is shorter and less repetitive;
the complete source remains available on demand.

Regressions: None observed.

Next action: Continue the phase-E cross-route audit through comparison, device
tree, workspace forms and route error states; inspect keyboard and recovery
paths for concrete user-visible failures.

## Cycle 50 — 2026-09-29

Area: Norm version comparison and legal-device tree.

Goal: Audit whether comparison output communicates its evidentiary limits and
whether the hierarchy remains operable with a keyboard.

Observed problems: On a real norm with OCR page markers, the comparison showed
many apparent row changes and unmatched lines. The screen called this “Diferenças
linha a linha” without explaining that the alignment is automatic and textual;
users could mistake OCR/layout noise for a substantive legal amendment.

Changes made: Renamed the section to “Comparação textual por linhas” and added
a visible, accessible method note explaining OCR/layout limitations and asking
the reader to verify the full text and normative events. No backend comparison
logic or legal inference was changed.

Browser validation: The note was present in the live accessibility tree on
`/normas/3/compare/`. On `/normas/3/tree/`, pressing Enter on “Recolher Art. 2º”
collapsed its child devices, updated the control label/state and retained focus.

Tests: Full `npm test` passed, including 19 real-Chromium scenarios, 20
workspace/norm structural contracts, 15 streaming/persistence checks, composer
lifecycle and contrast checks. The comparison-specific structural check passed.
`git diff --check` passed.

Console: Route capture completed 30 views with zero needing review.

Responsive validation: Capture covered 390×844, 1280×800 and 1440×900; no
horizontal overflow or navigation failures were reported.

Visual score: Comparison methodology is now stated before the diff, reducing
the chance that textual mismatches are presented as legal conclusions.

Regressions: None observed. A genuinely semantic/legal diff would require
backend comparison work and remains outside this frontend-only cycle.

Next action: Continue through empty/error routes and workspace forms, testing
submission, validation recovery, focus return and mobile layout in the live app.

## Cycle 51 — 2026-09-29

Area: Norma search empty state, clear controls and filter recovery.

Goal: Ensure clearing a search restores results instead of only changing the
input text, while preserving the user's other filters.

Observed problems: A live search for an impossible term returned zero norms.
Pressing Escape or activating “Limpar pesquisa” cleared the visible input but
left stale zero-result content and the old query in the URL. Separately, the
clear button's author `display:grid` rule overrode the native `hidden` state,
so an empty search still exposed a purposeless clear control.

Changes made: Escape and the clear button now submit the filter form with the
search field excluded from submission, preserving type/year/order filters and
returning to a clean query URL. Added an explicit `[hidden]` CSS rule, cache
busting for both changed frontend assets, and a real-Chromium test that checks
button and keyboard clearing, results recovery and preserved filters.

Browser validation: On the live `/normas/` route, an impossible query showed
the empty state. Clearing via Escape restored 10 results while retaining the
selected type filter. A fresh unfiltered page no longer exposes the empty clear
button. The same click and Escape cases passed in a real Chromium test fixture.

Tests: Full `npm test` passed, including 20 real-Chromium scenarios, 20
structural contracts, 15 streaming/persistence checks, composer lifecycle and
contrast checks. `git diff --check` passed.

Console: Route capture completed 30 views with zero needing review.

Responsive validation: Capture covered 390×844, 1280×800 and 1440×900; no
horizontal overflow or navigation failures were reported.

Visual score: Clear-search affordance now appears only when useful; the empty
state has a working recovery path and filter state remains predictable.

Regressions: None observed.

Next action: Continue cross-route testing on settings, collection forms,
history recovery and legal search; inspect direct URLs and mobile input states.

## Cycle 52 — 2026-09-29

Area: Legal search result interpretation and user-facing confidence language.

Goal: Keep search-result relevance from being mistaken for legal certainty.

Observed problems: A live query for “Lei nº 8206/2026 art. 8º” produced a
“Boa correspondência” result label. That label comes from automatic retrieval;
it does not establish legal pertinence, validity or authority. The current
search page did not explain this distinction near the result list.

Changes made: Added a concise, accessible note on queried search pages stating
that relevance is an automatic retrieval estimate and that the user should
verify the device and normative source before citing. Added restrained styling,
updated shared workspace CSS cache-busting and structural assertions. Search
ranking/API behavior was not changed.

Browser validation: The live `/pesquisa/` query rendered the note before the
results while preserving the query, filters, result count and links. Live
inspection also confirmed empty-state examples appear only before a query.

Tests: Full `npm test` passed: 20 real-Chromium scenarios, 20 structural
contracts, 15 streaming/persistence checks, composer lifecycle and contrast
checks. `git diff --check` passed.

Console: Route capture completed 30 views with zero needing review.

Responsive validation: Capture covered 390×844, 1280×800 and 1440×900; no
horizontal overflow or navigation failures were reported.

Visual score: The evidence/relevance boundary is now explained exactly where
users inspect results, without adding a heavy component or blocking workflow.

Regressions: None observed. Search ranking precision is a backend/RAG issue
and remains outside this frontend-only track.

Next action: Continue a live pass through settings persistence/reset,
collection and history routes, plus keyboard-only navigation and direct URLs.

## Cycle 53 — 2026-09-29

Area: Shared workspace sidebar composition.

Goal: Improve navigation hierarchy across all pages using the authenticated-
style workspace shell.

Observed problems: Desktop screenshots showed the primary navigation vertically
centered in the full viewport, leaving a large unexplained gap beneath the
brand/new-search action. The utility links happened to sit at the bottom, but
the primary route group was visually disconnected from the brand.

Changes made: Changed the sidebar to top-flow layout, let the primary nav take
remaining vertical space, and anchored utility actions with `margin-top:auto`.
Updated the shared stylesheet cache key and added a structural contract. No
navigation routes or mobile drawer behavior changed.

Browser validation: Captured the live `/pesquisa/` workspace at desktop and
mobile sizes. At 1440×900 the primary nav now starts directly below the brand
action while settings/quick search remain at the bottom. At 390×844 the
collapsed mobile shell remains clean and the menu trigger is unchanged.

Tests: Full `npm test` passed: 20 real-Chromium scenarios, 21 structural
contracts, 15 streaming/persistence checks, composer lifecycle and contrast
checks. `git diff --check` passed.

Console: Route capture completed 30 views with zero needing review.

Responsive validation: Screenshots reviewed at 1440×900 and 390×844; automated
capture also covered 1280×800 and reported no overflow/navigation failures.

Visual score: Navigation now follows a familiar product hierarchy: brand,
primary destinations, then persistent utilities at the lower edge.

Regressions: None observed.

Next action: Continue real-browser checks for settings preference persistence,
history restoration, and collection empty-state actions across viewport sizes.

## Cycle 54 — 2026-09-29

Area: Production 404/500 recovery screens.

Goal: Verify invalid routes and unexpected server failures provide a usable,
non-technical recovery path when production error handling is active.

Observed problems: The live 8004 development server has `DEBUG=True`, so an
invalid norm URL displayed Django's technical 404 page with URL patterns and
view details. This is a development-mode behavior, but production needed a
designed 404 page. A first 500-template attempt also failed because Django's
default 500 handler renders without a `request` context; that was corrected by
making the 500 page standalone and request-independent.

Changes made: Added an app-discovered branded 404 template with navigation,
clear explanation and links back to norms/assistant. Added a standalone 500
template with retry navigation and no exception output. Centered the 500
recovery state using existing workspace styles and bumped the shared CSS cache
key. Added structural assertions preventing technical-detail leakage.

Browser/runtime validation: A temporary local runserver with `DEBUG=False`
served `/normas/999999/` as the styled 404 page; its live screenshot showed the
shared shell and usable recovery links. Django's test client returned 404 with
the custom message and no `Request URL` details. A synthetic uncaught runtime
exception rendered status 500 with the friendly message and did not include
the sentinel exception text. The temporary server was stopped afterward.

Tests: Full `npm test` passed: 20 real-Chromium scenarios, 22 structural
contracts, 15 streaming/persistence checks, composer lifecycle and contrast
checks. `git diff --check` passed. Django runtime smoke checks verified both
custom response bodies.

Console: The production-mode 404 loaded all shell assets successfully (200).
Automated route capture completed 30 views with zero needing review.

Responsive validation: Global capture covered 390×844, 1280×800 and
1440×900. Error page visually checked in the production-mode browser; no
layout overflow observed.

Visual score: Invalid links now return users to the product rather than a
framework diagnostic. Unexpected failures have a compact, branded recovery
screen without exposing exception text.

Regressions: None observed. The 8004 development server will continue to show
Django diagnostics while DEBUG is enabled; production mode uses the new page.

Next action: Finish the remaining manual checks on settings, local history and
collection paths; then review the full acceptance checklist and unresolved
backend-only risks without changing out-of-scope services.

## Cycle 55 — 2026-09-29

Area: Full-repository regression suite after frontend template updates.

Goal: Verify the complete Python/Django suite as well as the frontend suite,
and distinguish product regressions from stale static assertions.

Observed problems: The first full pytest run reported 650 passed, 6 skipped
and 2 failures. One workspace-route test still expected the old comparison
heading after the user-facing label was clarified. A frontend static guard
looked for persisted preference parsing inside `chat.js`, although that
responsibility is already in `jurix-chat-api.js` and the chat correctly passes
search controls separately.

Changes made: Updated those two assertions to the current UI wording and actual
module boundary. No runtime production logic changed in this cycle.

Browser validation: Previous cycles in this run exercised the live norms,
comparison, tree, collections, history, settings and search routes; the
production-mode 404 was also opened in the browser. This cycle was test-only.

Tests: Full Python suite passed: 652 passed, 6 skipped, 7 expected
`DATABASES` override warnings. Frontend `npm test` had passed in Cycle 54:
20 real-Chromium scenarios, 22 structural contracts, 15 streaming/persistence
checks, composer lifecycle and contrast checks. Focused tests for the two
updated assertions passed; `git diff --check` passed.

Console: No runtime code changed; prior route captures reported no unexpected
console errors or failed requests.

Responsive validation: No visual changes in this test-only cycle. Existing
capture set covers 390×844, 1280×800 and 1440×900.

Visual score: No visual change. Test guardrails now match the user-visible
copy and the current modular frontend architecture.

Regressions: None observed after updating the stale expectations.

Next action: Continue the user-requested final pass across settings, history,
collection actions and command-palette interactions; keep any RAG relevance
or ranking findings documented as backend-only follow-up.

## Cycle 56 — 2026-09-29

Area: Real assistant journey — submit, stream completion, evidence drawer and
reload persistence.

Goal: Validate the principal chat workflow in the running Django application,
not only through the isolated browser fixtures.

Observed problems: A direct question about Lei nº 8206/2026 returned the right
Art. 8º evidence, but the generated answer repeated signatures/authorship
metadata and lacked an explicit citation marker. An earlier query about a
different available law had returned “Evidência insuficiente”. These point to
retrieval/generation quality, not a frontend presentation defect.

Changes made: No production code changed. This was an end-to-end audit cycle;
backend/RAG behavior remains outside the frontend-only work contract.

Browser validation: In the live `/assistente/` flow, Enter submitted the
question and the composer returned to its ready state after generation. The
completed answer exposed a sources pill; opening it showed two grouped
evidences from Lei nº 8206/2026 (Arts. 8º and 7º), contribution labels and
SAPL links. Escape closed the drawer. Reloading the stable conversation URL
restored both the new question, answer and source summary.

Tests: Full Python suite passed in Cycle 55 (652 passed, 6 skipped). Full
frontend `npm test` passed in Cycle 54 (20 real Chromium, 22 structural,
15 streaming/persistence, composer and contrast checks). No code changed since
those runs.

Console: The live interaction completed and rendered both source links; route
capture in the preceding cycle found no failed assets or unexpected console
errors. This manual CUA pass did not collect a separate console trace.

Responsive validation: The live chat was inspected at the current desktop
viewport; responsive assistant states are covered by the 390×844 browser and
capture checks in prior cycles.

Visual score: The composer, completed response and source drawer are coherent
and legible. The answer's legal-content quality and explicit citation
relationship remain materially below the UI's evidence presentation.

Regressions: No UI regression observed. The test query was appended to the
currently active local anonymous conversation; it remained after reload, as
intended by the persistence test.

Next action: Continue the final audit through direct settings and history
recovery, then classify remaining acceptance items as verified, open frontend
defect, or backend-only dependency without expanding into backend changes.

## Cycle 57 — 2026-09-29

Area: Recheck of reported palette, shell consistency, norm metadata and empty
states.

Goal: Verify each item in the latest UI issue list against current templates,
styles and the running application; fix any residual frontend defects.

Observed problems: The `/normas/` page already extends the shared workspace
base and the command palette already renders trusted SVG markup as actual SVG
elements. The collections page already separates empty state, account
availability and public-corpus action. Settings already has a visible blue
select chevron, and legal-search empty state uses compact padding. In the norm
card stylesheet, however, a later duplicate rule overrode earlier secondary
metadata styling: labels remained 9px and values 12px. The chat sidebar had
the same navigation and utility actions as the shared shell, but placed Normas
before Pesquisa Jurídica.

Changes made: Corrected the effective norm metadata rules to 10px labels with
less tracking and 13px/600 values, keeping publication and validity subordinate
to the 18–22px norm title. Aligned chat navigation order with the shared shell
and added a cache-busted stylesheet URL. Updated the existing UI contracts to
assert the effective metadata hierarchy and menu ordering. No backend code or
API behavior changed.

Browser validation: Opened the live `/normas/` page and confirmed the common
sidebar, topbar, filters and result cards. Opened `/assistente/` and confirmed
the same nav ordering, settings and quick-search actions remain available in
the active conversation layout. The active answer still contains irrelevant
signatory boilerplate; this is the previously recorded backend/RAG quality
issue and is outside the frontend-only contract.

Tests: Frontend `npm test` passed: 22 structural contracts, 20 real Chromium
scenarios, 15 streaming/persistence checks, security/CSP, settings and
contrast tests. The SVG visibility regression explicitly asserts the raw
`viewBox` string is not visible in palette text. The first run caught the new
menu-order assertion checking URL occurrences outside the nav; the assertion
was narrowed to the nav markup and passed on rerun. Full Python suite remains
green from Cycle 55 (652 passed, 6 skipped); this cycle changes only CSS,
templates and frontend test assertions.

Console: No failed requests or unexpected console errors observed during the
live route inspection.

Responsive validation: Existing Chromium suite covers 390px mobile, compact
sidebar, command palette, and norm-list filter clearing. Norm cards use the
same responsive layout with improved readable metadata.

Visual score: Norm title now has a clearer typographic lead over dates while
retaining enough contrast and size for secondary data. Workspace and assistant
nav content/order are aligned. The assistant keeps its specialized
conversation canvas, but shared topbar and navigation behavior are consistent.

Regressions: None observed after the complete frontend suite passed.

Next action: Continue the acceptance audit on settings, collections and search
at narrow viewport widths; keep structural chat-shell consolidation and
backend-generated answer quality as separate open items if further evidence
shows material inconsistency.

## Cycle 58 — 2026-09-29

Area: Theme preference, especially the previously non-functional light theme.

Goal: Make the existing Claro preference render as a coherent light interface
through the shared workspace, assistant, evidence drawer and normative detail,
without changing the production backend or default dark appearance.

Observed problem: The settings UI exposed a light option and persisted it, but
large parts of the product retained dark surfaces and light-theme foreground
tokens. This caused mixed-theme pages and, on blue primary actions, low
contrast labels. The light theme was therefore a misleading product setting.

Changes made: Added semantic light palette values and targeted light surfaces
for the shared workspace shell, assistant sidebar/header/composer/user
messages, legal detail actions, anonymous notice and evidence drawer. Primary
action labels now use the accent-appropriate foreground token. Updated
cache-busted stylesheet references and extended real-browser theme coverage to
assert key surface colors and WCAG AA action-label contrast. Updated static
contracts for the new cache key and valid foreground token. No backend or API
behavior changed.

Browser validation: Inspected the running app at 390×844 for settings,
collections, legal search, norm list/detail, assistant and source drawer.
Appearance was coherent in light mode and no horizontal overflow was found.
Restored the user's browser preference to Escuro through the settings UI and
reset the temporary viewport override.

Automated visual validation: Refreshed `docs/ui-audit/after` with 30 views
(10 routes × 1440×900, 1280×800 and 390×844). All 30 returned HTTP 200, had a
visible main region, no horizontal overflow, no console errors, no failed
requests and no HTTP error responses.

Tests: `npm test` passed, including 20 real Chromium scenarios, 23 norm/UI
contracts, 15 streaming/persistence scenarios and 2 visual contrast contracts.
Focused Python tests passed (29 tests); design-token guard passed; `git diff
--check` passed. One initial run exposed stale static expectations for a
versioned stylesheet URL and the light/dark foreground token; both tests were
updated to assert the current contract and the full suite passed afterward.

Remaining boundary: This closes the light-theme rendering defect only.
Answer grounding/relevance, corpus completeness and other backend/RAG issues
remain outside this frontend cycle and are still tracked separately.

Next action: Continue visual and interaction audits from the remaining
acceptance criteria, prioritizing any reproducible user-facing issue and
retaining screenshots/tests as evidence.

## Cycle 59 — 2026-09-29

Area: Norm library search by legal identifier.

Goal: Fix a reproducible search failure without changing server-side query
contracts.

Observed problems: The visible list contained Lei 8205/2026, but entering the
common identifier `Lei nº 8205/2026` returned zero results. The list view
filters the number and year separately, while the search field was submitting
the complete string to the number substring search.

Changes made: The norm-list controller now recognizes exact number/year
identifiers (with optional Lei, Decreto, Decreto Legislativo or Resolução
prefix) and translates them into the existing number query plus year facet
before form submission. It only applies the transformation when the year is a
valid option in the current filter. Existing type/order filters and all server
contracts remain intact. Added static and real Chromium regression tests,
updated the script cache key, and added a norm-number/year route to the visual
capture matrix.

Browser validation: Reproduced the original zero-result behavior on the real
`/normas/` page, then searched `Lei nº 8205/2026` after the change. The URL
became `?q=8205&tipo=&ano=2026&ordenar=recentes`, the year filter showed 2026,
and the single correct Lei 8205/2026 card appeared. Also switched grid/list
views and confirmed the selected state updates.

Tests: Added real-browser coverage for the identifier conversion; all 21
Chromium scenarios passed. The initial full run caught that adding the year
field changed the existing clear-search fixture URL; updated that fixture's
expected query, after which the full frontend suite completed with passing TAP
sections. Focused Python checks from Cycle 58 remain valid because this cycle
only touches client JS/template cache version and tests. `git diff --check`
will be rerun before commit.

Console: No page errors were observed during the live search interaction or
the Chromium identifier scenario.

Responsive validation: The refreshed visual matrix captures 33 views across
the existing ten routes plus normalized number/year search at desktop and
mobile widths. No route was flagged for review.

Visual score: The search now matches the product's advertised “number” search
and gives a directly interpretable URL with the year visible as a selected
facet; no backend dependency was introduced.

Regressions: The first automated run exposed a stale query expectation in the
clear-search fixture; corrected and revalidated. No product regression
observed.

Next action: Continue the phase-E audit for visual/interaction defects not
covered by route captures, especially failure/empty states and keyboard focus
across the normative workflow.

## Cycle 60 — 2026-09-29

Area: Legal certainty cues for missing effective dates.

Goal: Align norm-list and norm-detail language so missing corpus data is not
visually presented as a verified legal conclusion.

Observed problems: The list rendered missing effective dates as “Não
informada”, while the detail page used a green “Vigente desde a publicação”
badge and the timeline used a “vigente” badge. A smaller disclaimer qualified
the assertion, but the dominant visual state still communicated certainty.

Changes made: Norm cards now identify missing effective dates as “Não
registrada no corpus”. In the detail page, the temporal status and timeline
use neutral “não registrada” labels unless the corpus has a date; a revoked
status remains visible as such. The caveat now explicitly directs users to
confirm vigência in the official source. Updated the Python route assertion and
added a frontend contract forbidding the former inference wording. No model,
RAG or backend computation changed.

Browser validation: Reloaded the live Lei 8206/2026 detail page and confirmed
the temporal table says “Data de vigência não registrada no corpus”, includes
the official-source caveat, and the timeline badge says “Vigência não
registrada”. Visual audit recaptured 33 views across 11 routes and 3 sizes;
the capture reported zero views needing review.

Tests: Focused Python frontend/workspace route tests passed (29). Norm UI
contracts passed (25). Full frontend `npm test` is running now and must pass
before this cycle is committed. The first Python run caught the prior test's
expectation of “Vigente desde a publicação”; updated that stale assertion to
the new neutral contract and reran successfully.

Console: No new console errors observed in the live detail-page reload.

Responsive validation: Visual matrix remains clear at desktop and 390px mobile;
the detail page retains its responsive action grid and metadata layout.

Visual score: Improved legal clarity: absence of a date is no longer encoded
as a green verified state. The remaining `status` interpretation still
depends on source data, but missing vigência now remains explicitly uncertain.

Regressions: None observed in focused Python tests or the browser check.

Next action: Continue the final audit of focus behavior and empty/error states
in the assistant and normative workflows.

## Cycle 61 — 2026-09-29

Area: Legal-search empty-state recovery link.

Goal: Ensure the “Buscar no acervo normativo” action produces a clean URL when
the user did not select a year.

Observed problems: On `/pesquisa/?q=zzzzinexistente2026`, the recovery CTA
linked to `/normas/?q=...&tipo=&ano=None`. The list view ignored the invalid
year safely, but the literal `None` leaked into a user-facing URL and shared
links.

Changes made: The template now applies Django's `default_if_none` filter to
the optional year before URL encoding. Added a Python route regression test
that uses an overlength query to exercise the empty/error state without
invoking the semantic backend, and updated the frontend template contract.
No backend logic changed.

Browser validation: Reproduced the CTA on the live semantic-search empty
state. It now links to `/normas/?q=zzzzinexistente2026&tipo=&ano=`; clicking it
opens the normative list with the search preserved, an empty year facet, and
the expected no-results state.

Tests: The new Python route test passed; all 25 norm/workspace frontend
contracts passed. The complete 29-test focused workspace-route suite passed
after the effective-date copy change in Cycle 60. Full `npm test` passed in
Cycle 60 and this cycle's updated static contract passed independently.

Console: No new page errors during CTA navigation.

Responsive validation: Recaptured the 33-view, 11-route matrix at 1440×900,
1280×800 and 390×844; route sweep reported no views needing review.

Visual score: Recovery behavior remains visually consistent, and the
destination URL now accurately encodes an unset year as empty rather than a
Python sentinel value.

Regressions: None observed.

Next action: Continue the final interactive pass over empty/error recovery,
focus order, and mobile actions; keep backend/search-ranking limitations
separate from frontend defects.

## Cycle 62 — 2026-09-29

Area: Command palette relevance and keyboard recovery.

Goal: Make the quick-navigation palette select the most likely destination
when a term matches both a destination title and another item's description.

Observed problems: Typing “normas” put “Pesquisa Jurídica” first because its
description mentioned normas and the palette used declaration order. “Normas
Consolidadas” matched the title but was only the second option, so Enter could
navigate to the wrong workspace.

Changes made: Palette search now ranks exact title, title prefix, title
substring, then description match while preserving prior order within equal
scores. Added structural and Chromium assertions for the initial selected
result, updated both workspace/chat cache-busted URLs, and taught the visual
capture to preserve a searchable “normas” palette state at desktop and mobile
sizes.

Browser validation: On the live `/normas/` page, opened the palette, typed
“normas”, and confirmed “Normas Consolidadas” became the selected first
result. Pressed Escape and verified focus returned to the original
`command-palette-trigger` button.

Tests: The full `npm test` suite passed, including 21 real Chromium scenarios,
26 norm/UI contracts, streaming/persistence and security checks. The focused
Chromium file verifies palette ranking, compact SVG icons, focus containment,
Escape and focus restoration. Visual capture completed 36 views (12 routes ×
3 viewports) with zero views flagged for review.

Console: No new errors in the live palette interaction or browser tests.

Responsive validation: Capture includes 390×844 in addition to 1280×800 and
1440×900; prior real-browser tests verify the palette remains within mobile
gutters and SVG icons remain bounded.

Visual score: Quick navigation now resolves obvious title matches ahead of
incidental descriptive matches, reducing accidental navigation without
changing the palette layout or adding dependencies.

Regressions: None observed.

Next action: Continue keyboard and mobile checks across the remaining primary
routes and address the next reproducible frontend defect.

## Cycle 63 — 2026-09-29

Area: Tablet and breakpoint transition coverage.

Goal: Validate the main product routes at the explicit 768px and 1024px
breakpoints from the UX rubric, beyond the saved 390px and desktop captures.

Observed problems: The visual screenshot matrix covered mobile and desktop,
but there was no repeatable route sweep at tablet width or immediately above
the 900px sidebar breakpoint. A layout could therefore fail at those widths
without appearing in the existing 30–36 image review.

Changes made: Added `tests/js/responsive-breakpoint-smoke.mjs` and exposed it
as `npm run test:responsive`, a repeatable headless Chromium check for 11 real
workspace routes at 768×1024 and
1024×768. It checks HTTP status, visible main content, horizontal overflow,
page errors, console errors and failed requests without generating redundant
screenshots or modifying the app.

Browser validation: The smoke run checked all 22 route/viewport combinations
against the running Django app on port 8004.

Tests: All 22 returned HTTP 200, exposed a visible main region, had no
horizontal document overflow, and produced no console errors or failed
requests. The script exited successfully. Existing full frontend suite passed
in Cycle 62; this cycle adds an independent real-app responsive check.

Console: Zero errors across all 22 visits.

Responsive validation: Both sides of the mobile/desktop shell transition
(768px mobile-navigation layout and 1024px desktop layout) passed for
assistant, search, norm catalog/search/detail/compare/tree, collections,
history and settings.

Visual score: This closes a blind spot in breakpoint coverage; no visual
regression was found at tablet or transition widths.

Regressions: None observed.

Next action: Continue the cross-route keyboard/accessibility audit and correct
any reproducible issue before the final phase assessment.

## Cycle 64 — 2026-09-29

Area: Assistant sidebar utility reachability at short desktop heights.

Goal: Recheck the reported shell inconsistencies and ensure navigation remains
usable when the viewport is short and the conversation history is long.

Observed problems: The seven reported issues U1–U7 were already resolved in
the current templates and styles; prior live-browser evidence is recorded in
Cycles 43 and 57. A separate geometry check at 1280×600 did reproduce a new
sidebar defect: the assistant sidebar's content-box sizing made it 648px tall
inside a 600px viewport, placing Settings and Quick Search below the visible
area. The long history itself was scrollable, but the utility footer was not.

Changes made: The assistant sidebar now stretches to its flex parent's height
without exceeding it. Its brand, primary navigation and history form a
bounded, independently scrollable region, while the utility footer remains
fixed at the bottom. Added a restrained native scrollbar treatment and
cache-busted the changed stylesheet. Added static and real-Chromium regression
tests with an expanded history and 1280×600 viewport.

Browser validation: The live app at 1280×600 now reports a 600px sidebar,
scrollable navigation content (616px content in a 460px viewport), and both
Settings and Quick Search wholly inside the viewport. The screenshot confirms
the utilities remain visible while the history region scrolls.

Tests: Full `npm test` passed, including 27 norm/UI contracts, 22 real
Chromium scenarios, 15 streaming/persistence checks and the security/CSP,
accessibility and contrast suites. The focused short-viewport Chromium test
also passed independently. No backend or API code changed.

Console: No new errors in the live route check or Chromium tests.

Responsive validation: Existing mobile sidebar open/close, focus and overflow
tests continue to pass; the new 1280×600 scenario covers short desktop
viewports with large history.

Visual score: Utility actions remain predictably anchored and reachable under
constrained vertical space; the history can scroll without displacing global
navigation actions.

Regressions: None observed.

Next action: Continue the route-by-route product audit at narrow and short
viewports, then verify the remaining acceptance criteria in GOAL.md.

## Cycle 65 — 2026-09-29

Area: Shared workspace sidebar height and utility navigation.

Goal: Ensure `/normas/`, search, history, collections and settings keep their
utility actions visible on shorter screens, just as the assistant now does.

Observed problems: The common workspace sidebar had the same content-box
height overflow, measuring 756px in a 720px viewport. On `/normas/`, the
Configurações and Busca rápida footer controls were clipped at the bottom.

Changes made: Set the workspace sidebar to border-box viewport sizing and
bounded its navigation as the independently scrollable flex region. The
utility footer no longer shrinks or moves offscreen. Added matching subtle
scrollbar styling, refreshed the workspace stylesheet cache key, and extended
the real-browser shell fixture with a long navigation list and persistent
footer actions. Updated keyboard expectations to reflect the now-real brand
and new-research links in that fixture.

Browser validation: On the live `/normas/` route, verified at 1280×720 and
1280×600 that the sidebar exactly fits the viewport and both footer actions
remain fully visible. In the expanded browser fixture, the navigation scrolls
while both utility actions remain inside the 600px viewport. The existing
mobile open/close/focus flow also passes.

Tests: Full `npm test` passed (111 tests across the frontend suites, including
23 real-Chromium scenarios); `npm run test:responsive` passed all 22 route /
tablet combinations. Focused short-height checks passed for both shell
variants, and `git diff --check` passed. An initial fixture expectation still
assumed the first focusable item was the first nav link; it now correctly
accounts for the brand and new-research links. No backend or API code changed.

Console: No new route errors observed.

Responsive validation: Browser screenshots and geometry checks at 1280×600
and 1280×720 show the footer in view; tablet and mobile breakpoint sweep from
Cycle 64 remains green.

Visual score: Both shell variants now preserve the same clear rule at short
heights: primary navigation scrolls, global utility actions stay anchored.

Regressions: No product behavior regression observed; the initial failing
keyboard assertion was a stale test-fixture expectation and now reflects the
brand-first focus order.

Next action: Repeat the full frontend suite, responsive route sweep and
cross-route visual audit before selecting the next highest-impact defect.

## Cycle 66 — light-theme evidence summary contrast

Cross-route inspection of `/configuracoes/`, `/normas/`, `/normas/3/`,
`/pesquisa/` and an active `/assistente/<session>/` conversation in light mode
found a real readability defect in the assistant's compact source summary:
the control, evidence-count badge and action label retained dark-theme colors
against a dark translucent surface. Updated the light-theme semantic surface,
foreground and hover tokens with sufficient specificity to override the legacy
RAG pill declarations, and refreshed the shared stylesheet cache key. Added a
browser contrast assertion for all three controls and a source-contract test.

Live browser validation: the assistant source summary now renders on a white
surface with readable slate text and blue action/badge colors. The source drawer
and its evidence cards remain legible in light mode. The normal user-facing
theme preference screen was inspected; the browser automation environment does
not expose writable browser storage, so its temporary isolated light-mode state
could not be persisted back to dark. This is confined to the audit tab, not the
user's browser profile. Rebuilt ignored Django static assets so the local app
served the updated stylesheet.

Tests: Focused light-theme browser contrast test and static source-contract test
passed. Full `npm test` passed, including 23 real-Chromium scenarios and the
assistant-history, streaming, source drawer, CSP/XSS, navigation, and responsive
flows. `git diff --check` passed. No backend, API or model behavior changed.

Next action: continue the cross-route visual audit, prioritizing remaining
interactive affordances and content hierarchy across the workspace shells.

## Cycle 67 — cross-route navigation, legal text and source deep links

Fixed the shared workspace shell so `/normas/`, norm details and
`/configuracoes/` scroll at document level; the assistant retains its dedicated
streaming frame. Desktop collapse now persists as a 72px icon rail on both
shells, with icons visible, accessible names/tooltips retained, and mobile
navigation continuing to behave as an off-canvas drawer. Removed the duplicate
device-type label that made hierarchy read as “Art. 2º > Inciso IV Inciso”.
The norm-detail control now expands/collapses the actual full device text with
keyboard focus retained and an explicit `aria-expanded` state; its appearance
matches the workspace design system.

Official PDF links in evidence cards now use the full source text (the API's
`text` field is only a 200-character preview ending in an ellipsis). Longer
devices use text-fragment start/end anchors so the link remains short and does
not include an incomplete final word. Non-PDF SAPL links remain unchanged;
unsafe URL protocols remain rejected. If a browser/PDF viewer cannot resolve a
text fragment, its standard fallback is the document itself.

Cross-route UI capture uncovered an asynchronous race in the command palette:
if recent-history loading completed after typing, it replaced filtered results
with the unfiltered list. The palette now rerenders using the current query when
the request completes. Added a delayed-response Chromium regression test.
Strengthened light-mode contrast for the source-summary control, which had been
overridden by higher-priority legacy CSS.

Validation: full `npm test` passed (26 real Chromium scenarios plus unit,
security, persistence, streaming and accessibility tests); `npm run
test:responsive` passed all 22 route/viewport checks; `manage.py check` passed;
the local visual audit captured 36 desktop/mobile views with zero items needing
review; `git diff --check` passed. No backend source, API contract, model, RAG
pipeline or Celery behavior was changed. Static assets were recollected for the
running local app.

Next action: continue cross-route usability testing and audit the actual SAPL
PDF navigation behavior against representative long and short legal devices.

## Cycle 68 — stream continuity, conversation memory and provider controls

Restored visible provisional streaming while keeping unverified draft text out
of saved history. The SSE client now continues reading after the final-answer
event so a locally generated conversation title can arrive independently;
anonymous and authenticated history use a concise Ollama-generated title with
a deterministic short fallback. The history subtitle now shows answer content
instead of repeating the opening question/title.

Short article follow-ups inherit only a legal citation explicitly present in
the last five user questions. The history search now ranks matches using a
bounded weighted bag-of-words score over titles and recent message text;
anonymous browser history has a client-side relevance search as well.

Added generation-provider selection for Ollama, OpenAI, Gemini, Anthropic,
OpenRouter, Groq, and OpenAI-compatible local endpoints (including LiteLLM or
AirLLM deployments). Embeddings/retrieval remain local. API credentials are
kept in tab-scoped `sessionStorage`, are never written to localStorage/history,
and are sent only when a chat request is made. Custom compatible endpoints are
restricted to approved local hostnames and redirects are disabled. README and
settings explain that remote providers receive the question and retrieved
passages.

Cross-route browser inspection found `/normas/` still rendered the persisted
legacy SAPL detail URL even though chat sources had been canonicalized. Norma
cards now normalize that route too; Lei 8206/2026 points to `/norma/9387/`.
Also retained history swipe-to-delete confirmation, grouped source evidence,
clickable answer citations and consistent citation-copy controls from the
preceding iteration.

Validation: full Python suite passed (661 passed, 6 skipped); focused rerun
after the final URL/provider changes passed (61 passed); JavaScript suite passed
all groups (120 tests, including 26 Chromium scenarios); `manage.py check`,
Ruff and `git diff --check` passed. The configured local Ollama endpoint
responded to its health/version request. Browser inspection confirmed the
assistant, `/normas/`, `/pesquisa/`, `/historico/` and `/configuracoes/` routes
render, and the corrected SAPL destination is present in the norm cards.

Next action: test a real local-model follow-up exchange and verify each
third-party provider against credentials/accounts supplied by the project
owner; no external API key was available or transmitted in this cycle.

## Cycle 69 — evidence UX, stream completion, and closing legal metadata

Replaced the app's cup glyph with the Jurix quill SVG across the shared shell,
assistant and response renderer. Evidence groups now animate in gently, and
the expand/collapse-all control reflects individual group state changes.

Separated successful SSE completion from secondary UI refresh failures so a
history/title callback or reader shutdown cannot render a false “connection
unavailable” alert over a delivered answer. Network messaging is reserved for
explicit transport errors rather than every JavaScript `TypeError`.

The legal parser now excludes a corroborated signature/publication colophon
from the final article while preserving the original OCR. It extracts the
publication date from the Diário Oficial and fills effective date only when
the statute explicitly makes publication the effective date; a session date
is never used as a substitute. Regression cases cover Art. 4 and both positive
and negative effective-date scenarios.

Cycle 69 validation: full pytest passed (664 passed, 6 skipped); all JavaScript
suites passed (125/125, including 26 Chromium scenarios). The isolated Chromium
evidence-drawer scenario verifies manual expansion, expand-all, collapse-all,
and their synchronized accessible label. Django system checks, Ruff on the
modified parser/task modules, and `git diff --check` passed. The live assistant
accessibility tree confirms the shared navigation, quill-backed brand image,
completed response and sources control are present in the running app.

## Cycle 70 — empty recent-history state

The post-change live screenshot exposed the recent-history empty-state link in
browser-default blue/underline styling. Styled the empty-state copy with the
existing muted/blue tokens, removed the permanent underline, retained an
underline hover affordance and added a visible keyboard focus ring. The link
still invokes the existing new-research action.

Validation: static template/CSS regression test and all 32 `norma_ui_v3`
JavaScript tests pass; the Python static frontend suite passes (11/11). A live
1440x900 Chromium check confirms the link uses the intended color/no underline,
the page has no horizontal overflow, and there are no console errors.

## Cycle 71 — legally calibrated landing-page claims

Removed unsupported implications of comprehensive legal grounding, guaranteed
precision, and current corpus freshness from the assistant's welcome screen.
The hero now states the observable capabilities (municipal-law search, version
comparison, and traceable provisions); side labels identify the municipal
corpus, traceability, and official sources instead of implying jurisprudence
and doctrine collections that are not part of this search experience.

Validation: the full static frontend suite passes (11/11), all `norma_ui_v3`
tests pass (33/33), and live Chromium returns HTTP 200 with the updated copy,
no JavaScript console errors, and no horizontal overflow at 1440px.

## Cycle 72 — persisted legal publication metadata

Added a Django-backed segmentation regression test for the concrete Lei
8204/2026 closing-text shape. It runs the actual Celery task synchronously,
then verifies that the final article excludes signatures/editorial matter and
that the Diário Oficial date is persisted as publication/effective date only
under the explicit “entra em vigor na data de sua publicação” clause.

Validation: the new task integration test passes against the test database;
Ruff on the test module and `git diff --check` pass.

## Cycle 73 — readable hierarchy for consolidated legal provisions

The live `/normas/3/` page rendered its 24 provisions as a nearly continuous
text stream. Added token-based provision cards, explicit left-aligned legal
text, consistent line length and line height, nested indentation by provision
level, and compact responsive spacing. Updated the page asset version and
added browser assertions for the real stylesheet, keyboard expansion/focus,
and mobile overflow.

Before/after captures are saved under `docs/ui-audit/{before,after}/` for
1440x900 and 390x844. Direct Chromium checks returned HTTP 200, found all 24
provisions, and reported no console errors or horizontal overflow. The mobile
cards keep a 10px radius and readable 1.7 line height.

Validation: full Python suite passed (665 passed, 6 skipped). The focused
norma UI tests passed. A full JavaScript run exposed a brittle contrast check
that treated a transparent control background as black; it now measures the
blue action label against the actual page surface. After that correction, all
JavaScript suites passed (128/128, including real-browser coverage).

## Cycle 74 — comparison summary hierarchy

On the version-comparison route, three highly saturated inline badges made
line counts and applied-event counts look like one status cluster. Replaced
them with a labelled summary group: large tabular counts, explicit descriptions
for OCR lines, consolidated-text lines, and normative events, and restrained
blue/purple/amber accents that do not imply legal validation. The metrics form
three columns on desktop and stack on mobile. No comparison logic or legal
interpretation changed.

Before/after captures: existing baseline `norm-compare-{1440x900,390x844}.png`
and updated `norm-compare-summary-{1440x900,390x844}.png` in the UI audit
folders. Live `/normas/3/compare/` returned HTTP 200 at both widths; the
summary contains the expected 75/43/0 values, uses three columns at 1440px and
one at 390px, has no horizontal overflow, and produced no browser errors.

Validation: all `norma_ui_v3` tests pass; Django system check and
`git diff --check` pass.

## Cycle 75 — compact norma-search prompt on mobile

Cross-route review found the `/normas/` search placeholder was clipped after
“tipo ou” at 390px, leaving the final search field (ementa) undiscoverable.
Shortened the prompt from “Pesquisar por número, tipo ou ementa…” to
“Número, tipo ou ementa…”, preserving the input's accessible label and all
search behavior.

Baseline and refreshed captures are `norms-390x844.png` and
`norm-search-placeholder-390x844.png` (also captured at 1440x900). Live route
checks returned HTTP 200, showed the complete placeholder, reported no
horizontal overflow, and recorded no page errors. The existing norma UI
JavaScript tests pass with a copy regression assertion.

The complete JavaScript suite passed; full pytest passed (665 passed, 6
skipped, 7 warnings), Django system check passed, and `git diff --check` passed.

The prior collection-title clipping seen in an older capture was checked
against the live DOM before changing code: the title box starts at the correct
14px mobile content inset and a fresh screenshot renders it in full. No patch
was made for that stale visual observation.

## Cycle 76 — concise semantic-search example

The mobile `/pesquisa/` field also clipped its long example before users could
read the actual subject. Replaced it with “Ex.: zoneamento ou IPTU
progressivo”; the empty state continues to show the richer set of example
queries. This keeps guidance in the field while reserving the detailed list
for the space where it can be read comfortably.

The existing `search-empty-390x844.png` is the baseline; updated 390x844 and
1440x900 captures are `legal-search-placeholder-*.png`. The live route
returned HTTP 200, the complete placeholder measures 266px against 298px
available at mobile width, and there is no page overflow or browser error.
`norma_ui_v3` tests and `git diff --check` pass.

## Cycle 77 — light-theme suggestion card consistency

The cross-route light-theme audit found the assistant's dynamic legal
suggestion retained its dark slate card, white text and pale-blue source badge
against the otherwise light workspace. Added explicit light-theme surface,
hover, title, icon, arrow, and source-badge treatments using existing
semantic tokens; disabled the dark blur/shadow treatment in this theme. No
suggestion content or interaction changed.

Captured before/after in `assistant-light-suggestions-1440x900.png` under the
respective audit folders. Live `/assistente/` returned HTTP 200 in light mode;
the suggestion is now white (`rgb(255, 255, 255)`), title ink is
`rgb(15, 23, 42)`, badge uses the readable blue token, and the page has no
overflow or browser errors. The light-theme CSS contract was added to the
frontend tests.
Validation: complete JavaScript suite passed (129/129), Django system check
passed, and `git diff --check` passed.

## Cycle 78 — fresh cross-route visual and HTTP audit

Re-captured the canonical UI audit after the interaction, responsive-copy, and
light-theme fixes. Exercised the assistant, palette, empty/results search,
norm list, exact number/year search, detail, comparison, tree, collections,
history, and settings at 1440x900, 1280x800, and 390x844. All 36 navigations
returned HTTP 200, each main region was visible, and the browser audit found
zero navigation errors, failed requests, HTTP errors, console errors, or
horizontal overflow. Refreshed `docs/ui-audit/after/` captures and manifest to
preserve the current rendered state.

## Cycle 79 — unified SVG navigation across workspace shells

The assistant used consistent outline SVGs while the shared workspace shell
used font-dependent Unicode symbols for navigation and utility actions.
Replaced the workspace glyphs with inline, aria-hidden outline SVGs using a
consistent 18px stroke treatment, and aligned “Nova pesquisa” with the
assistant's square-pencil compose icon. Navigation labels, URLs, active
states, keyboard behavior, and collapsed-rail accessibility are unchanged.

The 1440x900 settings baseline/updated captures use the same canonical names;
`settings-collapsed-1440x900.png` records the icon rail. Browser interaction
on `/configuracoes/` returned HTTP 200, measured all eight icons at 18x18,
confirmed labels remain accessible after collapse to 72px, and found no
console errors or horizontal overflow. The 36-view cross-route audit again
returned all HTTP 200 with no failed requests, console errors, or overflow.

Validation: full JavaScript suite passed, including the real-browser collapse
interaction; Django system check and `git diff --check` passed.

## Cycle 80 — light-theme contrast for norm status

The light-theme pass measured the “Consolidado” label at RGB 220, 252, 231
against white—a low-contrast pale green intended as a surface token, not text.
Changed the light-theme status foreground to the existing dark green text
token and versioned the norma-list stylesheet. The status remains semantically
green and keeps its separate dot indicator.

Captured `/normas/` before/after at 1440x900 and after at 1280x800 and 390x844.
Live Chromium measured the new foreground as RGB 4, 120, 87 and a 5.20:1
contrast ratio against the page surface; all three widths returned HTTP 200,
had no horizontal overflow or page errors, and displayed the same status text.
Added a CSS contract regression assertion. All 130 JavaScript tests passed on
the diagnostic rerun, Django system check passed, and `git diff --check`
passed. A prior dot-reporter run had one transient failure; its isolated
browser suite (26/26) and subsequent full named run (130/130) passed.

## Cycle 81 — light-theme cross-route audit support and baseline

The visual audit runner previously captured only the default theme. Added a
`dark|light` option that seeds the browser's theme preference before each
route, keeps dark captures in their existing paths, and writes light captures
and a separate manifest under `docs/ui-audit/<phase>/light/`.

Ran the complete light-theme audit at 1440x900, 1280x800, and 390x844 across
all 12 canonical routes (36 views). The manifest reports 36/36 HTTP 200,
visible main content, zero failed requests, zero console errors, and zero
horizontal overflow. Manually reviewed light-theme comparison, settings, and
norm-detail screens; the existing status contrast issue was fixed and
captured separately in Cycle 80. `node --check` passes for the updated audit
runner.

## Cycle 82 — intermediate responsive breakpoints and drawer interaction

Expanded the capture matrix to include 1024x768 and 768x1024 in addition to
1440x900, 1280x800, and 390x844. Re-ran all 12 routes in dark and light themes:
60 views per theme. Both manifests report 60/60 HTTP 200 and zero navigation
errors, failed requests, console errors, or horizontal overflow.

At 768x1024, interacted with the actual workspace drawer on
`/configuracoes/`: it opens to the 240px rail, leaves the SVG icons visible,
sets `aria-expanded=true`, closes on Escape, resets `aria-expanded=false`,
and never creates horizontal overflow. Saved the open-drawer screenshot as
`workspace-drawer-768x1024.png`. `node --check` and `git diff --check` pass.

## Cycle 83 — compose affordance, evidence partial state, and network errors

Aligned “Nova pesquisa” with the familiar compose-square/pencil action while
retaining the Jurix quill mark as the product identity. In the evidence drawer,
opening a single norm now changes the global action to “Expandir restantes
(n de total abertas)”; opening every group switches it to “Recolher todas”.
Closing an individual group updates the label and `data-state`/`aria-expanded`
asynchronously with the native disclosure state. The real-browser regression
covers source navigation, partial expansion, expand-all, manual collapse, and
re-opening from a citation.

Also stopped mapping every generic `fetch` failure to a definitive lost-
internet message. If the browser explicitly reports offline, the UI says so;
otherwise it reports a communication failure without blaming the user's
connection. Added a JS regression for both online/offline cases.

Validation: targeted evidence-drawer browser test passed; streaming behavior
tests passed (19/19); the complete JavaScript suite passed (131/131), including
real-browser interaction. Initial runs exposed an expected-label mismatch in
the updated partial-state scenario and a stale stylesheet cache-bust assertion;
both were corrected and the complete suite re-run successfully. `git diff
--check` passes.

## Cycle 84 — repair persisted legal closing metadata

The source parser already excluded a corroborated SAPL session/signature footer
from the last article and extracted the official Diário date, but existing
database rows were never re-segmented after that behavior was introduced. A
read-only audit found the defect persisted in Lei 8206/2026 (Art. 8º), Lei
8204/2026 (Art. 4º), and Lei 8201/2026 (Art. 8º): footer/signatures remained
inside the article and effective date was null.

Added `repair_legal_colophons`, an idempotent management command with a dry-run
default and explicit `--apply`. It surgically updates the existing final
article row (stable PKs preserve alteration-event references), fills missing
publication metadata, infers effective date only for an explicit “entra em
vigor na data de sua publicação” clause, rebuilds consolidated text, and bumps
the RAG corpus cache. Applying it to those three records removed the footer;
effective dates now equal official publication dates (21/09/2026, 21/09/2026,
and 09/09/2026). A second dry-run found zero remaining corrections.

Added a Django regression covering dry-run, apply, preserved event/device
reference, article body, publication/effective date, rebuilt text, and
idempotence. Validation: Python suite 666 passed, 6 skipped, 7 warnings;
JavaScript suite 131/131; targeted Ruff, `manage.py check`, and `git diff
--check` passed.

## Cycle 85 — long ementa disclosure on norma detail

Visual review of `/normas/3/` showed its official ementa consuming most of the
first mobile viewport, delaying the legal structure and article entry points.
For ementas longer than 220 characters, the detail now shows a three-line
preview inside a native `<details>` control, with a clear “Ler ementa
completa”/“Recolher ementa” state. Short ementas retain their original
presentation, and the complete official wording stays in the document.

Captured before/after at 1440x900, 1280x800, and 390x844; added expanded-state
captures at all five viewports for both dark and light themes. Interacted with
the live Django route: pointer expansion/collapse and Enter-key expansion/
collapse both worked. The two route manifests show 5/5 HTTP 200 per theme, no
horizontal overflow, no console errors, visible preview, and successful
keyboard state changes. The mobile collapsed ementa card is about 173px high;
the previous full ementa was roughly 377px, with all text still available on
expansion.

Validation: complete JavaScript suite 132/132; frontend static Python tests
11/11; Django system check, audit-runner `node --check`, and `git diff --check`
passed. No route/API behavior changed.

Visual score for this component: hierarchy 9, mobile density 9, accessibility
9, responsive behavior 9. Next: audit the legal-search results/filter flow for
keyboard clarity and dense result scanning before returning to the remaining
norm timeline/tree details.

## Cycle 86 — legal-search form flow and result labels

The `/pesquisa/` audit found that keyboard users reached the submit button
before the filters, result counts always used the plural, and the retrieval
badge exposed the internal English value `semantic`. Reordered the form's DOM
so focus moves from query to type/year/relevance and then submit; desktop keeps
the query and CTA on one row, while narrow layouts stack query, filters, and
CTA. Localized retrieval labels, corrected singular result wording, and made
search errors announce through an assertive alert region.

Captured and inspected the real route in dark and light themes at 1440x900,
1280x800, 1024x768, 768x1024, and 390x844. All ten captures returned HTTP 200,
had no horizontal overflow, console errors, or failed requests. The browser
audit confirmed keyboard order `tipo → ano → similaridade → Pesquisar` after
the query input at every viewport. The mobile card now uses the available width
cleanly, with filter controls and CTA clearly separated.

Validation: complete JavaScript suite 133/133; frontend static Python tests
11/11; Django system check and `git diff --check` passed. No backend/API
behavior changed.

Visual score for this component: hierarchy 9, keyboard flow 9, mobile layout 9,
clarity 9. Next: resume the remaining norm timeline/tree and broader cross-route
interaction audit.

## Cycle 87 — refresh the legal quill mark and evidence reveal motion

The requested writing mark is already a quill in the current SVG, but its
unchanged static URL could leave the earlier cached mark visible; the legacy
PNG touch icon also remains a separate fallback. Added a versioned SVG URL to
the workspace, assistant, public shell, favicon, and rendered assistant avatar
so clients refresh the current legal mark. The existing compose icon remains
the same familiar square-and-pencil affordance used for “new chat”.

Moved the evidence-card entrance animation from component creation to the open
state, so it runs when a law group actually expands. The native disclosure's
`toggle` handler continues synchronizing “expand all” for zero, partial, and
all-open states, and reduced-motion still suppresses the animation. Verified
the actual same-norm evidence group browser flow and captured the assistant in
both themes at five viewport sizes; all captures passed with no review flags.

Validation: complete JavaScript suite 134/134; focused workspace UI tests
39/39; frontend static Python tests 11/11; Django check and diff check passed.
No API or backend behavior changed.

Visual score: familiarity 9, disclosure feedback 9, reduced-motion support 9.
Next: audit the sources drawer and assistant controls end-to-end at mobile and
desktop, then return to unresolved cross-route interactions.

## Cycle 88 — evidence drawer visual audit and norm-title rhythm

Added a reproducible open-drawer state to the browser audit. It uses local
sample records with the known SAPL PDF URLs for Lei 8204/2026 and Lei 8205/2026,
groups the two Lei 8204 devices, opens one group, then expands all. The captured
drawer makes the official-source action visible instead of auditing cards with
missing link metadata. The real-browser drawer test also confirms same-law
grouping, partial/all expansion state, focus restoration, and no browser errors.

The cross-route review caught a compact two-line heading on `/normas/` at
390px (`line-height: 1.02`), where the serif glyphs nearly touched. Increased
mobile title leading to 1.12 and refreshed the stylesheet URL. The result now
has a clear title/subtitle gap in both dark and light mode.

Captured `/assistente/` with the drawer open and `/normas/` at 1440x900,
1280x800, 1024x768, 768x1024, and 390x844 in both themes. Across all four route
manifests, each route has 5/5 HTTP 200, zero overflow, zero console errors, and
zero failed requests. The drawer interaction report confirms two expanded
groups with 2+1 citations and `all-open` state.

Validation: complete JavaScript suite 135/135; focused norm UI tests 40/40;
frontend static tests 11/11; Django check and `git diff --check` passed. The
design-token guard exposed five existing, unbaselined red/white literals in
`workspace.css` (not introduced by this cycle); cleaning those semantic danger
colors is the next focused design-system task.

Visual score: source drawer 9, mobile title typography 9, theme parity 9.
Next: remove the five legacy hardcoded danger colors through explicit semantic
tokens, then continue the cross-route dialog/settings and history audit.

## Cycle 89 — semantic danger colors and history confirmation audit

The design-token gate found five unbaselined hardcoded colors in workspace
delete/confirmation states. Added theme-aware `--figma-red-action` tokens and
replaced literals for swipe-delete, confirm, warning icon, and error text with
semantic palette variables. Both shared-shell stylesheet URLs now refresh the
token changes. The design-token guard passes; one unrelated historical literal
remains explicitly tracked in its baseline.

Added a reproducible history-delete-dialog state to the browser auditor by
injecting a clearly local-only demo card into `/historico/`. The real route
opens the actual confirmation component; the runner verifies the rounded
dialog, theme, danger-button colors, focus placement, Escape dismissal, and
focus restoration, then captures the open state. Dark and light screenshots
were reviewed at five viewports. Contrast/appearance remained consistent, the
dialog is 20px rounded, and no actual delete request is sent by the audit.

Validation: complete JavaScript suite 136/136; focused confirmation browser
test passed; frontend static tests 11/11; Django check; design-token gate (pass,
1 known baseline literal); `git diff --check`. The five-view manifests for
`/historico/` and its local dialog state report HTTP 200, no overflow, no console
errors, and no failed requests in both themes.

Visual score: destructive action clarity 9, dialog hierarchy 9, light/dark
parity 9, keyboard behavior 9. Next: continue history/settings interaction
audit and then check the remaining high-priority assistant flows for keyboard,
loading/error states, and responsive regressions.

## Cycle 90 — align the installed-app icon with the quill identity

The public shell's Apple touch icon still pointed to an older column mark while
the favicon and app shell already used the legal quill. Rendered the canonical
SVG into a transparent 180×180 RGBA PNG with headless Chrome and updated the
touch-icon cache key. This removes the last visible fallback with a different
brand mark without adding an image dependency or replacing the SVG source.

Inspected the resulting raster: the quill is centered, legible, and retains
transparency. Added a regression for the PNG signature, dimensions, alpha
channel, and template URL version.

Validation: complete JavaScript suite 137/137; focused UI tests 42/42;
frontend static tests 11/11; Django check; design-token guard passes with one
known legacy occurrence in its approved baseline; `git diff --check`.

Visual score: mark consistency 10, small-format legibility 9. Next: continue
the required final-pass audits of history, settings, assistant loading/error,
and remaining keyboard paths; the overall objective remains open.

## Cycle 91 — settings provider flow and mobile select clarity

The settings audit found that the compatible-provider label was clipped at
390px, hiding the end of “LiteLLM, AirLLM ou local”. Shortened it to
“Compatível (LiteLLM, AirLLM, local)”; the full name now fits the mobile
select while preserving the supported integrations.

Added a real-route interaction to the browser audit: select the compatible
provider, verify required-field feedback and focus, enter dummy model/key/local
endpoint values, save, reload, and verify the selected provider, label, and
fields are restored. The audit explicitly asserts the key is absent from
`localStorage`, remains in this tab's `sessionStorage`, and no external request
is made. Values are test-only and never leave the browser.

Captured `/configuracoes/` in both themes at 1440x900, 1280x800, 1024x768,
768x1024, and 390x844. All ten views returned HTTP 200 with no horizontal
overflow, console errors, or failed requests. The mobile capture confirms the
short provider label fits and the key remains masked.

Validation: complete JavaScript suite 137/137; focused UI tests 42/42;
frontend static tests 11/11; Django check; design-token guard passes with one
known baseline occurrence; `git diff --check`.

Visual score: settings form clarity 9, mobile select readability 9, security
feedback 10, session restore 10. Next: continue the assistant end-to-end
keyboard/loading/error audit and any remaining responsive regressions; final
section-17 verification is still outstanding.

## Cycle 92 — assistant streaming and navigation regression pass — 2026-09-30

Re-ran the real-Chromium assistant lifecycle scenarios after the recent shell,
source-drawer, and settings work: navigating back during active streaming,
out-of-order navigation responses, complex Markdown with deferred source fade-in,
and interruption preserving both partial response and original question.

All four browser scenarios passed (4 passed, 22 intentionally filtered). No
production code change was needed; the source timeline and request ownership
remain consistent when users navigate or interrupt generation. The broader
suite remains green at 137/137 from Cycle 91, including settings, evidence,
security, and responsive checks.

Visual score: stream readability 9, interruption recovery 9, navigation state
integrity 9. Next: perform the complete cross-route/dual-theme audit for the
section-17 closeout, then fix any remaining issues it exposes; do not mark the
goal complete until that evidence is reviewed.

## Cycle 93 — cross-route dual-theme audit and legal-text alignment — 2026-09-30

The complete Chromium audit now includes 16 real routes/states × five
viewports × both themes (160 captures). Every route returned HTTP 200; both
manifests report zero horizontal overflow, console errors, failed requests, or
bad responses. Interaction checks cover command-palette navigation, search
keyboard order, long ementa disclosure, grouped source expansion, local-only
provider settings, and delete-dialog keyboard/focus behavior. All 34 original
baseline screenshots now have same-name after captures in both themes.

The focused norm-reading screenshot exposed legal text beginning with OCR
indentation whitespace, which made the first line visibly drift to the right
while later lines aligned at the card edge. Added a presentation-only trim to
the preview and full-text nodes in the existing legal-detail controller; the
stored source text and backend are unchanged. The browser audit asserts the
rendered text starts without whitespace and remains fully within its device
card. At 390px, Art. 1º's opening line now shares the same left edge as the
remaining lines.

Validation: full JavaScript suite 137/137; focused UI tests 42/42; frontend
static Python tests 11/11; Django system check; design-token guard passes with
one approved baseline literal; `git diff --check`. The new scroll-state captures
for `/normas/3/` pass in dark and light at all five viewport sizes.

Visual score: legal-text readability 9, cross-route consistency 9, theme parity
9, responsive coverage 10. Next: audit lower-page norm actions/timeline and
collection/history empty and populated states, then complete a final review of
keyboard/focus and performance. Section-17 completion is not yet established.

## Cycle 94 — history error wording and evidence interaction verification — 2026-09-30

Reviewed the reported connection warning and found the history-delete dialog
used connectivity-specific wording for every rejected deletion, including
authorization/server failures. Replaced it with a neutral recoverable message;
the conversation remains in place and the action can be retried. Added a
regression test simulating HTTP 403 and asserting that the UI does not claim
the browser is offline.

Re-verified the evidence groups: opening an individual law updates the
“Expandir restantes (n de total)” state, expand-all opens every group and
changes to “Recolher todas”, and manually closing a group restores the partial
state. The disclosure cards already fade/translate in on expansion and honor
reduced motion. The `Nova pesquisa` action already uses a lightweight inline
compose/pencil SVG consistent with a “new chat” affordance; Jurix’s bespoke
quill mark remains the brand icon rather than copying another product’s logo.

Validation: focused streaming/history suite 20/20; full JavaScript run had one
unrelated Chromium timeout in the mobile-sidebar test (25/26), then that exact
test passed on isolated rerun. Other real-browser scenarios in the full run,
including grouped evidence disclosure and legal-source interactions, passed.
`git diff --check` passed. Backend/model/RAG scope remains unchanged.

Visual score: history error clarity 9, evidence disclosure behavior 9, icon
consistency 9. Next: inspect lower-page norm actions/timeline and populated
history/collections states; investigate whether the lone mobile sidebar timeout
is environmental before closing out the final keyboard/focus pass. Section-17
completion is not established.

## Cycle 95 — history empty/populated states and norm action hierarchy — 2026-09-30

Cross-route captures exposed a real anonymous-history empty-state bug: an
actually empty history was presented as a failed search. The view now shows a
purposeful “Histórico vazio” state with a direct Assistente CTA; a real query
with no matches retains the distinct search-empty message. Added support for
the browser-native `search` event so clearing a `type=search` field refreshes
results. Browser inspection also showed anonymous conversation cards bypassed
the shared card interior, leaving text flush against their borders; their
markup now uses the existing padded card surface. The search action now stays
beside the query field on desktop and stacks on small screens.

The legal-detail action row had four uneven columns with two orphan buttons at
wide desktop sizes. It now uses a stable 3/2/1-column layout (desktop/tablet/
phone), with explicit 44px hit targets retained. Extended the actual Chromium
audit to inspect the lower action row and timeline, and to seed two sample
anonymous history conversations in an isolated browser context for responsive
rendering and Bag-of-Words search/clear checks. This sample does not write to
the application backend. Reviewed the 0-event norm case: the separate timeline
still presents dated corpus events, and the timeline cards remain readable at
390px.

Validation: full `npm test` passed, including all 26 real-Chromium flows;
focused history and norma UI suites passed (22 and 43 tests respectively);
frontend static Python tests 11/11; Django system check clean; `git diff
--check` clean. Dark/light browser captures passed for 20 history states (empty
and populated × five viewports × two themes), plus the norm action/timeline
scroll states at the same five viewports; zero navigation errors, console
errors, failed requests, bad responses, or horizontal overflow. A transient
automation-only key-combination mismatch was replaced with an explicit input
event for the Chromium harness, then the full captures passed.

Visual score: empty-state clarity 9, populated-card padding 9, search layout 9,
norm action rhythm 9, timeline phone readability 9. Next: continue populated
collection/history interaction review where authenticated data is available,
then run the complete keyboard/focus/reduced-motion/performance closeout across
all real routes. Section-17 completion is not established.
