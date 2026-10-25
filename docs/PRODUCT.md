# TaskVault — Product spec

> A company splits a project into tasks, each with a budget. Freelances apply with their own price (at most the budget). The company picks one freelance per task, at the price that freelance proposed. Each task is paid in USDC from its own escrow on Stellar when the company validates the delivery.

Hackathon version (Hack Meridian, Stellar **testnet** only). UI copy is English and is quoted as-is below; URL paths stay French (`/projets/`, `/taches/`, …). The payment asset is configurable (`STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER`, default Circle testnet USDC); "USDC" below means that asset.

> History: TaskVault v1 was a reverse auction; the task board replaced it on 2026-10-25.

The rules below are derived from `projects/services.py`, `projects/scoring.py` and `payments/services.py`; each one is covered by `projects/tests.py`, `projects/tests_links.py`, `projects/tests_seed.py`, `payments/tests.py`, `payments/tests_flow.py`, `payments/tests_dispute.py` or the e2e run (`tests/e2e/run.js`).

## 1. Personas

**Claire, runs Studio Nova (the company)**
- A 12-person studio that ships two or three small web projects a year for its clients and cannot staff all of them.
- Knows what each piece of work is worth and wants to fix the price herself, not negotiate it.
- Wants to pay only for work that was delivered, and to see quickly which freelances already worked well for her.

**Yanis, freelance dev (freelance A)**
- Independent, three years of Django and UI work.
- Once waited 60 days for a wire transfer, and once was never paid.
- Wants proof that the money exists *before* starting, and to be paid within seconds of delivering.

**Nora, freelance Stellar / JS (freelance B)**
- Strong skills, no history with Studio Nova yet.
- Wants a fair chance: her skills count in the ranking even without history, and the company stays free to pick her.

## 2. The flow

1. The company connects its **Freighter** wallet (testnet). Login is a signed message, no password.
2. It creates a **project** ("New project": title, description) and adds **tasks** inline on the project page: title, description, **budget** in USDC (the maximum price), up to 3 skill tags. The project is "Draft".
3. Freelances connect their own wallet and browse the project list (`/projets/`) or the **kanban** (`/taches/`: Open · Taken · Delivered · Paid).
4. A freelance **applies** to an open task ("Apply to this task" → "Send my application"): **their price** (prefilled with the budget, at most the budget), a message of up to 280 characters and up to 3 tags.
5. The task page ranks the candidates by **score** (§4) and shows the badges "Validated" and "Recommended". The list refreshes every 5 seconds while the task is open.
6. **The company chooses** one candidate ("Choose", confirmed in a dialog). The task becomes "Taken" and its price becomes the chosen freelance's price, the chosen application "Chosen", every other one "Not selected".
7. The company **funds**: "Fund the project" creates one Trustless Work escrow per task with a chosen freelance ("Create the escrow", first Freighter signature) and locks the task's price in it ("Lock the funds", second signature). The project becomes "Funded" once every assigned task holds its money.
8. The freelance **delivers**: a link to the PR, the demo or the repository, optionally a **fingerprint** of the work (git commit SHA or SHA-256) and the link to the **full deliverable** (repository, archive…), then "Declare the delivery". In escrow mode this marks the escrow's milestone as done on chain, with the fingerprint and the link as evidence (one signature by the freelance). The task becomes "Delivered" and the company's **review window** opens (`LOWBID_REVIEW_DAYS`, default 7 days, R33). The full deliverable stays hidden from the company until the task is paid; the fingerprint lets it check later that the revealed work is the one declared. Every link is shown with its domain in large type, and a link outside the trusted hosts carries "Unknown domain — open with care" (R43–R44).
9. Within the review window the company either **requests changes** ("Request changes" with a message, at most `LOWBID_MAX_REVISIONS` times, R34–R35: the task goes back to "Taken", the money stays locked and the freelance delivers again, every delivery kept in the history, R36), or — in escrow mode — **opens a dispute** if the delivery does not match ("Open a dispute" with a reason, R37–R38: the escrow is frozen on chain and the arbiter splits it from `/litiges/`, R39–R41), or it **validates and rates** (the "Validate + rate" step: 1 to 5 stars, optional comment, submitted with "Validate and release …"). The rating is saved first; then the page asks for two signatures: "Validate the delivery" (approve) and "Release the funds" (release). The escrow pays the freelance, minus fees, and the task becomes "Paid".
10. When every task of the project is paid (or resolved by the arbiter), the project is "Closed". If the company never answers, the freelance may open a dispute for no response once the review window is over (R37). The freelance's rating and paid task now count in the score of that company's next tasks.

**Direct mode** (fallback: `LOWBID_PAYMENT_MODE=direct`, or an empty mode without `TRUSTLESS_WORK_API_KEY`, and always when the asset is native XLM): step 7 does not exist ("Fund the project" is not shown), step 8 is a declaration without a transaction, step 9 ("Validate and pay …") ends with one "Pay the freelancer" payment signed by the company, change requests work the same way, and there is no dispute: the panel warns "unprotected payment" (R42).

## 3. Business rules (testable statements)

### Identity
- **R1** The wallet is the identity: login is a SEP-53 signature of a server challenge (`/auth/challenge/` → `/auth/verify/`, TTL `WALLET_CHALLENGE_TTL_SECONDS` = 300 s), single use: any verify attempt consumes it, a failed signature included (the wallet asks a fresh one per login). Any wallet can act as a company on its own projects and as a freelance on other projects.

### Projects and tasks
- **R2** Any signed-in wallet can create a project; it becomes that project's company. Title 3 to 120 characters, description required. A new project is `draft` ("Draft").
- **R3** Only the project's company can add a task (`forbidden`, 403), at any time until the project is `closed` (`wrong_state`, 409): one escrow per task means funding locks a task's price, never the project. Title 3 to 120 characters; price strictly positive (a comma is accepted as decimal separator), at most 7 decimals, below 10¹¹ (`invalid`, 400); tags given as a list or as a string split on commas, spaces or semicolons, normalised to lowercase slugs, de-duplicated, at most 3, at most 24 characters each (`bad_tags`, 400); description optional.
- **R4** A task can be deleted only by the company and only while it is `open` (`wrong_state` once a freelance is chosen), whatever the project status. Its applications are deleted with it.

