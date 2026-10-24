# Lowbid — Design system & front-end (reference)

The whole front end is **server-rendered** (Django) and styled by three stylesheets loaded in this order by `templates/base.html`:

1. `static/css/lowbid-tokens.css` — the palette (`:root`, light mode under `html[data-theme="light"]`);
2. `static/css/lowbid-components.css` — the `ui-` / `lb-` / `seg-` / `rcard` / `glass-` / `kanban-` / `cand-` vocabulary;
3. `static/css/tailwind.css` — **build artifact** (`npm run build:css`), loaded last so utilities win specificity ties.

Golden rules: components only read `var(--*)` (never a hardcoded colour); any new Tailwind class means rebuilding **and committing** `tailwind.css`; any change to `lowbid-*.css` / `lowbid-*.js` means bumping `LOWBID_ASSET_VERSION` (30-day static cache). UI copy is French; this reference quotes it as-is.

---

## 1. Tokens (`lowbid-tokens.css`)

| Family | Variables | Role |
|--------|-----------|------|
| Brand (amber) | `--brand-500` `--brand-600` `--brand-700` `--brand-800` `--brand-soft` `--brand-ink` | Accent, primary buttons (`--brand-ink` = text on amber) |
| Brand RGB | `--brand-50-rgb` … `--brand-950-rgb` | `r g b` triplets for Tailwind utilities such as `bg-brand-500/20` (see `tailwind.config.js`) |
| Secondary / accent | `--secondary-500` `--secondary-soft` `--accent-500` `--accent-soft` | Sky / violet, occasional use |
| Status | `--success` `--warning` `--error` `--info` + `*-soft` | Solid colour + translucent background |
| Badge text | `--ui-badge-ok-text` `--ui-badge-attn-text` `--ui-badge-danger-text` `--ui-badge-brand-text` `--ui-badge-info-text` | ≥ 4.5:1 on the `*-soft` background in both themes |
| Type | `--text-meta` 12px · `--text-body` 14px · `--text-heading` 16px · `--text-display` 28px · `--font-sans` · `--font-mono` | Four-step scale, system font (no web font) |
| Surfaces | `--bg-1/2/3` (canvas + gradient) `--surface` `--surface-soft` `--glass-bg` `--soft-bg` | Page background, cards, insets |
| Text | `--text` (= `--text-main`) `--muted` (= `--text-muted`) | Main / secondary text |
| Borders & shadows | `--border` `--border-strong` `--glass-border` `--soft-border` `--hover-border` `--divider` `--shadow` `--glass-shadow` `--hover-shadow` | Rules, hover |
| Glows | `--glow-1` `--glow-2` | Radial halo behind the page (transparent in light mode) |
| Radii | `--radius-lg` 16px · `--radius-md` 12px | |
| Navbar | `--nav-bg` `--nav-border` `--nav-link-hover-bg` `--nav-active` | Shared with the mobile tab bar |
| Rows | `--row-hover` | Table / list row hover |
| Layout | `--tabbar-h` | Height of the mobile tab bar (0 on desktop), read by `.ui-sticky-actions` |

**Light mode**: `html[data-theme="light"]` redefines the same variables (flat white canvas, dark amber `#B45309` for 5:1 on white, transparent glows). The theme is applied **before** the stylesheets by an inline script in `base.html` (no flash) and persisted in `localStorage["lowbid_theme"]`; `Lowbid.toggleTheme()` / `[data-theme-toggle]`.

---

## 2. CSS vocabulary (`lowbid-components.css`)

### Surfaces & structure

