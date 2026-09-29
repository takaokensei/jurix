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
