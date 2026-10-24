# Lowbid — Design system & front-end (référence)

Tout le front est **rendu côté serveur** (Django) et habillé par trois feuilles chargées dans cet ordre, dans `templates/base.html` :

1. `static/css/lowbid-tokens.css` — la palette (`:root`, mode clair sous `html[data-theme="light"]`) ;
2. `static/css/lowbid-components.css` — le vocabulaire `ui-` / `lb-` / `seg-` / `rcard` / `glass-` ;
3. `static/css/tailwind.css` — **artefact compilé** (`npm run build:css`), chargé en dernier pour que les utilitaires gagnent les égalités de spécificité.

Règles d'or : les composants ne lisent que des `var(--*)` (jamais une couleur en dur) ; toute classe Tailwind nouvelle impose de reconstruire **et committer** `tailwind.css` ; toute modification de `lowbid-*.css` / `lowbid-*.js` impose de bumper `LOWBID_ASSET_VERSION` (cache statique 30 jours).

---

## 1. Tokens (`lowbid-tokens.css`)

| Famille | Variables | Rôle |
|---------|-----------|------|
| Marque (ambre) | `--brand-500` `--brand-600` `--brand-700` `--brand-800` `--brand-soft` `--brand-ink` | Accent, boutons primaires (`--brand-ink` = texte sur fond ambre) |
| Marque RGB | `--brand-50-rgb` … `--brand-950-rgb` | Triplets `r g b` pour les utilitaires Tailwind `bg-brand-500/20` (voir `tailwind.config.js`) |
| Secondaire / accent | `--secondary-500` `--secondary-soft` `--accent-500` `--accent-soft` | Ciel / violet, usage ponctuel |
| Statut | `--success` `--warning` `--error` `--info` + `*-soft` | Couleur pleine + fond translucide |
| Texte de badge | `--ui-badge-ok-text` `--ui-badge-attn-text` `--ui-badge-danger-text` `--ui-badge-brand-text` `--ui-badge-info-text` | Garantit ≥ 4,5:1 sur le fond `*-soft` dans les deux thèmes |
| Typo | `--text-meta` 12px · `--text-body` 14px · `--text-heading` 16px · `--text-display` 28px · `--font-sans` · `--font-mono` | Échelle à 4 crans, police système (aucune web font) |
| Surfaces | `--bg-1/2/3` (canvas + dégradé) `--surface` `--surface-soft` `--glass-bg` `--soft-bg` | Fond de page, cartes, encarts |
| Texte | `--text` (= `--text-main`) `--muted` (= `--text-muted`) | Texte principal / secondaire |
| Bordures & ombres | `--border` `--border-strong` `--glass-border` `--soft-border` `--hover-border` `--divider` `--shadow` `--glass-shadow` `--hover-shadow` | Filets, survol |
| Lueurs | `--glow-1` `--glow-2` | Halo radial du fond (transparent en clair) |
| Rayons | `--radius-lg` 16px · `--radius-md` 12px | |
| Navbar | `--nav-bg` `--nav-border` `--nav-link-hover-bg` `--nav-active` | Partagé avec la barre d'onglets mobile |
| Lignes | `--row-hover` | Survol de ligne de tableau / liste |
| Layout | `--tabbar-h` | Hauteur de la barre d'onglets mobile (0 sur desktop), lue par `.ui-sticky-actions` |

**Mode clair** : `html[data-theme="light"]` redéfinit les mêmes variables (canvas blanc plat, ambre foncé `#B45309` pour 5:1 sur blanc, lueurs transparentes). Le thème est appliqué **avant** les feuilles par un script inline de `base.html` (anti-flash) et persisté dans `localStorage["lowbid_theme"]` ; `Lowbid.toggleTheme()` / `[data-theme-toggle]`.

---

## 2. Vocabulaire CSS (`lowbid-components.css`)

### Surfaces & structure

