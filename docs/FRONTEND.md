# Lowbid — Design system & front-end (reference)

The whole front end is **server-rendered** (Django) and styled by three stylesheets loaded in this order by `templates/base.html`:

1. `static/css/lowbid-tokens.css` — the palette (`:root` = the **light « Papier » canvas**, the « Coffre » dark palette under `html[data-theme="dark"]` **and** on any `.theme-coffre` element);
2. `static/css/lowbid-components.css` — the `ui-` / `lb-` / `seg-` / `rcard` / `glass-` / `kanban-` / `cand-` vocabulary;
3. `static/css/tailwind.css` — **build artifact** (`npm run build:css`), loaded last so utilities win specificity ties.

Golden rules: components only read `var(--*)` (never a hardcoded colour); any new Tailwind class means rebuilding **and committing** `tailwind.css`; any change to `lowbid-*.css` / `lowbid-*.js` means bumping `LOWBID_ASSET_VERSION` (30-day static cache). UI copy is French; this reference quotes it as-is.

---

## 1. Tokens (`lowbid-tokens.css`)

**The look (« Registre »: if it lives on chain, it shows).** A cool mineral canvas (`--bg-1` `#F1F3F5`), near-white surfaces (`#FBFCFC`) with a 1px hairline (`--border` `#DDE1E6`, 6px controls / 10px panels, no shadow), graphite text (`#151922`). No pills: controls are 6px blocks, chips 4px. Graphite (`--ink`) = an off-chain decision (primary button, active tab); **Signal yellow** (`--brand-500` `#FDDA24`, Stellar's yellow) = money: a signature that moves funds (`.ui-btn-signal`, and automatically any `.ui-btn-primary[data-pay-step|data-fund|data-validate-submit]`), the done blocks of the escrow chain, the live dot, the « Recommandé » chip. **Everything on chain is mono with tabular figures**: amounts (`|usdc_parts` = faint decimals), addresses, tx hashes, KPI values. The landing hero and every escrow receipt are always in the graphite Coffre palette (`.theme-coffre`).

| Family | Variables | Role |
|--------|-----------|------|
| Signal (yellow) | `--brand-500` `--brand-600` `--brand-700` `--brand-800` `--brand-hover` `--brand-soft` `--brand-ink` | The one accent, it means money (`--brand-700` = yellow-family text readable on paper, `--brand-ink` = graphite text on a yellow fill) |
| Ink (graphite) | `--ink` `--ink-hover` `--on-ink` `--icon-accent` `--rule` | Primary off-chain buttons, active nav tab / chip / pager page (off-white in the Coffre); `--icon-accent` = accent icons (graphite on paper, yellow in the Coffre); `--rule` = the heavy top rule of a ledger line |
| Brand RGB | `--brand-50-rgb` … `--brand-950-rgb` | `r g b` triplets for Tailwind utilities such as `bg-brand-500/20` (see `tailwind.config.js`) |
| Secondary / accent | `--secondary-500` `--secondary-soft` `--accent-500` `--accent-soft` | Sky / violet, occasional use |
| Status | `--success` `--warning` `--error` `--info` + `*-soft` (+ `--on-error`) | Dark tint for text / icons + the pastel fill of the soft pills and alerts |
| Badge text | `--ui-badge-ok-text` `--ui-badge-attn-text` `--ui-badge-danger-text` `--ui-badge-brand-text` `--ui-badge-info-text` | ≥ 4.5:1 on the `*-soft` background in both themes |
| Type | `--text-meta` 12px · `--text-body` 14px · `--text-heading` ≈15.5px · `--text-display` ≈23px · `--font-sans` · `--font-mono` | Four-step scale, system font (no web font) |
| Surfaces | `--bg-1/2/3` (canvas + gradient) `--surface` `--surface-soft` `--glass-bg` `--soft-bg` | Page background, cards, insets |
| Text | `--text` (= `--text-main`) `--muted` (= `--text-muted`) `--text-faint` | Main / secondary / placeholder text |
| Borders & shadows | `--border` `--border-strong` `--glass-border` `--soft-border` `--hover-border` `--divider` `--shadow` `--glass-shadow` `--hover-shadow` `--shadow-pop` `--backdrop` `--focus-ring` | Hairlines, hover, floating panels (menus, toasts, modal), the modal backdrop, the keyboard focus ring |
| Glows | `--glow-1` `--glow-2` | Radial halo behind the page (transparent in light mode) |
| Radii | `--radius-lg` 16px · `--radius-md` 13px · `--radius-sm` 10px | Cards / panels · inputs, alerts |
| Navbar | `--nav-bg` `--nav-border` `--nav-link-hover-bg` `--nav-active` | Canvas-coloured bar with a hairline; the links sit in a 10px surface block, the active one is `--nav-active` (= `--ink`) |
| Rows | `--row-hover` | Table / list row hover |
| Layout | `--tabbar-h` | Height of the mobile tab bar (0 on desktop), read by `.ui-sticky-actions` |

**The site is dark only**: `base.html` renders `<html data-theme="dark">` on every page, there is no toggle. The `:root` block holds the light « Papier » values as the base; the « Coffre » block `html[data-theme="dark"]` redefines the same variables (`#0E1117` canvas, `#151922` surfaces, `#262C3A` hairlines, the same Signal yellow; graphite ink becomes off-white). The same block applies to `.theme-coffre`, so a fragment can force the graphite palette on its own.

---

## 2. CSS vocabulary (`lowbid-components.css`)

### Surfaces & structure

| Class | Use |
|-------|-----|
| `.glass-card` | Card (white, 1px hairline, 13px radius, no visible shadow; stronger hairline on hover) |
| `.glass-soft` | Secondary inset (`--soft-bg`, 8px radius) |
| `.ui-panel` + `.ui-panel-head` `.ui-panel-title` `.ui-panel-sub` | Padded section; two consecutive panels space themselves |
| `.ui-page-header` + `.ui-page-title` `.ui-page-sub` `.ui-page-actions` | Page header (title + subtitle + buttons) — see `partials/page_header.html`. Title: 800 weight, tight tracking. `{{ title\|underline_last }}` still wraps the last word in `<span class="ui-underline">`, now a no-op hook |
| `.ui-underline` | Kept as a hook (no decoration in Registre); `.ui-mono` / `.ui-dec` = mono figure / faint decimals |
| `.ui-icon-tile` | 36px rounded square on a light grey fill, for an icon at the start of a row |
| `.ui-section` + `.ui-section-head` `.ui-section-title` `.ui-section-sub` | h2 above a grid — see `components/section_head.html` |
| `.ui-split` (+ `.is-even`) / `.ui-stack` | Two columns 3/2 (or 1/1) from 1024px, stacked below; vertical stack |
| `.ui-facts` | Stat rows: label left, bold value right, one hairline per row (dashboard stats, funding totals) |
| `.ui-form-scope` | Declares a *container* so `.ui-sticky-actions` knows its width |

### Text

`.ui-meta` (12px grey) · `.ui-label` (uppercase label) · `.ui-link` (text-coloured, hairline underline that darkens on hover) · `.ui-num` / `.ui-num-strong` (**mono**, tabular figures) · `.text-muted` · `.text-strong` · `.ui-price` + `.ui-price-unit` (mono amount on a 4px grey chip, faint decimals via `\|usdc_parts`, `components/price.html`; inside `.ui-kpi-value` it is a bare figure) · `.font-mono`.

### Forms

`.ui-field` · `.ui-input` `.ui-select` `.ui-textarea` (42px, white, 10px radius, soft amber focus ring, `aria-invalid="true"` → red border) · `.ui-help` · `.ui-error` · `.ui-form-grid` (1 column, 2 from 640px, `.ui-field-wide` for full width) · `.ui-input-group` + `.ui-input-addon` (the « USDC » suffix of the task price) · `.ui-search` (a pill input + the round black `.ui-search-btn` submit at its end + optional `[data-search-clear]`) · `.ui-select-inline` (compact pill select).

Server-side field errors from `Lowbid.api` land in `<p class="ui-error" data-error-for="<field>" hidden>` (add-task form: `title`, `price`, `tags`; apply form: `message`, `tags`; `_` for the rest).

### Buttons

6px blocks. `.ui-btn` = surface with a hairline (secondary); `-primary` = **graphite** (`--ink`); `-signal` = **yellow** (moves money; applied automatically to `-primary` buttons carrying `data-pay-step`, `data-fund` or `data-validate-submit`); `-ghost` = bare; `-danger` = surface with red text, `-danger-solid` = red; sizes `-sm` (34px) / default 40px (44px on touch screens) / `-lg` (46px); `-block`; `:active` nudges 1px down; states `:disabled` / `.is-loading` (an `<i class="fa-spinner">` spins). `.ui-copy-btn` (32px, icon only, `data-copy="…"`). `.lb-icon-btn` (38px, navbar).

### Badges, tags, alerts, states

| Class | Use |
|-------|-----|
| `.ui-badge` + `-ok` `-attn` `-danger` `-info` `-brand` `-neutral` | 4px chip, soft tint with dark text (≥ 4.5:1). Task: Ouvert `info`, Pris `brand`, Livré `attn`, Payé `ok`. Project: Brouillon `neutral`, Financé `ok`, Terminé `brand`. **`.ui-badge-brand` is the FILLED Signal chip** (« Recommandé » / « Choisi » / « Postulé »), `.ui-badge-ok.badge-validated` = « Validé » |
| `.ui-status` + `.ui-dot` (`.is-open` `.is-taken` `.is-delivered` `.is-paid`) | Coloured dot + label (kanban column titles) |
| `.ui-live` + `.ui-live-dot` | "live" with a pulsing dot (`[data-live-dot]` on the task page while polling) |
| `.ui-tag` (+ `.is-match`) | Skill chip (4px) on a light grey fill; `.is-match` (also asked by the task / the active filter) = graphite chip |
| `.ui-chip-row` | Row of filter chips (bordered, the active one graphite) that scrolls horizontally on a phone, wraps from 768px (popular tags on the list page) |
| `.ui-alert` + `-ok` `-attn` `-danger` `-info` | Inline message with icon (payment errors `[data-last-error]`, « Tâche payée ») |
| `.empty-state` + `-icon` `-title` `-desc` | Centred empty state: grey icon tile, bold title, grey line, graphite CTA — see `components/empty_state.html` |
| `.ui-skeleton` / `.ui-skeleton-line` (+ `.w-1/2` `.w-1/3` `.w-3/4`) | Animated placeholders (`aria-hidden`) |
| `.ui-progress` (+ `.is-ok`) `> span` | Progress bar (inline width) — paid tasks / tasks on the project card |

### KPI

```html
<section class="ui-kpi-band" aria-label="Chiffres clés">        <!-- 2 columns, 4 from 768px; .is-3 for three -->
  <a href="…" class="ui-kpi-tile is-link">
    <span class="ui-kpi-head"><span class="ui-kpi-label">Budget total</span><span class="ui-kpi-icon"><i class="fa-solid fa-coins"></i></span></span>
    <span class="ui-kpi-value" data-kpi-total>1,200.00<span class="ui-price-unit">USDC</span></span>
    <span class="ui-kpi-hint ui-meta">3 tâches à prix fixe</span>
  </a>
</section>
```
→ `components/kpi.html`.

### Navigation

| Class | Use |
|-------|-----|
| `.lb-nav` `.lb-nav-inner` `.lb-brand` `.lb-brand-name` `.lb-brand-mark` `.lb-nav-links` `.lb-nav-link.is-active` `.lb-nav-actions` | Sticky bar (`partials/navbar.html`): the Signal square mark + lowercase wordmark « lowbid » left, the links **centred in a surface block** (the active link is graphite with its icon; labels hide between 1024 and 1200px), theme toggle + wallet chip right |
| `.lb-mobile-nav` (`#lb-mobile-nav`, `[data-nav-toggle]`) | Drop-down mobile menu under the bar |
| `.lb-wallet-btn` (+ `.is-connected`) `.lb-wallet-dot` `.lb-wallet-menu` `.lb-wallet-dropdown` `.lb-dropdown-item` | « Connecter » = graphite block; the connected chip = surface block with the pixel identicon, the short address and a chevron, opening the menu (« Tableau de bord », « Mon profil public », logout) |
| `.lb-tabbar` + `.lb-tab` (+ `.is-active` `.is-primary`) | Fixed white bottom tab bar, < 1024px, **signed-in only** (`body.has-tabbar`, `partials/tabbar.html`, fed by `NAV_LINKS`: Projets · Tableau · Créer (yellow tile) · Mes projets · Bord); the active tab's icon sits in a graphite tile |
| `.seg-tabs` + `.seg-tab.is-active` (+ `.seg-count`) | Filter tabs (En cours / Terminés / Tous): surface with a hairline, the active one graphite; full width below 480px |
| `.ui-toolbar` `.ui-toolbar-grow` `.ui-toolbar-end` | List toolbar (search · tabs · sort · count) |
| `.ui-pager` `.ui-pager-count` `.ui-pager-nav` `.ui-pager-btn` `.ui-pager-num.is-active` | Pagination; numbers hidden below 480px — see `components/pager.html` |

```html
<form method="get" class="ui-toolbar">
  <div class="ui-search ui-toolbar-grow">
    <input class="ui-input" type="search" name="q" value="{{ q }}" placeholder="Rechercher un projet, une tâche, une compétence…">
    {% if q %}<button type="button" class="ui-search-clear" data-search-clear aria-label="Effacer"><i class="fa-solid fa-xmark"></i></button>{% endif %}
    <button type="submit" class="ui-search-btn" aria-label="Rechercher"><i class="fa-solid fa-magnifying-glass"></i></button>
  </div>
  <nav class="seg-tabs">…</nav>
  <div class="ui-toolbar-end">
    <label class="ui-select-inline"><span class="ui-meta">Trier</span><select name="sort" class="ui-select" data-auto-submit>…</select></label>
    <span class="ui-meta">2 projets</span>
  </div>
</form>
```

### Menus & modals

```html
<details class="ui-menu">
  <summary class="ui-btn ui-btn-sm"><i class="fa-solid fa-ellipsis"></i></summary>
  <div class="ui-menu-panel">                              <!-- .is-start to align it left -->
    <div class="ui-menu-label">Actions</div>
    <a class="ui-menu-item" href="…" data-share="…"><i class="fa-solid fa-share-nodes"></i> Partager</a>
    <div class="ui-menu-sep"></div>
    <button class="ui-menu-item is-active" type="button">…</button>
  </div>
</details>
```
The menu opens without JS; `lowbid-ui.js` closes it on outside click and `Escape`.

```html
<dialog class="ui-modal is-danger">                    <!-- native top layer; blurred backdrop -->
  <form method="dialog" class="ui-modal-card">
    <div class="ui-modal-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
    <h2 class="ui-modal-title">Supprimer cette tâche ?</h2>
    <p class="ui-modal-body">Ses candidatures seront supprimées avec elle.</p>
    <div class="ui-modal-actions"><button value="cancel" class="ui-btn ui-btn-ghost">Annuler</button><button value="ok" class="ui-btn ui-btn-danger-solid">Supprimer</button></div>
  </form>
</dialog>
```
The global confirm modal `#lb-confirm` (`partials/modal.html`, included by `base.html`, with `[data-modal-title]` `[data-modal-body]` `[data-modal-icon]` `[data-modal-ok]` `[data-modal-cancel]`) is driven by `Lowbid.confirm()`; for a custom modal: `Lowbid.modal.open("#id")` / `close`.

### Lists, rows, tables

| Class | Use |
|-------|-----|
| `.ui-list` + `.ui-list-row` + `.ui-rank` | Vertical list separated by hairlines; `.ui-rank` is a 32px rounded-square tile with the rank; `a.ui-list-row` is hoverable |
| `.rcard` | **Mandatory wrapper around a `<table>`**; every `<td data-label="Colonne">`; `th/td.ui-col-end` right-aligns; `tr.is-attn` highlights (a project with candidates to choose or a delivery to validate). Below 720px of **container** width the table becomes stacked cards (no horizontal scroll); `td.is-stack` puts the label above a multi-block cell (title + tags + description). Used by the project's task table (`.task-row[data-task-id][data-status]`, `projects/_task_row.html`), Mes projets and the profile |
| `.project-card` | Project card on the list and the landing (lift on hover) — `projects/_project_card.html` |

```html
<div class="rcard"><table>
  <thead><tr><th>Tâche</th><th class="ui-col-end">Prix</th></tr></thead>
  <tbody><tr class="task-row" data-task-id="12" data-status="open"><td data-label="Tâche">…</td><td data-label="Prix" class="ui-col-end ui-num">300.00 USDC</td></tr></tbody>
</table></div>
```

### Task board components

**Candidate row + score bar** (`projects/_candidates.html`, also returned as `html` by `candidats.json` and swapped in place):

```html
<div class="ui-list" data-candidates data-count="2" data-task="12">
  <div class="ui-list-row cand-row" data-app-id="7" data-freelancer="G…">    <!-- + .is-chosen / .is-rejected -->
    <span class="ui-rank" data-rank>1</span>
    <div class="flex-1 min-w-0">
      …wallet chip…
      <span class="ui-badge ui-badge-ok badge-validated" data-badge="valide">Validé</span>
      <span class="ui-badge ui-badge-brand" data-recommended>Recommandé</span>
      <div class="ui-scorebar" aria-hidden="true">
        <span class="ui-scorebar-seg is-history" style="width: 40.0%"></span>
        <span class="ui-scorebar-seg is-rating" style="width: 40.0%"></span>
        <span class="ui-scorebar-seg is-skills" style="width: 10.0%"></span>
      </div>
      <strong data-score="90.0">90.0</strong> / 100
    </div>
    <button class="ui-btn ui-btn-primary ui-btn-sm" data-choose="7" data-choose-url="/taches/12/choisir/7/">Choisir</button>
  </div>
</div>
```
`.ui-scorebar` is a 160px track cut into **ten blocks** by a CSS mask; each segment's width is its points (out of 100): history Signal, ratings `--secondary-500`, skills `--success`. `.cand-row.is-chosen` gets the brand-soft background and a yellow rank tile, `.is-rejected` fades to 55 % opacity. The legend under the list repeats the weights (Historique 40, Notes ×8, Compétences 20).

**Kanban** (`projects/board.html`, `projects/_board_card.html`):

```html
<div class="kanban-wrap"><div class="kanban" data-kanban>
  <section class="kanban-col" data-col="open">                     <!-- open · taken · delivered · paid -->
    <header class="kanban-col-head"><h2 class="kanban-col-title"><span class="ui-dot is-open"></span>Ouvert</h2><span class="kanban-count" data-col-count>3</span></header>
    <p class="kanban-col-hint ui-meta">Toutes les tâches ouvertes, à prendre.</p>
    <div class="kanban-cards">
      <article class="kanban-card glass-card is-applied" data-task-id="12" data-status="open">…title, price, project, tags, company, CTA…</article>
    </div>
    <!-- or <p class="kanban-empty ui-meta">…</p> -->
  </section>
</div></div>
```
`.kanban-wrap` is a container (`container-name: kanban`): 4 columns, 2 below 1024px, and below 640px one full-width column at a time with horizontal **snap-scroll** — the one deliberate exception to "no horizontal scroll" (the page itself never overflows). Columns sit directly on the canvas (bold title + mono count); the cards are white. `.kanban-card.is-applied` marks a task the freelance already applied to (graphite border).

**Star rating** (`.ui-stars`, in the validation form of the payment panel):

```html
<div class="ui-stars" role="radiogroup" aria-label="Note de 1 à 5">     <!-- row-reverse: 5 first in the DOM -->
  <input type="radio" name="note" id="rate-5" value="5" data-rate="5" checked><label for="rate-5" title="5/5"><i class="fa-solid fa-star"></i><span class="sr-only">5 sur 5</span></label>
  …4, 3, 2, 1…
</div>
<span class="ui-help" data-rate-help>5/5 — excellent</span>
```
Five visually hidden radios, the labels are 44px stars; hover and `:checked ~ label` colour the stars up to the choice; keyboard focus shows a ring.

**Funding banner** (`projects/_funding_panel.html`, project page, `#funding-panel[data-pay-summary][data-mode="escrow|direct"]`): title « Financement en escrow » or « Paiement direct USDC », a `.ui-facts` list (Total des tâches `[data-pay-total]`, Bloqués ou versés `[data-pay-funded]`, Payés aux freelances `[data-pay-paid]`), one row per non-open task (`[data-pay-task][data-escrow-status]`) with its escrow badge and every explorer link, and for the company the funding hint `[data-pay-status]` + `[data-pay-error]`. The « Financer le projet » button (`[data-fund][data-pending-url]`) lives in the page header and is disabled with the hint as tooltip when there is nothing to fund.

**Payment panel** (`payments/_escrow_panel.html`, rendered by `{% escrow_panel task wallet %}` on the task page for every non-open task, `#escrow-panel[data-mode][data-escrow-status]` + `#paiement` anchor):

- header: « Paiement en escrow » or « Paiement direct USDC » + « sans escrow » badge, the escrow status badge `[data-escrow-badge]`;
- `.ui-stepper` + `.ui-step.is-done/.is-current/.is-todo` `.ui-step-dot` `.ui-step-label` — escrow: Escrow créé · Fonds bloqués · Livré · Fonds libérés; direct: Livré · Payé;
- the freelance's wallet and live balance `<span class="ui-balance" data-usdc-balance="G…" data-watch>` (`.ui-balance.is-bumped` when it moves);
- alerts: `[data-platform-fallback]` (company, no platform address), `[data-last-error]` (vendor / Horizon message, or the pending-hash info);
- one action block, depending on `next_action()`: the delivery form `#deliver-panel` (`#deliver-form`, `#deliver-link`, `[data-pay-step="deliver"][data-deliver]`), the rating form `#validate-panel` (`#validate-form[data-validate]`, `.ui-stars`, `#validate-comment`, `[data-validate-submit]` « Valider et libérer … » / « Valider et payer … »), a single step button `[data-pay-step][data-prepare-url]`, or a waiting message for the other party;
- `[data-pay-trustline]` « Ajouter la trustline USDC » for the two parties (hidden for native XLM);
- `[data-explorer-links]`: every stored hash and the contract, linked to stellar.expert.

### Timeline, "what's next"

```html
<ol class="ui-timeline">
  <li class="ui-timeline-item is-ok"><span class="ui-timeline-dot"><i class="fa-solid fa-money-bill-transfer"></i></span>
    <div class="ui-timeline-body"><div class="ui-timeline-title">Paiement reçu — « Landing page » (300.00 USDC)</div><div class="ui-timeline-time" data-time-ago="2026-10-24T21:00:00Z"></div></div></li>
  <li class="ui-timeline-item is-brand">…</li>
  <li class="ui-timeline-item is-muted">…</li>
</ol>
```
Used by the dashboard activity (`#activity`) and the profile.

```html
<a href="…" class="ui-next-card act">                    <!-- act = your move · wait = someone else's · done -->
  <span class="ui-next-kicker"><span class="ui-next-dot"></span>Candidatures</span>
  <div class="ui-next-row"><div><p class="ui-next-headline">Choisir un freelance pour « Intégration Freighter »</p><p class="ui-next-body">2 candidatures</p></div><span class="ui-btn ui-btn-sm ui-btn-primary">Choisir</span></div>
</a>
<div class="ui-next-list" data-todo-list>…several cards…</div>
```
→ `components/next_card.html` (the dashboard's to-do list, `#todo`).

### Wallet (identicon + address)

```html
<a href="{% url 'dashboard:profile' addr %}" class="ui-wallet" data-identicon="{{ addr }}" title="{{ addr }}">
  <span class="ui-identicon is-lg" aria-hidden="true"></span>            <!-- is-lg 44px · is-xl 64px -->
  <span class="ui-wallet-text"><span class="ui-wallet-name">Yanis</span><span class="ui-wallet-addr">GABC…WXYZ</span></span>
</a>
<button class="ui-copy-btn" data-copy="{{ addr }}"><i class="fa-regular fa-copy"></i></button>
```
The identicon is a **mirrored 5×5 pixel grid** (Signal yellow + one hue from the address), painted by `Lowbid.identicon()` (lowbid-ui.js) as an SVG background on every `[data-identicon]`; before JS it is a plain grey square. The `|hue` style it still receives is unused. → `components/wallet.html`.

### Sticky actions & misc

- `.ui-sticky-actions`: static on wide screens; below 640px of container width (it needs a `.ui-form-scope` ancestor) it becomes a white bar stuck to the bottom, above the tab bar (`--tabbar-h`), with stretched buttons. Used by the project form, the add-task form, the apply form and the payment panel's forms.
- `.lb-toast-container` `.lb-toast` (+ `[data-type]`): toasts (`Lowbid.toast`).
- Landing: `.lb-hero-band.lb-story[data-story]` (full-bleed `.theme-coffre` band, no horizontal overflow: box-shadow + clip-path) is ONE scroll track › `.lb-story-grid[data-story-grid]` (grid areas hero / scene / flow; two columns from 1024px, the scene spans both rows) › `.lb-hero[data-story-hero]` (`.lb-kicker`, `.lb-hero-title`, `.lb-hero-sub`, `.lb-hero-cta`, `.lb-hero-stats`) · `.lb-scene-wrap` (sticky; `core.views.STORY_TASKS` as worked example) › `.lb-scene` (geometry in `--w` / `--d` / `--h`) › `.lb-cube[data-cube]` › `.lb-slab[data-slab]` × 4 › `.lb-face.is-{front,back,left,right,top,bottom}` (+ `.lb-face-no` / `-title` / `-price` / `-lock` / `-glow` / `-release`) and `.lb-bids` › `.lb-bid(.is-chosen)`; `.lb-scene-caption` · `.lb-story-flow` › `.lb-story-intro` (`.lb-section-title`, `.lb-story-sub`) + `.lb-story-steps` › `.lb-step[data-story-step]` (+ `.is-signal`, `.theme-coffre`, `.is-active` set by `lowbid-landing.js`) with `.lb-step-head` / `-title` / `-desc` / `-call`. The cube is CSS 3D only; anime.js (`vendor/anime.umd.min.js`, global `anime`) runs four scrubbed timelines (`onScroll`, `sync: true`), one per chapter: the hero scrolling out splits the cube, then each step card drives its own chapter (window: card top at the viewport bottom → card centre at the viewport centre; the `.lb-story-steps` gap keeps the windows apart). Only transforms and opacity are animated — never set a CSS `transform` on `.lb-cube`, `.lb-slab`, `.lb-bid` or a `[data-face-*]` span. `prefers-reduced-motion` parks the cube on the locked pose; `.lb-tape` (ledger tape: the latest real tx events, `core.views.ledger_tape`, looped marquee, paused on hover).
- Receipt: `.ui-receipt` (inside `.theme-coffre`) › `.ui-receipt-head` / `-title` / `-amount` / `-unit` / `-sub` / `-rows`; the escrow panel is `.glass-card.ui-receipt-card` = receipt + `.ui-receipt-body` (alerts, forms, actions). `.ui-stepper` is a row of blocks: done = yellow, current = graphite outline + blinking dot, todo = dashed.
- Global keyboard focus: graphite ring on paper, yellow in the Coffre (`--focus-ring`) on `:focus-visible`. `@media print` hides nav, tab bar, toasts, sticky actions. `prefers-reduced-motion` stops animations.
- Present in the CSS but not used by the current templates: `.ui-sparkline` (+ `Lowbid.sparkline`) and `.seg-radio`.

---

## 3. Template components (`templates/components/`)

| Include | Parameters | Renders |
|---------|-----------|---------|
| `components/wallet.html` | `address` (required), `name`, `label`, `size="lg\|xl"`, `keep` (chars kept, 4), `copy=True`, `nolink=True`, `you=True` | Identicon + short address, linked to `dashboard:profile` unless `nolink` |
| `components/status_badge.html` | `obj` (any object with `badge_class` / `status_label`: Project, Task, Application), `live=True` (adds `data-status-badge`) | `.ui-badge` of the status |
| `components/tags.html` | `tags`, `linked=True` (filter the project list), `matched` (set), `class` | Row of `.ui-tag` |
| `components/kpi.html` | `label`, `value` (pre-formatted), `unit`, `hint`, `icon`, `href`, `attr` (e.g. `"data-kpi-count"`) | KPI tile, a link if `href` |
| `components/price.html` | `amount` (Decimal or None), `size` (class), `attr` | `.ui-price` + unit |
| `components/empty_state.html` | `icon`, `title`, `desc`, `cta_href`, `cta_label`, `cta_icon`, `class` | Empty state card |
| `components/pager.html` | `page` (Django `Page`) | Pagination keeping the query string (`{% qs %}`) |
| `components/next_card.html` | `tone="act\|wait\|done"`, `kicker`, `headline`, `body`, `href`, `cta`, `icon` | "What's next" card |
| `components/section_head.html` | `title`, `sub`, `icon`, `link_href`, `link_label` | Section title + link |
| `partials/page_header.html` | `title`, `subtitle`, `actions` (safe HTML) | Page header (the title goes through `\|underline_last`) |
| `partials/modal.html` / `partials/tabbar.html` / `partials/toasts.html` / `partials/navbar.html` | — | Included once by `base.html` |

Task-board partials (not generic, but reusable within `projects`): `_project_card.html` (list / landing card), `_task_row.html` (task table row), `_task_form.html` (inline add-task form), `_candidates.html` (ranked candidates), `_funding_panel.html` (project funding banner), `_board_card.html` (kanban card).

`base.html` blocks: `title`, `meta_description`, `extra_head`, `body_class`, `content`, `extra_js`. Context available everywhere: `wallet_address`, `wallet_user`, `nav_links`, `STELLAR_*`, `asset_code`, `asset_issuer`, `asset_native`, `payment_mode`, `LOWBID_ASSET_VERSION`, `messages`.

### Filters and tags (`{% load lowbid_extras %}`)

| | Example | Result |
|--|---------|--------|
| `short_addr` | `{{ addr\|short_addr }}` / `{{ addr\|short_addr:6 }}` | `GABC…WXYZ` (tolerates an empty `keep`) |
| `usdc` | `{{ x\|usdc }}` / `{{ x\|usdc:"" }}` / `{{ x\|usdc:asset_code }}` | `1,234.50 USDC` (unit = the configured asset) / `1,234.50`; `—` when empty |
| `usdc_parts` | `{{ x\|usdc_parts }}` | `1,234<span class="ui-dec">.50</span>`: the bare number with faint decimals (prices, receipts, KPI values); `—` when empty |
| `plain` | `{{ x\|plain }}` | `500`, `400.5` (never `500.0000000`) — for `data-*` attributes |
| `qs` (tag) | `{% qs page=2 sort="" %}` | `?tab=active&page=2` — replaces / drops keys, keeps the rest |
| `pct` | `{{ done\|pct:total }}` | integer 0–100 |
| `hue` | `style="{{ addr\|hue }}"` | `--id-a:38;--id-b:200`: the identicon's two hues (same algorithm as `Lowbid.identicon`), rendered server-side so nothing flashes before the JS |
| `underline_last` | `{{ "Mes projets"\|underline_last }}` | `<span class="ui-title">Mes <span class="ui-underline">projets</span></span>` — a no-op hook on a title's last word (input escaped) |

`{% load payments_extras %}`: `{% escrow_panel task wallet %}` renders `payments/_escrow_panel.html`.

---

## 4. JavaScript API (`window.Lowbid`)

Load order (`base.html`, not deferred unless noted): `lowbid-base.js` → `lowbid-ui.js` → `vendor/freighter-api.js` → `vendor/stellar-sdk.min.js` (`defer`) → `lowbid-wallet.js` → `lowbid-pay.js` (`defer`) → `{% block extra_js %}` (`lowbid-projects.js` on the project and task pages; the landing adds `vendor/anime.umd.min.js` then `lowbid-landing.js`). Per-request values: `window.LOWBID` (`network`, `networkPassphrase`, `horizonUrl`, `sorobanRpcUrl`, `asset:{code, issuer, native}`, `paymentMode`, `walletAddress`, `urls:{challenge, verify, logout, landing, dashboard, trustlinePrepare, trustlineSend}`), `window.LOWBID_PROJECT` (project page: `id`, `status`, `isCompany`, `tasksCount`, `paymentMode`, `urls:{addTask, deleteTask, fund}`) and `window.LOWBID_TASK` (task page: `id`, `status`, `isCompany`, `isAssignee`, `urls:{candidates, apply, choose, deliver, validate, pay}`, `payAction`, `payMode` = the mode frozen on the task's escrow row).

### `lowbid-base.js`

- `Lowbid.api(url, {method, body})` → Promise JSON; adds CSRF + `Accept: application/json` + `X-Requested-With: fetch`; rejects with `err.status` / `err.data` on non-2xx.
- `Lowbid.toast(message, type="info|success|warning|error", {title, duration=4500})` → `{el, dismiss}`; `duration: 0` = sticky.
- `Lowbid.escapeHtml`, `Lowbid.csrf()`, `Lowbid.shortAddr(addr, keep)`, `Lowbid.formatUsdc(value, code)` (unit = `LOWBID.asset.code`; `code=""` → bare number).
- Delegated: `[data-nav-toggle][aria-controls]`, `[data-copy="…"]` (toast « Adresse copiée »), closing the wallet menu.

### `lowbid-ui.js`

- `Lowbid.confirm({title, message, confirmLabel, cancelLabel, danger, icon})` → `Promise<boolean>`.
- `Lowbid.modal.open(el|"#id")` / `Lowbid.modal.close(el, value)`; focus on `[data-autofocus]`.
- `Lowbid.identicon(address)` → `{a, b}`; applied to `[data-identicon]`.
- `Lowbid.timeAgo(iso)` → « il y a 3 min »; `[data-time-ago="ISO"]` refreshed every minute, `title` = local date.
- `Lowbid.poll(fn, {interval=5000, maxInterval=60000})` → `{stop(), now()}`: paused while the tab is hidden, immediate resume on return / `online`, ×2 backoff on rejection.
- `Lowbid.refreshUI(root)`: re-runs identicons + time-ago (+ sparklines) inside an injected fragment.
- `Lowbid.setBusy(btn, on, label)`: busy button (spinner, `aria-busy`), restores the label.
- `Lowbid.sparkline(svg)`: builds `svg.ui-sparkline[data-points]` (kept, currently unused).
- Delegated: `[data-share="URL"]` (Web Share or copy), `form[data-confirm="…"]` (+ `data-confirm-title`, `data-confirm-danger`), `[data-search-clear]`, `[data-auto-submit]`, closing `details.ui-menu` (outside click / Escape).

### `lowbid-wallet.js`

`Lowbid.wallet.isInstalled() / getAddress() / requestAccess() / ensureNetwork() / signMessage(message, address) / connect(next) / disconnect()`; `Lowbid.signTransaction(xdr, {networkPassphrase?, address?})` → signed XDR. Buttons `[data-wallet-connect][data-next]`.

### `lowbid-pay.js`

Markup: `<button data-pay-step="fund" data-prepare-url="/pay/prepare/<task>/fund/" [data-send-url] [data-pay-body='{…}'] [data-loading-label] [data-no-reload] [data-confirm-title data-confirm-message data-confirm-label]>`, `<form data-pay-form>` (its fields join the body, e.g. `delivery_link`), `<p data-pay-error hidden>` (the nearest one gets the server error), `<button data-pay-trustline>`, `<button data-fund data-pending-url="/pay/project/<pk>/pending.json">`, `<span data-usdc-balance="G…" data-watch>`. Server contract: `prepare` → `{ok, xdr, send_url, extra?}` or `{ok, redirect, message, next}`; `send` `{signed_xdr, …extra}` → `{ok, hash, contract_id?, redirect, message, next}`. API: `Lowbid.pay.signAndSend({xdr, sendUrl, extra})`, `run({step, prepareUrl, body})`, `runChain(next, {stopAfter, onStep})` (follows `next` while it is the viewer's own signature: deploy → fund, approve → release), `runStep(button)`, `fundProject(button)`, `ensureTrustline(button?)`, `watchBalance(el, {interval, maxMs})` → `stop()`, `fetchUsdcBalance(address)` (configured asset), `explorerTxUrl/explorerAccountUrl/explorerContractUrl`, `toastTx(message, hash)`.

### `lowbid-projects.js`

- `Lowbid.parseTags(raw)` (same normalisation as `services.clean_tags`, display only); `form[data-submit-once]` (one submission: the project form, the profile name).
- Project page (`LOWBID_PROJECT`): the inline add-task form `#task-form` (`#task-title`, `#task-description`, `#task-price`, `#task-tags`, `[data-task-add]`, `[data-error-for]`, `[data-add-tag][data-target]` suggestions) posts through `Lowbid.api` and reloads; `[data-task-delete]` asks `Lowbid.confirm` first.
- Task page (`LOWBID_TASK`): the apply form `#apply-form` (`#apply-message`, `#apply-tags`, `[data-apply-submit]`); while the task is open, `Lowbid.poll` fetches `candidats.json` every 5 s and swaps `#candidates-list` when `fingerprint` changes (updates `[data-kpi-count]`, shows `[data-live-dot]`, reloads when the status changes); `[data-choose]` (delegated, also on the project page's `#candidates-<task>` blocks) asks `Lowbid.confirm` then posts; `#validate-form[data-validate]` posts the rating, then runs `Lowbid.pay.runChain(next)` for the payment signatures.

---

## 5. Responsive & accessibility

- **Container queries** rather than media queries whenever a component can live in a column: `.rcard` (720px), `.ui-sticky-actions` (640px, `.ui-form-scope` ancestor), `.kanban` (1024px / 640px). Page grids (`.ui-split`, `.ui-kpi-band`, `.lb-story-grid`) use media queries.
- Breakpoints: 480 (full-width tabs, pager numbers hidden, modal actions stacked), 640 (2-column forms, full-width toasts), 768 (4-column KPIs, tags wrap), 1024 (desktop nav links, mobile tab bar hidden, two columns).
- No page scrolls horizontally: `body` is `overflow-x-hidden`, cells use `overflow-wrap: anywhere`, grids `min-w-0`. The e2e checks `scrollWidth <= innerWidth` at 390×844 on the landing, list, form, kanban, project, task and dashboard pages, and that every button of the candidates block is at least 32px tall on a phone.
- Touch targets 44px (buttons, inputs, list rows, pager, stars); 40px for secondary navbar controls.
- Mobile tab bar: `body.has-tabbar` adds a `padding-bottom` = `--tabbar-h` + safe area; toasts stay at the top.
- Accessibility: `aria-label` on navs, `aria-current="page"` on the active tab and `aria-current="step"` on the current payment step, `role="status"` / `role="alert"` on messages and toasts, `aria-live="polite"` on the toast container, `role="radiogroup"` on the stars, `aria-hidden` on decorative icons and score bars, `sr-only` labels for icons, global visible focus, native `<dialog>` (trapped focus, Escape), `prefers-reduced-motion` honoured, RTL-ready (logical `inset-inline-*`, `margin-inline-*`).

---

## 6. Recipes

**List page (toolbar + grid + pager)**
```django
{% extends "base.html" %}{% load static lowbid_extras %}
{% block content %}
{% include "partials/page_header.html" with title="Projets" subtitle="…" %}
<form method="get" class="ui-toolbar">…(§2 Navigation)…</form>
{% if projects %}
  <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{% for project in projects %}{% include "projects/_project_card.html" %}{% endfor %}</div>
  {% include "components/pager.html" with page=page %}
{% else %}
  {% include "components/empty_state.html" with icon="fa-diagram-project" title="Aucun projet" cta_href=… cta_label="Nouveau projet" %}
{% endif %}
{% endblock %}
```

**Detail page (two columns)**
```django
<section class="ui-kpi-band mb-6">{% include "components/kpi.html" with label="Prix fixe" value=… unit=asset_code %}…</section>
<div class="ui-split">
  <div class="ui-stack"><section class="ui-panel" id="candidates-panel">…{% include "projects/_candidates.html" %}…</section></div>
  <aside class="ui-stack">{% escrow_panel task wallet %}</aside>
</div>
```

**Form with a sticky button on a phone**
```django
<form method="post" class="ui-panel ui-form-scope max-w-3xl" novalidate data-submit-once>
  {% csrf_token %}
  <div class="ui-form-grid">…`.ui-field`…</div>
  <div class="ui-sticky-actions"><a href="…" class="ui-btn ui-btn-ghost">Annuler</a><button class="ui-btn ui-btn-primary">Créer et ajouter des tâches</button></div>
</form>
```

**Dashboard tile**
```django
{% include "components/kpi.html" with label="À valider" value=stats.to_validate icon="fa-check-double" href=my_projects_url hint="livraisons en attente" %}
{% include "components/next_card.html" with tone="act" kicker="Livraison déclarée" headline="Valider et noter « Landing page »" href=task_url cta="Valider" icon="fa-star" %}
```

**Confirm, then call the API**
```js
Lowbid.confirm({ title: "Choisir ce freelance ?", message: "Les autres candidatures seront marquées « Non retenu ».", confirmLabel: "Choisir" }).then(function (ok) {
  if (!ok) return;
  Lowbid.setBusy(btn, true, "Choix…");
  Lowbid.api(url, { method: "POST" }).then(function (d) { Lowbid.toast(d.message, "success"); location.reload(); })
    .catch(function (err) { Lowbid.setBusy(btn, false); Lowbid.toast((err.data && err.data.message) || "Action impossible.", "error"); });
});
```