### Applications, score and badges
- **R5** Any signed-in wallet except the project's company can apply to an `open` task (`wrong_state`, 409, checked first; `own_task`, 403), once per task (`duplicate`, 409, also a database constraint). Message at most 280 characters (`invalid`); tags as in R3. An application carries the freelance's **price**: required by the endpoint, strictly positive, 7 decimals at most (`invalid`), at most the task's budget (`over_budget`, 400). The price never changes the score.
- **R6** The ranked candidate list and the scores are public (task page and `GET /taches/<pk>/candidats.json`). Only the company sees "Choose", on every row, and only while the task is open.
- **R7** The score (§4) is computed when the application is created and stored. After every rating and every paid task of a company, the pending applications on that company's open tasks are rescored.
- **R8** "Recommended": exactly one application per open task carries it, the best score among the **pending** applications; ties go to the earliest application. It disappears once the task is no longer open.
- **R9** "Validated" is relative to the company looking at the candidate: the freelance has at least one task **paid** by this company **and** an average rating from this company of at least 3. The same freelance can be "Validated" for one company and new to another.

### Choice
- **R10** Only the company chooses (`forbidden`), only on an `open` task (`wrong_state`: "A freelancer has already been chosen for this task."). It may choose **any** application of the task, recommended or not. The chosen application becomes `chosen`, every other one `rejected`, the task `taken` with `assigned_to` = the freelance and `price` = the chosen application's price (what the escrow locks or the direct payment sends; it can only lower the project budget, so deposit coverage holds). A choice cannot be undone.

### Funding
- **R11** A task can be funded only once a freelance is chosen (`not_chosen`): Trustless Work fixes the escrow's receiver when it is deployed. In escrow mode the company signs `deploy` then `fund` for each task; the escrow's amount is the task's price and its receiver is the chosen freelance. "Fund the project" chains both steps for every `taken` task whose escrow is not funded yet (two signatures per task); with nothing to fund it is disabled and says why.
- **R12** A project moves from `draft` to `funded` ("Funded") when every assigned (non-open) task's escrow holds its money (escrow mode), or at the first payment (direct mode, where nothing is locked in advance). It goes back to `draft` when a freelance is chosen for a task whose escrow holds nothing yet (escrow mode, no direct payment made), so "Funded" always means every assigned task is covered; a `closed` project never changes. Tasks can still be added; only an `open` task can be deleted (R4).

### Delivery
- **R13** Only the chosen freelance delivers (`not_assigned`: 403 on the database endpoint, HTTP 200 `{ok:false}` on the payment endpoints), only a `taken` task (`wrong_state`). The link is required, starts with `http://` or `https://` and has at most 500 characters (`invalid`). In escrow mode the delivery is an on-chain milestone change signed by the freelance, possible only once the escrow is funded (a database-only delivery is refused); the evidence (R32) goes on chain. In direct mode the delivery is a declaration with no transaction.
- **R30** *Fingerprint.* The delivery may carry a fingerprint of the work (`Task.delivery_hash`): empty, or exactly 40 hexadecimal characters (a git commit SHA) or 64 (a SHA-256), normalised to lowercase; anything else is refused (`invalid`, on the database endpoint and on both payment endpoints, before anything is written or signed). Once delivered, the fingerprint is public (task page and payment panel, with a copy button); in escrow mode it is part of the on-chain evidence, in direct mode it exists in the database only and the panel says so.
- **R31** *Two-step delivery.* The delivery link (`Task.delivery_link`, demo / preview, required) is public once the task is delivered. The full deliverable (`Task.source_link`, optional, same http(s) / 500-character rules as the link) is visible to the chosen freelance always, to the company **only once the task is settled** (`paid`, or `resolved` by the arbiter, R41), and to nobody else (`projects.services.source_visible`; the templates only read the boolean the view computed). Before payment the company sees "Full deliverable revealed once the task is paid" and the fingerprint, so it can later verify the revealed work is the one declared.
- **R32** *Evidence format.* What goes on chain as the milestone evidence (`newEvidence`) and is kept in `Escrow.delivery_note` is `payments.services.build_evidence(link, hash)`: `sha256:<64 hex> <link>` or `git:<40 hex> <link>` when a fingerprint was given, else `<link>`, cut at 280 characters (the fingerprint comes first, so a truncation only ever shortens the link). The full deliverable link never goes on chain.

### Review window and revisions
- **R33** *Review window.* Once a task is `delivered`, the company has `LOWBID_REVIEW_DAYS` days (default 7) to validate or to request changes: `review_deadline(task)` = `delivered_at` + that many days while the task is `delivered` (None otherwise), computed when a page is read — nothing runs on a timer. The deadline is shown to everyone on the task page and in the payment panel (`[data-review-deadline]`, with a live countdown; "Review window over" once passed). `is_review_overdue(task)` is true when the task is delivered, unrated and the deadline is past — the freelance's protection: from there the freelance may open a dispute for no response (R37). A change request clears `delivered_at`: the window restarts at the next delivery.
- **R34** *Request changes.* Only the company (`forbidden`), only a `delivered` task (`wrong_state`) that is not rated yet (`wrong_state`: "already been validated"), with a non-empty message of at most 280 characters telling the freelance what to change (`invalid`). Effects, in one transaction: a `RevisionRequest` row (company, message), the task goes `delivered → taken`, `revision_count` += 1, `delivered_at` = None; then the payments hook moves the escrow row back — `delivered → funded` in escrow mode (the money stays locked, every transaction hash is kept), `delivered → created` in direct mode; an escrow at any other stage refuses the request (`wrong_state`). The chosen freelance then delivers again ("Deliver again"), through the same deliver step: in escrow mode a second `change-milestone-status` with the new evidence (the contract accepts it), in direct mode a declaration.
- **R35** *Maximum.* At most `LOWBID_MAX_REVISIONS` change requests per task (default 2): the next one is refused with `too_many_revisions` (409, the message states the maximum) and the UI disables "Request changes" with "Revisions requested: n/N". After the maximum the company validates (or disputes, R37).
- **R36** *History.* Every (re)delivery is a `Delivery` row (freelance, link, fingerprint, full-deliverable link, the on-chain transaction hash in escrow mode, date) written by `projects.services.deliver`; the task itself holds the latest one. The task page lists deliveries and change requests newest first (`[data-delivery-history]`), visible to everyone; a delivery's full-deliverable link obeys R31 (never in the markup otherwise). A replay of a previous delivery's signed transaction is refused (`tampered`): the new delivery needs its own signature.

