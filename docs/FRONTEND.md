# TaskVault — Design system & front-end (reference)

The whole front end is **server-rendered** (Django) and styled by three stylesheets loaded in this order by `templates/base.html` (after the vendored Font Awesome `vendor/fontawesome/css/all.min.css`):

1. `static/css/lowbid-tokens.css` — the palette: `:root` = the light « Papier » base values, redefined by the « Coffre » palette under `html[data-theme="dark"]` **and** on any `.theme-coffre` element;
2. `static/css/lowbid-components.css` — the `ui-` / `lb-` / `seg-` / `rcard` / `glass-` / `kanban-` / `cand-` vocabulary;
3. `static/css/tailwind.css` — **build artifact** (`npm run build:css`, input `static/css/tailwind.src.css`), loaded last so utilities win specificity ties.

Golden rules: components only read `var(--*)` (never a hardcoded colour); any new Tailwind class means rebuilding **and committing** `tailwind.css`; every static URL carries `?v={{ LOWBID_ASSET_VERSION }}` (30-day cache outside DEBUG), so any change to `lowbid-*.css` / `lowbid-*.js` (or a vendored file) means bumping `LOWBID_ASSET_VERSION` (default in `lowbid/settings.py`, override in `.env`). UI copy is English; the product name shown by the templates is « TaskVault » (titles, footer, wordmark) while file names and code identifiers stay `lowbid-*` / `Lowbid` / `LOWBID`.

---

## 1. Tokens (`lowbid-tokens.css`)

**The site is dark only**: `base.html` renders `<html data-theme="dark">` (plus `color-scheme: dark`) on every page, there is no toggle. The `:root` block holds the light « Papier » values as the base; the « Coffre » block `html[data-theme="dark"], .theme-coffre` redefines the same variables, so **Coffre is what renders everywhere** and `.theme-coffre` (landing band, escrow receipt) changes no colour today; it only adds `background: var(--bg-1); color: var(--text)`. The values below are the rendered Coffre ones.

**The look (« Vault »: the money is locked, and it shows).** A deep blue-steel canvas (`--bg-1` `#0A0D13`, darkening to `#05070B` through the fixed gradient layer in `base.html`) with a faint mint / cobalt glow (`--glow-1` / `--glow-2`, the two radial halos of that layer; the landing band adds its own `--glow-1` halo), machined surfaces (`--surface` `#10141C`) with a 1px hairline (`--border` `#222938`) and a faint inset top highlight + 1px drop (`--shadow`), steel-white text (`#E8EDF4`). Corners: 8px controls, 12px cards / panels, 16px dialog, 5px chips; no pills. **Ink** (`--ink` steel-white, `--on-ink` `#0A0D13` text on it) = an off-chain decision (primary button, active chip / filter tab / pager page); **Signal mint** (`--brand-500` `#34E5B0`) = money: a signature that moves funds (`.ui-btn-signal`, and automatically any `.ui-btn-primary[data-pay-step|data-fund|data-validate-submit]`), the done blocks of the escrow chain, the live dot, the filled `.ui-badge-brand` chip, the « Vault » half of the wordmark, the active nav underline, the accent icons (`--icon-accent`), the focus ring. Success is lime (`--success` `#A3E36A`) so it never reads as the accent. **Everything on chain is mono with tabular figures**: amounts (`|usdc_parts` = faint decimals), addresses, tx hashes, KPI values.

