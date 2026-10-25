# TaskVault — Pitch

> Aligned with the real UI (English labels copied from the templates). The click-by-click script is [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md) §3.
> Testnet amounts (the Circle faucet gives 10 USDC per day): T1 "Landing page" **3 USDC**, T2 "Freighter integration" 5 USDC, T3 "Dashboard" 2 USDC. Only T1 is funded and paid on camera.

One-line pitch: **"A company splits its project into fixed-price tasks; each task's money is locked on Stellar before the work starts and released to the freelance's wallet the moment the company approves."**

## A. Video script (2:30 to 3:00)

The voice-over is recorded in French for the demo; the English text below is the reference. The on-screen labels are in English.

**0:00 — The problem** *(face camera or slide 1)*
"Freelances get paid late, sometimes never. Small companies that split a project between several freelances juggle quotes, invoices and trust, one person at a time. In between, the big platforms typically take 10 to 20 % and hold the money until their payout cycle. TaskVault fixes both sides."

**0:25 — Project, tasks, candidates** *(screen)*
"I'm Claire, I run Studio Nova. I connect my Freighter wallet and sign: no account, no password. I create my project, a booking site for a yoga studio, and split it into three tasks with a fixed price each: the landing page at 3 dollars — we're on testnet —, the Freighter integration, the dashboard.
Yanis and Nora apply to the landing page: a short message and their skills. Nobody haggles: the price is mine. My candidate list updates live. TaskVault ranks them with a simple, explainable score, and Yanis gets "Recommended". I choose him."

**1:10 — Funding** *(screen, then stellar.expert)*
"I click "Fund the project". Two signatures in Freighter: Trustless Work deploys an escrow for this task on Stellar, with Yanis as the receiver, and my 3 USDC go into it. They are not with Yanis yet, and not with us either. Here is the contract, public, on stellar.expert. Yanis knows the money exists before he writes a line of code."

**1:45 — Delivery, rating, release** *(screen: payment panel, "Freelancer USDC balance")*
"Yanis delivers: he pastes his pull-request link and signs; the link is recorded on chain as the delivery evidence. I check it, give him five stars, and sign twice: approve, release. Look at his balance: it just went up, in five seconds. No wire, no thirty days."

**2:15 — Why it compounds** *(screen: task T2)*
"Next task. Yanis and Nora apply again. Nora matches the skills better, but Yanis has already delivered well for me: he is now "Validated" and on top, 90 against 20. The company still decides — but trust is earned task by task, and it is on chain."

> **Direct-mode variant** (if `LOWBID_PAYMENT_MODE=direct`, see runbook §1.10 / §4.2) — replaces 1:10 and 1:45:
> **1:10** "Here the payment goes wallet to wallet, without escrow: it's our fallback mode. Nothing is locked in advance."
> **1:45** "Yanis declares his delivery with the link. I check, give five stars, click "Validate and pay" and sign once in Freighter. Look at his balance: up, in five seconds. Here is the transaction on stellar.expert."
> Never say "escrow" or "contract" in this variant.

**2:35 — Why Stellar** *(slide 4)*
"Why Stellar? Because digital dollars, USDC, settle in five seconds for a fraction of a cent. Because the contract that holds the money runs on Soroban, with no bank in the middle. And because the wallet, Freighter, is both the identity and the signature. Three building blocks, one flow. TaskVault: fixed prices, earned trust, guaranteed payment."

*(About 350 spoken words, 2:45 at a normal pace including waits. Read it aloud once with a timer before recording. Cut the Freighter popup waits in editing.)*

## B. Five-slide deck

**Slide 1 — Problem**
- Freelances paid late, or never.
- Companies that split a project juggle several freelances, quotes and invoices, with no shared track record.
- Platforms: typically 10 to 20 % commission (public fee schedules of the big marketplaces), funds held until payout.
- *Speaker note: one figure, one sentence per problem, 30 seconds max.*

**Slide 2 — Solution**
- The company splits a project into tasks with a fixed price in USDC.
- Freelances apply with a message and their skills; no race to the bottom.
- A deterministic score (history with this company, ratings, skills) recommends; the company chooses.
- Each task's price is locked in its own Trustless Work escrow once the freelance is chosen, released when the company approves the delivery.
- *Speaker note: stress "the company chooses" and "fixed price".*