| Class | Use |
|-------|-----|
| `.glass-card` | Card (`--glass-bg` background, border, shadow, amber hover) |
| `.glass-soft` | Secondary inset (`--soft-bg`, 8px radius) |
| `.ui-panel` + `.ui-panel-head` `.ui-panel-title` `.ui-panel-sub` | Padded section; two consecutive panels space themselves |
| `.ui-page-header` + `.ui-page-title` `.ui-page-sub` `.ui-page-actions` | Page header (title + subtitle + buttons) — see `partials/page_header.html` |
| `.ui-section` + `.ui-section-head` `.ui-section-title` `.ui-section-sub` | h2 above a grid — see `components/section_head.html` |
| `.ui-split` (+ `.is-even`) / `.ui-stack` | Two columns 3/2 (or 1/1) from 1024px, stacked below; vertical stack |
| `.ui-facts` | Two-column `<dl>`, label / right-aligned value (the funding banner's totals) |
| `.ui-form-scope` | Declares a *container* so `.ui-sticky-actions` knows its width |

### Text

`.ui-meta` (12px grey) · `.ui-label` (uppercase label) · `.ui-link` · `.ui-num` / `.ui-num-strong` (tabular figures) · `.text-muted` · `.text-strong` · `.ui-price` + `.ui-price-unit` (amount + small unit) · `.font-mono`.

### Forms

`.ui-field` · `.ui-input` `.ui-select` `.ui-textarea` (44px, amber focus, `aria-invalid="true"` → red border) · `.ui-help` · `.ui-error` · `.ui-form-grid` (1 column, 2 from 640px, `.ui-field-wide` for full width) · `.ui-input-group` + `.ui-input-addon` (the « USDC » suffix of the task price) · `.ui-search` (input + icon + `[data-search-clear]`) · `.ui-select-inline` (compact toolbar select).

Server-side field errors from `Lowbid.api` land in `<p class="ui-error" data-error-for="<field>" hidden>` (add-task form: `title`, `price`, `tags`; apply form: `message`, `tags`; `_` for the rest).

### Buttons

`.ui-btn` + modifiers `-primary` `-ghost` `-danger` `-danger-solid` `-sm` `-lg` `-block`; states `:disabled` / `.is-loading` (an `<i class="fa-spinner">` spins). `.ui-copy-btn` (32px, icon only, `data-copy="…"`). `.lb-icon-btn` (40px, navbar).

### Badges, tags, alerts, states

| Class | Use |
|-------|-----|
| `.ui-badge` + `-ok` `-attn` `-danger` `-info` `-brand` `-neutral` | Status pill. Task: Ouvert `info`, Pris `brand`, Livré `attn`, Payé `ok`. Project: Brouillon `neutral`, Financé `ok`, Terminé `brand`. **`.ui-badge-brand` = « Recommandé » / « Choisi »**, `.ui-badge-ok.badge-validated` = « Validé » |
| `.ui-status` + `.ui-dot` (`.is-open` `.is-taken` `.is-delivered` `.is-paid`) | Coloured dot + label (kanban column titles) |
| `.ui-live` + `.ui-live-dot` | "live" with a pulsing dot (`[data-live-dot]` on the task page while polling) |
| `.ui-tag` (+ `.is-match`) | Skill; `.is-match` = also asked by the task |
| `.ui-chip-row` | Row of tags that scrolls horizontally on a phone, wraps from 768px (popular tags on the list page) |
| `.ui-alert` + `-ok` `-attn` `-danger` `-info` | Inline message with icon (payment errors `[data-last-error]`, « Tâche payée ») |
| `.empty-state` + `-icon` `-title` `-desc` | Centred empty state — see `components/empty_state.html` |
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
| `.lb-nav` `.lb-nav-inner` `.lb-brand` `.lb-brand-mark` `.lb-nav-links` `.lb-nav-link.is-active` `.lb-nav-actions` | Sticky glass bar (`partials/navbar.html`); desktop links from 1024px |
| `.lb-mobile-nav` (`#lb-mobile-nav`, `[data-nav-toggle]`) | Drop-down mobile menu under the bar |
| `.lb-wallet-btn` (+ `.is-connected`) `.lb-wallet-dot` `.lb-wallet-menu` `.lb-wallet-dropdown` `.lb-dropdown-item` | « Connecter » button / the connected wallet's menu (« Tableau de bord », « Mon profil public », logout) |
| `.lb-tabbar` + `.lb-tab` (+ `.is-active` `.is-primary`) | Fixed bottom tab bar, < 1024px, **signed-in only** (`body.has-tabbar`, `partials/tabbar.html`, fed by `NAV_LINKS`: Projets · Tableau · Créer (raised) · Mes projets · Bord) |
| `.seg-tabs` + `.seg-tab.is-active` | Segmented tabs (list filters: En cours / Terminés / Tous); full width below 480px |
| `.ui-toolbar` `.ui-toolbar-grow` `.ui-toolbar-end` | List toolbar (search · tabs · sort · count) |
| `.ui-pager` `.ui-pager-count` `.ui-pager-nav` `.ui-pager-btn` `.ui-pager-num.is-active` | Pagination; numbers hidden below 480px — see `components/pager.html` |

```html
<form method="get" class="ui-toolbar">
  <div class="ui-search ui-toolbar-grow"><i class="fa-solid fa-magnifying-glass"></i>
    <input class="ui-input" type="search" name="q" value="{{ q }}" placeholder="Rechercher un projet, une tâche, une compétence…">
    {% if q %}<button type="button" class="ui-search-clear" data-search-clear aria-label="Effacer"><i class="fa-solid fa-xmark"></i></button>{% endif %}
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
| `.ui-list` + `.ui-list-row` + `.ui-rank` | Vertical list separated by rules; `a.ui-list-row` is hoverable |
| `.rcard` | **Mandatory wrapper around a `<table>`**; every `<td data-label="Colonne">`; `th/td.ui-col-end` right-aligns; `tr.is-attn` highlights (a project with candidates to choose or a delivery to validate). Below 640px of **container** width the table becomes stacked cards (no horizontal scroll). Used by the project's task table (`.task-row[data-task-id][data-status]`, `projects/_task_row.html`), Mes projets and the profile |
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
`.ui-scorebar` is a 160px track; each segment's width is its points (out of 100): history brand, ratings `--info`, skills `--success`. `.cand-row.is-chosen` gets the brand-soft background, `.is-rejected` fades to 55 % opacity. The legend under the list repeats the weights (Historique 40, Notes ×8, Compétences 20).

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
`.kanban-wrap` is a container (`container-name: kanban`): 4 columns, 2 below 1024px, and below 640px one full-width column at a time with horizontal **snap-scroll** — the one deliberate exception to "no horizontal scroll" (the page itself never overflows). `.kanban-card.is-applied` marks a task the freelance already applied to.

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
The identicon's two hues are derived from the address by `Lowbid.identicon()` (JS) or the `|hue` filter (SSR, `style="--id-a:…;--id-b:…"`). → `components/wallet.html`.

### Sticky actions & misc

- `.ui-sticky-actions`: static on wide screens; below 640px of container width (it needs a `.ui-form-scope` ancestor) it becomes a glass bar stuck to the bottom, above the tab bar (`--tabbar-h`), with stretched buttons. Used by the project form, the add-task form, the apply form and the payment panel's forms.
- `.lb-toast-container` `.lb-toast` (+ `[data-type]`): toasts (`Lowbid.toast`).
- `.lb-hero*` `.lb-steps` `.lb-step*`: landing.
- Global keyboard focus: amber ring on `:focus-visible`. `@media print` hides nav, tab bar, toasts, sticky actions. `prefers-reduced-motion` stops animations.
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
| `partials/page_header.html` | `title`, `subtitle`, `actions` (safe HTML) | Page header |
| `partials/modal.html` / `partials/tabbar.html` / `partials/toasts.html` / `partials/navbar.html` | — | Included once by `base.html` |

Task-board partials (not generic, but reusable within `projects`): `_project_card.html` (list / landing card), `_task_row.html` (task table row), `_task_form.html` (inline add-task form), `_candidates.html` (ranked candidates), `_funding_panel.html` (project funding banner), `_board_card.html` (kanban card).

`base.html` blocks: `title`, `meta_description`, `extra_head`, `body_class`, `content`, `extra_js`. Context available everywhere: `wallet_address`, `wallet_user`, `nav_links`, `STELLAR_*`, `asset_code`, `asset_issuer`, `asset_native`, `payment_mode`, `LOWBID_ASSET_VERSION`, `messages`.

### Filters and tags (`{% load lowbid_extras %}`)

| | Example | Result |
|--|---------|--------|
| `short_addr` | `{{ addr\|short_addr }}` / `{{ addr\|short_addr:6 }}` | `GABC…WXYZ` (tolerates an empty `keep`) |
| `usdc` | `{{ x\|usdc }}` / `{{ x\|usdc:"" }}` / `{{ x\|usdc:asset_code }}` | `1,234.50 USDC` (unit = the configured asset) / `1,234.50`; `—` when empty |
| `plain` | `{{ x\|plain }}` | `500`, `400.5` (never `500.0000000`) — for `data-*` attributes |
| `qs` (tag) | `{% qs page=2 sort="" %}` | `?tab=active&page=2` — replaces / drops keys, keeps the rest |
| `pct` | `{{ done\|pct:total }}` | integer 0–100 |
| `hue` | `style="{{ addr\|hue }}"` | `--id-a:38;--id-b:200`: the identicon's two hues (same algorithm as `Lowbid.identicon`), rendered server-side so nothing flashes before the JS |

`{% load payments_extras %}`: `{% escrow_panel task wallet %}` renders `payments/_escrow_panel.html`.

---

## 4. JavaScript API (`window.Lowbid`)

Load order (`base.html`, not deferred unless noted): `lowbid-base.js` → `lowbid-ui.js` → `vendor/freighter-api.js` → `vendor/stellar-sdk.min.js` (`defer`) → `lowbid-wallet.js` → `lowbid-pay.js` (`defer`) → `{% block extra_js %}` (`lowbid-projects.js` on the project and task pages). Per-request values: `window.LOWBID` (`network`, `networkPassphrase`, `horizonUrl`, `sorobanRpcUrl`, `asset:{code, issuer, native}`, `paymentMode`, `walletAddress`, `urls:{challenge, verify, logout, landing, dashboard, trustlinePrepare, trustlineSend}`), `window.LOWBID_PROJECT` (project page: `id`, `status`, `isCompany`, `tasksCount`, `paymentMode`, `urls:{addTask, deleteTask, fund}`) and `window.LOWBID_TASK` (task page: `id`, `status`, `isCompany`, `isAssignee`, `urls:{candidates, apply, choose, deliver, validate, pay}`, `payAction`, `payMode` = the mode frozen on the task's escrow row).

### `lowbid-base.js`

- `Lowbid.api(url, {method, body})` → Promise JSON; adds CSRF + `Accept: application/json` + `X-Requested-With: fetch`; rejects with `err.status` / `err.data` on non-2xx.
- `Lowbid.toast(message, type="info|success|warning|error", {title, duration=4500})` → `{el, dismiss}`; `duration: 0` = sticky.
- `Lowbid.escapeHtml`, `Lowbid.csrf()`, `Lowbid.shortAddr(addr, keep)`, `Lowbid.formatUsdc(value, code)` (unit = `LOWBID.asset.code`; `code=""` → bare number), `Lowbid.toggleTheme()`.
- Delegated: `[data-theme-toggle]`, `[data-nav-toggle][aria-controls]`, `[data-copy="…"]` (toast « Adresse copiée »), closing the wallet menu.

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

- **Container queries** rather than media queries whenever a component can live in a column: `.rcard` (640px), `.ui-sticky-actions` (640px, `.ui-form-scope` ancestor), `.kanban` (1024px / 640px). Page grids (`.ui-split`, `.ui-kpi-band`, `.lb-steps`) use media queries.
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