### Disputes (escrow mode only)
- **R37** *Who may open a dispute.* `payments.services.can_dispute(task, wallet)` → `(allowed, why)`: escrow mode only, then `projects.services.can_dispute`. The **company** while the task is `delivered` and **not rated yet** (a rated delivery is validated: it releases the funds instead); the **chosen freelance** only once the review window is over (`is_review_overdue`, "Dispute for no response"); anybody else never (`forbidden`). Out of these windows a party is refused with `wrong_state` and the reason ("You validated this delivery…", "The company still has until … to answer…"). The panel shows "Open a dispute" (`[data-open-dispute]`) only when `can_dispute` says so.
- **R38** *Opening.* A reason is required, 1 to 280 characters once stripped (`invalid`, checked at prepare and again at send, before anything is signed or submitted). The session wallet signs Trustless Work `dispute-escrow` as `signer` — the escrow row's `payer_address` (company) or `payee_address` (freelance), never a body field. Trustless Work v1 has **no reason field**: the reason lives in TaskVault only (`projects.Dispute`). The dispute freezes the **whole** escrow. Once confirmed: Escrow `delivered|approved → disputed` (`dispute_tx_hash`, `disputed_at`), Task `delivered → disputed`, one `Dispute` row (task, opened_by, reason). From then on approve, release, validate, request changes and a second dispute are `wrong_state`; the funds stay locked (`holds_funds`).
- **R39** *The arbiter.* `LOWBID_DISPUTE_RESOLVER` (default: `LOWBID_PLATFORM_ADDRESS`) is the escrow's `disputeResolver`, stored on the row as `resolver_address` when the row is created and sent at deploy. Only that wallet resolves (`forbidden` otherwise, and also when the session wallet is not the row's `resolver_address`), only a `disputed` task (`wrong_state`). It alone sees `/litiges/` (403 for everyone else) and the "Disputes" nav entry. A party keeps its party role even if it is also the arbiter wallet.
- **R40** *The split.* The arbiter picks `freelance_pct`, a whole number from 0 to 100 (`invalid` otherwise). The balance is read on chain (`get-escrow`, `validateOnChain=true`); if the read fails or returns no usable balance, the stored `Escrow.amount` is used and a warning logged. `freelance_amount = balance × pct / 100` rounded **down** to 7 decimals, `company_amount = balance − freelance_amount`, so the two always sum exactly to the balance (Trustless Work requires it; its fees are then deducted proportionally from each entry). `distributions` keeps only the entries > 0, and its addresses come from the escrow row only (`payee_address` for the freelance, `payer_address` for the company) — never from the request, never the same address twice. Every receiving address needs the asset trustline.
- **R41** *Resolution.* Once `resolve-dispute` is confirmed: Escrow `disputed → resolved` (`resolve_tx_hash`, `resolved_at`, terminal), Task `disputed → resolved` (`resolved_at`) through `projects.services.mark_resolved(task, pct)` — the **only** gate to `resolved`, idempotent, refused on a task that is not disputed — and the `Dispute` row gets `freelance_pct` and `resolved_at`. A resolved task counts as **settled, not paid** (dashboards: "paid" and "earned" stay release/direct-payment figures). A project closes when every task is `paid` **or** `resolved` (`mark_paid` and `mark_resolved` apply the same rule). A replayed signed transaction (one already stored for another step) is refused (`tampered`); the same resolve sent twice is "Step already confirmed.".
- **R42** *Direct mode = no protection.* In direct mode nothing is locked, so there is nothing to arbitrate: `dispute` / `resolve` answer `wrong_mode` ("Direct mode: nothing is locked, so there is no dispute."), and every non-open task's payment panel shows `[data-direct-warning]`: "Direct mode: unprotected payment — nothing is locked, no dispute is possible."

### Links (delivery link, full deliverable)
- **R43** *Rendering.* Every user-supplied link — the delivery link (`Task.delivery_link`, every `Delivery` row) and the full deliverable (`Task.source_link`, when R31 lets the viewer see it) — on the task page, the payment panel, the delivery history and the disputes desk is rendered by one include, `templates/components/ext_link.html`: the **domain in large bold type** (`.ui-link-host`) with the full URL smaller and truncated underneath, `target="_blank"` and exactly `rel="noopener noreferrer nofollow ugc"` (no `window.opener`, no referrer, no SEO credit). The verdict comes from one rule, `projects.services.link_info(url)` → `{url, href, host, display, trusted}`, computed by the view / inclusion tag / `delivery_history` row, never by the template. `host` is the lowercase ASCII host (an internationalised domain is shown as its `xn--` punycode, so a look-alike cannot pass for a known name; `https://github.com@evil.example/` shows `evil.example`). A value that is not an http(s) URL with a host (`javascript:`, `data:`, malformed) gets no `href` and renders as plain text — `clean_link` / `clean_source_link` already refuse it at delivery (`invalid`, R13); `link_info` never raises.
- **R44** *Trusted hosts.* `LOWBID_TRUSTED_LINK_HOSTS` (comma-separated, default `github.com,gitlab.com,vercel.app,netlify.app`; an empty value means the default) lists the hosts shown without a warning: a link is trusted when its host equals an entry or is a subdomain of it (`my-app.vercel.app`), case-insensitive, trailing dot ignored. Any other link carries the inline warning `[data-untrusted-host]` "Unknown domain — open with care" with a warning icon, for every viewer. The warning is information, not a block: the link stays clickable.

