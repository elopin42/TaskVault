# Lowbid — Product spec

> A company splits a project into fixed-price tasks. Freelances apply. The company picks one freelance per task. Each task is paid in USDC from its own escrow on Stellar when the company validates the delivery.

Hackathon version (Hack Meridian, Stellar **testnet** only). UI copy is French; it is quoted as-is below.

> History: Lowbid v1 was a reverse auction; the task board replaced it on 2026-10-25.

The rules below are derived from `projects/services.py`, `projects/scoring.py` and `payments/services.py`; each one is covered by `projects/tests.py`, `payments/tests_flow.py` or the e2e run (`tests/e2e/run.js`).

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
2. It creates a **project** (« Nouveau projet »: title, description) and adds **tasks** inline on the project page: title, description, **fixed price** in USDC, up to 3 skill tags. The project is « Brouillon ».
3. Freelances connect their own wallet and browse the project list (`/projets/`) or the **kanban** (`/taches/`: Ouvert · Pris · Livré · Payé).
4. A freelance **applies** to an open task (« Postuler »): a message of up to 280 characters and up to 3 tags. No price.
5. The task page ranks the candidates by **score** (§4) and shows the badges « Validé » and « Recommandé ». The list refreshes every 5 seconds.
6. **The company chooses** one candidate (« Choisir », confirmed in a dialog). The task becomes « Pris », the chosen application « Choisi », every other one « Non retenu ».
7. The company **funds**: « Financer le projet » creates one Trustless Work escrow per task with a chosen freelance (« Créer l’escrow », first Freighter signature) and locks the task's price in it (« Bloquer les fonds », second signature). The project becomes « Financé » once every assigned task holds its money.
8. The freelance **delivers**: a link to the PR, the demo or the repository, then « Déclarer la livraison ». In escrow mode this marks the escrow's milestone as done on chain, with the link as evidence (one signature by the freelance). The task becomes « Livré ».
9. The company **validates and rates** (« Valider + noter », 1 to 5 stars, optional comment). The rating is saved first; then the page asks for two signatures: « Valider la livraison » (approve) and « Libérer les fonds » (release). The escrow pays the freelance, minus fees, and the task becomes « Payé ».
10. When every task of the project is paid, the project is « Terminé ». The freelance's rating and paid task now count in the score of that company's next tasks.

**Direct mode** (fallback, `LOWBID_PAYMENT_MODE=direct`, or automatically when the asset is native XLM): step 7 does not exist, step 8 is a declaration without a transaction, and step 9 ends with one « Payer le freelance » payment signed by the company.

## 3. Business rules (testable statements)

### Identity
- **R1** The wallet is the identity: login is a SEP-53 signature of a single-use challenge (`/auth/challenge/` → `/auth/verify/`, TTL `WALLET_CHALLENGE_TTL_SECONDS` = 300 s). Any wallet can act as a company on its own projects and as a freelance on other projects.

### Projects and tasks
- **R2** Any signed-in wallet can create a project; it becomes that project's company. Title 3 to 120 characters, description required. A new project is `draft` (« Brouillon »).
- **R3** Only the project's company can add a task (`forbidden`, 403), at any time until the project is `closed` (`wrong_state`, 409): one escrow per task means funding locks a task's price, never the project. Title 3 to 120 characters; price strictly positive, at most 7 decimals, below 10¹¹ (`invalid`, 400); tags separated by commas, spaces or semicolons, normalised to lowercase slugs, de-duplicated, at most 3, at most 24 characters each (`bad_tags`, 400); description optional.
- **R4** A task can be deleted only by the company and only while it is `open` (`wrong_state` once a freelance is chosen), whatever the project status. Its applications are deleted with it.

