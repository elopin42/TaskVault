# TaskVault — Product spec

> A company splits a project into fixed-price tasks. Freelances apply. The company picks one freelance per task. Each task is paid in USDC from its own escrow on Stellar when the company validates the delivery.

Hackathon version (Hack Meridian, Stellar **testnet** only). UI copy is English and is quoted as-is below; URL paths stay French (`/projets/`, `/taches/`, …). The payment asset is configurable (`STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER`, default Circle testnet USDC); "USDC" below means that asset.

> History: TaskVault v1 was a reverse auction; the task board replaced it on 2026-10-25.

The rules below are derived from `projects/services.py`, `projects/scoring.py` and `payments/services.py`; each one is covered by `projects/tests.py`, `payments/tests.py`, `payments/tests_flow.py` or the e2e run (`tests/e2e/run.js`).

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
2. It creates a **project** ("New project": title, description) and adds **tasks** inline on the project page: title, description, **fixed price** in USDC, up to 3 skill tags. The project is "Draft".
3. Freelances connect their own wallet and browse the project list (`/projets/`) or the **kanban** (`/taches/`: Open · Taken · Delivered · Paid).
4. A freelance **applies** to an open task ("Apply to this task" → "Send my application"): a message of up to 280 characters and up to 3 tags. No price.
5. The task page ranks the candidates by **score** (§4) and shows the badges "Validated" and "Recommended". The list refreshes every 5 seconds while the task is open.
6. **The company chooses** one candidate ("Choose", confirmed in a dialog). The task becomes "Taken", the chosen application "Chosen", every other one "Not selected".
7. The company **funds**: "Fund the project" creates one Trustless Work escrow per task with a chosen freelance ("Create the escrow", first Freighter signature) and locks the task's price in it ("Lock the funds", second signature). The project becomes "Funded" once every assigned task holds its money.
8. The freelance **delivers**: a link to the PR, the demo or the repository, then "Declare the delivery". In escrow mode this marks the escrow's milestone as done on chain, with the link as evidence (one signature by the freelance). The task becomes "Delivered".
9. The company **validates and rates** (the "Validate + rate" step: 1 to 5 stars, optional comment, submitted with "Validate and release …"). The rating is saved first; then the page asks for two signatures: "Validate the delivery" (approve) and "Release the funds" (release). The escrow pays the freelance, minus fees, and the task becomes "Paid".
10. When every task of the project is paid, the project is "Closed". The freelance's rating and paid task now count in the score of that company's next tasks.

**Direct mode** (fallback: `LOWBID_PAYMENT_MODE=direct`, or an empty mode without `TRUSTLESS_WORK_API_KEY`, and always when the asset is native XLM): step 7 does not exist ("Fund the project" is not shown), step 8 is a declaration without a transaction, and step 9 ("Validate and pay …") ends with one "Pay the freelancer" payment signed by the company.

## 3. Business rules (testable statements)

### Identity
- **R1** The wallet is the identity: login is a SEP-53 signature of a server challenge (`/auth/challenge/` → `/auth/verify/`, TTL `WALLET_CHALLENGE_TTL_SECONDS` = 300 s), single use: any verify attempt consumes it, a failed signature included (the wallet asks a fresh one per login). Any wallet can act as a company on its own projects and as a freelance on other projects.

### Projects and tasks
- **R2** Any signed-in wallet can create a project; it becomes that project's company. Title 3 to 120 characters, description required. A new project is `draft` ("Draft").
- **R3** Only the project's company can add a task (`forbidden`, 403), at any time until the project is `closed` (`wrong_state`, 409): one escrow per task means funding locks a task's price, never the project. Title 3 to 120 characters; price strictly positive (a comma is accepted as decimal separator), at most 7 decimals, below 10¹¹ (`invalid`, 400); tags given as a list or as a string split on commas, spaces or semicolons, normalised to lowercase slugs, de-duplicated, at most 3, at most 24 characters each (`bad_tags`, 400); description optional.
- **R4** A task can be deleted only by the company and only while it is `open` (`wrong_state` once a freelance is chosen), whatever the project status. Its applications are deleted with it.