R25–R29 are not used (the delivery rules started at R30); R50+ and R60+ are reserved.

### Validation and rating
- **R14** Only the company validates (`forbidden`), only a `delivered` task (`wrong_state`; a disputed task can no longer be validated). The rating is an integer from 1 to 5 (`invalid` otherwise); the comment is optional and cut at 280 characters. One rating per task (`duplicate`). Validating stores the rating and pays nothing by itself.
- **R15** No payment step (approve, release, direct payment) is possible before the rating exists: "Validate and rate the delivery before the payment." (`wrong_state`).
- **R16** Right after the rating the page chains the company's signatures: approve → release in escrow mode, the direct payment in direct mode. Stopping half-way is safe: the payment panel shows the remaining step as a button, and the dashboard lists it.

### Payment
- **R17** Every payment step has exactly one signer: the company for deploy, fund, approve, release and direct payment; the chosen freelance for deliver; the company or the chosen freelance for dispute (R37); the arbiter wallet for resolve (R39) (`forbidden` otherwise). The role is checked against the session wallet when the transaction is prepared **and** when it is sent, and every address put in a transaction comes from the task's escrow row (the project's company, the chosen freelance, the platform wallet, the arbiter), never from the request body.
- **R18** Every step also checks the escrow status and the task status (state table §5); a step out of order is refused (`wrong_state`), a step that does not exist in the current mode too (`wrong_mode`), an unknown step name with `unknown_step`.
- **R19** For a direct payment, the signed transaction must be exactly one `payment` from the company to the chosen freelance, for the task's price, in the configured asset; anything else is refused (`tampered`).
- **R20** A task becomes `paid` only through the confirmed release (escrow) or the confirmed direct payment, and only once (`projects.services.mark_paid` is idempotent). When every task of the project is paid or resolved (R41), the project becomes `closed` ("Closed").
- **R21** Sending the same signed transaction twice answers "Step already confirmed." and writes nothing twice.
- **R22** A Trustless Work or Horizon failure never changes a status: the vendor message is kept (`Escrow.last_error`) and shown in the panel, and the user retries. When Horizon times out on a direct payment, the hash is stored as pending and the next attempt reconciles it without asking for a new signature.
- **R23** The payment mode is frozen on a task's escrow row when the row is created (first payment step, or the rating). It may still change while nothing is on chain (status `created`), so switching to direct mode after a failed deploy works. A native-XLM asset always means direct mode (Trustless Work v1 needs an issuer).
- **R24** Any signed-in wallet can add the asset's trustline from the payment panel ("Add the USDC trustline"); there is nothing to sign when Horizon already shows it, or when the asset is native XLM. The signed transaction must be one `change_trust` from that wallet for the configured asset code and issuer (`tampered`).

### Publication deposit
Active only when `LOWBID_DEPOSIT_ENABLED` (default 1) **and** the payment mode is `escrow` (`payments.deposits.deposits_active`). Every rule lives in `payments/deposits.py`; every delay is evaluated when a request reads it — there is no timer.
- **R60** *Publication.* With deposits active a new project is **unpublished** (`published_at` empty): it is absent from the project list, the board and the landing, and refuses applications (`not_published`, 409). Funding the publication deposit sets `published_at` (the project is published). With deposits not active (direct mode, or disabled) a project is published at creation, as before; projects created before this feature are published (migration).
- **R61** *Amount.* Publication deposit = max(`LOWBID_DEPOSIT_RATE` × project budget, `LOWBID_DEPOSIT_MIN`) (defaults 1 %, 5 USDC), 7 decimals rounded up. A project without tasks has nothing to deposit: add tasks first.
- **R62** *Coverage and top-up.* Each funded (or settled) deposit row covers part of the budget (`covered_budget`: the whole budget for the publication deposit, the uncovered gap for a top-up). A task takes applications only when the covered budget reaches the cumulated prices of the project's tasks in creation order up to and including it (`not_covered`, 409): a task added after the last funded deposit waits for a top-up = max(rate × gap, `LOWBID_DEPOSIT_TOPUP_MIN`) (default 1 USDC).
- **R63** *Escrow roles.* The deposit is a Trustless Work single-release escrow deployed and funded by the company in Freighter (two signatures: "Publish the project (deposit X)"): signer and **receiver** = the company; approver = serviceProvider = releaseSigner = platformAddress = the platform key (`LOWBID_PLATFORM_SECRET`, public key = `LOWBID_PLATFORM_ADDRESS`); disputeResolver = a second server key (`LOWBID_DEPOSIT_RESOLVER_SECRET`); platform fee 0; one milestone "Deposit for project #pk"; engagement id `taskvault-deposit-<pk>-<n>`.
- **R64** *Company steps.* Only the company prepares / sends a deposit step (`forbidden`), only while the project is neither closed nor cancelled (`wrong_state`), in order deploy → fund (`wrong_state`), with deposits active (`wrong_mode`); the signed transaction's source must be the company (`tampered`); replaying the same signed transaction answers "Step already confirmed." and writes nothing twice; a provider failure keeps the status and stores the message. Addresses come from the session and the settings, never from the body.
- **R65** *Verdict.* `deposit_verdict(project, now)` (pure): closed → **refund**; cancelled with no application → refund; no application `LOWBID_NO_APPLICATION_DAYS` (30) days after publication → refund; at least one application, the first one `LOWBID_CHOICE_DAYS` (14) days old and no freelance ever chosen → **forfeit**; cancelled with at least one application → forfeit; otherwise **locked**. The deadline shown is the date the verdict changes if nothing happens ("Refundable if no application by …" / "Choose a freelancer before …").
- **R66** *Refund.* Signed by the server's platform key: milestone status change ("deposit refund"), approve, release → the escrow pays the company (minus the Trustless Work protocol fee). Each step is skipped when its hash is stored; a failure stores `last_error`, keeps the deposit `funded`, and the next attempt only sends the missing steps.
- **R67** *Forfeit.* Needs the guarantee fund's asset trustline (checked first: no call at all without it, "The guarantee fund has no USDC trustline."). The platform key opens a dispute, then the resolver key resolves it sending the escrow's whole on-chain balance (read with `validateOnChain`) to `LOWBID_GUARANTEE_FUND_ADDRESS`. Same idempotence and failure rules as R66.
- **R68** *Triggers.* Settling happens (a) automatically right after the commit that makes the project `closed` (last task paid) or `cancelled` (a `post_save` receiver registers an `on_commit` callback; a failure is logged and shown on the panel, never raised), (b) on "Reclaim my deposit" (company only, verdict refund; also the retry), (c) on "Report a ghost listing" (any connected wallet, verdict forfeit; also the retry). A request whose verdict does not match is refused (`wrong_state`).
- **R69** *Cancel.* Only the company (`forbidden`) cancels a project, only while it is neither closed nor cancelled and no freelance was chosen on any task (`wrong_state`). A cancelled project takes no application (`wrong_state`, every mode), no new task, no choice. The confirmation says whether the deposit will be refunded (nobody applied) or forfeited (applications received).
- **R70** *Server keys.* Deposits are active only when the three server settings are set (a missing one makes `manage.py check` warn and keeps deposits off); `manage.py check` fails (Tags.security) when the platform secret is invalid or does not match `LOWBID_PLATFORM_ADDRESS`, when the resolver secret is missing, invalid or equal to the platform key, or when the fund address is missing, invalid or equal to the platform address. The secrets are never logged, rendered or returned (only public addresses are).
- **R71** *Guarantee fund page.* `/fonds/` (public) shows the fund's balance (Horizon; "Balance unavailable right now" when unreachable), its account link, and every forfeited deposit (project, amount, the resolve transaction on stellar.expert): "Money from ghost listings protects scammed freelancers."
- **R72** *No silent erasure.* While a deposit is locked (`funded`), an open task that already received applications cannot be deleted (`wrong_state`): deleting it would remove the applications the verdict counts (R65) and turn a ghost listing into a refund. The company cancels the project instead (R69) — and forfeits.