**Slide 3 — Demo (screenshots from `docs/screenshots/`)**
- `03-projet-entreprise.png` — the project page: tasks, statuses, candidates, funding panel.
- `04-tache-candidats.png` — ranked candidates, "Recommended", "Choose" on every row.
- `05-tache-livree-freelance.png` — the freelance's view after "Declare the delivery".
- `06-valider-noter.png` — the five-star rating form.
- `14-paiement-tache.png` — "Task paid", hashes linked to stellar.expert, the freelance's balance.
- `08-tache-valide-recommande.png` — the next task: A 90.0 "Validated" + "Recommended" vs B 20.0.
- Optional: `07-tableau-kanban.png` (the freelance's kanban), `mobile-tache-candidats.png` (phone).
- *Speaker note: the screenshots are the safety net if the live demo fails. They were produced by the e2e run in direct mode; the live demo shows the escrow.*

**Slide 4 — Stellar stack (diagram)**
- Freighter: login by signed message (SEP-53), every payment step signed in the user's wallet.
- USDC on Stellar testnet (asset configurable): ~5 s; a classic payment costs ≈ 0.00001 XLM (100 stroops), the Soroban escrow calls add resource fees.
- Trustless Work: one single-release Soroban escrow per task, built by its API, proxied by Django, signed in Freighter.
- Django + vanilla JS + `@stellar/stellar-sdk`; fallback: a direct USDC payment.
- *Speaker note: draw the flow (browser + Freighter → Django → Trustless Work / Horizon → Stellar) and say "track Composed".*

**Slide 5 — Next**
- Disputes through Trustless Work's dispute-resolver role (already set to the platform wallet).
- Portable reputation (ratings and paid tasks) beyond one company.
- Off-ramp to euros through an anchor (SEP-24).
- *Speaker note: end on the one-line pitch, not on the roadmap.*

## C. Judge Q&A

**1. Why fixed prices instead of letting freelances compete on price?**
Because a race to the lowest price produces rushed work and punishes the freelances who are good. The company knows what a task is worth; freelances compete on fit and track record. The score is public and explainable: 40 points if this company has already paid the freelance for at least one task, 8 points per star of average rating from this company, up to 20 points for the share of the task's skills they match. Maximum 100.

**2. Isn't the score unfair to newcomers?**
A newcomer can still reach 20 points on skills, and the company can choose anyone: "Choose" is on every row. The history and rating parts only count the company's own experience with that freelance, so being well rated elsewhere does not crush a newcomer here, and one paid delivery rated 3 stars or more is enough to become "Validated".

**3. What if the freelance never delivers?**
The money stays in the escrow: it only moves to the freelance after the company approves and releases. For disagreements, the company opens an on-chain dispute while the task is delivered, and the freelance can open one when the company stays silent past the review window; the arbiter (`LOWBID_DISPUTE_RESOLVER`) splits the escrow between the two from `/litiges/`. See section E.

**4. Why one escrow per task and not one per project?**
Trustless Work v1 fixes the receiver when the escrow is deployed, and freezes it once funded. Tasks get their freelance at different times, so a project-wide escrow funded up front could not pay them. Multi-release escrows (one milestone per task) were studied: they allow a receiver per milestone, but only one service provider per escrow, so freelances could not sign their own delivery, and adding a task after deploy needs a platform signature. One single-release escrow per task keeps each freelance in control of their own delivery, and each escrow holds exactly one task's price.

**5. Why does the company sign four times per task?**
Every money movement or contract state change is signed by the person it concerns, in their own wallet: deploy the escrow, fund it, approve the delivery, release the funds. The freelance signs the delivery. TaskVault holds no private key: Trustless Work builds unsigned transactions, Freighter signs them, and nobody else can move the funds. The app already chains them ("Fund the project" = deploy + fund, "Validate and release" = rating + approve + release), so it is two clicks.

**6. Why not mainnet?**
To avoid handling real funds during a hackathon. The code is the same: change the network and Horizon / Soroban URLs (`STELLAR_NETWORK=public`, `STELLAR_HORIZON_URL`, `STELLAR_SOROBAN_RPC_URL`), the asset (`STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER`) and the Trustless Work URL and key. That is also why the demo uses a few USDC: it is what the test faucet gives.

**7. What does a transaction cost?**
A classic payment costs about 0.00001 XLM in network fees; the Soroban escrow calls add resource fees, still a fraction of a cent. The escrow takes a platform fee (`platformFee`), set to the minimum for the demo, plus the Trustless Work protocol fee. TaskVault has no business model in code yet: the fee is just the `LOWBID_PLATFORM_FEE` setting. Our hypothesis is that 2 to 3 % would be sustainable, far below the usual 10 to 20 %.

**8. What is on chain, honestly?**
On chain: each task's Soroban escrow (deploy, funding, delivery with the link as evidence, approval, release) and the USDC payments. Off chain, in the database: projects, tasks, applications, scores, ratings and the company's choice. Login is verified server-side from a Freighter signature.

**9. What really ran live, and what was built from the docs?**
What you see in the video ran on Stellar testnet with test USDC: every stellar.expert link in the README proves it, and the README only ticks the steps that worked on the recording. The Trustless Work integration was written from the source of their SDK and their API reference without network access during the build, and tested offline (mocked API) plus an end-to-end browser run in direct mode against a fake Horizon. *(Only if the runbook's smoke test §1.8 and rehearsal §1.9 passed: "then validated on testnet the day before.")* One vendor detail is still unconfirmed: the exact unit of the platform fee, hence the minimum value. *(If the video uses direct mode: "the escrow is coded and tested offline, but live we used our fallback, the direct payment; the README says so.")*

**10. Why Django and not React?**
Server-side rendering, fewer moving parts, faster to build in a weekend and more robust in a demo. The Stellar part runs in the browser with the official SDK and Freighter, which is where signing must happen; a framework changes nothing there.

## E. Anti-cheat

« Lowbid ne détient ni l'argent, ni la vérité. » TaskVault holds neither the money nor the truth: the money of cheaters finances the protection of the honest, and everything is verifiable on Stellar.

Every fact a dispute could turn on lives on chain and links to stellar.expert; the database only remembers who clicked what.

| Cheat | Answer | Where the proof is |
|---|---|---|
| The freelance swaps the work after approval | The delivery carries a **fingerprint** (git commit SHA or SHA-256) sent as the milestone evidence (`git:<sha> <link>`); the full deliverable is revealed to the company only once the task is paid, and must match the fingerprint | `change-milestone-status` tx |
| The company sits on a delivery to avoid paying | A **review window** (`LOWBID_REVIEW_DAYS`, 7 days by default) starts at the delivery tx; the company may ask for changes at most `LOWBID_MAX_REVISIONS` times (each re-delivery is a new evidence tx), then it is validate or dispute | delivery txs, review deadline computed from them |
| Either side disputes in bad faith | **On-chain dispute**: the company while the task is delivered, the freelance once the review window is over ("dispute for silence"). The arbiter signs the split in Freighter; an arbiter never judges a case it is party to | `dispute-escrow` and `resolve-dispute` txs |
| A company posts ghost listings to harvest applications | A **publication deposit** (max(1 % of the budget, 5 USDC)) is locked in a dedicated escrow before the project is visible. Closed project or no application after 30 days: refunded. Applications but no freelance chosen after 14 days, or cancelled after applications: **forfeited, 100 % to the guarantee fund**, never to the candidates (fake accounts would farm it) and never to TaskVault | deposit escrow, `resolve-dispute` tx to `LOWBID_GUARANTEE_FUND_ADDRESS`, public `/fonds/` page |
| A wallet claims a history it does not have | Badges are computed only from escrows with confirmed transactions, counting distinct partners: "Reliable payer", "New account", and "wallet without history" shown on a chosen candidate. Freelances rate companies too. Optional "Verified GitHub": a public gist signed with the wallet, GitHub account older than a year, one account per wallet | release / payment txs behind every figure |

What TaskVault signs itself: only the deposit's refund and forfeit (two testnet keys in `.env`, never in a template or a log). What the users sign in Freighter: everything else. What stays in the database only: applications, scores, ratings, messages and the arbiter's reasons.

## D. Demo-day checklist

> Detailed, tickable version: [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md).

- [ ] **Alarms**: the evening before (charge devices), 2 h before (full rehearsal), 30 min before (final check), then the submission time and the deadline.
- [ ] **Funded accounts**: company, freelance A, freelance B (+ platform) have XLM (friendbot); the company holds at least T1's price in test USDC.
- [ ] **USDC trustlines** on the 4 accounts (the freelance cannot be paid without it).
- [ ] **3 Chrome profiles** (Company, Freelance A, Freelance B), Freighter on **TESTNET** in each.
- [ ] **Seed with random wallets** (`make seed` with the `LOWBID_DEMO_*` variables empty) so the real freelances start with no history with the real company.
- [ ] **Tabs open in advance**: deck, TaskVault in each profile (signed in), stellar.expert on the company's and A's accounts.
- [ ] **Fallback tested**: `LOWBID_PAYMENT_MODE=direct` + restart (≈ 10 s) → "Direct payment USDC", "Validate and pay".
- [ ] **Backup video** stored locally (yesterday's rehearsal), phone hotspot ready.
- [ ] Browser zoom **110 %** (the site is dark-only), bookmarks bar hidden, notifications and screen saver off.