### Applications, score and badges
- **R5** Any signed-in wallet except the project's company can apply to an `open` task (`own_task`, 403; `wrong_state`, 409), once per task (`duplicate`, 409, also a database constraint). Message at most 280 characters; tags as in R3. An application carries no price.
- **R6** The ranked candidate list and the scores are public (task page and `GET /taches/<pk>/candidats.json`). Only the company sees « Choisir ».
- **R7** The score (§4) is computed when the application is created and stored. After every rating and every paid task of a company, the pending applications on that company's open tasks are rescored.
- **R8** « Recommandé »: exactly one application per open task carries it, the best score among the **pending** applications; ties go to the earliest application. It disappears once the task is no longer open.
- **R9** « Validé » is relative to the company looking at the candidate: the freelance has at least one task **paid** by this company **and** an average rating from this company of at least 3. The same freelance can be « Validé » for one company and new to another.

### Choice
- **R10** Only the company chooses (`forbidden`), only on an `open` task (`wrong_state`: « Un freelance a déjà été choisi pour cette tâche. »). It may choose **any** application of the task, recommended or not. The chosen application becomes `chosen`, every other one `rejected`, the task `taken` with `assigned_to` = the freelance. A choice cannot be undone.

### Funding
- **R11** A task can be funded only once a freelance is chosen (`not_chosen`): Trustless Work fixes the escrow's receiver when it is deployed. In escrow mode the company signs `deploy` then `fund` for each task; the escrow's amount is the task's price and its receiver is the chosen freelance. « Financer le projet » chains both steps for every assigned task that is not funded yet (two signatures per task); with nothing to fund it is disabled and says why.
- **R12** A project moves from `draft` to `funded` (« Financé ») when every assigned (non-open) task's escrow holds its money (escrow mode), or at the first payment (direct mode, where nothing is locked in advance). Tasks can still be added; only an `open` task can be deleted (R4).

### Delivery
- **R13** Only the chosen freelance delivers (`not_assigned`, 403), only a `taken` task (`wrong_state`). The link is required, starts with `http://` or `https://` and has at most 500 characters (`invalid`). In escrow mode the delivery is an on-chain milestone change signed by the freelance, possible only once the escrow is funded (a database-only delivery is refused); the first 280 characters of the link go on chain as evidence. In direct mode the delivery is a declaration with no transaction.

### Validation and rating
- **R14** Only the company validates, only a `delivered` task. The rating is an integer from 1 to 5 (`invalid` otherwise); the comment is optional and cut at 280 characters. One rating per task (`duplicate`). Validating stores the rating and pays nothing by itself.
- **R15** No payment step (approve, release, direct payment) is possible before the rating exists: « Validez et notez la livraison avant le paiement. »
- **R16** Right after the rating the page chains the company's signatures: approve → release in escrow mode, the direct payment in direct mode. Stopping half-way is safe: the payment panel shows the remaining step as a button, and the dashboard lists it.

### Payment
- **R17** Every payment step has exactly one signer: the company for deploy, fund, approve, release and direct payment; the chosen freelance for deliver. The role is checked when the transaction is prepared **and** when it is sent, and every address put in a transaction comes from the session wallet, never from the request body (`forbidden`).
- **R18** Every step also checks the escrow status and the task status (state table §5); a step out of order is refused (`wrong_state`), a step that does not exist in the current mode too (`wrong_mode`).
- **R19** For a direct payment, the signed transaction must be exactly one `payment` from the company to the chosen freelance, for the task's price, in the configured asset; anything else is refused (`tampered`).
- **R20** A task becomes `paid` only through the confirmed release (escrow) or the confirmed direct payment, and only once (`projects.services.mark_paid` is idempotent). When every task of the project is paid, the project becomes `closed` (« Terminé »).
- **R21** Sending the same signed transaction twice answers « Étape déjà confirmée. » and writes nothing twice.
- **R22** A Trustless Work or Horizon failure never changes a status: the vendor message is kept (`Escrow.last_error`) and shown in the panel, and the user retries. When Horizon times out on a direct payment, the hash is stored as pending and the next attempt reconciles it without asking for a new signature.
- **R23** The payment mode is frozen on a task's escrow row at its first payment step. It may still change while nothing is on chain (status `created`), so switching to direct mode after a failed deploy works. A native-XLM asset always means direct mode (Trustless Work v1 needs an issuer).
- **R24** Any signed-in wallet can add the asset's trustline from the payment panel (« Ajouter la trustline USDC »); there is nothing to sign when it already exists, or when the asset is native XLM.