### Applications, score and badges
- **R5** Any signed-in wallet except the project's company can apply to an `open` task (`wrong_state`, 409, checked first; `own_task`, 403), once per task (`duplicate`, 409, also a database constraint). Message at most 280 characters (`invalid`); tags as in R3. An application carries no price.
- **R6** The ranked candidate list and the scores are public (task page and `GET /taches/<pk>/candidats.json`). Only the company sees "Choose", on every row, and only while the task is open.
- **R7** The score (§4) is computed when the application is created and stored. After every rating and every paid task of a company, the pending applications on that company's open tasks are rescored.
- **R8** "Recommended": exactly one application per open task carries it, the best score among the **pending** applications; ties go to the earliest application. It disappears once the task is no longer open.
- **R9** "Validated" is relative to the company looking at the candidate: the freelance has at least one task **paid** by this company **and** an average rating from this company of at least 3. The same freelance can be "Validated" for one company and new to another.

### Choice
- **R10** Only the company chooses (`forbidden`), only on an `open` task (`wrong_state`: "A freelancer has already been chosen for this task."). It may choose **any** application of the task, recommended or not. The chosen application becomes `chosen`, every other one `rejected`, the task `taken` with `assigned_to` = the freelance. A choice cannot be undone.

### Funding
- **R11** A task can be funded only once a freelance is chosen (`not_chosen`): Trustless Work fixes the escrow's receiver when it is deployed. In escrow mode the company signs `deploy` then `fund` for each task; the escrow's amount is the task's price and its receiver is the chosen freelance. "Fund the project" chains both steps for every `taken` task whose escrow is not funded yet (two signatures per task); with nothing to fund it is disabled and says why.
- **R12** A project moves from `draft` to `funded` ("Funded") when every assigned (non-open) task's escrow holds its money (escrow mode), or at the first payment (direct mode, where nothing is locked in advance). It goes back to `draft` when a freelance is chosen for a task whose escrow holds nothing yet (escrow mode, no direct payment made), so "Funded" always means every assigned task is covered; a `closed` project never changes. Tasks can still be added; only an `open` task can be deleted (R4).

### Delivery
- **R13** Only the chosen freelance delivers (`not_assigned`: 403 on the database endpoint, HTTP 200 `{ok:false}` on the payment endpoints), only a `taken` task (`wrong_state`). The link is required, starts with `http://` or `https://` and has at most 500 characters (`invalid`). In escrow mode the delivery is an on-chain milestone change signed by the freelance, possible only once the escrow is funded (a database-only delivery is refused); the first 280 characters of the link go on chain as evidence. In direct mode the delivery is a declaration with no transaction.

### Validation and rating
- **R14** Only the company validates (`forbidden`), only a `delivered` task (`wrong_state`). The rating is an integer from 1 to 5 (`invalid` otherwise); the comment is optional and cut at 280 characters. One rating per task (`duplicate`). Validating stores the rating and pays nothing by itself.
- **R15** No payment step (approve, release, direct payment) is possible before the rating exists: "Validate and rate the delivery before the payment." (`wrong_state`).
- **R16** Right after the rating the page chains the company's signatures: approve → release in escrow mode, the direct payment in direct mode. Stopping half-way is safe: the payment panel shows the remaining step as a button, and the dashboard lists it.