| Family | Variables | Role |
|--------|-----------|------|
| Signal (mint) | `--brand-500` `--brand-600` `--brand-700` `--brand-800` `--brand-hover` `--brand-soft` `--brand-ink` | The one accent, it means money. In Coffre `--brand-600/700` = `#34E5B0` (in Papier `--brand-700` `#0B6E52` is the mint-family text readable on paper), `--brand-800` `#7FF2CF`, `--brand-hover` `#5EEDC2`; `--brand-soft` = 13 % mint (chosen candidate, `.act` card, `tr.is-attn`, active tab tile); `--brand-ink` `#03150E` = text on a mint fill |
| Ink | `--ink` `--ink-hover` `--on-ink` `--icon-accent` `--rule` `--bevel` | `--ink` `#E8EDF4` / `--ink-hover` `#FFFFFF` / `--on-ink` `#0A0D13`: primary off-chain buttons, active states; `--icon-accent` = `--brand-500` in Coffre (graphite in Papier); `--rule` = the heavy top rule of a ledger line (`.ui-kpi-band`); `--bevel` (6 % white) = the top highlight of the brand mark |
| Brand RGB | `--brand-50-rgb` … `--brand-950-rgb` | `r g b` triplets of the mint family for Tailwind utilities such as `bg-brand-500/20` (see `tailwind.config.js`); Coffre overrides `--brand-500-rgb` only; no template uses one today |
| Secondary / accent | `--secondary-500` `--secondary-soft` `--accent-500` `--accent-soft` | Cobalt `#6F8FFF` (the ratings segment of `.ui-scorebar`) / orange `#FF8A5C` (defined, unused) |
| Status | `--success` `--warning` `--error` `--info` + `*-soft` (+ `--on-error`) | Light tint for text / icons (lime `#A3E36A`, `#FFC46B`, `#FF7B7B`, `#8EAAFF`) + the translucent fill of badges, alerts, toast icons |
| Badge text | `--ui-badge-ok-text` `--ui-badge-attn-text` `--ui-badge-danger-text` `--ui-badge-brand-text` `--ui-badge-info-text` | Text on the `*-soft` fills (= the status colours in Coffre; `brand` = `--brand-ink` on the mint fill) |
| Type | `--text-meta` 0.75rem (12px) · `--text-body` 0.875rem (14px) · `--text-heading` 0.97rem (≈15.5px) · `--text-display` 1.85rem (≈29.6px) · `--font-sans` · `--font-mono` | Four-step scale, system font stack (no web font) |
| Surfaces | `--bg-1` `#0A0D13` `--bg-2` `#080A10` `--bg-3` `#05070B` · `--surface` `#10141C` · `--surface-soft` `#181D28` · `--glass-bg` (= surface) `--soft-bg` (= surface-soft) | Canvas + the body gradient, cards, insets / chips / tiles |
| Text | `--text` (= `--text-main` `#E8EDF4`) `--muted` (= `--text-muted` `#98A2B4`) `--text-faint` `#7D8799` | Main / secondary / placeholder and trailing decimals |
| Borders & shadows | `--border` `--border-strong` `--glass-border` `--soft-border` `--hover-border` `--divider` `--shadow` `--glass-shadow` `--hover-shadow` `--shadow-pop` `--backdrop` `--focus-ring` | Hairlines (`#222938`, strong `#313A4C`, hover `#3B4559`, divider `#1B212D`; `--glass-border` / `--soft-border` = `--border`), `--shadow` / `--glass-shadow` = inset top highlight + 1px drop (cards, panels), `--hover-shadow`, floating panels (`--shadow-pop`: menus, toasts, modal, wallet dropdown), the modal backdrop, the focus ring (40 % mint) |
| Glows | `--glow-1` `--glow-2` | Mint / cobalt halos (7 %) of the body background layer; `--glow-1` also lights the landing band (`transparent` in Papier) |
| Radii | `--radius-lg` 16px · `--radius-md` 12px · `--radius-sm` 8px · `--radius-xs` 5px | Modal · cards, panels, toasts, menus, step cards · buttons, inputs, tabs, tiles · badges, tags, prices, identicons |
| Navbar | `--nav-bg` `--nav-border` `--nav-link-hover-bg` `--nav-active` | Translucent canvas bar (12px backdrop blur) with a hairline; the links sit in a surface block; `--nav-active` = `--surface-soft` (the active link's tile) |
| Rows | `--row-hover` | Table / list row and secondary-button hover |
| Layout | `--tabbar-h` | Declared in `lowbid-components.css`: `0px`, `60px` below 1024px on `body.has-tabbar`; read by `.ui-sticky-actions` |

---

## 2. CSS vocabulary (`lowbid-components.css`)

### Surfaces & structure

| Class | Use |
|-------|-----|
| `.glass-card` | Card (surface, 1px hairline, `--shadow`, 12px radius; `--hover-border` + `--hover-shadow` on hover) |
| `.ui-panel` + `.ui-panel-head` `.ui-panel-title` `.ui-panel-sub` | Padded section (12px radius, `--shadow`); two consecutive panels space themselves |
| `.ui-page-header` + `.ui-page-title` `.ui-page-sub` `.ui-page-actions` | Page header (title + subtitle + buttons). Title: `--text-display`, 800 weight, −0.04em tracking. Only `projects/project_form.html` uses `partials/page_header.html`; the other pages write the same markup inline. Titles go through `\|underline_last` (`<span class="ui-title">…<span class="ui-underline">last</span></span>`, a no-op hook; `.ui-page-title .ui-title` wraps anywhere) |
| `.ui-underline` | Kept as a hook (no decoration); `.ui-dec` = faint decimals (from `\|usdc_parts`) |
| `.ui-section` + `.ui-section-head` `.ui-section-title` `.ui-section-sub` | h2 above a grid (landing, profile) — see `components/section_head.html` |
| `.ui-split` (+ `.is-even`) / `.ui-stack` | Two columns 3/2 (or 1/1) from 1024px, stacked below; vertical stack with a 1.25rem gap |
| `.ui-facts` | `<dl>` stat rows: label left, bold value right, one hairline per row (dashboard stats, funding totals) |
| `.ui-form-scope` | Declares an inline-size *container* so `.ui-sticky-actions` knows its width |

### Text

`.ui-meta` (12px muted) · `.ui-label` (11px uppercase label) · `.ui-link` (text-coloured, `--border-strong` underline that turns `--text` on hover) · `.ui-num` (**mono**, tabular figures) · `.text-muted` · `.text-strong` (+ `.hover:text-strong`) · `.ui-price` + `.ui-price-unit` (mono amount on a 5px `--surface-soft` chip, faint decimals via `\|usdc_parts`, `components/price.html`; inside `.ui-kpi-value` it is a bare figure) · `.ui-link-host` + `.ui-link-url` + `.ui-link-warn` (user-supplied external link: domain large, URL small, unknown-domain warning — `components/ext_link.html`) · `.font-mono` (also `code`, `kbd`).

### Forms

`.ui-field` · `.ui-input` `.ui-select` `.ui-textarea` (42px, surface fill, 8px radius; focus = `--ink` border + 3px `--focus-ring`; `aria-invalid="true"` → red border; `.ui-textarea` 120px min) · `.ui-help` · `.ui-error` · `.ui-form-grid` (1 column, 2 from 640px, `.ui-field-wide` for full width) · `.ui-input-group` + `.ui-input-addon` (the asset-code suffix of the task price) · `.ui-search` (a 40px input with the 30px ink-square `.ui-search-btn` submit at its end, optional `.ui-search-clear[data-search-clear]`, optional leading `<i>` icon) · `.ui-select-inline` (compact label + select). · `.ui-range` (a 44px-tall range slider, mint thumb, the filled part driven by `--range-pct`; the arbiter's split on `/litiges/`) + `.ui-split-preview` › `.ui-split-side` (`.ui-split-label`, `.ui-split-pct`, `.ui-split-amount`): the two-sided amount preview under it.

Server-side field errors from `Lowbid.api` land in `<span|p class="ui-error" data-error-for="<field>" hidden>` (add-task form: `title`, `price`, `tags`; apply form: `message`, `tags`; validate form: `note`; `_` for the rest). `<span class="ui-help" data-tags-help="<input id>">` turns into a live « n / 3 skills: a, b » counter (red above 3).

### Buttons

8px blocks. `.ui-btn` = surface with a hairline (secondary); `-primary` = **ink** (steel-white fill, dark text); `-signal` = **mint** (moves money; applied automatically to `-primary` buttons carrying `data-pay-step`, `data-fund` or `data-validate-submit`); `-ghost` = bare, muted; `-danger` = surface with red text, `-danger-solid` = red; sizes `-sm` (34px) / default 40px / `-lg` (46px), on coarse pointers 44px (`-sm` 40px); `-block`; `:active` nudges 1px down; `:disabled` / `[aria-disabled="true"]` / `.is-loading` fade to 50 % (an `<i class="fa-spinner">` spins). `.ui-copy-btn` (32px, icon only, `data-copy="…"`). `.lb-icon-btn` (38px, navbar menu toggle).

### Badges, tags, alerts, states

| Class | Use |
|-------|-----|
| `.ui-badge` + `-ok` `-attn` `-danger` `-info` `-brand` `-neutral` | 5px chip, soft tint with light text (`badge_class` on the models). Task: Open `info`, Taken `brand`, Delivered `attn`, Paid `ok`. Project: Draft `neutral`, Funded `ok`, Closed `brand`. Application: Pending / Not selected `neutral`, Chosen `ok`. Escrow: created `neutral`, deployed / funded `info`, delivered / approved `attn`, released / paid `ok`, failed `danger`. **`.ui-badge-brand` is the FILLED mint chip** (« Recommended », « Chosen » in the candidates list, « Applied » on the kanban, the dashboard to-do count); `.ui-badge-ok.badge-validated` = « Validated » (`badge-validated` is a hook, no CSS) |
| `.ui-dot` (`.is-open` `.is-taken` `.is-delivered` `.is-paid`) | 7px square coloured with `currentColor` (info / mint / warning / success) — the kanban column titles |
| `.ui-live` + `.ui-live-dot` | Mono « live » with a blinking mint dot (`[data-live-dot]` on the task page, shown after the first successful poll) |
| `.ui-tag` (+ `.is-match`) | Skill chip (5px) on `--surface-soft`; `a.ui-tag` / `button.ui-tag` get a hover border; `.is-match` (asked by the task / the active filter) = ink chip |
| `.ui-chip-row` | Row of filter chips that **wraps at every width** (nothing hidden off-screen); its tags are 32px, surface + hairline, the active one ink (popular skills on the project list) |
| `.ui-alert` + `-ok` `-attn` `-danger` `-info` | Inline message with a leading `<i>` (Django messages in `base.html`, payment errors `[data-last-error]`, « Funds released … Task paid … ») |
| `.empty-state` + `-icon` `-title` `-desc` | Centred empty state: icon tile, bold title, muted line, ink CTA — see `components/empty_state.html` |
| `.ui-progress` (+ `.is-ok`) `> span` | 6px bar, mint fill (lime with `.is-ok` at 100 %), width inline — paid tasks on the project card |

### KPI

```html
<section class="ui-kpi-band" aria-label="Key figures">         <!-- 2 columns, 4 from 768px -->
  <a href="…" class="ui-kpi-tile is-link">
    <span class="ui-kpi-head"><span class="ui-kpi-label">Total budget</span><span class="ui-kpi-icon" aria-hidden="true"><i class="fa-solid fa-coins"></i></span></span>
    <span class="ui-kpi-value" data-kpi-total>1,200<span class="ui-dec">.00</span><span class="ui-price-unit">USDC</span></span>
    <span class="ui-kpi-hint ui-meta">3 fixed-price tasks</span>
  </a>
</section>
```
A ledger line, not boxes: heavy `--rule` top border, hairline bottom, transparent tiles, values mono 1.35rem. → `components/kpi.html`. The dashboard narrows it with `!grid-cols-2 !gap-3`.

### Navigation

| Class | Use |
|-------|-----|
| `.lb-nav` `.lb-nav-inner` `.lb-brand` `.lb-brand-mark` `.lb-brand-name` `.lb-brand-accent` `.lb-nav-links` `.lb-nav-link.is-active` `.lb-nav-actions` | Sticky bar (`partials/navbar.html`), a 3-column grid (72rem, 80rem from 1536px). Left: the vault-door mark (inline SVG stroked in `currentColor` = mint, on a 1.9rem steel plate with a `--bevel` highlight, turns 90° on hover) + the wordmark `Task<span class="lb-brand-accent">Vault</span>` (« Vault » in mint) + a mono network badge (from 640px). Centre, from 1024px: the links in a surface block (active link = `--nav-active` tile, `--text` label, 2px mint inset underline, mint icon, `aria-current="page"`; labels hidden between 1024 and 1199.98px). Right: wallet chip + menu toggle. Links flagged `wallet` in `NAV_LINKS` are shown only to a signed-in wallet |
| `.lb-mobile-nav` (`#lb-mobile-nav[hidden]`, toggled by `[data-nav-toggle][aria-controls]`) | Drop-down menu under the bar, below 1024px |
| `.lb-wallet-btn` (+ `.is-connected`) `.lb-wallet-dot` `.lb-wallet-menu` `.lb-wallet-dropdown` `.lb-dropdown-item` | « Connect wallet » (`[data-wallet-connect][data-next]`, « wallet » hidden below 640px) = ink block; the connected chip (`summary` of `details.lb-wallet-menu`) = surface block with the pixel identicon, a lime dot, the short address (hidden below 400px) and a chevron, opening the `.glass-card` dropdown (identity, « Dashboard », « My public profile », « Copy address », « Log out » POST form) |
| `.lb-tabbar` + `.lb-tab` (+ `.is-active` `.is-primary`) | Fixed bottom tab bar on `--surface`, below 1024px, **signed-in only** (`body.has-tabbar`, `partials/tabbar.html`, fed by `NAV_LINKS` `short` labels: Projects · Board · Create (`is-primary`, mint tile) · My projects · Home); the active tab's icon sits in a `--brand-soft` tile, in mint |
| `.seg-tabs` + `.seg-tab.is-active` | Filter tabs (In progress / Closed / All on the list and on My projects): 36px surface blocks, the active one ink; full width below 480px |
| `.ui-toolbar` `.ui-toolbar-grow` `.ui-toolbar-end` | List toolbar (search · tabs · sort · count); below 480px `.ui-toolbar-end` takes the full width |
| `.ui-pager` `.ui-pager-count` `.ui-pager-nav` `.ui-pager-btn` `.ui-pager-num.is-active` | Pagination (36px blocks, active page ink); numbers hidden below 480px — see `components/pager.html` |

```html
<form method="get" class="ui-toolbar" role="search" aria-label="Search and filter projects">
  <div class="ui-search ui-toolbar-grow">
    <input type="search" name="q" value="{{ q }}" class="ui-input" placeholder="Search a project, a task, a skill…" aria-label="Search">
    {% if q %}<button type="button" class="ui-search-clear" data-search-clear aria-label="Clear search"><i class="fa-solid fa-xmark"></i></button>{% endif %}
    <button type="submit" class="ui-search-btn" aria-label="Search"><i class="fa-solid fa-magnifying-glass"></i></button>
  </div>
  <nav class="seg-tabs" aria-label="Filter projects">…</nav>
  <div class="ui-toolbar-end">
    <label class="ui-select-inline"><span class="ui-meta"><i class="fa-solid fa-arrow-down-wide-short"></i><span class="sr-only">Sort</span></span><select name="sort" class="ui-select" data-auto-submit>…</select></label>
    <span class="ui-meta whitespace-nowrap" data-result-count>2 projects · 5 open tasks</span>
  </div>
</form>
```

### Menus & modals

```html
<details class="ui-menu">
  <summary class="ui-btn" aria-label="More actions"><i class="fa-solid fa-share-nodes"></i><span class="hidden sm:inline"> Share</span></summary>
  <div class="ui-menu-panel">                              <!-- .is-start to align it left -->
    <button type="button" class="ui-menu-item" data-share="…"><i class="fa-solid fa-share-nodes"></i> Share this project</button>
    <button type="button" class="ui-menu-item" data-copy="…"><i class="fa-regular fa-copy"></i> Copy link</button>
    <div class="ui-menu-sep"></div>
    <a class="ui-menu-item" href="…"><i class="fa-solid fa-id-badge"></i> Company profile</a>
  </div>
</details>
```
The menu opens without JS; `lowbid-ui.js` closes it on outside click and `Escape`, and flips the panel to `.is-start` when it would spill past the left edge. Also defined: `.ui-menu-label`, `.ui-menu-item.is-active`.

```html
<dialog class="ui-modal is-danger">                    <!-- native top layer; blurred --backdrop -->
  <form method="dialog" class="ui-modal-card">          <!-- 440px max, 16px radius -->
    <div class="ui-modal-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
    <h2 class="ui-modal-title">Delete this task?</h2>
    <p class="ui-modal-body">"Landing page" will be removed from the project, with its applications.</p>
    <div class="ui-modal-actions"><button value="cancel" class="ui-btn ui-btn-ghost">Keep</button><button value="ok" class="ui-btn ui-btn-danger-solid">Delete</button></div>
  </form>
</dialog>
```
The global confirm modal `#lb-confirm` (`partials/modal.html`, included by `base.html`, with `[data-modal-title]` `[data-modal-body]` `[data-modal-icon]` `[data-modal-cancel]` `[data-modal-ok][data-autofocus]`) is driven by `Lowbid.confirm()`; for a custom modal: `Lowbid.modal.open("#id")` / `close`.

### Lists, rows, tables

| Class | Use |
|-------|-----|
| `.ui-list` + `.ui-list-row` + `.ui-rank` | Vertical list separated by `--divider` hairlines (rows 48px min); `.ui-rank` is a 32px 8px-radius tile with the rank; `a.ui-list-row` is hoverable |
| `.rcard` | **Mandatory wrapper around a `<table>`**; every `<td data-label="Column">`; `th/td.ui-col-end` right-aligns; `tr.is-attn` gets `--brand-soft` (project table: a delivered task, for the company; My projects: a project with a delivery to validate or candidates to choose). Below 720px of **container** width the table becomes stacked cards (no horizontal scroll, empty cells hidden); `td.is-stack` puts the label above a multi-block cell (title + tags + description). Used by the project's task table (`.task-row[data-task-id][data-status]`, `projects/_task_row.html`), My projects and the profile |
| `.project-card` | `.glass-card` project card on the list and the landing (1px lift on hover) — `projects/_project_card.html` |

```html
<div class="rcard" data-tasks data-count="1"><table>
  <thead><tr><th>Task</th><th class="ui-col-end">Price</th></tr></thead>
  <tbody><tr class="task-row" data-task-id="12" data-status="open"><td data-label="Task" class="is-stack">…</td><td data-label="Price" class="ui-col-end ui-num">{% include "components/price.html" with amount=task.price %}</td></tr></tbody>
</table></div>
```

### Task board components

**Candidate row + score bar** (`projects/_candidates.html`, also returned as `html` by `candidats.json` and swapped in place):

```html
<div class="ui-list" data-candidates data-count="2" data-task="12">
  <div class="ui-list-row cand-row" data-app-id="7" data-freelancer="G…">    <!-- + .is-chosen / .is-rejected -->
    <span class="ui-rank" data-rank>1</span>
    <div class="flex-1 min-w-0">
      …{% include "components/wallet.html" %}…
      <span class="ui-badge ui-badge-ok badge-validated" data-badge="valide"><i class="fa-solid fa-circle-check"></i> Validated</span>
      <span class="ui-badge ui-badge-brand" data-recommended><i class="fa-solid fa-star"></i> Recommended</span>
      …message, tags, history, time-ago…
      <div class="ui-scorebar" aria-hidden="true">
        <span class="ui-scorebar-seg is-history" style="width: 40.0%"></span>
        <span class="ui-scorebar-seg is-rating" style="width: 40.0%"></span>
        <span class="ui-scorebar-seg is-skills" style="width: 10.0%"></span>
      </div>
      <span class="ui-meta ui-num"><strong class="text-strong" data-score="90.0">90.0</strong> / 100</span>
    </div>
    <button type="button" class="ui-btn ui-btn-primary ui-btn-sm" data-choose="7" data-choose-url="/taches/12/choisir/7/" data-choose-label="Yanis"><i class="fa-solid fa-check"></i> Choose</button>
  </div>
</div>
```
`.ui-scorebar` is a 160px (max 45vw) track cut into **ten blocks** by a CSS mask; each segment's width is its points (out of 100): history mint, ratings `--secondary-500`, skills `--success`. `.cand-row` wraps: the text keeps 13rem and « Choose » drops under it, pushed to the end. `.cand-row.is-chosen` gets the `--brand-soft` background and a mint rank tile (badge « Chosen »), `.is-rejected` fades to 55 % opacity (badge « Not selected »). The legend under the list repeats the weights (History (40), Ratings (×8), Skills (20)) with square `.ui-scorebar-key.is-{history,rating,skills}` swatches in the segment colours. No candidate: `.empty-state[data-candidates][data-count="0"]`.

**Kanban** (`projects/board.html`, `projects/_board_card.html`):

```html
<div class="kanban-wrap"><div class="kanban" data-kanban>
  <section class="kanban-col" data-col="open" aria-labelledby="col-open">      <!-- open · taken · delivered · paid -->
    <header class="kanban-col-head"><h2 class="kanban-col-title" id="col-open"><span class="ui-dot is-open"></span>Open</h2><span class="kanban-count ui-num" data-col-count>3</span></header>
    <p class="kanban-col-hint ui-meta">Every open task, available to take.</p>
    <div class="kanban-cards">
      <article class="kanban-card glass-card is-applied" data-task-id="12" data-status="open">…title, price, project, tags, company, CTA or <span data-applied> badge…</article>
      <!-- or <div class="kanban-empty ui-meta">No open tasks yet.</div> -->
    </div>
  </section>
</div></div>
```
`.kanban-wrap` is a container (`container-name: kanban`): 4 columns, 2 below 1024px, and below 640px a flex row of 86 %-wide columns with horizontal **snap-scroll** — the one deliberate exception to "no horizontal scroll" (the page itself never overflows). Columns sit directly on the canvas (bold title + mono count); the cards are `.glass-card`. `.kanban-card.is-applied` marks a task the freelance already applied to (ink border).

**Star rating** (`.ui-stars`, in the validation form of the payment panel):

```html
<div class="ui-stars" role="radiogroup" aria-label="Rating from 1 to 5">     <!-- row-reverse: 1 first in the DOM, shown last -->
  <input type="radio" name="note" id="rate-1" value="1" data-rate="1"><label for="rate-1" title="1/5"><i class="fa-solid fa-star"></i><span class="sr-only">1 out of 5</span></label>
  …2, 3, 4, 5 (checked)…
</div>
<span class="ui-help" data-rate-help>5/5 — excellent</span>
```
Five visually hidden radios, the labels are 44px stars (`--border-strong`); hover and `:checked ~ label` paint them `--icon-accent` (mint); keyboard focus shows a ring; `[data-rate-help]` follows the choice (« 1/5 — poor » … « 5/5 — excellent »).

**Funding banner** (`projects/_funding_panel.html`, project page aside, `#funding-panel[data-pay-summary][data-mode="escrow|direct"]`, shown once a task is assigned, always in direct mode): title « Escrow funding » or « Direct payment USDC », a `.ui-facts` list (Tasks total `[data-pay-total]`, Locked or paid out / Paid out `[data-pay-funded]`, Paid to freelancers `[data-pay-paid]`), a `[data-pay-rows]` list with one row per non-open task (`[data-pay-task][data-escrow-status]`) with its escrow badge and every explorer link, and for the company in escrow mode the funding hint `[data-pay-status]` + `[data-pay-error]`. The « Fund the project » button (`.ui-btn-primary[data-fund][data-pending-url][data-loading-label]`, so mint) lives in the page header; when there is nothing to fund it is `disabled` with the hint as `title` and as a visible `[data-pay-hint]` line.

**Payment panel** (`payments/_escrow_panel.html`, rendered by `{% escrow_panel task wallet %}` in the task page aside for every non-open task: `section.glass-card.ui-receipt-card#escrow-panel[data-task][data-status][data-mode][data-escrow-status]` + `#paiement` anchor):

- the receipt `.ui-receipt.theme-coffre`: `.ui-receipt-head` (`.ui-receipt-title` « Escrow payment · task #N » or « Direct payment USDC · task #N » + « no escrow » `ui-badge-attn`; the escrow status badge `[data-escrow-badge]`), `.ui-receipt-amount` + `.ui-receipt-unit`, `.ui-receipt-sub`;
- `.ui-stepper` + `.ui-step.is-done/.is-current/.is-todo` `.ui-step-dot` (01, 02…) `.ui-step-label` — escrow: Escrow created · Funds locked · Delivered · Funds released; direct: Delivered · Paid;
- `<dl class="ui-receipt-rows" data-explorer-links>`: the freelance's address (link + copy), the live balance `<span class="ui-num ui-balance" data-usdc-balance="G…" data-watch>` (`.ui-balance.is-bumped` when it moves), then every stored hash and the contract, linked to stellar.expert;
- `.ui-receipt-body`: alerts `[data-platform-fallback]` (company, no platform address) and `[data-last-error]` (vendor / Horizon message, or the pending-hash info), then `[data-pay-action]` with one block depending on `next_action()`: the « paid » alert, the rating form `#validate-panel` (`#validate-form[data-validate][data-validate-url]`, `.ui-stars`, `#validate-comment`, `[data-validate-submit]` « Validate and release … » / « Validate and pay … »), the delivery form `#deliver-panel` (`#deliver-form[data-pay-form]`, `#deliver-link`, `[data-pay-step][data-deliver]`, with a `data-confirm-*` prompt in direct mode), a single step button `[data-pay-step][data-prepare-url]`, or a waiting `ui-alert-info` for the other party;
- `[data-pay-trustline]` « Add the USDC trustline » (ghost, small) for the two parties (hidden for native XLM).

### Trust network

One-hop badges (see `docs/PRODUCT.md` § Trust network). Colours come from `var(--*)` only (section "Trust network" of `lowbid-components.css`).

| Class | Role |
|-------|------|
| `.ui-netbadges` | inline wrapper, `data-network="strong\|weak\|following"` |
| `.ui-netbadge.is-strong` | "Yanis recommends" (someone you follow recommends this wallet) |
| `.ui-netbadge.is-weak` | "Followed by Yanis" (someone you follow follows this wallet) |
| `.ui-netbadge.is-following` | "Following" (you follow this wallet) |
| `.cand-row.is-network` / `.cand-row.is-network-strong` | light highlight on a candidate row (weak or following / strong). Never changes the order |
| `.ui-network-panel` › `.ui-network-counts` › `.ui-network-count` (`-value`, `-label`), `.ui-network-known`, `.ui-network-actions`, `.ui-network-form` (`-foot`), `.ui-network-counter` (`.is-near`, `.is-over`), `.ui-network-quote` | profile block `#network-panel` |
| `.ui-network-feed` › `.ui-network-feed-item` (`.is-recommendation`, …) › `.ui-network-feed-icon`, `.ui-network-feed-body`, `.ui-network-feed-time` | dashboard block `#network-feed` "In your network" |

**Badges** → `components/network_badges.html` (the only way to render them):

```html
<span class="ui-netbadges" data-network="strong">
  <span class="ui-badge ui-netbadge is-strong" data-network-badge="recommends" title="Recommended by Yanis"><i class="fa-solid fa-user-group" aria-hidden="true"></i> Yanis recommends</span>
  <span class="ui-badge ui-netbadge is-following" data-network-badge="following" title="You follow this wallet"><i class="fa-solid fa-check" aria-hidden="true"></i> Following</span>
</span>
<!-- weak: <span class="ui-badge ui-netbadge is-weak" data-network-badge="followed-by" title="Followed by …"><i class="fa-solid fa-user-plus"></i> Followed by Yanis</span> -->
```
Strong when recommenders exist, else weak when followers exist; "Following" is added whenever the viewer follows the wallet. Nothing at all for an anonymous viewer or your own wallet.

**Profile panel** (`dashboard/profile.html`, driven by `lowbid-network.js`, whose header is the reference; `net` = `network.services.profile_network(...)`):

```html
<section id="network-panel" class="ui-panel ui-network-panel">
  <ul class="ui-network-counts">
    <li class="ui-network-count"><span class="ui-network-count-value" data-followers-count>3</span><span class="ui-network-count-label">Followers</span></li>
    <li class="ui-network-count"><span class="ui-network-count-value" data-following-count>1</span><span class="ui-network-count-label">Following</span></li>
    <li class="ui-network-count"><span class="ui-network-count-value" data-recommendations-count>1</span><span class="ui-network-count-label">Recommendations</span></li>
  </ul>
  {% include "components/network_badges.html" with signal=net.signal %}
  <p class="ui-network-known" data-known-followers>Followed by 1 people you follow: <strong>Yanis</strong></p>
  <div class="ui-network-actions">                       <!-- only when net.can_act -->
    <button type="button" class="ui-btn ui-btn-primary" data-follow data-follow-url="…/suivre/" data-unfollow-url="…/ne-plus-suivre/" data-following="0" data-name="Chloé" aria-pressed="false"><i class="fa-solid fa-user-plus"></i> Follow</button>
    <button type="button" class="ui-btn" data-recommend data-recommended="0" aria-controls="recommend-form" aria-expanded="false"><i class="fa-solid fa-user-group"></i> Recommend</button>
    <button type="button" class="ui-btn ui-btn-ghost" data-unrecommend data-unrecommend-url="…/retirer-recommandation/" data-name="Chloé" hidden>Withdraw</button>
  </div>
  <form id="recommend-form" class="ui-network-form" hidden>
    <label class="ui-label" for="recommend-message">Your recommendation (optional)</label>
    <textarea id="recommend-message" class="ui-textarea" maxlength="280" placeholder="What did they do well?"></textarea>
    <div class="ui-network-form-foot">
      <span class="ui-network-counter" data-recommend-counter>0 / 280</span>
      <button type="submit" class="ui-btn ui-btn-primary" data-recommend-submit data-recommend-url="…/recommander/">Publish</button>
    </div>
  </form>
  <ol id="recommendations" class="ui-timeline">…one .ui-timeline-item per recommendation (author wallet chip, .ui-network-quote, [data-time-ago])…</ol>
</section>
```
The Follow button swaps to `.ui-btn.is-following` "Following" in place; recommend / withdraw update the counters, toast, then reload the page for the list.

### Timeline, "what's next"

```html
<ol class="ui-timeline">
  <li class="ui-timeline-item is-ok"><span class="ui-timeline-dot" aria-hidden="true"><i class="fa-solid fa-money-bill-transfer"></i></span>
    <div class="ui-timeline-body"><a href="…" class="ui-timeline-title">Payment received — "Landing page" (300.00 USDC)</a><div class="ui-timeline-time"><span data-time-ago="2026-10-24T21:00:00+00:00">Oct 24 21:00</span></div></div></li>
  <li class="ui-timeline-item is-brand">…</li>      <!-- is-brand = mint dot · is-ok = lime · is-danger = red (a dispute) · none = neutral (is-muted: defined, unused) -->
</ol>
```
Used by the dashboard activity (`#activity`), the profile ratings and the project form aside.

```html
<a href="…" class="ui-next-card act">                    <!-- act = your move · wait = someone else's · done -->
  <span class="ui-next-kicker"><span class="ui-next-dot"></span>Applications</span>
  <div class="ui-next-row"><div class="min-w-0"><p class="ui-next-headline">Choose a freelancer for "Freighter integration"</p><p class="ui-next-body">2 applications</p></div><span class="ui-btn ui-btn-sm ui-btn-primary">Choose</span></div>
</a>
<div class="ui-next-list" data-todo-list>…several cards…</div>
```
`.act` = `--brand-soft` fill + mint border, ink dot; `.wait` = info dot; `.done` = success dot. → `components/next_card.html` (the dashboard's to-do list `#todo`, the project page « To validate » panel).

### Wallet (identicon + address)

```html
<a href="{% url 'dashboard:profile' addr %}" class="ui-wallet is-stacked" data-identicon="{{ addr }}" title="{{ addr }}">
  <span class="ui-identicon is-lg" style="{{ addr|hue }}" aria-hidden="true"></span>   <!-- 24px · is-lg 44px · is-xl 64px -->
  <span class="ui-wallet-text"><span class="ui-wallet-name">Yanis</span><span class="ui-wallet-addr">GABC…WXYZ</span></span>
</a>
<button type="button" class="ui-copy-btn" data-copy="{{ addr }}" aria-label="Copy address"><i class="fa-regular fa-copy"></i></button>
```
The identicon is a **mirrored 5×5 pixel grid** (one hue from the address + Signal mint, read from `--brand-500`), painted by `lowbid-ui.js` as an SVG `background-image` on the `.ui-identicon` inside every `[data-identicon]` (or on the element itself); before JS it is a plain `--surface-soft` square. The `|hue` style it receives (`--id-a` / `--id-b`) is read by no CSS. → `components/wallet.html`.

### Sticky actions & misc

- `.ui-sticky-actions`: right-aligned row on wide screens; below 640px of container width (it needs a `.ui-form-scope` ancestor) it becomes a surface bar stuck to the bottom, above the tab bar (`--tabbar-h`, + safe area), with stretched buttons. Used by the project form, the add-task form, the apply form and the payment panel's deliver / validate forms.
- `.lb-toast-container` (`#lb-toasts`, top-end, full width below 640px) › `.lb-toast[data-type]` (`.lb-toast-icon`, `.lb-toast-body` › `.lb-toast-title` + `.lb-toast-message`, `.lb-toast-close`, `.is-leaving`): toasts (`Lowbid.toast`).
- Landing (`templates/core/landing.html`): `.lb-hero-band.theme-coffre.lb-story[data-story]` (full-bleed band without horizontal overflow: `box-shadow` + `clip-path`, a `--glow-1` halo at 72 % / 38 %) is ONE scroll track › `.lb-story-grid[data-story-grid]` (grid areas hero / scene / flow; from 1024px two columns `1.15fr 1fr`, the scene spans both rows) › `.lb-hero[data-story-hero]` (`.lb-kicker`, `.lb-hero-title` with a mint `.lb-hero-accent` span, `.lb-hero-sub`, `.lb-hero-cta` with a `.ui-btn-primary.ui-btn-signal.ui-btn-lg` + a transparent secondary, `.lb-hero-stats[data-landing-stats]`) · `.lb-story-flow` › `.lb-story-intro` (`.lb-section-title`, `.lb-story-sub`) + `ol.lb-story-steps` › `.lb-step[data-story-step]` × 4 (step 3 `.is-signal` = mint card; `.lb-step-head` / `-title` / `-desc` / `code.lb-step-call`) · `.lb-scene-wrap` (sticky: 44vh opaque strip at `top: 3.5rem` below 1024px, full height at `top: 5rem` from 1024px; `aria-hidden`) › `.lb-scene[data-scene]` (geometry in `--w` / `--d` / `--h` / `--n`, `--scene-scale` 0.78 below 1024px, 0.62 below 400px) › `.lb-cube[data-cube]` › `.lb-slab[data-slab]` (one per `core.views.STORY_TASKS` worked example, `--i` = index) › `.lb-face.is-{front,right,back,left,top,bottom}` (front: `.lb-face-no`, `.lb-face-title[data-face-title]`, `.lb-face-price`, `.lb-face-lock[data-face-lock]`, `.lb-face-glow[data-face-glow]`; right: `.lb-face-release` + `.lb-face-release-sub`, both `[data-face-release]`) and `.lb-bids` › `.lb-bid[data-bid="chosen|other"]` (`.is-chosen` on the first; identicon, `.lb-bid-name` (ellipsis at 7rem), `.lb-bid-score`); `.lb-scene-caption` (`[data-scene-no]` + `[data-scene-caption]`). The cube is CSS 3D only; the CSS is also the no-JS pose (cube closed, padlocks on, bids hidden). The copy follows `payment_mode` (`{% with escrow=payment_mode|default:"escrow" %}`): escrow = kicker « Soroban · Trustless Work », steps Split · Apply · Lock (`deploy · fund`) · Deliver, release, faces « RELEASED » / « ESCROW · TRUSTLESS WORK »; direct = « direct payment », steps Split · Apply · Work (`off-chain`) · Deliver, pay, faces « PAID » / « DIRECT · STELLAR ».
- `lowbid-landing.js` (anime.js v4, `vendor/anime.umd.min.js`, global `anime`) runs four timelines, each `autoplay: anime.onScroll({target, enter, leave, sync: true})` with `composition: "none"` (the latest scrubbed timeline wins the cube): 01 (trigger: the hero, from scroll 0 until it has left the viewport — the cube turns and its slabs pull apart), 02 (step card 2 — three applications per task slide in, the chosen one stays), 03 (card 3 — slabs close ranks, mint frame + padlock), 04 (card 4 — the cube turns to its RELEASED / PAID face). A card's window runs from its top at the viewport bottom to its centre at the viewport centre (below 1024px: to its top at 55 % of the viewport); from 1024px `.lb-story-steps` has a 38vh gap (+ `4vh 0 36vh` padding) so the windows never overlap. The script adds `.lb-story.is-live` (inactive steps dim to 50 %), toggles `.lb-step.is-active` and writes the chapter number + the active card's `.lb-step-title` into the caption. Only transforms and opacity are animated, on `.lb-cube`, `.lb-slab`, `.lb-bid` and the `[data-face-*]` spans — do not add CSS transforms or transitions to them beyond the existing no-JS pose. `prefers-reduced-motion` parks chapters 01–03 at their end (the locked pose, chapter 03 active). Without the section or the vendor bundle nothing runs.
- `.lb-tape` (ledger tape under the band, only when there are events: the latest real tx events from `core.views.ledger_tape()`, repeated by `tape_loop()`): a full-bleed mint band › `.lb-tape-track` (60s marquee, paused on hover) › two `ul.lb-tape-list` copies (the second `aria-hidden`) › `.lb-tape-item` (`b` label, title · amount, `.lb-tape-tx`). Below it: a `.ui-section` of project cards and a `.ui-kpi-band` of key facts.
- Receipt: `.ui-receipt` (used inside `.theme-coffre` by the escrow panel) › `.ui-receipt-head` (dashed bottom rule) / `-title` / `-amount` / `-unit` (mint) / `-sub` / `-rows`; the escrow panel is `.glass-card.ui-receipt-card` (no hover change) = receipt + `.ui-receipt-body`. `.ui-stepper` is a row of equal blocks: done = mint fill, current = ink outline + blinking mint dot, todo = dashed.
- Global keyboard focus: 3px `--focus-ring` (mint) box-shadow on `:focus-visible` of links, buttons, inputs, `summary` and `[tabindex]`. `@media print` hides the nav, tab bar, toasts, sticky actions and footer. `prefers-reduced-motion` drops the transitions of toasts, tabs, buttons, cards and the brand mark and the animations of the modal, menus, skeleton, live dot, stepper dot and tape.
- Present in the CSS but not used by the current templates: `.glass-soft`, `.ui-icon-tile`, `.ui-mono`, `.ui-num-strong`, `.ui-status`, `.seg-count`, `.seg-radio`, `.ui-skeleton` / `.ui-skeleton-line` (+ `.w-1/2` `.w-1/3` `.w-3/4`), `.ui-sparkline` / `.ui-sparkline-meta` (+ `Lowbid.sparkline`), `.ui-kpi-band.is-3`, `.ui-price.is-bare`, `.ui-timeline-item.is-muted`, `.ui-menu-label`.

---

## 3. Template components (`templates/components/`)

| Include | Parameters | Renders |
|---------|-----------|---------|
| `components/wallet.html` | `address` (required), `name`, `label` (kicker before the name / address), `size="lg\|xl"`, `keep` (chars kept on each side, 4), `copy=True`, `nolink=True`, `you=True` (« you » badge) | Identicon + short address (`.is-stacked` with a name), linked to `dashboard:profile` unless `nolink` |
| `components/status_badge.html` | `obj` (any object with `badge_class` / `status_label`: Project, Task, Application), `live=True` (adds `data-status-badge`) | `.ui-badge` of the status |
| `components/tags.html` | `tags`, `linked=True` (each tag filters the project list), `matched` (set → `.is-match`), `class` | Flex row of `.ui-tag` |
| `components/kpi.html` | `label`, `value` (pre-formatted), `unit`, `hint`, `icon`, `href`, `attr` (e.g. `"data-kpi-count"`) | KPI tile, an `a.is-link` if `href` |
| `components/price.html` | `amount` (Decimal or None → `—`), `size` (class), `attr` | `.ui-price` + `\|usdc_parts` + `.ui-price-unit` (asset code) |
| `components/empty_state.html` | `icon` (default `fa-inbox`), `title`, `desc`, `cta_href`, `cta_label`, `cta_icon`, `class` | `.empty-state.glass-card` |
| `components/pager.html` | `page` (Django `Page`) | Pagination keeping the query string (`{% qs %}`), elided range (`.ui-pager-gap`, hidden with the page numbers under 480px), nothing when one page |
| `components/next_card.html` | `tone="act\|wait\|done"` (default `wait`), `kicker`, `headline`, `body`, `href`, `cta`, `icon` | "What's next" card (primary CTA only for `act`) |
| `components/section_head.html` | `title`, `sub`, `icon`, `link_href`, `link_label` (default « View all ») | Section title + link |
| `components/ext_link.html` | `info` (required: `projects.services.link_info(url)` computed by the view / inclusion tag / `delivery_history` row — `{url, href, host, display, trusted}`), `label` (text before the link, e.g. "Full deliverable"), `attr` (a data attribute put on the `<a>`, e.g. `"data-delivery-link"`, `"data-source-link"`), `size="sm"` (compact: timelines, receipt rows) | Every user-supplied link (delivery link, full deliverable): `.ui-ext-link` › `a.ui-ext-anchor` (`target="_blank"`, exactly `rel="noopener noreferrer nofollow ugc"`) with the domain in `.ui-link-host` (bold, large) and the full URL in `.ui-link-url` (mono, muted, one line, ellipsis), then `.ui-link-warn[data-untrusted-host]` "Unknown domain — open with care" when `info.trusted` is false (`LOWBID_TRUSTED_LINK_HOSTS`, docs/PRODUCT.md R43–R44). No `href` (non-http(s) value) → plain text. Never write a raw `<a href="{{ task.delivery_link }}">` |
| `components/network_badges.html` | `signal` (a `network.services.NetworkSignal` or None: `row.network`, `project.company_signal`, `net.signal`) | `.ui-netbadges` with the strong (`Yanis recommends`) or weak (`Followed by Yanis`) badge, plus `Following`; nothing when the signal is falsy |
| `partials/page_header.html` | `title`, `subtitle`, `actions` (safe HTML) | Page header (the title goes through `\|underline_last`) |
| `partials/navbar.html` / `partials/toasts.html` / `partials/modal.html` | — | Included once by `base.html`; `partials/tabbar.html` only when `wallet_address` |

Task-board partials (not generic, but reusable within `projects`): `_project_card.html` (list / landing card), `_task_row.html` (task table row), `_task_form.html` (inline add-task form, `#task-form-panel`), `_candidates.html` (ranked candidates), `_funding_panel.html` (project funding banner), `_board_card.html` (kanban card).

`base.html` blocks: `title`, `meta_description`, `extra_head`, `body_class`, `content`, `extra_js`. `<main id="app-main">` is `max-w-6xl 2xl:max-w-7xl` (72rem / 80rem). Context available everywhere: `request`, `wallet_address`, `wallet_user`, `nav_links`, `STELLAR_NETWORK`, `STELLAR_NETWORK_PASSPHRASE`, `STELLAR_HORIZON_URL`, `STELLAR_SOROBAN_RPC_URL`, `asset_code`, `asset_issuer`, `asset_native`, `payment_mode`, `LOWBID_ASSET_VERSION`, `messages`.

### Filters and tags (`{% load lowbid_extras %}`)

| | Example | Result |
|--|---------|--------|
| `short_addr` | `{{ addr\|short_addr }}` / `{{ addr\|short_addr:6 }}` | `GABC…WXYZ` (tolerates an empty `keep`) |
| `usdc` | `{{ x\|usdc }}` / `{{ x\|usdc:"" }}` / `{{ x\|usdc:asset_code }}` | `1,234.50 USDC` (unit = the configured asset) / `1,234.50`; `—` when empty |
| `usdc_parts` | `{{ x\|usdc_parts }}` | `1,234<span class="ui-dec">.50</span>`: the bare number with faint decimals (prices, receipts, KPI values); `—` when empty |
| `plain` | `{{ x\|plain }}` | `500`, `400.5` (never `500.0000000`) — for `data-*` attributes |
| `qs` (tag) | `{% qs page=2 sort="" %}` | `?tab=active&page=2` — replaces / drops keys (`None` or `""`), keeps the rest |
| `pct` | `{{ done\|pct:total }}` | integer 0–100 (0 when `total` is 0) |
| `hue` | `style="{{ addr\|hue }}"` | `--id-a:38;--id-b:200` — two hues from its own hash (not the `Lowbid.identicon` algorithm); no CSS reads them |
| `underline_last` | `{{ "My projects"\|underline_last }}` | `<span class="ui-title">My <span class="ui-underline">projects</span></span>` — a no-op hook on a title's last word (input escaped) |

`{% load payments_extras %}`: `{% escrow_panel task wallet %}` renders `payments/_escrow_panel.html`.

---

## 4. JavaScript API (`window.Lowbid`)

Load order (`base.html`, not deferred unless noted): `lowbid-base.js` → `lowbid-ui.js` → `vendor/freighter-api.js` (global `freighterApi`) → `vendor/stellar-sdk.min.js` (global `StellarSdk`, `defer`) → `lowbid-wallet.js` → `lowbid-pay.js` (`defer`) → `{% block extra_js %}`: `lowbid-projects.js` on every content page (landing, project list / form / page, task page, board, My projects, dashboard, profile); the landing then adds `vendor/anime.umd.min.js` (anime.js 4.5.0, global `anime`) and `lowbid-landing.js`. Vendored files are copied by `npm run vendor` (Font Awesome, Freighter API, Stellar SDK, anime.js); nothing loads from a CDN.

Per-request values: `window.LOWBID` (`network`, `networkPassphrase`, `horizonUrl`, `sorobanRpcUrl`, `asset:{code, issuer, native}`, `paymentMode`, `walletAddress`, `urls:{challenge, verify, logout, landing, dashboard, trustlinePrepare, trustlineSend}`), `window.LOWBID_PROJECT` (project page: `id`, `status`, `isCompany`, `tasksCount`, `paymentMode`, `urls:{addTask, deleteTask, fund}` — `deleteTask` holds a `0` placeholder, `fund` = `pending.json`) and `window.LOWBID_TASK` (task page: `id`, `status`, `isCompany`, `isAssignee`, `urls:{candidates, apply, choose, deliver, validate, pay}` — `choose` holds a `0` placeholder, `payMode` = the mode frozen on the task's escrow row, `payAction` = `{step, mine, prepareUrl}` or `null`).

### `lowbid-base.js`

- `Lowbid.api(url, {method, body})` → Promise JSON; same-origin credentials, `Accept: application/json` + `X-Requested-With: fetch`, and for unsafe methods `X-CSRFToken` (+ JSON body when `body` is given); rejects with an `Error` (message = `data.error` or `HTTP n`) carrying `err.status` / `err.data` on non-2xx.
- `Lowbid.toast(message, type="info|success|warning|error", {title, duration=4500})` → `{el, dismiss}` (or `null` without `#lb-toasts`); `duration: 0` = sticky; text-only (XSS-safe), `role="alert"` for errors.
- `Lowbid.escapeHtml(s)`, `Lowbid.csrf()` (`<meta name="csrf-token">`, else the cookie), `Lowbid.shortAddr(addr, keep=4)`, `Lowbid.formatUsdc(value, code)` (`1,234.50 USDC`; unit = `LOWBID.asset.code`; `code=""` → bare number; `—` when not a number).
- Delegated: `[data-nav-toggle][aria-controls]` (toggles `hidden` + `aria-expanded`), `[data-copy="…"]` (toast « Address copied to the clipboard. »), closing an open `details.lb-wallet-menu` on outside click.

### `lowbid-ui.js`

- `Lowbid.confirm({title, message, confirmLabel, cancelLabel, danger, icon})` (or a plain message string) → `Promise<boolean>`; `danger` adds `.is-danger` and a `ui-btn-danger-solid` OK button; falls back to `window.confirm` only when `#lb-confirm` is missing.
- `Lowbid.modal.open(el|"#id")` (focus on `[data-autofocus]`, else the first control) / `Lowbid.modal.close(el, value)`.
- `Lowbid.identicon(address)` → `{hue, cells}` (FNV-1a hash; 25 cells, 0 empty · 1 `hsl(hue 58% 46%)` · 2 Signal); painted on every `[data-identicon]`.
- `Lowbid.timeAgo(isoOrDate)` → « just now » / « 3 min ago » / « in 2 h » (min, h, d, mo); every `[data-time-ago="ISO"]` is refreshed each minute, `title` = local date (`en-US`).
- `Lowbid.poll(fn, {interval=5000, maxInterval=60000})` → `{stop(), now()}`: skips ticks while the tab is hidden, re-runs 150 ms after the tab returns or the browser goes `online`, ×2 backoff on rejection.
- `Lowbid.refreshUI(root)`: re-runs identicons + sparklines + time-ago inside an injected fragment.
- `Lowbid.setBusy(btn, on, label)`: busy button (disabled, `.is-loading`, `aria-busy`, spinner + label, default « … »), restores the previous HTML.
- `Lowbid.sparkline(svg)`: builds `svg.ui-sparkline[data-points][data-cap]` (kept, currently unused).
- Delegated: `[data-share="URL"]` (Web Share, else copy + « Link copied. »), `form[data-confirm="…"]` (+ `data-confirm-title`, `data-confirm-danger`; currently unused), `[data-search-clear]` (empties the sibling input and submits), `[data-auto-submit]` (submits its form on change), closing `details.ui-menu` (outside click / Escape) and flipping its panel to `.is-start`.

### `lowbid-wallet.js`

`Lowbid.wallet.isInstalled() / getAddress() / requestAccess() / ensureNetwork() / signMessage(message, address) / connect(next) / disconnect()`; `Lowbid.signTransaction(xdr, {networkPassphrase?, address?})` → signed XDR. Delegated: `[data-wallet-connect][data-next]` (SEP-53 login, then redirect to `next` / the current page; errors become a « Wallet » toast) and `[data-wallet-logout]` (unused by the templates: the navbar logs out with a POST form). While signed in, a Freighter account switch raises a warning toast (no auto-logout).

### `lowbid-pay.js`

Markup: `<button data-pay-step="fund" data-prepare-url="/pay/prepare/<task>/fund/" [data-send-url] [data-pay-body='{…}'] [data-loading-label] [data-no-reload] [data-confirm-title data-confirm-message data-confirm-label]>`, `<form data-pay-form>` (its fields join the body, e.g. `delivery_link`), `<p data-pay-error hidden>` (the nearest one gets the server error), `<button data-pay-trustline [data-prepare-url]>`, `<button data-fund data-pending-url="/pay/project/<pk>/pending.json">`, `<span data-usdc-balance="G…" data-watch>` (polled from Horizon: 5 s for 2 min, then 15 s up to 15 min; « — » after 3 consecutive failures). Server contract: `prepare` → `{ok, xdr, send_url, extra?}` or `{ok, redirect, message, next}`; `send` `{signed_xdr, …extra}` → `{ok, hash, contract_id?, redirect, message, next}`; refusals are `{ok:false, error, message}`. API: `Lowbid.pay.signAndSend({xdr, sendUrl, extra})`, `run({step, prepareUrl, body, sendUrl?})`, `runChain(next, {stopAfter, onStep, body})` → `{completed, last, next}` (follows `next` while it is the viewer's own plain signature: deploy → fund, approve → release, direct_pay; a failure carries `.completed` / `.pending`), `runStep(button)`, `fundProject(button)`, `ensureTrustline(button?)`, `watchBalance(el, {interval, maxMs, address, onIncrease})` → `stop()`, `fetchUsdcBalance(address)` (configured asset), `explorerTxUrl/explorerAccountUrl/explorerContractUrl`, `toastTx(message, hash, opts)`.

### `lowbid-network.js`

Profile `#network-panel` only: `[data-follow]` toggles follow / unfollow, `[data-recommend]` opens `#recommend-form` (`#recommend-message` + `[data-recommend-counter]`), `[data-recommend-submit]` POSTs `{message}`, `[data-unrecommend]` withdraws behind `Lowbid.confirm`. Delegated on `document`; refusals toast `res.message`. Its header documents the full DOM contract.

### `lowbid-projects.js`

- `Lowbid.parseTags(raw)` (same normalisation as `services.clean_tags`, display only); `form[data-submit-once]` (one submission: `#project-form`, the profile name form); `[data-tags-help="<input id>"]` live counter; delegated `[data-add-tag][data-target]` (adds a suggested tag, max 3).
- Project page (`LOWBID_PROJECT`): the inline add-task form `#task-form` (`#task-title`, `#task-description`, `#task-price`, `#task-tags`, `[data-task-add]`, `[data-error-for]`) posts through `Lowbid.api` and reloads; `[data-task-delete][data-task-title]` asks `Lowbid.confirm` (danger) first.
- Task page (`LOWBID_TASK`): the apply form `#apply-form` (`#apply-message`, `#apply-tags`, `[data-apply-submit]`); while the task is open, `Lowbid.poll` fetches `candidats.json` every 5 s and swaps `#candidates-list` when `fingerprint` changes (updates `[data-kpi-count]`, shows `[data-live-dot]`, reloads when the status changes, stops on 404); `[data-choose][data-choose-url][data-choose-label]` (delegated, also on the project page's `#candidates-<task>` blocks) asks `Lowbid.confirm` then posts; `#validate-form[data-validate]` confirms, posts the rating to `data-validate-url`, then runs `Lowbid.pay.runChain(next)` for the payment signatures (a declined / failed signature swaps the form for a « Rating saved » alert + the pending `[data-pay-step]` button).

---

## 5. Responsive & accessibility

- **Container queries** rather than media queries whenever a component can live in a column: `.rcard` (720px), `.ui-sticky-actions` (640px, `.ui-form-scope` ancestor), `.kanban-wrap` (1024px / 640px). Page grids (`.ui-split`, `.ui-kpi-band`, `.ui-form-grid`, `.lb-story-grid`) use media queries.
- Breakpoints: 400 (connected wallet chip keeps only the identicon, landing scene at 0.62 scale), 480 (full-width tabs and toolbar end, pager numbers hidden, modal actions stacked), 640 (2-column forms, full-width toasts, navbar padding, Tailwind `sm`), 768 (4-column KPIs, taller hero band), 1024 (desktop nav links, mobile menu and tab bar hidden, two-column `.ui-split` and landing story), 1200 (navbar link labels shown again; hidden from 1024 to 1199.98px), 1536 (shell 80rem: `.lb-nav-inner` and `main` `2xl:max-w-7xl`). The layout holds from 320px.
- No page scrolls horizontally: `body` is `overflow-x-hidden`, `.rcard` cells use `overflow-wrap: anywhere`, grid children `min-width: 0`, the landing band bleeds with `box-shadow` + `clip-path`. The e2e checks `scrollWidth <= innerWidth` at 1280×800 and at 390×844 on the landing, list, form, kanban, project, task and dashboard pages, and that every button of the candidates block is at least 32px tall on a phone.
- Touch targets: buttons 44px on coarse pointers (`-sm` 40px), stars 44px, tabs 56px, list rows 48px, inputs 42px, navbar controls 38px, pager / segmented tabs 36px.
- Mobile tab bar: `body.has-tabbar` sets `--tabbar-h: 60px` and a `padding-bottom` = `--tabbar-h` + safe area; toasts stay at the top.
- Accessibility: `aria-label` on navs, `aria-current="page"` on the active nav link / tab / filter tab / pager page and `aria-current="step"` on the current payment step, `role="status"` / `role="alert"` on messages and toasts, `aria-live="polite"` on the toast container, `role="radiogroup"` on the stars, `aria-hidden` on decorative icons, score bars and the landing scene, `sr-only` labels for icon-only controls, global visible focus, native `<dialog>` (focus trapped, Escape), `prefers-reduced-motion` honoured (CSS + landing JS), RTL-ready (logical `inset-inline-*`, `margin-inline-*`, `text-align: start/end`).

---

## 6. Recipes

**List page (toolbar + grid + pager)**
```django
{% extends "base.html" %}{% load static lowbid_extras %}
{% block content %}
{% include "partials/page_header.html" with title="Projects" %}
<form method="get" class="ui-toolbar">…(§2 Navigation)…</form>
{% if projects %}
  <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{% for project in projects %}{% include "projects/_project_card.html" with project=project %}{% endfor %}</div>
  {% include "components/pager.html" with page=page %}
{% else %}
  {% include "components/empty_state.html" with icon="fa-diagram-project" title="No projects" desc="…" cta_href=create_url cta_label="New project" cta_icon="fa-plus" %}
{% endif %}
{% endblock %}
{% block extra_js %}<script src="{% static 'js/lowbid-projects.js' %}?v={{ LOWBID_ASSET_VERSION }}"></script>{% endblock %}
```

**Detail page (two columns)**
```django
<section class="ui-kpi-band mb-6" aria-label="Key figures">{% include "components/kpi.html" with label="Fixed price" value=… unit=asset_code %}…</section>
<div class="ui-split">
  <div class="ui-stack"><section class="ui-panel" id="candidates-panel">…<div id="candidates-list" data-fingerprint="…">{% include "projects/_candidates.html" %}</div></section></div>
  <aside class="ui-stack">{% escrow_panel task wallet %}</aside>
</div>
```

**Form with a sticky button on a phone**
```django
<div class="ui-split is-even ui-form-scope">
  <form method="post" class="ui-panel" novalidate id="project-form" data-submit-once>
    {% csrf_token %}
    <div class="ui-form-grid">…`.ui-field.ui-field-wide`…</div>
    <div class="ui-sticky-actions mt-4"><a href="…" class="ui-btn ui-btn-ghost">Cancel</a><button type="submit" class="ui-btn ui-btn-primary">Create and add tasks</button></div>
  </form>
  <aside class="hidden lg:block">…</aside>
</div>
```

**Dashboard tile**
```django
{% include "components/kpi.html" with label="To validate" value=kpis.to_validate icon="fa-star" href=my_projects_url hint="deliveries waiting" %}
{% include "components/next_card.html" with tone="act" kicker="Delivered" headline="Validate and rate \"Landing page\"" href=task_url cta="Validate + rate" icon="fa-star" %}
```

**Confirm, then call the API**
```js
Lowbid.confirm({ title: "Choose this freelancer?", message: "The other applications will move to \"Not selected\".", confirmLabel: "Choose", icon: "fa-user-check" }).then(function (ok) {
  if (!ok) return;
  Lowbid.setBusy(btn, true, "…");
  Lowbid.api(url, { method: "POST" }).then(function (d) { Lowbid.toast(d.message || "Freelancer chosen.", "success"); location.reload(); })
    .catch(function (err) { Lowbid.setBusy(btn, false); Lowbid.toast((err.data && err.data.message) || "Could not choose.", "error"); });
});
```