### Error codes

| Code | HTTP (projects) | Meaning |
|------|-----------------|---------|
| `forbidden`, `own_task`, `not_assigned` | 403 | wrong role for this action |
| `wrong_state`, `duplicate` | 409 | not possible at this stage / already done |
| `invalid`, `bad_tags` | 400 | bad input |
| `wallet_required` | 401 | no session (any `@wallet_required` endpoint called with `fetch`) |

Payment refusals (`/pay/…`) answer HTTP **200** `{ok: false, error, message}` with the codes `not_chosen · forbidden · wrong_state · wrong_mode · unknown_step · tampered · provider · stellar · invalid · not_assigned`.

## 4. The score

Deterministic, no AI (`projects/scoring.py`). For an application by freelance F on a task of company C:

```
score = 40 × [F has at least one task PAID by C]
      +  8 × average rating given by C to F           (0 without rating)
      + 20 × (common tags / task tags)                 (0 when the task has no tags)
```

Maximum 100, stored rounded to one decimal. The bar under each candidate shows the three parts (history in brand colour, ratings in blue, skills in green). The history and rating parts are **per company**: being paid and well rated elsewhere does not count.

### Worked example (the seed and e2e scenario)

Studio Nova's project « Plateforme de réservation pour un studio de yoga » has three tasks: T1 « Landing page » (300 USDC, `django, ui`), T2 « Intégration Freighter » (500 USDC, `stellar, js`), T3 « Dashboard » (400 USDC, `django, charts`).

**Round 1 — T1, no history for anyone.**

| Candidate | Tags | History | Ratings | Skills | Score |
|-----------|------|---------|---------|--------|-------|
| Yanis (A) | `django, ui` | 0 | 0 | 20 × 2/2 = 20 | **20.0** « Recommandé » |
| Nora (B) | `django` | 0 | 0 | 20 × 1/2 = 10 | **10.0** |

Studio Nova chooses Yanis. He delivers, the company rates him **5/5**, and T1 is paid.

**Round 2 — T2.**

| Candidate | Tags | History | Ratings | Skills | Score |
|-----------|------|---------|---------|--------|-------|
| Yanis (A) | `stellar` | 40 (T1 paid) | 8 × 5 = 40 | 20 × 1/2 = 10 | **90.0** « Validé » + « Recommandé » |
| Nora (B) | `stellar, js` | 0 | 0 | 20 × 2/2 = 20 | **20.0** |

**A = 90 vs B = 20.** Nora has the better skill match, but Yanis has delivered well for this company. The company can still choose Nora: « Choisir » is on both rows.

## 5. States

### Project

| Status | Label | Enters when | Leaves when |
|--------|-------|-------------|-------------|
| `draft` | « Brouillon » | created | every assigned task holds its money in escrow, or the first direct payment → `funded`; the last task paid → `closed` |
| `funded` | « Financé » | see above | every task paid → `closed` |
| `closed` | « Terminé » | every task `paid` | — |

Tasks can be added until `closed`; only an `open` task can be deleted. A project with a single task paid directly goes from `draft` straight to `closed`.

### Task

| Status | Label | Enters when | Next |
|--------|-------|-------------|------|
| `open` | « Ouvert » | added | the company chooses → `taken` (or deleted while still open) |
| `taken` | « Pris » | a freelance is chosen | the freelance delivers → `delivered` |
| `delivered` | « Livré » | delivery confirmed (on chain in escrow mode) | the company rates, then the payment is confirmed → `paid` |
| `paid` | « Payé » | release / direct payment confirmed | — |

There is no cancellation and no re-assignment.

### Application

| Status | Label | Meaning |
|--------|-------|---------|
| `pending` | « En attente » | waiting for the company's choice; the only status that is scored and can be « Recommandé » |
| `chosen` | « Choisi » | this freelance got the task |
| `rejected` | « Non retenu » | another freelance got the task |

### Escrow (one per task, `payments.Escrow`)

Escrow mode (Trustless Work single-release, one milestone):