### Payment
- **R17** Every payment step has exactly one signer: the company for deploy, fund, approve, release and direct payment; the chosen freelance for deliver (`forbidden` otherwise). The role is checked against the session wallet when the transaction is prepared **and** when it is sent, and every address put in a transaction comes from the task's escrow row (the project's company, the chosen freelance, the platform wallet), never from the request body.
- **R18** Every step also checks the escrow status and the task status (state table §5); a step out of order is refused (`wrong_state`), a step that does not exist in the current mode too (`wrong_mode`), an unknown step name with `unknown_step`.
- **R19** For a direct payment, the signed transaction must be exactly one `payment` from the company to the chosen freelance, for the task's price, in the configured asset; anything else is refused (`tampered`).
- **R20** A task becomes `paid` only through the confirmed release (escrow) or the confirmed direct payment, and only once (`projects.services.mark_paid` is idempotent). When every task of the project is paid, the project becomes `closed` ("Closed").
- **R21** Sending the same signed transaction twice answers "Step already confirmed." and writes nothing twice.
- **R22** A Trustless Work or Horizon failure never changes a status: the vendor message is kept (`Escrow.last_error`) and shown in the panel, and the user retries. When Horizon times out on a direct payment, the hash is stored as pending and the next attempt reconciles it without asking for a new signature.
- **R23** The payment mode is frozen on a task's escrow row when the row is created (first payment step, or the rating). It may still change while nothing is on chain (status `created`), so switching to direct mode after a failed deploy works. A native-XLM asset always means direct mode (Trustless Work v1 needs an issuer).
- **R24** Any signed-in wallet can add the asset's trustline from the payment panel ("Add the USDC trustline"); there is nothing to sign when Horizon already shows it, or when the asset is native XLM. The signed transaction must be one `change_trust` from that wallet for the configured asset code and issuer (`tampered`).

### Error codes

| Code | HTTP (projects) | Meaning |
|------|-----------------|---------|
| `forbidden`, `own_task`, `not_assigned` | 403 | wrong role for this action |
| `wrong_state`, `duplicate` | 409 | not possible at this stage / already done |
| `invalid`, `bad_tags` | 400 | bad input |
| `wallet_required` | 401 | no session (any `@wallet_required` endpoint called with `fetch` or `Accept: application/json`) |

Payment refusals (`/pay/…`) answer HTTP **200** `{ok: false, error, message}` with the codes `not_chosen · forbidden · wrong_state · wrong_mode · unknown_step · tampered · provider · stellar · invalid · not_assigned`.

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

`make seed` (`seed_demo --flush`) builds exactly this state: T1 paid to A (recorded as a direct payment with a demo hash whatever the configured mode, so the project is "Funded"), T2 open with A and B, T3 open with no candidate, plus a second draft project (a bakery rebrand: three open tasks, no application).

## 5. States

### Project

| Status | Label | Enters when | Leaves when |
|--------|-------|-------------|-------------|
| `draft` | "Draft" | created | every assigned task holds its money in escrow, or the first direct payment → `funded`; the last task paid → `closed` |
| `funded` | "Funded" | see above | every task paid → `closed` |
| `closed` | "Closed" | every task `paid` | — |

Tasks can be added until `closed`; only an `open` task can be deleted. A project with a single task paid directly goes from `draft` straight to `closed`.

### Task

| Status | Label | Enters when | Next |
|--------|-------|-------------|------|
| `open` | "Open" | added | the company chooses → `taken` (or deleted while still open) |
| `taken` | "Taken" | a freelance is chosen | the freelance delivers → `delivered` |
| `delivered` | "Delivered" | delivery confirmed (on chain in escrow mode) | the company rates, then the payment is confirmed → `paid` |
| `paid` | "Paid" | release / direct payment confirmed | — |

There is no cancellation and no re-assignment.

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
| deliver | freelance | `funded → delivered` | `taken → delivered` | "Declare the delivery" |
| validate | company | — (Rating saved) | `delivered` | "Validate + rate" |
| approve | company | `delivered → approved` | `delivered` | "Validate the delivery" (chained) |
| release | company | `approved → released` | `delivered → paid` | "Release the funds" (chained) |

Direct mode (no `deployed`, `funded` or `approved`):

