---
phase: quick
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - templates/index.html
autonomous: false
requirements: [QUICK-UI-REDESIGN]
must_haves:
  truths:
    - "Dashboard renders with earthy dark glassmorphism theme - deep charcoal backgrounds, muted forest greens, warm earth accent tones"
    - "All glassmorphism cards have backdrop-filter blur, semi-transparent backgrounds, subtle border glow, and elevated shadows"
    - "Typography uses Inter for UI text and JetBrains Mono for numeric/code values with proper weight hierarchy (300-800)"
    - "All interactive elements (buttons, tabs, inputs) have smooth hover/focus transitions and visual feedback"
    - "Layout uses generous spacing, proper visual hierarchy, and premium padding - no cramped or AI-slop feel"
    - "All existing JS functionality remains intact - charts, SSE updates, bot controls, tab switching, modals all work"
  artifacts:
    - path: "templates/index.html"
      provides: "Complete redesigned dashboard"
      contains: "backdrop-filter"
  key_links:
    - from: "templates/index.html CSS"
      to: "templates/index.html JS"
      via: "Element IDs and class names preserved for JS selectors"
      pattern: "getElementById|querySelector|className"
---

<objective>
Redesign the trading bot dashboard with a premium fintech glassmorphism dark earthy theme. This is a full structural CSS overhaul of templates/index.html - not just color variable swaps.

Purpose: Transform the dashboard from a generic/AI-slop look into a premium, polished fintech interface with earthy nature palette, glassmorphism depth, proper typography hierarchy, and refined spacing.

Output: Fully redesigned templates/index.html with overhauled CSS and refined HTML structure, all JS preserved.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@templates/index.html
@.planning/STATE.md

Key constraint from user memory: "Color-only changes are not enough for UI redesigns. Always address: glassmorphism (backdrop-filter: blur), border-radius, box-shadow, transitions/animations, typography weights, padding/spacing, button shapes, input styling, and scrollbar styling."

CRITICAL: All element IDs used by JavaScript (lines 1244-2728) MUST be preserved exactly. Class names referenced in JS must also be preserved. Only CSS styling, HTML structure/classes (non-JS-referenced), and visual presentation should change.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Overhaul CSS variables, base styles, and component design system</name>
  <files>templates/index.html</files>
  <action>
Rewrite the entire CSS section (lines 11-613) of templates/index.html with a premium fintech glassmorphism dark earthy theme. This is a FULL CSS rewrite, not incremental edits.