| Classe | Usage |
|--------|-------|
| `.glass-card` | Carte (fond `--glass-bg`, bordure, ombre, survol ambré) |
| `.glass-soft` | Encart secondaire (fond `--soft-bg`, rayon 8px) |
| `.ui-panel` + `.ui-panel-head` `.ui-panel-title` `.ui-panel-sub` | Section avec padding ; deux panneaux consécutifs s'espacent seuls |
| `.ui-page-header` + `.ui-page-title` `.ui-page-sub` `.ui-page-actions` | En-tête de page (titre + sous-titre + boutons) — voir `partials/page_header.html` |
| `.ui-section` + `.ui-section-head` `.ui-section-title` `.ui-section-sub` | Titre h2 au-dessus d'une grille — voir `components/section_head.html` |
| `.ui-split` (+ `.is-even`) / `.ui-stack` | Deux colonnes 3/2 (ou 1/1) à partir de 1024px, empilées en dessous ; pile verticale |
| `.ui-facts` | `<dl>` deux colonnes label / valeur alignée à droite |
| `.ui-form-scope` | Déclare un *container* pour que `.ui-sticky-actions` sache sa largeur |

### Texte

`.ui-meta` (12px gris) · `.ui-label` (étiquette majuscule) · `.ui-link` · `.ui-num` / `.ui-num-strong` (chiffres tabulaires) · `.text-muted` · `.text-strong` · `.ui-price` + `.ui-price-unit` (montant + unité réduite) · `.ui-countdown` (+ `.is-urgent`) · `.font-mono`.

### Formulaires