| Step | Signs | Escrow status | Task status | Button |
|------|-------|---------------|-------------|--------|
| choose | company | — (no row yet) | `open → taken` | « Choisir » |
| deploy | company | `created → deployed` | `taken` | « Créer l’escrow » (or « Financer le projet ») |
| fund | company | `deployed → funded` | `taken` | « Bloquer les fonds » (chained) |
| deliver | freelance | `funded → delivered` | `taken → delivered` | « Déclarer la livraison » |
| validate | company | — (Rating saved) | `delivered` | « Valider + noter » |
| approve | company | `delivered → approved` | `delivered` | « Valider la livraison » (chained) |
| release | company | `approved → released` | `delivered → paid` | « Libérer les fonds » (chained) |

Direct mode (no `deployed`, `funded` or `approved`):

| Step | Signs | Escrow status | Task status | Button |
|------|-------|---------------|-------------|--------|
| deliver | freelance (no transaction) | `created → delivered` | `taken → delivered` | « Déclarer la livraison » |
| validate | company | — (Rating saved) | `delivered` | « Valider + noter » |
| direct_pay | company | `created`/`delivered → paid` | `delivered → paid` | « Payer le freelance » (chained) |

`failed` exists in the status choices but no step sets it: a failure leaves the status unchanged (R22).

Signatures for one task: escrow mode = 4 by the company (deploy, fund, approve, release) + 1 by the freelance (deliver); direct mode = 1 by the company.

## 6. Screens

| URL | Who | What | Screenshot |
|-----|-----|------|------------|
| `/` | everyone | Landing: pitch, live stats (open tasks, projects, USDC paid), latest projects; « Nouveau projet » once signed in | `01-landing.png`, `mobile-landing.png` |
| `/projets/` | everyone | Project list: tabs En cours / Terminés / Tous, search (project or task title, tags), tag chips, sort (newest, highest total, most open tasks), pagination | `02-liste-projets.png`, `mobile-liste.png` |
| `/projets/nouveau/` | signed in | New project form (title, description) | — |
| `/projets/<pk>/` | everyone | Project page: KPIs (total of the task prices, tasks, applications, paid tasks), the task table with each task's status and payment status, the inline add-task form (company, until the project is closed), candidates per open task with « Choisir » (company), the funding banner and « Financer le projet » (company) | `03-projet-entreprise.png`, `15-financement-projet.png`, `mobile-projet.png` |
| `/taches/<pk>/` | everyone | Task page: KPIs (fixed price, candidates, project, current step), tags, the apply form (freelance), the ranked candidates with badges and score bars (polled every 5 s), the payment panel (stepper, next step, delivery form, rating form, trustline, live balance, stellar.expert links) | `04-tache-candidats.png`, `05-tache-livree-freelance.png`, `06-valider-noter.png`, `08-tache-valide-recommande.png`, `12-tache-light.png`, `13-paiement-echec.png`, `14-paiement-tache.png`, `mobile-tache-candidats.png` |
| `/taches/` | signed in | Freelance kanban: Ouvert (open tasks of other companies, the ones I applied to first), Pris, Livré, Payé (my tasks) | `07-tableau-kanban.png`, `mobile-kanban.png` |
| `/mes-projets/` | signed in | The company's projects: KPIs (drafts, tasks to choose for, deliveries to validate, finished), tabs En cours / Terminés / Tous, a row per project with its next action | `09-mes-projets.png` |
| `/tableau-de-bord/` | signed in | Dashboard: to-do list (choose, fund, validate, pay, deliver, waiting on the other side), KPIs as company and as freelance, recent activity | `10-tableau-de-bord.png`, `mobile-tableau-de-bord.png` |
| `/profil/<address>/` | everyone | Public profile: identicon, display name (editable by its owner), projects posted, tasks paid, average rating, ratings received | `11-profil.png` |

## 7. Out of scope for the hackathon

- Disputes (Trustless Work supports them; the dispute resolver role is set to the platform wallet, but no screen raises or resolves a dispute).
- Cancelling a project or a task, un-choosing a freelance, editing a task after creation.
- Several freelances on one task, partial payments, milestones inside a task.
- Messaging, notifications, email.
- Mainnet.