### Error codes

| Code | HTTP (projects) | Meaning |
|------|-----------------|---------|
| `forbidden`, `own_task`, `not_assigned` | 403 | wrong role for this action |
| `wrong_state`, `duplicate` | 409 | not possible at this stage / already done (e.g. validating or requesting changes on a disputed task) |
| `too_many_revisions` | 409 | the task already had `LOWBID_MAX_REVISIONS` change requests (R35) |
| `not_published`, `not_covered` | 409 | the project's publication deposit is not funded yet / the task is not covered by a funded deposit (R60, R62) |
| `invalid`, `bad_tags` | 400 | bad input |
| `wallet_required` | 401 | no session (any `@wallet_required` endpoint called with `fetch` or `Accept: application/json`) |

Payment refusals (`/pay/…`) answer HTTP **200** `{ok: false, error, message}` with the codes `not_chosen · forbidden · wrong_state · wrong_mode · unknown_step · tampered · provider · stellar · invalid · not_assigned`. For disputes: `forbidden` (not a party / not the arbiter), `wrong_state` (outside the R37 windows, or not disputed for resolve), `wrong_mode` (direct mode, R42), `invalid` (reason empty or > 280, `freelance_pct` outside 0–100), `tampered` (replayed transaction).

### Reputation

Computed by `reputation/services.py`; nothing here feeds the score (§4).

- **R50** *Company rating.* Once a task is settled (status `paid`, or `resolved` once disputes exist), its chosen freelance can rate the company once: an integer from 1 to 5 (`invalid`, 400), an optional comment cut at 280 characters. Anyone else is refused (`forbidden`, 403), a task not settled yet too (`wrong_state`, 409), a second rating of the same task as well (`duplicate`, 409, also a database constraint). The rating is public: the task page shows it to everyone, the company's profile shows "Rated by freelancers 4.5/5 · 3 ratings" once there is one.
- **R51** Company ratings, the payer profile and the badges below never change a score, « Validated » (R9) or « Recommended » (R8).
- **R52** *Payer profile.* The "Payer profile" panel of a wallet that posted at least one project is computed **only** from escrow rows whose payout is confirmed on chain: a release hash (escrow mode) or a payment hash on a row in status `paid` (direct mode; a pending hash kept after a Horizon timeout does not count). A task marked paid without such a row counts for nothing. The panel is hidden for a wallet that never posted a project.
- **R53** Its figures: tasks paid, distinct freelances paid, total paid, average delay between delivery and payment (informational only), disputes lost, deposits forfeited. Every figure lists the stellar.expert links of the transactions behind it, labelled "task #N", so each number can be checked on chain.
- **R54** *Reliable payer.* The badge needs at least `LOWBID_RELIABLE_PAYER_MIN_PARTNERS` (default 3) distinct freelances paid with a confirmed transaction, no dispute lost and no deposit forfeited (both are always 0 until disputes and project deposits exist).
- **R55** *New account.* A wallet with no task paid with a confirmed transaction, in either role (company payer or freelance payee), carries "New account" on its profile; the chosen candidate row of a task shows "No history" for the same reason. Both are hints, never a refusal.
- **R56** *Verified GitHub — the proof.* The wallet signs `lowbid:<its G… address>` with Freighter (`signMessage`, the same schemes as the login, R1) and publishes a **public** gist (any file name) whose content holds the two lines `lowbid:<G…>` and `signature: <base64 signature>`. The profile page signs and fills these two lines for its owner.
- **R57** The gist is given as `https://gist.github.com/<login>/<32 hex>` or as its bare 32-hex id (`invalid`, 400). It must exist (`not_found`, 404) and be public (`not_public`, 400); the message line must be exactly the wallet's and the signature valid for it (`bad_signature`, 400); the gist owner's GitHub account must be at least `LOWBID_GITHUB_MIN_AGE_DAYS` (default 365) days old (`too_recent`, 400). One GitHub account per wallet and one wallet per GitHub account (`already_used`, 409, when the account is linked to another wallet; `duplicate`, 409, when this wallet already has one). A GitHub failure stores nothing and answers `provider` (502). The optional `LOWBID_GITHUB_TOKEN` only raises GitHub's rate limit; it is never rendered nor logged.
- **R58** Only the owner (the session wallet) links or unlinks its GitHub account (`not_found`, 404, when there is nothing to unlink); the "Verified GitHub" badge links to `https://github.com/<login>`.
- **R59** Every reputation endpoint acts as the session wallet: an address in the request body is ignored. Badges and panels are pure reads (no network call when a page renders).