`.ui-field` · `.ui-input` `.ui-select` `.ui-textarea` (44px, focus ambré, `aria-invalid="true"` → bordure rouge) · `.ui-help` · `.ui-error` · `.ui-form-grid` (1 col, 2 cols ≥ 640px, `.ui-field-wide` pour pleine largeur) · `.ui-input-group` + `.ui-input-addon` (suffixe « USDC », « jours ») · `.ui-range` (slider) · `.ui-search` (champ + icône + `[data-search-clear]`) · `.ui-select-inline` (select compact de barre d'outils).

```html
<div class="seg-radio" role="radiogroup" aria-label="Durée">
  <input type="radio" id="d30" name="duration" value="30"><label for="d30">30 min</label>
  <input type="radio" id="d120" name="duration" value="120" checked><label for="d120">2 h</label>
</div>
```

### Boutons

`.ui-btn` + modificateurs `-primary` `-ghost` `-danger` `-danger-solid` `-sm` `-lg` `-block` ; état `:disabled` / `.is-loading` (un `<i class="fa-spinner">` tourne). `.ui-copy-btn` (32px, icône seule, `data-copy="…"`). `.lb-icon-btn` (40px, navbar).

### Badges, tags, alertes, états

| Classe | Usage |
|--------|-------|
| `.ui-badge` + `-ok` `-attn` `-danger` `-info` `-brand` `-neutral` | Statut en pastille ; **`.ui-badge-brand` = « Recommandé »** |
| `.ui-status` + `.ui-dot` | Point coloré + libellé |
| `.ui-live` + `.ui-live-dot` | « live » avec point pulsant |
| `.ui-tag` (+ `.is-match`) | Compétence ; `.is-match` = demandée par le client |
| `.ui-chip-row` | Rangée de tags qui défile horizontalement sur mobile, se replie ≥ 768px |
| `.ui-alert` + `-ok` `-attn` `-danger` `-info` | Message inline avec icône |
| `.empty-state` + `-icon` `-title` `-desc` | État vide centré — voir `components/empty_state.html` |
| `.ui-skeleton` / `.ui-skeleton-line` (+ `.w-1/2` `.w-1/3` `.w-3/4`) | Placeholders animés (`aria-hidden`) |
| `.ui-progress` (+ `.is-ok`) `> span` | Barre de progression (largeur en style inline) |

### KPI

```html
<section class="ui-kpi-band" aria-label="Chiffres clés">        <!-- 2 colonnes, 4 ≥ 768px ; .is-3 pour trois -->
  <a href="…" class="ui-kpi-tile is-link">
    <span class="ui-kpi-head"><span class="ui-kpi-label">Budget max</span><span class="ui-kpi-icon"><i class="fa-solid fa-coins"></i></span></span>
    <span class="ui-kpi-value">500<span class="ui-price-unit">USDC</span></span>
    <span class="ui-kpi-hint ui-meta">prix plafond</span>
  </a>
</section>
```
→ `components/kpi.html`.

### Navigation

| Classe | Usage |
|--------|-------|
| `.lb-nav` `.lb-nav-inner` `.lb-brand` `.lb-brand-mark` `.lb-nav-links` `.lb-nav-link.is-active` `.lb-nav-actions` | Barre sticky en verre (`partials/navbar.html`) ; liens desktop ≥ 1024px |
| `.lb-mobile-nav` (`#lb-mobile-nav`, `[data-nav-toggle]`) | Menu déroulant mobile sous la barre |
| `.lb-wallet-btn` (+ `.is-connected`) `.lb-wallet-dot` `.lb-wallet-menu` `.lb-wallet-dropdown` `.lb-dropdown-item` | Bouton « Connecter le wallet » / menu du wallet connecté |
| `.lb-tabbar` + `.lb-tab` (+ `.is-active` `.is-primary`) | Barre d'onglets fixe en bas, < 1024px, **seulement wallet connecté** (`body.has-tabbar`, `partials/tabbar.html`, alimentée par `NAV_LINKS`) |
| `.seg-tabs` + `.seg-tab.is-active` | Onglets segmentés (filtres de liste) ; pleine largeur < 480px |
| `.ui-toolbar` `.ui-toolbar-grow` `.ui-toolbar-end` | Barre d'outils de liste (recherche · onglets · tri · compteur) |
| `.ui-pager` `.ui-pager-count` `.ui-pager-nav` `.ui-pager-btn` `.ui-pager-num.is-active` | Pagination ; les numéros disparaissent < 480px — voir `components/pager.html` |

```html
<form method="get" class="ui-toolbar">
  <div class="ui-search ui-toolbar-grow"><i class="fa-solid fa-magnifying-glass"></i>
    <input class="ui-input" type="search" name="q" value="{{ q }}" placeholder="Rechercher…">
    {% if q %}<button type="button" class="ui-search-clear" data-search-clear aria-label="Effacer"><i class="fa-solid fa-xmark"></i></button>{% endif %}
  </div>
  <nav class="seg-tabs">…</nav>
  <div class="ui-toolbar-end">
    <label class="ui-select-inline"><span class="ui-meta">Trier</span><select name="sort" class="ui-select" data-auto-submit>…</select></label>
    <span class="ui-meta">12 besoins</span>
  </div>
</form>
```

### Menus & modales

```html
<details class="ui-menu">
  <summary class="ui-btn ui-btn-sm"><i class="fa-solid fa-ellipsis"></i></summary>
  <div class="ui-menu-panel">                              <!-- .is-start pour l'aligner à gauche -->
    <div class="ui-menu-label">Actions</div>
    <a class="ui-menu-item" href="…"><i class="fa-solid fa-share-nodes"></i> Partager</a>
    <div class="ui-menu-sep"></div>
    <button class="ui-menu-item is-active" type="button">…</button>
  </div>
</details>
```
Le menu s'ouvre sans JS ; `lowbid-ui.js` le ferme au clic extérieur et à `Échap`.

```html
<dialog class="ui-modal is-danger">                    <!-- top layer natif ; backdrop flouté -->
  <form method="dialog" class="ui-modal-card">
    <div class="ui-modal-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
    <h2 class="ui-modal-title">Annuler ce besoin ?</h2>
    <p class="ui-modal-body">Cette action est définitive.</p>
    <div class="ui-modal-actions"><button value="cancel" class="ui-btn ui-btn-ghost">Annuler</button><button value="ok" class="ui-btn ui-btn-danger-solid">Confirmer</button></div>
  </form>
</dialog>
```
La modale de confirmation globale `#lb-confirm` (`partials/modal.html`, dans `base.html`) est pilotée par `Lowbid.confirm()` ; pour une modale sur mesure : `Lowbid.modal.open("#id")` / `close`.

### Listes, lignes, tableaux

| Classe | Usage |
|--------|-------|
| `.ui-list` + `.ui-list-row` + `.ui-rank` | Liste verticale séparée par des filets ; `a.ui-list-row` survolable |
| `.bid-row` (+ `.is-won` `.is-lost`) | Ligne d'offre (hérite de `.ui-list-row`) |
| `.need-card` | Carte de besoin (lift au survol) |
| `.ui-scorebar` + `.ui-scorebar-seg.is-price/.is-delay/.is-skills` | Barre de score tri-segment (largeurs inline en %) |
| `.rcard` | **Wrapper obligatoire autour d'un `<table>`** ; chaque `<td data-label="Colonne">` ; `th/td.ui-col-end` aligne à droite ; `tr.is-attn` surligne. Sous 640px de largeur de **conteneur**, le tableau devient des cartes empilées (pas de scroll horizontal) |

```html
<div class="rcard"><table>
  <thead><tr><th>Besoin</th><th class="ui-col-end">Offres</th></tr></thead>
  <tbody><tr><td data-label="Besoin">…</td><td data-label="Offres" class="ui-col-end ui-num">3</td></tr></tbody>
</table></div>
```

### Chronologie, « et maintenant », sparkline

```html
<ol class="ui-timeline">
  <li class="ui-timeline-item is-brand"><span class="ui-timeline-dot"><i class="fa-solid fa-check"></i></span>
    <div class="ui-timeline-body"><div class="ui-timeline-title">GABC…WXYZ propose 400 USDC</div><div class="ui-timeline-time" data-time-ago="2026-10-24T21:00:00Z"></div></div></li>
  <li class="ui-timeline-item is-ok">…</li>
  <li class="ui-timeline-item is-muted">…</li>          <!-- offre remplacée -->
</ol>
```

```html
<a href="…" class="ui-next-card act">                    <!-- act = c'est à vous · wait = à quelqu'un d'autre · done -->
  <span class="ui-next-kicker"><span class="ui-next-dot"></span>À faire</span>
  <div class="ui-next-row"><div><p class="ui-next-headline">Choisir une offre</p><p class="ui-next-body">3 offres reçues</p></div><span class="ui-btn ui-btn-sm ui-btn-primary">Choisir</span></div>
</a>
<div class="ui-next-list">…plusieurs cartes…</div>
```
→ `components/next_card.html`.

```html
<svg class="ui-sparkline" data-points="500,450,420,400" data-cap="500" role="img" aria-label="Historique des prix"></svg>
<div class="ui-sparkline-meta"><span>500 USDC</span><span>400 USDC</span></div>
```
`Lowbid.sparkline(el)` dessine la ligne, l'aire, le point final et la ligne pointillée du plafond (`data-cap`) ; `Lowbid.refreshUI()` le fait pour tout `svg.ui-sparkline[data-points]`.

### Wallet (identicon + adresse)

```html
<a href="{% url 'dashboard:profile' addr %}" class="ui-wallet" data-identicon="{{ addr }}" title="{{ addr }}">
  <span class="ui-identicon is-lg" aria-hidden="true"></span>            <!-- is-lg 44px · is-xl 64px -->
  <span class="ui-wallet-text"><span class="ui-wallet-name">Claire</span><span class="ui-wallet-addr">GABC…WXYZ</span></span>
</a>
<button class="ui-copy-btn" data-copy="{{ addr }}"><i class="fa-regular fa-copy"></i></button>
```
Les deux teintes de l'identicon sont dérivées de l'adresse par `Lowbid.identicon()` (JS) ou le filtre `|hue` (SSR, `style="--id-a:… ;--id-b:…"`). → `components/wallet.html`.

### Actions collantes & divers

- `.ui-sticky-actions` : statique sur écran large ; sous 640px de largeur de conteneur (il faut un ancêtre `.ui-form-scope`), devient une barre de verre collée en bas, au-dessus de la barre d'onglets (`--tabbar-h`), boutons étirés.
- `.ui-stepper` + `.ui-step.is-done/.is-current` `.ui-step-dot` `.ui-step-label` : frise du paiement.
- `.ui-balance.is-bumped` : solde USDC qui vient de bouger.
- `.lb-toast-container` `.lb-toast` (+ `[data-type]`) : toasts (`Lowbid.toast`).
- `.lb-hero*` `.lb-steps` `.lb-step*` : landing.
- Focus clavier global : anneau ambré sur `:focus-visible`. `@media print` masque nav, tabbar, toasts, actions collantes. `prefers-reduced-motion` coupe les animations.

---

## 3. Composants de template (`templates/components/`)

| Include | Paramètres | Rend |
|---------|-----------|------|
| `components/wallet.html` | `address` (obligatoire), `name`, `label`, `size="lg\|xl"`, `keep` (chars conservés, 4), `copy=True`, `nolink=True`, `you=True` | Identicon + adresse abrégée, lien vers `dashboard:profile` sauf `nolink` |
| `components/status_badge.html` | `need`, `live=True` (ajoute `data-status-badge`) | `.ui-badge` du statut effectif |
| `components/countdown.html` | `need`, `main=True` (`data-countdown-main`), `class` | `.ui-countdown` tické par `lowbid-auctions.js` |
| `components/tags.html` | `tags`, `linked=True` (filtre de liste), `matched` (ensemble), `class` | Rangée de `.ui-tag` |
| `components/kpi.html` | `label`, `value` (déjà formaté), `unit`, `hint`, `icon`, `href`, `attr` (ex. `"data-kpi-best"`) | Tuile KPI, lien si `href` |
| `components/price.html` | `amount` (Decimal ou None), `size` (classe), `attr` | `.ui-price` + unité `STELLAR_USDC_CODE` |
| `components/empty_state.html` | `icon`, `title`, `desc`, `cta_href`, `cta_label`, `cta_icon`, `class` | État vide en carte |
| `components/pager.html` | `page` (objet `Page` Django) | Pagination conservant la query string (`{% qs %}`) |
| `components/next_card.html` | `tone="act\|wait\|done"`, `kicker`, `headline`, `body`, `href`, `cta`, `icon` | Carte « et maintenant » |
| `components/section_head.html` | `title`, `sub`, `icon`, `link_href`, `link_label` | Titre de section + lien |
| `partials/page_header.html` | `title`, `subtitle`, `actions` (HTML sûr) | En-tête de page |
| `partials/modal.html` / `partials/tabbar.html` / `partials/toasts.html` / `partials/navbar.html` | — | Inclus une fois par `base.html` |

Blocs de `base.html` : `title`, `meta_description`, `extra_head`, `body_class`, `content`, `extra_js`. Contexte disponible partout : `wallet_address`, `wallet_user`, `nav_links`, `STELLAR_*`, `LOWBID_ASSET_VERSION`, `messages`.

### Filtres et tags (`{% load lowbid_extras %}`)

| | Exemple | Résultat |
|--|---------|----------|
| `short_addr` | `{{ addr\|short_addr }}` / `{{ addr\|short_addr:6 }}` | `GABC…WXYZ` (tolère `keep` vide) |
| `usdc` | `{{ x\|usdc }}` / `{{ x\|usdc:"" }}` | `1,234.50 USDC` / `1,234.50` ; `—` si vide |
| `plain` | `{{ x\|plain }}` | `500`, `400.5` (jamais `500.0000000`) — pour `max=`, `data-*` |
| `qs` (tag) | `{% qs page=2 sort="" %}` | `?tab=open&page=2` — remplace/retire des clés, garde le reste |
| `pct` | `{{ done\|pct:total }}` | entier 0–100 |
| `hue` | `style="{{ addr\|hue }}"` | `--id-a:38;--id-b:200` : les deux teintes de l'identicon (même algorithme que `Lowbid.identicon`), rendues côté serveur pour éviter tout flash avant le JS |

`{% load payments_extras %}` : `{% escrow_panel need wallet %}` rend `payments/_escrow_panel.html`.

---

## 4. API JavaScript (`window.Lowbid`)

Chargement (`base.html`, non différé sauf mention) : `lowbid-base.js` → `lowbid-ui.js` → `vendor/freighter-api.js` → `vendor/stellar-sdk.min.js` (`defer`) → `lowbid-wallet.js` → `lowbid-pay.js` (`defer`) → `{% block extra_js %}` (`lowbid-auctions.js` sur les pages enchères). Valeurs par requête : `window.LOWBID` (`network`, `networkPassphrase`, `horizonUrl`, `sorobanRpcUrl`, `usdc:{code,issuer}`, `walletAddress`, `urls:{challenge,verify,logout,landing,dashboard,trustlinePrepare,trustlineSend}`) et `window.LOWBID_NEED` (page détail).

### `lowbid-base.js`

- `Lowbid.api(url, {method, body})` → Promise JSON ; ajoute CSRF + `Accept: application/json` + `X-Requested-With: fetch` ; rejette avec `err.status` / `err.data` sur non-2xx.
- `Lowbid.toast(message, type="info|success|warning|error", {title, duration=4500})` → `{el, dismiss}` ; `duration: 0` = persistant.
- `Lowbid.escapeHtml`, `Lowbid.csrf()`, `Lowbid.shortAddr(addr, keep)`, `Lowbid.formatUsdc(value, code)` (`code=""` → nombre seul), `Lowbid.toggleTheme()`.
- Délégué : `[data-theme-toggle]`, `[data-nav-toggle][aria-controls]`, `[data-copy="…"]` (toast « Adresse copiée »), fermeture du menu wallet.

### `lowbid-ui.js`

- `Lowbid.confirm({title, message, confirmLabel, cancelLabel, danger, icon})` → `Promise<boolean>` (repli `window.confirm` si `<dialog>` indisponible).
- `Lowbid.modal.open(el|"#id")` / `Lowbid.modal.close(el, value)` ; focus sur `[data-autofocus]`.
- `Lowbid.identicon(address)` → `{a, b}` ; appliqué à `[data-identicon]` (vars `--id-a/--id-b` sur `.ui-identicon` enfant ou l'élément).
- `Lowbid.timeAgo(iso)` → « il y a 3 min » / « dans 2 h » ; `[data-time-ago="ISO"]` rafraîchi chaque minute, `title` = date locale.
- `Lowbid.sparkline(svg)` (voir §2).
- `Lowbid.poll(fn, {interval=5000, maxInterval=60000})` → `{stop(), now()}` : pause quand l'onglet est caché, reprise immédiate au retour / `online`, backoff ×2 sur rejet.
- `Lowbid.refreshUI(root)` : relance identicons + sparklines + time-ago dans un fragment injecté.
- `Lowbid.setBusy(btn, on, label)` : bouton occupé (spinner, `aria-busy`), restaure le libellé.
- Délégué : `[data-share="URL"]` (Web Share ou copie), `form[data-confirm="…"]` (+ `data-confirm-title`, `data-confirm-danger`) demande confirmation avant envoi, `[data-search-clear]`, `[data-auto-submit]`, fermeture des `details.ui-menu` (clic extérieur / Échap).

### `lowbid-wallet.js`

`Lowbid.wallet.isInstalled/isConnected/getAddress/requestAccess/ensureNetwork/signMessage/connect(next)/disconnect()` ; `Lowbid.signTransaction(xdr, {networkPassphrase?, address?})` → XDR signé. Boutons `[data-wallet-connect][data-next]`.

### `lowbid-pay.js`

Markup : `<button data-pay-step="fund" data-prepare-url="/pay/…" [data-send-url] [data-pay-body='{…}'] [data-loading-label] [data-no-reload]>`, `<p data-pay-error hidden>` (le plus proche reçoit l'erreur serveur), `<button data-pay-trustline>`, `<span data-usdc-balance="G…" data-watch>` (Horizon : 5 s pendant 2 min, puis 15 s, jusqu'à 15 min). Contrat serveur : `prepare` → `{ok, xdr, send_url, extra?}` ; `send` `{signed_xdr, …extra}` → `{ok, hash?, contract_id?, redirect?, message?, error?}`. API : `Lowbid.pay.signAndSend({xdr, sendUrl, extra})`, `runStep(button)`, `ensureTrustline(button?)`, `watchBalance(el, {interval, maxMs})` → `stop()`, `fetchUsdcBalance(address)`, `explorerTxUrl/explorerAccountUrl/explorerContractUrl`.

### `lowbid-auctions.js`

- Compte à rebours : `<span class="ui-countdown" data-ends-at="ISO" data-status="open|…">` ; `data-status != open` → « Terminé » ; `.is-urgent` sous 10 min ; à zéro, émet `lowbid:countdown-end` (bulle) ; `[data-countdown-main]` déclenche un rafraîchissement de la liste.
- `Lowbid.parseTags(raw)` (même normalisation que `services.clean_tags`).
- `form[data-submit-once]` : un seul envoi.
- Page détail (`window.LOWBID_NEED = {id, status, budgetMax, bestPrice, weights, isClient, canChoose, showRecommended, urls:{bids, bid, close, cancel, award}}`) : formulaire `#bid-form` (`#bid-price`, `#bid-delay`, `#bid-tags`, `#bid-message`, `[data-bid-submit]`, `[data-error-for="price|delay_days|tags|_"]`, `[data-price-cap]`, `[data-add-tag]`), polling de `encheres.json` toutes les 5 s (remplace `#bids-list` quand `fingerprint` change, met à jour `[data-kpi-count]`, `[data-kpi-best]`, affiche `[data-live-dot]`, recharge si le statut change), curseurs `[data-weight]` / `[data-weight-out]` / `[data-weights-reset]` (somme 100, re-classement côté client depuis `data-price-ratio/-delay-ratio/-skills-ratio`, badge `[data-recommended]`), actions `[data-choose]`, `[data-need-close]`, `[data-need-cancel]` (confirmation via `Lowbid.confirm`).

---

## 5. Responsive & accessibilité

- **Container queries** plutôt que media queries dès que le composant peut vivre dans une colonne : `.rcard` (640px), `.ui-sticky-actions` (640px, ancêtre `.ui-form-scope`). Les grilles de page (`.ui-split`, `.ui-kpi-band`, `.lb-steps`) utilisent des media queries.
- Points de rupture : 480 (onglets pleine largeur, numéros de pagination masqués, actions de modale en colonne), 640 (formulaires 2 colonnes, toasts pleine largeur), 768 (KPI 4 colonnes, tags repliés), 1024 (liens de nav desktop, barre d'onglets mobile masquée, deux colonnes).
- Aucune page ne doit scroller horizontalement : `body` est `overflow-x-hidden`, les cellules utilisent `overflow-wrap: anywhere`, les grilles `min-w-0`. L'e2e vérifie `scrollWidth <= innerWidth` à 390×844.
- Cibles tactiles 44px (boutons, champs, lignes de liste, pager) ; 40px pour les contrôles secondaires de navbar.
- Barre d'onglets mobile : `body.has-tabbar` ajoute un `padding-bottom` = `--tabbar-h` + safe-area ; les toasts restent en haut.
- Accessibilité : `aria-label` sur les nav, `aria-current="page"` sur l'onglet actif, `role="status"` / `role="alert"` sur messages et toasts, `aria-live="polite"` sur le conteneur de toasts, `aria-hidden` sur les icônes décoratives, `sr-only` pour les libellés d'icône, focus visible global, `<dialog>` natif (focus piégé, Échap), `prefers-reduced-motion` respecté, RTL-ready (propriétés logiques `inset-inline-*`, `margin-inline-*`).

---

## 6. Recettes

**Page liste (toolbar + grille + pager)**
```django
{% extends "base.html" %}{% load static lowbid_extras %}
{% block content %}
{% include "partials/page_header.html" with title="Besoins" subtitle="…" %}
<form method="get" class="ui-toolbar">…(§2 Navigation)…</form>
{% if page.object_list %}
  <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{% for need in page %}{% include "auctions/_need_card.html" %}{% endfor %}</div>
  {% include "components/pager.html" with page=page %}
{% else %}
  {% include "components/empty_state.html" with icon="fa-gavel" title="Aucun besoin" cta_href=… cta_label="Poster un besoin" %}
{% endif %}
{% endblock %}
{% block extra_js %}<script src="{% static 'js/lowbid-auctions.js' %}?v={{ LOWBID_ASSET_VERSION }}"></script>{% endblock %}
```

**Page détail (deux colonnes)**
```django
<section class="ui-kpi-band mb-6">{% include "components/kpi.html" with label=… value=… %}…</section>
<div class="ui-split">
  <div class="ui-stack"><section class="ui-panel">…contenu…</section><section class="ui-panel">…liste / timeline…</section></div>
  <aside class="ui-stack"><section class="ui-panel">…formulaire ou action…</section>{% escrow_panel need wallet %}</aside>
</div>
```

**Formulaire avec bouton collant sur mobile**
```django
<form method="post" class="ui-panel ui-form-scope max-w-3xl" novalidate data-submit-once>
  {% csrf_token %}
  <div class="ui-form-grid">…`.ui-field`…</div>
  <div class="ui-sticky-actions"><a href="…" class="ui-btn ui-btn-ghost">Annuler</a><button class="ui-btn ui-btn-primary">Publier</button></div>
</form>
```

**Tuile de tableau de bord**
```django
{% include "components/kpi.html" with label="Besoins ouverts" value=open_count icon="fa-list-ul" href=need_list_url hint="en cours d’enchères" %}
{% include "components/next_card.html" with tone="act" kicker="À faire" headline="Choisir une offre" body="3 offres reçues" href=need_url cta="Choisir" icon="fa-check" %}
```

**Confirmer puis appeler l'API**
```js
Lowbid.confirm({ title: "Clôturer ?", message: "Plus aucune offre ne sera acceptée.", confirmLabel: "Clôturer" }).then(function (ok) {
  if (!ok) return;
  Lowbid.setBusy(btn, true, "Clôture…");
  Lowbid.api(url, { method: "POST" }).then(function (d) { Lowbid.toast(d.message, "success"); location.reload(); })
    .catch(function (err) { Lowbid.setBusy(btn, false); Lowbid.toast((err.data && err.data.message) || "Action impossible.", "error"); });
});
```