| Step | Signs | Escrow status | Task status | Button |
|------|-------|---------------|-------------|--------|
| deliver | freelance (no transaction) | `created → delivered` | `taken → delivered` | "Declare the delivery" |
| validate | company | — (Rating saved) | `delivered` | "Validate + rate" |
| direct_pay | company | `created`/`delivered → paid` | `delivered → paid` | "Pay the freelancer" (chained) |

Status labels in the UI: `created` "Preparing", `deployed` "Escrow created", `funded` "Funds locked", `delivered` "Delivered", `approved` "Delivery validated", `released` "Funds released", `paid` "Paid". `failed` ("Failed") exists in the status choices but no step sets it: a failure leaves the status unchanged (R22).

Signatures for one task: escrow mode = 4 by the company (deploy, fund, approve, release) + 1 by the freelance (deliver); direct mode = 1 by the company.

## 6. Screens

The site is dark only and responsive down to phone width; below 1024 px a signed-in wallet gets a bottom tab bar (Projects · Board · Create · My projects · Home).

| URL | Who | What | Screenshot |
|-----|-----|------|------------|
| `/` | everyone | Landing: pitch, live stats (open tasks, projects, USDC paid), a ledger tape of the latest on-chain events, the 3D project cube scrolled through four chapters (decorative example figures), the 3 latest projects with an open task; "New project" + "Task board" once signed in, "Connect my Freighter wallet" otherwise | `01-landing.png`, `mobile-landing.png` |
| `/projets/` | everyone | Project list: tabs In progress / Closed / All, search (project title or description, task title, tags), the 8 most used tags on open tasks as chips, sort (Newest, Highest budget, Most open tasks), 24 per page | `02-liste-projets.png`, `mobile-liste.png` |
| `/projets/nouveau/` | signed in | New project form (title, description) | — |
| `/projets/<pk>/` | everyone | Project page: KPIs (total budget, tasks, pending applications, paid tasks), the task table with each task's status and payment status, the inline add-task form (company, until the project is closed), candidates per open task with "Choose" (company), the funding banner and "Fund the project" (company, escrow mode) | `03-projet-entreprise.png`, `15-financement-projet.png`, `mobile-projet.png` |
| `/taches/<pk>/` | everyone | Task page: KPIs (fixed price, candidates, project, stage), tags, the apply form (freelance), the ranked candidates with badges and score bars (polled every 5 s while open), the payment panel (stepper, next step, delivery form, rating form, trustline, live balance, stellar.expert links), the project's other tasks | `04-tache-candidats.png`, `05-tache-livree-freelance.png`, `06-valider-noter.png`, `08-tache-valide-recommande.png`, `12-tache-dark.png`, `13-paiement-echec.png`, `14-paiement-tache.png`, `mobile-tache-candidats.png` |
| `/taches/` | signed in | Freelance kanban: Open (every open task of other companies, the ones I applied to first), Taken, Delivered, Paid (my tasks) | `07-tableau-kanban.png`, `mobile-kanban.png` |
| `/mes-projets/` | signed in | The company's projects: KPIs (drafts, tasks to choose for, deliveries to validate, closed), tabs In progress / Closed / All, a row per project (status, tasks, applications, budget) with its next action | `09-mes-projets.png` |
| `/tableau-de-bord/` | signed in | Dashboard: to-do list (choose, fund, validate, pay, deliver, add tasks to an empty draft, waiting on the other side), KPIs as company and as freelance, recent activity | `10-tableau-de-bord.png`, `mobile-tableau-de-bord.png` |
| `/profil/<address>/` | everyone | Public profile: identicon, display name (editable by its owner, up to 80 characters), member since / last login, projects posted, tasks paid, earned, average rating, latest projects and tasks, ratings received | `11-profil.png` |

## 7. Out of scope for the hackathon

- Disputes (Trustless Work supports them; the dispute resolver role is set to the platform wallet, but no screen raises or resolves a dispute).
- Cancelling a project or a task, un-choosing a freelance, editing a task after creation.
- Several freelances on one task, partial payments, milestones inside a task.
- Messaging, notifications, email.
- Mainnet.
