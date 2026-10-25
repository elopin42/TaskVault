# TaskVault — Live demo runbook

The end-to-end task-board demo on Stellar testnet, in escrow mode, with the direct mode as the fallback. Labels are quoted from the templates (English UI; URL paths stay French). The pitch lines are in [`PITCH.md`](PITCH.md); the code map in [`ARCHITECTURE.md`](ARCHITECTURE.md); the Trustless Work reference in [`STELLAR_NOTES.md`](STELLAR_NOTES.md).

> **Amounts:** the Circle faucet gives **10 USDC per address per 24 h**. Keep the live task prices small: the demo project below uses **3 / 5 / 2 USDC**, and only T1 (3 USDC) is funded and paid live. The seeded data uses 300 / 500 / 400 USDC but never touches the chain.

## 0. TL;DR — the demo in 10 lines

1. Company (Studio Nova) creates the project "Booking platform for a yoga studio" and adds 3 tasks: T1 "Landing page" 3 USDC `django, ui`, T2 "Freighter integration" 5 USDC `stellar, js`, T3 "Dashboard" 2 USDC `django, charts`.
2. Freelance A (Yanis) applies to T1 with `django, ui`; freelance B (Nora) with `django`. The company's task page refreshes live: A 20.0 "Recommended", B 10.0.
3. Company clicks "Choose" on A (confirm dialog). T1 "Taken", B "Not selected".
4. Company clicks "Fund the project": **2 signatures** ("Create the escrow", "Lock the funds"). 3 USDC leave the company wallet for the escrow contract.
5. A opens T1, pastes the PR link, "Declare the delivery": **1 signature** (milestone marked done, link as evidence).
6. Company: "Validate + rate", 5 stars, "Validate and release 3.00 USDC": the rating is saved, then **2 signatures** (approve, release).
7. A's balance in the panel climbs by the price minus fees; stellar.expert shows the release.
8. A and B apply to T2 (A `stellar`, B `stellar, js`): A ranks first at **90.0** with "Validated" + "Recommended", B at **20.0**.

Signatures: company 4, freelance A 1. Direct mode (fallback): company 1, freelance 0.

---

## 1. The day before — Stellar preparation

> Allow 1 h 30. Do it in order. Keep a `notes-demo.txt` open to paste the addresses.

### 1.1 Three browser profiles, four accounts