| Code | HTTP (reputation) | Meaning |
|------|-------------------|---------|
| `forbidden` | 403 | not the task's freelance |
| `wrong_state`, `duplicate`, `already_used` | 409 | task not settled / already rated or linked / GitHub account taken |
| `invalid`, `not_public`, `bad_signature`, `too_recent` | 400 | bad input or proof |
| `not_found` | 404 | no such gist / GitHub account / link |
| `provider` | 502 | GitHub unreachable or unreadable |

## 4. The score

Deterministic, no AI (`projects/scoring.py`). For an application by freelance F on a task of company C:

```
score = 40 × [F has at least one task PAID by C]
      +  8 × average rating given by C to F           (0 without rating)
      + 20 × (common tags / task tags)                 (0 when the task has no tags)
```

Each part is rounded to one decimal (half up) and the score is the sum of the rounded parts, so the bar always adds up to the printed score; maximum 100. The bar under each candidate shows the three parts (history in the brand mint, ratings in blue, skills in green). The history and rating parts are **per company**: being paid and well rated elsewhere does not count.

### Worked example (the seed and e2e scenario)

Studio Nova's project "Booking platform for a yoga studio" has three tasks: T1 "Landing page" (300 USDC, `django, ui`), T2 "Freighter integration" (500 USDC, `stellar, js`), T3 "Dashboard" (400 USDC, `django, charts`).

**Round 1 — T1, no history for anyone.**

| Candidate | Tags | History | Ratings | Skills | Score |
|-----------|------|---------|---------|--------|-------|
| Yanis (A) | `django, ui` | 0 | 0 | 20 × 2/2 = 20 | **20.0** "Recommended" |
| Nora (B) | `django` | 0 | 0 | 20 × 1/2 = 10 | **10.0** |

Studio Nova chooses Yanis. He delivers, the company rates him **5/5**, and T1 is paid.

**Round 2 — T2.**

| Candidate | Tags | History | Ratings | Skills | Score |
|-----------|------|---------|---------|--------|-------|
| Yanis (A) | `stellar` | 40 (T1 paid) | 8 × 5 = 40 | 20 × 1/2 = 10 | **90.0** "Validated" + "Recommended" |
| Nora (B) | `stellar, js` | 0 | 0 | 20 × 2/2 = 20 | **20.0** |

**A = 90 vs B = 20.** Nora has the better skill match, but Yanis has delivered well for this company. The company can still choose Nora: "Choose" is on both rows.

`make seed` (`seed_demo --flush`) builds exactly this state: T1 paid to A (recorded as a direct payment with a demo hash whatever the configured mode, so the project is "Funded"), T2 open with A and B, T3 open with no candidate, plus a second draft project (a bakery rebrand: three open tasks, no application) and a third project, "Mobile app for a food truck", for the anti-scam features: "Menu page" chosen freelance B, delivered with a fingerprint, sent back once ("Please fix the mobile layout on the menu page.") and delivered again — "Delivered", revision 1/2, two deliveries and one change request in the history, review window running, a direct-mode row so the company can still validate and pay it live; "Order tracking" chosen freelance A, an escrow-mode row with demo contract id and deploy / fund / deliver / dispute hashes, disputed by the company ("The demo does not match the agreed scope."), its delivery link on an unknown domain so the warning shows. That project stays "Draft": the disputed escrow holds its funds but the Menu page's direct row holds nothing until it is paid (R12). A fourth wallet is the arbiter (`LOWBID_DEMO_ARBITER`, else `LOWBID_DISPUTE_RESOLVER` / `LOWBID_PLATFORM_ADDRESS`, else random): `/litiges/` opens only when `LOWBID_DISPUTE_RESOLVER` (or the platform address) equals it, and the seed prints a hint otherwise. The food-truck hashes are demo values: nothing behind them on chain, so that dispute cannot be resolved live.

## 5. States

### Project

| Status | Label | Enters when | Leaves when |
|--------|-------|-------------|-------------|
| `draft` | "Draft" | created | every assigned task holds its money in escrow (funded, delivered, approved, released, disputed or resolved), or the first direct payment → `funded`; the last task paid or resolved → `closed` |
| `funded` | "Funded" | see above | every task paid or resolved → `closed` |
| `closed` | "Closed" | every task `paid` or `resolved` | — |
| `cancelled` | "Cancelled" | the company cancels before choosing anyone (R69) | — |

Independently of the status, a project is **published** (`published_at` set) once its publication deposit is funded (deposits active) or at creation (deposits not active) — R60.

Tasks can be added until `closed` or `cancelled`; only an `open` task can be deleted. A project with a single task paid directly goes from `draft` straight to `closed`.

### Task

| Status | Label | Enters when | Next |
|--------|-------|-------------|------|
| `open` | "Open" | added | the company chooses → `taken` (or deleted while still open) |
| `taken` | "Taken" | a freelance is chosen, or the company requested changes (R34, `revision_count` += 1) | the freelance delivers (again) → `delivered` |
| `delivered` | "Delivered" | delivery confirmed (on chain in escrow mode); the review window (R33) runs | the company rates, then the payment is confirmed → `paid`; or the company requests changes (before the rating, at most R35 times) → `taken`; or a party's dispute is confirmed (escrow mode, R37) → `disputed` |
| `paid` | "Paid" | release / direct payment confirmed | — |
| `disputed` | "Disputed" | the dispute-escrow transaction is confirmed (R38); funds locked | the arbiter's resolve-dispute is confirmed → `resolved` |
| `resolved` | "Resolved" | resolve-dispute confirmed (`mark_resolved`, R41) | — (settled, like `paid`) |