**Color palette (CSS custom properties):**
- --bg: deep charcoal-black with slight warm undertone (#090d0b or similar)
- --surface: translucent dark forest layers (rgba with 0.4-0.7 opacity for glass depth)
- --border: subtle earthy borders with low opacity greens/browns
- --text: warm off-white (#dce5d8 range), --text2: muted sage
- --green/--red: keep functional colors but refine saturation (less neon, more organic)
- --accent: warm earth tones (amber, terracotta, sage) for variety beyond green
- Add CSS variables for glass blur levels, glow intensities, animation timing

**Glassmorphism system (the core visual identity):**
- .glass class: backdrop-filter: blur(16-24px), semi-transparent bg, 1px border with rgba glow, layered box-shadows (inner highlight + outer depth)
- Cards: frosted glass with subtle top-edge highlight (inset shadow), hover state that lifts + increases glow
- Panels: slightly different glass opacity than cards for visual hierarchy
- Header: extra-strong blur (blur 32px+) for sticky overlay effect
- Modals: deep blur with dark overlay

**Typography hierarchy:**
- Already loading Inter + JetBrains Mono (keep CDN links)
- h1/headers: Inter 700-800, slightly larger sizes, letter-spacing: -0.02em for premium feel
- Labels: Inter 500, 10-11px, uppercase, letter-spacing: 0.08em
- Values/numbers: JetBrains Mono 600, tabular-nums for alignment
- Body text: Inter 400, 13px, line-height 1.6
- Muted/secondary: Inter 300-400, reduced opacity or --text2 color

**Component overhaul (every component class):**
- Cards (.card): 20px border-radius, 24px padding, glass bg, hover transform: translateY(-2px) with shadow increase, subtle gradient top border
- Buttons: pill shape (border-radius: 50px) for primary actions, 12px for secondary, smooth 0.25s transitions on hover/active, no harsh outlines
- Tab bar: glass background, active tab with bottom accent bar (not bg change), smooth sliding indicator if possible via CSS
- Tables: no visible row borders - use alternating row bg opacity, generous row padding (12px+), rounded corners on table container
- Inputs: dark glass bg, 12px radius, focus ring with green glow, no default outlines
- Badges: pill shape, backdrop-filter, subtle border, no heavy backgrounds
- Panels: 20px radius, glass bg, panel-header with bottom border separator
- Scrollbars: thin (5px), rounded thumb, earthy color

**Spacing and layout:**
- .page container: max-width 1400px, padding 28px, gap 24px
- Card grid: gap 20px, responsive columns (auto-fill, minmax(280px, 1fr))
- Section spacing: 28px between major sections
- Inner padding: 20-24px in cards/panels (not cramped 12px)

**Animations and micro-interactions:**
- @keyframes pulse for live indicators (already exists, refine timing)
- Hover transitions: 0.25s cubic-bezier(0.4, 0, 0.2, 1) on cards, buttons, tabs
- Focus states: soft green glow ring on inputs/buttons
- Active/pressed: slight scale(0.98) on buttons
- Toast: slide-in from right with fade
- Modal backdrop: smooth fade-in

**Start screen overlay:**
- Center the start-box with premium glass card treatment
- Larger padding (40px+), refined input/button styling
- Warning banner for live mode: red-tinted glass, not just colored bg

**Responsive:**
- Cards stack to single column below 768px
- Tab bar scrolls horizontally on mobile
- Header collapses gracefully (hide non-essential elements)
- Panels stack vertically below 1024px

CRITICAL PRESERVATION RULES:
- Keep ALL element IDs exactly as they are (id="equity", id="cash", id="pdt-display", etc.)
- Keep ALL class names that JavaScript references (check lines 1244-2728 for classList.add/remove, className, querySelector usage)
- JS-referenced classes to preserve: badge-running, badge-stopped, badge-idle, badge-starting, badge-stopping, badge-loss_limit_hit, badge-paper, badge-live, pdt-ok, pdt-warn, pdt-danger, tab, active, c-green, c-red, c-white, pos-row, order-row, toast, toast-error, flash-green, flash-red, start-box, kill-panel, etc.
- Keep the HTML structure order (header, tab-bar, tab-panes, modals) - CSS/class changes only
  </action>
  <verify>
    <automated>python -c "
import re
# Verify all JS-referenced IDs still exist
html = open('templates/index.html', encoding='utf-8').read()
critical_ids = ['equity','cash','daily-pnl','status-badge','pdt-display','live-price','live-change',
  'start-overlay','confirm-input','start-btn','logo-dot','sse-dot','last-update',
  'streak-banner','pdt-warning-banner','hdr-symbol','header-symbol',
  'tab-overview','tab-positions','tab-orders','tab-performance',
  'price-chart','rsi-chart','macd-chart','watchlist-body','news-list','trade-log',
  'paper-badge','live-badge','pdt-counter']
missing = [i for i in critical_ids if f'id=\"{i}\"' not in html]
assert not missing, f'Missing IDs: {missing}'
# Verify glassmorphism CSS exists
assert 'backdrop-filter' in html, 'No backdrop-filter found'
assert 'blur(' in html, 'No blur() found'
# Verify JS section intact
js_start = html.index('<script>')
assert 'function refreshUI' in html[js_start:], 'JS refreshUI function missing'
assert 'function switchTab' in html[js_start:], 'JS switchTab function missing'
print('All checks passed')
"
    </automated>
  </verify>
  <done>
- CSS section fully rewritten with premium glassmorphism dark earthy theme
- All glass effects (backdrop-filter, blur, translucent backgrounds) applied to cards, panels, header, modals
- Typography hierarchy uses Inter weights + JetBrains Mono properly
- All interactive elements have smooth hover/focus transitions
- Spacing is generous (20-28px gaps/padding), no cramped layouts
- All JS-referenced IDs and class names preserved
- Dashboard loads and all tabs render correctly
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>Complete dashboard UI redesign with premium fintech glassmorphism dark earthy theme. Full CSS structural overhaul including: glass card effects, earthy color palette, refined typography, hover animations, pill buttons, generous spacing, and polished component design.</what-built>
  <how-to-verify>
    1. Run `py server.py paper` (or just open templates/index.html directly if static preview works)
    2. Visit http://localhost:5000 in browser
    3. Check the start screen overlay - should have premium glass card feel
    4. After entering dashboard, verify:
       a. Overview tab: glass cards with hover lift effects, proper typography hierarchy, earthy color palette
       b. Price chart area: clean layout, glass panel, proper button styling
       c. Watchlist scanner: glass table with alternating rows, no harsh borders
       d. Bottom panels (News, Sentiment, Trade Log, Emergency): glass panels with proper spacing
       e. Tab switching works smoothly between Overview/Positions/Orders/Performance
       f. All badges (PAPER/LIVE, status, PDT) render with pill shapes and glass effects
    5. Check responsive: resize browser to mobile width - cards should stack, tabs should scroll
    6. Verify the overall feel is "premium fintech terminal" not "generic Bootstrap dashboard"
  </how-to-verify>
  <resume-signal>Type "approved" or describe specific areas that need adjustment</resume-signal>
</task>

</tasks>

<verification>
- Dashboard loads without console errors
- All 4 tabs render content correctly
- Bot start/stop controls function
- Chart.js and LightweightCharts render in their containers
- SSE connection establishes (green dot)
- No broken element references in JS console
</verification>

<success_criteria>
- Premium glassmorphism dark earthy theme fully applied - not a color swap but a structural overhaul
- Glass effects visible on all cards, panels, header, modals
- Typography hierarchy clear: headers bold, labels small/uppercase, values monospace
- All hover/focus transitions smooth
- All existing JS functionality preserved (charts, SSE, bot controls, tabs, modals)
- User approves the visual result at checkpoint
</success_criteria>

<output>
After completion, create `.planning/quick/260328-jal-redesign-dashboard-ui-with-premium-finte/260328-jal-SUMMARY.md`
</output>