- [ ] Chrome → profile icon → **Add**: `Company` (blue), `Freelance A` (green), `Freelance B` (orange).
- [ ] In **each** profile: install Freighter (https://www.freighter.app), **Create new wallet**, note the 12 words (testnet), ⚙️ **Settings → Network → Test Net**.
- [ ] **Platform account** (recommended): in the Company profile's Freighter → account menu → **Add a new address**. It is the escrow's dispute resolver and receives `LOWBID_PLATFORM_FEE`. Without it, TaskVault puts the company in both platform roles (panel alert "Platform address not configured: roles merged with the company") and Trustless Work may refuse the deploy. Switch back to the company account afterwards.
- [ ] Copy the 4 `G…` addresses into `notes-demo.txt`.

### 1.2 XLM (friendbot) — 4 times

- [ ] `https://friendbot.stellar.org/?addr=G…` for the company, A, B and the platform (JSON with a `hash` = OK), or **Fund with Friendbot** in Freighter.
- [ ] Each Freighter shows about 10 000 XLM.

### 1.3 USDC trustline — on the 4 accounts

> Without a trustline the faucet delivers nothing, the company cannot fund, and the release to the freelance fails on chain (Trustless Work v1 does not pre-check the receiver).

- **Way A — Freighter (works for all 4):** **Manage assets → Add an asset** → search `USDC` → check the issuer `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` (or **Add manually** with code `USDC` and that issuer) → sign → `USDC 0` appears.
- **Way B — the TaskVault button (company and chosen freelance):** on a task's payment panel, "Add the USDC trustline" → sign. Already there → toast "USDC trustline already present.". The button is shown to the two parties of a task while it is not paid.

### 1.4 Test USDC (Circle faucet)

- [ ] https://faucet.circle.com → **USDC** → **Stellar Testnet** → paste the company address → **Send**. Repeat for A, B and the platform.
- [ ] From A, B and the platform: Freighter **Send** → USDC → 10 → the company. Expected: company ≈ 40 USDC, **A = 0 USDC** (a clean before / after on camera).

### 1.5 Trustless Work API key (testnet)

- [ ] https://dapp.trustlesswork.com → connect the company's Freighter → sign.
- [ ] Click the address (bottom left) → **Settings → API Keys** → complete the profile (**use case** is required) → network **Testnet** → **Generate API Key**.
- [ ] **Copy it immediately**: it is shown once.

### 1.6 Fill `.env`

```dotenv
DJANGO_DEBUG=1
STELLAR_NETWORK=testnet
STELLAR_ASSET_CODE=USDC
STELLAR_ASSET_ISSUER=GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5
TRUSTLESS_WORK_API_URL=https://dev.api.trustlesswork.com
TRUSTLESS_WORK_API_KEY=<the key from 1.5>
LOWBID_PAYMENT_MODE=
LOWBID_PLATFORM_ADDRESS=G…PLATFORM
LOWBID_PLATFORM_FEE=1
```

- `LOWBID_PAYMENT_MODE=` empty = auto → **escrow** as soon as the key is set.
- `LOWBID_PLATFORM_FEE=1`: do not raise it (unit unverified, 1 is harmless either way).
- Do **not** set `STELLAR_ASSET_CODE=XLM` for the escrow demo: native XLM forces direct mode (`STELLAR_NOTES.md` §9).
- `.env` changed? **Restart**: `Ctrl+C`, then `make run`. The server does not re-read it.

### 1.7 Run + demo data

- [ ] Terminal 1: `make dev` → `Starting development server at http://0.0.0.0:8000/`. The navbar shows the `testnet` badge.
- [ ] Terminal 2: `make seed` (= `python manage.py seed_demo --flush`). It prints the payment mode, the asset, the 3 wallets and the project ids (ids keep counting after `--flush`).

What `seed_demo` creates (display names "Studio Nova (company)", "Yanis (freelancer A)", "Nora (freelancer B)"):

- Studio Nova's project "Booking platform for a yoga studio" **at the pitch state**, "Funded" (as a live direct payment leaves it): T1 "Landing page" (300 USDC) paid to A (rating 5, a direct-mode escrow row with a demo hash so the explorer links render — nothing is on chain), T2 "Freighter integration" (500 USDC) open with A (90.0, "Validated" + "Recommended") and B (20.0), T3 "Dashboard" (400 USDC) open.
- A draft project "Brand and showcase website redesign for a bakery" with three open tasks (250 / 600 / 120 USDC) and no candidate.

> **Seed with random wallets before the recording.** The score's history is per company: if `LOWBID_DEMO_CLIENT` / `LOWBID_DEMO_FREELANCE1` / `LOWBID_DEMO_FREELANCE2` point at your real Freighter accounts, the seed gives A a paid, 5-star task with **your** company, and in the live project A would already score 100 on T1. For the live run, leave those three variables empty (random actors fill the lists). Seed **with** your real wallets only to prepare the fallback screen (§4.3), and run `make seed` again (it flushes projects and ratings) before recording.

### 1.8 Trustless Work smoke test (STELLAR_NOTES §6, amount 1)

> Start a 30-minute timer now.

```python
# .venv/bin/python manage.py shell
from decimal import Decimal
from payments import trustless_work as tw
C, F, P = "G…COMPANY", "G…FREELANCE_A", "G…PLATFORM"
r = tw.deploy_single_release(signer=C, engagement_id="smoke-1", title="smoke", description="smoke",
        amount=Decimal("1"), approver=C, service_provider=F, receiver=F, release_signer=C,
        dispute_resolver=P, platform_address=P, platform_fee=Decimal("1"), milestone_description="m")
print(r["ok"], r["error"]); print(r["data"].get("unsignedTransaction"))
```

- [ ] `True None` + a long `AAAA…` XDR. Sign it at https://lab.stellar.org (Testnet → **Transactions → Sign** → Freighter, **company** account) and copy the signed XDR.

```python
s = tw.send_transaction(signed_xdr="<signed XDR>")
print(s["ok"], s["error"], s["data"].get("contractId"))
print(tw.get_escrow(contract_id=s["data"]["contractId"], signer=C)["data"])
```

- [ ] A `C…` contract id = success. Paste it in `notes-demo.txt`, take a **screenshot** (backup proof), note the `platformFee` read back.

### 1.9 Full rehearsal in the app (= backup video)

- [ ] **Start the screen recorder**: this rehearsal becomes the backup clip (§4.3).
- [ ] Run §3 end to end with prices of 1 USDC.
- [ ] Check: 4 company signatures + 1 freelance signature, every stellar.expert link opens, A's balance moved.
- [ ] Afterwards: A sends its USDC back to the company (A back to 0), then `make seed` (random wallets) to reset the history.

### 1.10 Decision point (end of the 30-minute timer)

- Smoke test **and** rehearsal OK → escrow mode. Done.
- Still failing → **direct mode**: `.env` `LOWBID_PAYMENT_MODE=direct`, restart, check the panels read "Direct payment USDC" + "no escrow", redo 1.9 (1 company signature), and say "direct payment", never "escrow", on camera (`PITCH.md` has the variant lines).

### 1.11 If it breaks

| Symptom | Cause | Fix |
|---|---|---|
| "The recipient has no USDC trustline." | missing trustline | §1.3 on the receiving account |
| Circle faucet: nothing arrives | trustline created **after** the request | add the trustline, request again (or another address) |
| "Insufficient USDC balance." | company below the task price | send USDC from another account (§1.4) or lower the price |
| "The recipient account does not exist on the network yet (fund it via friendbot)." / "Stellar account not found on the network: fund it first (friendbot on testnet)." | account never funded | friendbot (§1.2) |
| `Freighter is on "PUBLIC"; switch to TESTNET.` | wrong network | Freighter ⚙️ → Network → **Test Net** |
| "Transaction signed by an address other than the source account." | wrong active account in Freighter | pick the right account, then "Log out" and "Connect wallet" again |
| "The escrow service is not configured (Trustless Work API key missing)." | `TRUSTLESS_WORK_API_KEY` empty | fill `.env`, restart |
| "HTTP 401" | wrong key, or a **mainnet** key | generate a **Testnet** key (§1.5) |
| "HTTP 429" | 50 requests / 60 s exceeded | wait a minute; steps already sent are kept |
| Deploy error mentioning `disputeResolver` | `LOWBID_PLATFORM_ADDRESS` empty (company = resolver) | set the platform address, restart |
| "Fund the project" disabled | no task has a chosen freelance yet, or every assigned task is already funded | choose a freelance first; the hint under the button says which case |
| "Escrow task: declare the delivery from the payment panel (Freighter signature), once the company has locked the funds." | the freelance used a DB-only delivery in escrow mode | deliver from the payment panel, after the company funded |
| "Horizon did not confirm in time — check the transaction on the explorer before retrying." / "Transaction sent, confirmation pending — check the explorer." | Horizon 504, the tx may have passed | **do not sign again**; open the explorer link, reload in 30 s (direct payments reconcile on the next click) |
| Everything is empty in the morning | testnet reset | redo §1.2 → §1.4 (≈ 20 min) |

---

## 2. Browser setup for the recording

- One Chrome profile per actor (Company, Freelance A, Freelance B), side by side or on separate desktops. Freighter **unlocked** in each before recording; it asks for the password at most every 5 minutes.
- Tabs to open beforehand: `http://localhost:8000/` in each profile; in the company profile, `https://stellar.expert/explorer/testnet/account/G…COMPANY`; in A's profile, `https://stellar.expert/explorer/testnet/account/G…FREELANCE_A`; the USDC asset page `https://stellar.expert/explorer/testnet/asset/USDC-GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5`.
- Zoom 110–125 % (the site is dark-only, there is no theme toggle), notifications off, bookmarks bar hidden.
- Connect each profile once before recording ("Connect wallet" in the navbar, or "Connect my Freighter wallet" on the landing → sign): the session lasts 8 hours.

---

## 3. The scenario, step by step

### 3.1 The company creates the project and its tasks

*Window: Company.* "New project" (navbar, or the raised "Create" tab on a phone) → title "Booking platform for a yoga studio", a two-line description → "Create and add tasks". On the project page, the "Add a task" form adds the three tasks one by one (title, price, tags, "Add task"):

| Task | Price (live) | Tags |
|------|--------------|------|
| T1 "Landing page" | 3 USDC | `django, ui` |
| T2 "Freighter integration" | 5 USDC | `stellar, js` |
| T3 "Dashboard" | 2 USDC | `django, charts` |

Show: status "Draft", the "Total budget" KPI, each task "Open". *Say:* "The company sets the price. Nobody haggles it down."

### 3.2 A and B apply to T1

*Window: Freelance A.* "Board" (the kanban) → T1 in the "Open" column → message "Django + Tailwind every day, I deliver in 5 days including deployment.", tags `django, ui` → "Send my application". A sees its own score under "Your application": 20.0.

*Window: Freelance B.* T1 → message "Clean build from Figma, 2 iterations included.", tags `django` → score 10.0.

*Window: Company.* Keep T1's page open while they apply: the candidate list refreshes by itself every 5 seconds (live dot). A 20.0 with "Recommended", B 10.0; each row shows the score bar (History / Ratings / Skills) and "Choose". Screenshot reference: `docs/screenshots/04-tache-candidats.png`.

### 3.3 The company chooses A

*Window: Company.* "Choose" on A → the confirm dialog "Choose this freelancer?" → "Choose". T1 becomes "Taken", A "Chosen", B "Not selected". *Say:* "The score is a hint. I could have picked Nora."

### 3.4 The company funds: "Fund the project" — 2 signatures

*Window: Company.* Back to the project page. The "Escrow funding" panel shows "Tasks total", "Locked or paid out", "Paid to freelancers" and the hint "1 assigned task to fund (two Freighter signatures per task: create the escrow, lock the funds).". Click **"Fund the project"** in the header (the button reads `Task 1/1 "Landing page": …` while it runs):

1. Freighter pops up for "Create the escrow": Trustless Work deploys the single-release escrow of T1 (receiver = A, amount = 3 USDC). Sign.
2. Freighter pops up again for "Lock the funds": 3 USDC move into the contract. Sign.

Toast "Project funded: 1 escrow created and funded."; the panel now lists T1 "Funds locked" with its "Escrow contract", "Escrow creation" and "Funds locking" links; the project is "Funded". Screenshot reference (direct-mode variant of the panel): `docs/screenshots/15-financement-projet.png`.

**Show on stellar.expert:** click the "Escrow contract" link → the contract page holds 3 USDC; the company account lost 3 USDC.

> The same two steps are also available one at a time on T1's payment panel ("Create the escrow", then "Lock the funds"), and the company's dashboard "To do" lists `Fund "Landing page"`.

### 3.5 A delivers — 1 signature

*Window: Freelance A.* T1 → the payment panel "Escrow payment · task #…" shows the stepper (Escrow created ✓, Funds locked ✓) and the "Delivery link" form. Paste `https://github.com/studio-nova/booking/pull/1` → "Declare the delivery" → Freighter (A's account) → sign. T1 becomes "Delivered", the link is displayed, and the milestone change is on chain with the link as evidence. Screenshot reference (direct-mode variant): `docs/screenshots/05-tache-livree-freelance.png`.

*Before this step:* if A has no USDC trustline yet, click "Add the USDC trustline" in the same panel — the release would fail without it.

### 3.6 The company validates and rates — 2 signatures

*Window: Company.* The project page shows a "To validate" panel with "Validate + rate" on T1 (also in the dashboard "To do"). On T1: five stars are pre-selected, comment "Flawless, pixel-perfect and ahead of schedule." → "Validate and release 3.00 USDC" → confirm dialog "Validate the delivery?" → "Validate and release".

1. The rating is saved (no signature).
2. Freighter: "Validate the delivery" (approve the milestone). Sign.
3. Freighter again: "Release the funds" (release). Sign.

T1 becomes "Paid", the panel says "Funds released to the freelancer. Task paid on …", the stepper is complete, every hash links to stellar.expert. Screenshot references: `06-valider-noter.png` (the form), `14-paiement-tache.png` (the paid panel, direct-mode variant).

> If a signature is declined or fails half-way, nothing is lost: the rating is kept and the panel shows the remaining step as a button ("Release the funds"). Screenshot of an error state: `13-paiement-echec.png`.

### 3.7 A receives the USDC

Show, in this order:
- The payment panel's "Freelancer USDC balance" (polled from Horizon every 5 s): it bumps from 0 to the price minus fees.
- A's Freighter: USDC appears.
- stellar.expert: the "Funds release" transaction → the payout to A and the platform fee to the platform account.

*Say:* "Five seconds, no wire, and the money was locked before Yanis started."

### 3.8 The next task: A is on top

*Window: Freelance A.* T2 → message "I have already wired Freighter and Horizon into a Django back office.", tags `stellar` → score **90.0**.
*Window: Freelance B.* T2 → message "Stellar/JS specialist: SEP-53, trustlines, Soroban.", tags `stellar, js` → score **20.0**.
*Window: Company.* T2's candidates: A first with "Validated" + "Recommended" (40 history + 5 × 8 ratings + 20 × ½ skills), B second (20 × 2/2 skills). "Choose" is on both rows. Screenshot reference: `08-tache-valide-recommande.png`.

### Who signs what

| Step | Window | Freighter account | Escrow mode | Direct mode |
|------|--------|-------------------|-------------|-------------|
| Login | each | its own | 1 message signature | same |
| Fund T1 | Company | company | 2 (deploy, fund) | — |
| Deliver T1 | Freelance A | A | 1 (milestone change) | 0 (declaration) |
| Validate + pay T1 | Company | company | 2 (approve, release) | 1 (payment) |
| Trustline (if missing) | A or company | its own | 1 | 1 |

### Freighter popup slow or missing

Click the Freighter icon in the toolbar: the request is usually waiting there. If it never comes, reload the page — the panel shows exactly which step remains, and nothing was submitted.

---

## 4. Fallbacks during the recording

### 4.1 One signature fails

Read the message in the panel (`[data-last-error]`), fix the cause with §1.11, click the remaining step's button again. Statuses never move on a failure.

### 4.2 Trustless Work goes down mid-demo

- Nothing deployed yet for the task: `.env` `LOWBID_PAYMENT_MODE=direct`, restart (≈ 10 s), reload. The task's row is still `created`, so it switches to direct mode: the panels read "Direct payment USDC" + "no escrow", the delivery is a declaration, and "Validate and pay 3.00 USDC" ends with **one** company signature ("Pay the freelancer").
- Escrow already deployed: that task stays in escrow mode (its money is on chain). Finish it when Trustless Work is back, and run the next task in direct mode.

### 4.3 Everything is down (network, testnet, Horizon)

- Play the rehearsal clip from §1.9.
- Or show the seeded pitch state (seed with your real wallets, `make seed`): Studio Nova's project with T1 "Paid", T2's candidates A 90.0 "Validated" + "Recommended" vs B 20.0. Say plainly that the T1 payment shown is seeded demo data.

---

## 5. After the recording

1. Export the video (2:30–3:00), upload it, paste the link in `README.md`.
2. Fill the README's **Testnet addresses** table (company, A, B, platform, T1's escrow contract) with stellar.expert links, and tick the **Status / what works** lines that really worked live.
3. Deck: the five slides of `PITCH.md` §B, screenshots from `docs/screenshots/`.
4. Submit before the deadline; double-check the repository is public and `make check` is green on the submitted commit.