There is no task cancellation and no re-assignment (a whole project can be cancelled before any choice, R69). Every delivery is kept as a `Delivery` row and every change request as a `RevisionRequest` row (R36), the dispute (at most one per task) as a `Dispute` row (R38).

### Application

| Status | Label | Meaning |
|--------|-------|---------|
| `pending` | "Pending" | waiting for the company's choice; the only status that is rescored and can be "Recommended" |
| `chosen` | "Chosen" | this freelance got the task |
| `rejected` | "Not selected" | another freelance got the task |

### Escrow (one per task, `payments.Escrow`)

Escrow mode (Trustless Work single-release, one milestone):

| Step | Signs | Escrow status | Task status | Button |
|------|-------|---------------|-------------|--------|
| choose | company | — (no row yet) | `open → taken` | "Choose" |
| deploy | company | `created → deployed` | `taken` | "Create the escrow" (or "Fund the project") |
| fund | company | `deployed → funded` | `taken` | "Lock the funds" (chained) |
| deliver | freelance | `funded → delivered` | `taken → delivered` | "Declare the delivery" / "Deliver again" |
| request_changes | company (no transaction) | `delivered → funded` | `delivered → taken` | "Request changes" (max `LOWBID_MAX_REVISIONS`, before the Rating) |
| validate | company | — (Rating saved) | `delivered` | "Validate + rate" |
| approve | company | `delivered → approved` | `delivered` | "Validate the delivery" (chained) |
| release | company | `approved → released` | `delivered → paid` | "Release the funds" (chained) |
| dispute | company (delivered, unrated) or freelance (review window over) | `delivered`/`approved → disputed` | `delivered → disputed` | "Open a dispute" (reason required) |
| resolve | arbiter (`LOWBID_DISPUTE_RESOLVER`) | `disputed → resolved` | `disputed → resolved` | "Resolve the dispute" (on `/litiges/`, split slider) |

Direct mode (no `deployed`, `funded` or `approved`):

| Step | Signs | Escrow status | Task status | Button |
|------|-------|---------------|-------------|--------|
| deliver | freelance (no transaction) | `created → delivered` | `taken → delivered` | "Declare the delivery" / "Deliver again" |
| request_changes | company (no transaction) | `delivered → created` | `delivered → taken` | "Request changes" (max `LOWBID_MAX_REVISIONS`, before the Rating) |
| validate | company | — (Rating saved) | `delivered` | "Validate + rate" |
| direct_pay | company | `created`/`delivered → paid` | `delivered → paid` | "Pay the freelancer" (chained) |

Direct mode has no dispute step (R42): nothing is locked, the panel warns "unprotected payment".

Status labels in the UI: `created` "Preparing", `deployed` "Escrow created", `funded` "Funds locked", `delivered` "Delivered", `approved` "Delivery validated", `released` "Funds released", `paid` "Paid", `disputed` "In dispute", `resolved` "Resolved by the arbiter". `failed` ("Failed") exists in the status choices but no step sets it: a failure leaves the status unchanged (R22).

### Publication deposit (one or more per project, `payments.ProjectDeposit`)

| Step | Signs | Deposit status | Trustless Work call | Effect |
|------|-------|----------------|---------------------|--------|
| deploy | company (Freighter) | (none / `created`) → `deployed` | deployer/single-release | contract id stored |
| fund | company (Freighter) | `deployed → funded` | fund-escrow | `published_at` = now if empty (R60) |
| milestone, approve, release | platform key (server) | `funded → refunded` | change-milestone-status, approve-milestone, release-funds | the company gets the deposit back (R66) |
| dispute, resolve | platform key, then resolver key (server) | `funded → forfeited` | dispute-escrow, resolve-dispute | the balance goes to the guarantee fund (R67) |

Labels: `created` "Preparing", `deployed` "Deposit escrow created", `funded` "Deposit locked", `refunded` "Deposit refunded", `forfeited` "Forfeited to the guarantee fund". Kinds: `publication`, `topup`. No other status: the per-step hashes record the progress of the server chains.

Signatures for one task: escrow mode = 4 by the company (deploy, fund, approve, release) + 1 by the freelance (deliver); a disputed task = deploy, fund, deliver, then 1 by the party who disputes + 1 by the arbiter; direct mode = 1 by the company.

## 6. Screens

The site is dark only and responsive down to phone width; below 1024 px a signed-in wallet gets a bottom tab bar (Projects · Board · Create · My projects · Home, plus Disputes for the arbiter wallet).

| URL | Who | What | Screenshot |
|-----|-----|------|------------|
| `/` | everyone | Landing: pitch, live stats (open tasks, projects, USDC paid), a ledger tape of the latest on-chain events, the 3D project cube scrolled through four chapters (decorative example figures), the 3 latest projects with an open task; "New project" + "Task board" once signed in, "Connect my Freighter wallet" otherwise | `01-landing.png`, `mobile-landing.png` |
| `/projets/` | everyone | Project list: tabs In progress / Closed / All, search (project title or description, task title, tags), the 8 most used tags on open tasks as chips, sort (Newest, Highest budget, Most open tasks), 24 per page | `02-liste-projets.png`, `mobile-liste.png` |
| `/projets/nouveau/` | signed in | New project form (title, description) | — |
| `/projets/<pk>/` | everyone | Project page: the publication deposit panel first in the aside (`#deposit-panel`: amount due or locked, deadline, "Publish the project (deposit X)" / top-up for the company, "Reclaim my deposit" for the company when refundable, "Report a ghost listing" for any wallet when forfeitable, "Cancel the project", the last error with Retry, explorer links; "Direct mode: payment not protected." in direct mode), "Not published" / "Deposit locked X" badges, KPIs (total budget, tasks, pending applications, paid tasks), the task table with each task's status and payment status, the inline add-task form (company, until the project is closed), candidates per open task with "Choose" (company), the funding banner and "Fund the project" (company, escrow mode) | `03-projet-entreprise.png`, `15-financement-projet.png`, `mobile-projet.png` |
| `/taches/<pk>/` | everyone | Task page: KPIs (budget while open, then the agreed price, candidates, project, stage), tags, the apply form (freelance), the ranked candidates with badges and score bars (polled every 5 s while open), the delivery panel (link with its domain and the "Unknown domain" warning, fingerprint, full deliverable when visible, review deadline), the delivery history, the payment panel (stepper, next step, delivery form, change request, rating form, dispute, trustline, live balance, stellar.expert links), the project's other tasks | `04-tache-candidats.png`, `05-tache-livree-freelance.png`, `06-valider-noter.png`, `08-tache-valide-recommande.png`, `12-tache-dark.png`, `13-paiement-echec.png`, `14-paiement-tache.png`, `mobile-tache-candidats.png` |
| `/fonds/` | everyone | Guarantee fund: balance, fund wallet link, forfeited deposits with their resolve transaction | — |
| `/taches/` | signed in | Freelance kanban: Open (every open task of other companies, the ones I applied to first), Taken, Delivered, Paid (my tasks; a disputed task sits in Delivered and a resolved one in Paid, each with its own badge) | `07-tableau-kanban.png`, `mobile-kanban.png` |
| `/mes-projets/` | signed in | The company's projects: KPIs (drafts, tasks to choose for, deliveries to validate, closed), tabs In progress / Closed / All, a row per project (status, tasks, applications, budget) with its next action | `09-mes-projets.png` |
| `/tableau-de-bord/` | signed in | Dashboard: to-do list (choose, fund, validate, pay, deliver, add tasks to an empty draft, waiting on the other side), KPIs as company and as freelance, recent activity | `10-tableau-de-bord.png`, `mobile-tableau-de-bord.png` |
| `/litiges/` | the arbiter wallet only (403 otherwise) | Disputes desk: KPIs (open, resolved, the arbiter address), one card per open dispute (project, task, amount, fingerprint, delivery link, history, reason, who opened it, stellar.expert links) with the split form `#resolve-form-<task>` (slider `[data-freelance-pct]` 0–100, live preview of both amounts, "Resolve the dispute" behind a confirm dialog), then the resolved disputes with their split | — |
| `/profil/<address>/` | everyone | Public profile: identicon, display name (editable by its owner, up to 80 characters), member since / last login, projects posted, tasks paid, earned, average rating, latest projects and tasks, ratings received | `11-profil.png` |

Reputation additions: the profile header carries the badges "Reliable payer", "New account", "Verified GitHub" and "Rated by freelancers x/5"; a "Payer profile" panel (wallets that posted a project) lists the confirmed on-chain figures with their stellar.expert links; the owner gets a "Verified GitHub" panel (sign the proof in Freighter, paste the gist URL, unlink). On a settled task the freelance gets a "Rate the company" panel under the payment panel; the chosen candidate row shows "No history" for a wallet without a confirmed payout.

## 6b. Trust network

A personalised trust layer on top of the task board. It **informs** the company; it never decides anything.

### Rules

- Any signed-in wallet (company or freelance) can **follow** any other wallet, and **unfollow** it. Never yourself. One follow per (follower, followed) pair; following twice is a no-op.
- Any signed-in wallet can **recommend** any other wallet, with an optional message of at most **280 characters** (trimmed). Never yourself. One recommendation per (author, subject) pair: recommending again **updates** the message (upsert). A recommendation can be **withdrawn**.
- Follows and recommendations are **public**: a profile shows its followers / following / recommendations counts and the list of recommendations received (author, message, date).
- Refusals: `self` (yourself), `invalid` (message over 280 characters), `not_found` (unknown address).

### Signals (one hop)

A viewer V looking at a target T sees a badge only through the wallets **V follows** — one hop, never more:

| Signal | When | Label (exact) |
|--------|------|---------------|
| **recommends** (strong) | someone V follows recommends T | `Yanis recommends` · several: `Yanis and 2 others recommend` |
| **followed_by** (weak) | someone V follows follows T | `Followed by Yanis` · several: `Followed by Yanis and 1 other` |
| **following** | V follows T directly | `Following` |

The strong badge wins over the weak one; `Following` is added next to either. An anonymous viewer, or V looking at their own wallet, sees no badge at all. A wallet is named by its display name, else its short address. A recommendation two hops away (V follows X, X follows Y, Y recommends T) shows **nothing**: strangers cannot push a freelance into your list by recommending each other.

### What it does NOT touch

- The selection score (`projects/scoring.py`), the « Validated » / « Recommended » badges and the **order** of the candidate list: none of them read the network.
- The network badge is never the bare word "Recommended": it always carries a name (`Yanis recommends`).

### Where the badges show

- Candidate rows (task page `#candidates-panel` and the project page candidate blocks): the badge after the Validated / Recommended badges, and a light highlight on the row (`.cand-row.is-network`, `.is-network-strong` when recommended). The 5 s poll re-renders when the signal changes.
- The kanban cards (`/taches/`) and the project list cards: the badge next to the **company** chip.
- The public profile (`/profil/<address>/`): counters, Follow / Recommend / Withdraw buttons, "Followed by N people you follow", the received recommendations.
- The dashboard: an "In your network" feed of what the wallets you follow did recently (recommendations, follows, projects posted).

### The seed graph

`make seed` adds freelancer **C (Chloé)**, who applies to T3 « Dashboard », and three edges: the company follows A (Yanis), A recommends C ("Chloé shipped our analytics dashboard in a week, clean Django and sharp charts."), A follows B (Nora). Signed in as the company: C's row on T3 shows **"Yanis (freelancer A) recommends"**, B's row on T2 shows **"Followed by Yanis (freelancer A)"**, A shows **"Following"** — and T2 still ranks A 90.0 above B 20.0.

## 7. Out of scope for the hackathon

- A multisig arbiter driven by the UI: `LOWBID_DISPUTE_RESOLVER` may be a multisig account, but the site collects one Freighter signature — sequential signatures on one XDR need a validity window Trustless Work does not document (docs/STELLAR_NOTES.md §1.3). Disputes themselves are in (R37–R42).
- Cancelling a task (a project can be cancelled before any choice), un-choosing a freelance, editing a task after creation.
- Several freelances on one task, partial payments, milestones inside a task.
- Messaging, notifications, email.
- Mainnet.
