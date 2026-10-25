# TaskVault — Stellar / Trustless Work / Freighter integration notes

Research spike, 2026-10-24, updated for the task board (one escrow per task). Target: **Stellar testnet only**. Stack: Django builds/proxies, vanilla JS + Freighter signs in the browser.

In TaskVault terms: the **company** owns a project and its fixed-price tasks; the **freelance** is the one the company chose for a task. Each task with a chosen freelance gets its own single-release escrow (§1.2, §8).

> **How this was verified.** The research sandbox could not open HTTPS to `horizon-testnet.stellar.org`, `friendbot.stellar.org`, `*.trustlesswork.com` or `docs.freighter.app` (egress policy 403), so nothing below is "curl-verified against the live API". Instead every claim was checked against **primary source code**: the npm tarballs of `@stellar/freighter-api@6.0.1`, `@stellar/stellar-sdk@17.3.0`, `@trustless-work/escrow@3.0.5` (latest tag), the PyPI wheel `stellar-sdk==16.1.1`, a clone of `Trustless-Work/trustlesswork-skill` (commit `80e2467`, 2026-09-26 — the vendor's own REST reference), and a clone of `stellar/freighter` (extension source, `b1e795c`). The Confidence table after §6 says which is which. **First thing to do on a real network: run the smoke test in §6.**

---

## TL;DR — the 3 calls (Trustless Work v1, testnet), once per task

```
BASE = https://dev.api.trustlesswork.com        header: x-api-key: <key>   (+ Content-Type: application/json)
Every write returns {"status":"SUCCESS","unsignedTransaction":"<XDR>"}  →  Freighter signs  →
POST /helper/send-transaction {"signedXdr": "<XDR>"}  →  {"status":"SUCCESS","message":"..."}  (deploy also returns contractId + escrow)

1. COMPANY creates escrow   POST /deployer/single-release            signer = company wallet       → contractId (from send-transaction response)
2. COMPANY funds it         POST /escrow/single-release/fund-escrow   {contractId, signer: company, amount: 25}      (company must hold USDC + trustline)
3. COMPANY releases         POST /escrow/single-release/release-funds {contractId, releaseSigner: company}           (only after every milestone approved)
   between 2 and 3:  FREELANCER  POST /escrow/single-release/change-milestone-status {contractId, milestoneIndex:"0", newStatus:"completed", newEvidence:"<url>", serviceProvider: freelancer}
                     COMPANY      POST /escrow/single-release/approve-milestone       {contractId, milestoneIndex:"0", approver: company}
```

Amounts are **JSON numbers in USDC units** (`25`, not `"25"` and not stroops). `milestoneIndex` is a **string**. Trustline = `{"address": "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5", "symbol": "USDC"}` (issuer G-address, not the C-contract). The fallback (direct mode, no escrow) is one `payment` op signed by Freighter — §2. The asset is configurable — §9.

---

## 1. Trustless Work on testnet

### 1.1 Hosts, versions, key, auth

| | v1 (use this) | v2 "Core API" (beta) |
|---|---|---|
| Testnet base URL | `https://dev.api.trustlesswork.com` | `https://beta.api.trustlesswork.com` (testnet only) |
| Mainnet base URL | `https://api.trustlesswork.com` | none — not on mainnet |
| Swagger | `<base>/docs` | — |
| Auth header | `x-api-key: <key>` (**not** `Authorization: Bearer`) | `x-api-key: <id.secret>` on every request incl. reads |
| Submit endpoint | `POST /helper/send-transaction {signedXdr}` | `POST /stellar/send-transaction {signedXdr}` |
| Build response field | `unsignedTransaction` | `unsignedXdr` (+ `txHash`, deploy adds predicted `contractId`) |
| Roles | one address per role | arrays (`approvers[]`…) + `admin` |
| npm | `@trustless-work/escrow@3.0.5` (`latest`) | `@trustless-work/escrow@5.0.0-beta.*`, `@trustless-work/escrow-js@1.0.0-beta.1` |

**Decision: v1 on `dev.api.trustlesswork.com`.** It is the vendor's documented default ("V1 is production, V2 is beta — if ambiguous use V1", skill repo 2026-09-26), the key is self-serve, and `@trustless-work/escrow@latest` still targets it. v2 is listed in §1.6 as the fallback if v1 misbehaves.

**Getting the v1 API key (self-serve):** open `https://dapp.trustlesswork.com` → connect Freighter (sign the login message) → click your wallet address (bottom-left) → *Settings → API Keys* → complete the profile (**use case is required** or no key is issued) → network **Testnet** → *Request/Generate API Key* → **copy it immediately, it is shown once**. A testnet key does not work on mainnet and vice-versa. (`dapp.dev.trustlesswork.com` is mentioned in the 3.0.5 README as the testnet dApp; unverified — try the main dApp first, it has the Testnet toggle.) For v2 keys the docs say to ask the team on Telegram (`@TrustlessWork`).

**Rate limit:** 50 requests / 60 s per client (HTTP 429). **Fees:** none to fund up front. At release the contract deducts your `platformFee` (→ `platformAddress`) and the Trustless Work protocol fee (0.3 % on mainnet; on the testnet contract lineage the fee address is a call parameter, so expect ~0.3 % or 0 — observe it). Stellar network fee on each signed tx: 100 stroops/op baseline, paid in XLM by the signer.

### 1.2 Escrow type and role mapping for TaskVault

Use **single-release** with **one milestone** (one payout to one `receiver` after all milestones are approved), **one escrow per task**, deployed once the company has chosen the task's freelance: the `receiver` is fixed at deploy. §8 explains why one multi-release escrow per project was rejected.

| TW role | TaskVault | Notes |
|---|---|---|
| `signer` (deploy) | company wallet | pays the deploy tx fee; gains no role |
| `approver` | company | approves the milestone |
| `serviceProvider` | the task's chosen freelance | marks milestone done (the delivery link is the evidence) |
| `receiver` | the task's chosen freelance | receives the payout — **needs USDC trustline** |
| `releaseSigner` | company (simplest demo) or TaskVault platform wallet | signs release-funds |
| `disputeResolver` | TaskVault platform wallet (admin Freighter) | **cannot** be a party that raises disputes; contract rejects a resolver disputing |
| `platformAddress` | TaskVault platform wallet | receives `platformFee`; **needs USDC trustline if fee > 0** |

v1 allows the same address in several roles (company = approver = releaseSigner is fine). Keep `disputeResolver` distinct from company/freelancer.

### 1.3 Lifecycle, endpoint by endpoint (v1, `Content-Type: application/json`, `x-api-key`)

Every write below returns `{"status":"SUCCESS","unsignedTransaction":"AAAAAg..."}` (400 with `message` on validation errors, 401 bad key, 429, 500). The named wallet signs that XDR with Freighter and the signed XDR goes to `POST /helper/send-transaction`.

**Deploy — `POST /deployer/single-release` — signs: `signer` (company)**
```json
{
  "signer": "G<COMPANY>",
  "engagementId": "taskvault-task-42",
  "title": "Landing page redesign",
  "description": "TaskVault task #42 Landing page, fixed price 25 USDC",
  "roles": {
    "approver": "G<COMPANY>", "serviceProvider": "G<FREELANCER>", "receiver": "G<FREELANCER>",
    "releaseSigner": "G<COMPANY>", "disputeResolver": "G<PLATFORM>", "platformAddress": "G<PLATFORM>"
  },
  "amount": 25,
  "platformFee": 1,
  "milestones": [ { "description": "Deliver the landing page" } ],
  "trustline": { "address": "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5", "symbol": "USDC" }
}
```
Constraints: `amount > 0`; 1–50 milestones, each **only** `description` (no `status`/`approved` or it 400s); title ≤ 100, description ≤ 500 chars; `platformFee` ≤ "99 %". **Unit of `platformFee` in v1 is not stated by the docs** — all v1 examples use `100`, v2 docs say "integer percent, scaled to basis points on-chain", and the v1 contract divides by 10 000 (so `100` = 1 %). `1` is harmless under either reading (0.01 % or 1 %); read it back after the first deploy (§1.4) before choosing anything bigger.
`POST /helper/send-transaction` for a deploy returns `{"status":"SUCCESS","message":"...","contractId":"C...","escrow":{...}}` — **persist `contractId`**; it is the escrow's identity for every later call.

**Fund — `POST /escrow/single-release/fund-escrow` — signs: `signer` (company, must hold ≥ amount USDC + trustline)**
```json
{ "contractId": "C<ESCROW>", "signer": "G<COMPANY>", "amount": 25 }
```
Fund the configured `amount` (fees are taken from it at release, not on top). Partial/extra funding is accepted by the contract but release requires balance ≥ amount.

**Mark done — `POST /escrow/single-release/change-milestone-status` — signs: `serviceProvider` (freelancer)**
```json
{ "contractId": "C<ESCROW>", "milestoneIndex": "0", "newStatus": "completed",
  "newEvidence": "https://github.com/studio-nova/booking/pull/1", "serviceProvider": "G<FREELANCER>" }
```
`newEvidence` is required by the v1 reference (send `""` if nothing). Status is free text.

**Approve — `POST /escrow/single-release/approve-milestone` — signs: `approver` (company)**
```json
{ "contractId": "C<ESCROW>", "milestoneIndex": "0", "approver": "G<COMPANY>" }
```
400 if already approved or if the milestone status is still empty (so the freelancer must change status first).

**Release — `POST /escrow/single-release/release-funds` — signs: `releaseSigner`**
```json
{ "contractId": "C<ESCROW>", "releaseSigner": "G<COMPANY>" }
```
Requires every milestone approved, no open dispute, balance ≥ amount. Pays `amount − platformFee − protocolFee` to `receiver` in one transfer. 400 messages: "The escrow must be completed to release earnings", "Escrow has been opened for dispute resolution", "The escrow funds have been released".

**Dispute (optional) — `POST /escrow/single-release/dispute-escrow` — signs: `signer` = any role except disputeResolver**
```json
{ "contractId": "C<ESCROW>", "signer": "G<COMPANY or FREELANCER>" }
```

**Resolve (optional) — `POST /escrow/single-release/resolve-dispute` — signs: `disputeResolver` (platform)**
```json
{ "contractId": "C<ESCROW>", "disputeResolver": "G<PLATFORM>",
  "distributions": [ { "address": "G<FREELANCER>", "amount": 15 }, { "address": "G<COMPANY>", "amount": 10 } ] }
```
Amounts positive and **must sum exactly to the current escrow balance**; every address needs the USDC trustline.

**Submit — `POST /helper/send-transaction`**
```json
{ "signedXdr": "<signedTxXdr from Freighter>" }      →  { "status": "SUCCESS" | "FAILED", "message": "..." }
```

### 1.4 Reads and helpers (v1, `x-api-key`)

- `GET /escrow/single-release/get-escrow?contractId=C...&signer=G...` → the escrow object (`amount`, `balance`, `platformFee`, `flags{approved,disputed,released,resolved}`, `milestones[]`, `roles`, `trustline`). Add `&validateOnChain=true` before release/dispute decisions (slower, no stale cache).
- `GET /helper/get-escrows-by-signer?signer=G...&validateOnChain=true`, `GET /helper/get-escrows-by-role?role=approver&roleAddress=G...` — indexer lists (`type`, `isActive`, `createdAt{_seconds}`…).
- `GET /escrow/single-release/get-multiple-escrow-balance?addresses=C...` → `[{address, balance}]`.
- `POST /helper/set-trustline {"address": "G<user>", "assetAddress": "GBBD47…FLA5"}` → `unsignedTransaction` (a classic changeTrust) → sign with that user → send-transaction. Same thing as §2.3 without needing the Stellar SDK in the browser.
- Escrow balance is also visible on chain: `https://stellar.expert/explorer/testnet/contract/C<ESCROW>`.

### 1.5 Gotchas

1. **Trustlines**: the funder (company) needs USDC + trustline to fund; `receiver`, `platformAddress` (if fee > 0) and every resolve-dispute address need the USDC trustline *before* funds move, or the release tx fails on chain. Approve/release/resolve signers only need XLM for fees. Each trustline locks 0.5 XLM; accounts need ≥ 1 XLM base reserve (friendbot gives 10 000).
2. **Types**: `amount` number (USDC units, up to 7 decimals), `milestoneIndex` string `"0"`, `platformFee` number, addresses `G…`/`C…` strings.
3. **The `signer`/role field in the body is caller-supplied and the API trusts it** — the contract enforces authorization on chain, but Django must still set it from the session wallet, never from the form.
4. **Who submits**: the XDR built by TW is a Soroban invoke with the user's account as source; Freighter must sign it with **exactly** the address named in the body (pass `address:` to `signTransaction`). A different signer → `send-transaction` returns FAILED (`tx_bad_auth`).
5. **CORS / key exposure**: TW's own React SDK calls the API from the browser with a `NEXT_PUBLIC_` key, so the API does allow browser origins. We still **proxy through Django** (`POST /pay/prepare/<task_pk>/<step>/` then `POST /pay/send/<task_pk>/<step>/`, §7.4): key stays in `settings`, Django pins `signer` to the logged-in wallet, stores `contractId`, and `send-transaction` is called by Django so the result lands in the DB regardless of the browser.
6. **Network mismatch**: the XDR embeds the testnet passphrase; Freighter on PUBLIC refuses to sign if you pass `networkPassphrase`. Always pass it (§3).
7. **Testnet resets** (SDF resets testnet periodically): escrows, USDC balances and API-key-bound data vanish; keep the funding script from §5 handy.
8. **Indexer lag**: `get-escrow` may trail the chain by seconds; poll or use `validateOnChain=true`.
9. **No React required**: the SDK is just axios over the paths above (verified in `@trustless-work/escrow` dist). Raw HTTP works.

### 1.6 Plan A′ — v2 beta, if v1 fails

Same key header, host `https://beta.api.trustlesswork.com`, paths `POST /escrow/single-release/v2/{deploy|fund|change-milestone-status|approve-milestones|release-funds|dispute|resolve-dispute}`, submit `POST /stellar/send-transaction`. Payload differences: `roles: {approvers:[G], serviceProviders:[G], releaseSigners:[G], disputeResolvers:[G], platform: G, admin: G, receiver: G}`, `platformFee` is **integer percent**, `change-milestone-status` takes `updates:[{index:0,newStatus,newEvidence}]`, `approve-milestones` takes `milestoneIndexes:[0]`, dispute needs `reason`. Responses: `{unsignedXdr, txHash, contractId?}`; submit returns `{txHash, ledger, code}` where `STELLAR_TX_SUBMITTED_INDEXER_LAGGING` is **success** (do not retry). v2 pre-checks receiver trustlines (422 `ESCROW_RECEIVER_TRUSTLINE_MISSING`) and funder trustline (422 `TOKEN_TRUSTLINE_MISSING`).

### 1.7 Django proxy skeleton (v1)

Research-time sketch, kept for the payload shape. The shipped module is `payments/trustless_work.py` (§7.2): same calls, but it returns an `{ok, status, data, error}` envelope instead of raising, and reads the real settings `TRUSTLESS_WORK_API_URL`, `TRUSTLESS_WORK_API_KEY`, `LOWBID_PLATFORM_ADDRESS`, `LOWBID_PLATFORM_FEE` (§7.1).

```python
# sketch — the real module is payments/trustless_work.py
import requests
from django.conf import settings

BASE = settings.TRUSTLESS_WORK_API_URL  # "https://dev.api.trustlesswork.com"
HDRS = {"x-api-key": settings.TRUSTLESS_WORK_API_KEY, "Content-Type": "application/json"}
USDC_TESTNET = {"address": "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5", "symbol": "USDC"}

def tw_post(path: str, body: dict, timeout: float = 20.0) -> dict:
    r = requests.post(f"{BASE}{path}", json=body, headers=HDRS, timeout=timeout)
    data = r.json() if r.content else {}
    if r.status_code >= 400 or data.get("status") == "FAILED":
        raise RuntimeError(f"TW {path} {r.status_code}: {data.get('message') or data}")
    return data                      # {"status": "SUCCESS", "unsignedTransaction": "..."} or send-transaction result

def build_deploy(task, company_addr, freelancer_addr):
    return tw_post("/deployer/single-release", {
        "signer": company_addr, "engagementId": f"taskvault-task-{task.id}",
        "title": task.title[:100], "description": task.description[:500],
        "roles": {"approver": company_addr, "serviceProvider": freelancer_addr, "receiver": freelancer_addr,
                  "releaseSigner": company_addr, "disputeResolver": settings.LOWBID_PLATFORM_ADDRESS,
                  "platformAddress": settings.LOWBID_PLATFORM_ADDRESS},
        "amount": float(task.price), "platformFee": float(settings.LOWBID_PLATFORM_FEE),   # start with 1
        "milestones": [{"description": "Deliver the task"}], "trustline": USDC_TESTNET,
    })["unsignedTransaction"]

def submit(signed_xdr: str) -> dict:
    return tw_post("/helper/send-transaction", {"signedXdr": signed_xdr})   # deploy → also contractId, escrow
```
Flow per step (as shipped): `POST /pay/prepare/<task_pk>/<step>/` → Django builds → JSON `{ok, xdr, send_url}` → browser `freighterApi.signTransaction(xdr, {networkPassphrase, address})` → `POST /pay/send/<task_pk>/<step>/ {signed_xdr}` → Django `tw.send_transaction` → saves `contract_id` / tx hash / status on the `Escrow` row. Timeouts: TW builds a Soroban simulation, allow 20 s.

---

## 2. Direct mode — USDC payment without escrow (the fallback)

Assets: **USDC testnet** = code `USDC`, issuer `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` (Circle's listed Stellar-testnet issuer; also what Trustless Work expects), 7 decimals. Its Soroban SAC id (derived deterministically with the SDK, matches TW's v2 docs example) is `CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA` — only needed for Soroban calls / Freighter `addToken`. Mainnet for reference: issuer `GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN`, SAC `CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75`. Passphrase `Test SDF Network ; September 2015`. Horizon `https://horizon-testnet.stellar.org`, RPC `https://soroban-testnet.stellar.org`.

### 2.1 Vendored browser bundles (no CDN needed)

```
npm pack @stellar/stellar-sdk@17.3.0   → package/dist/stellar-sdk.min.js   (827 KB, UMD global `StellarSdk`)
npm pack @stellar/freighter-api@6.0.1  → package/build/index.min.js        (11 KB, UMD global `freighterApi`)
<!-- as shipped (npm run vendor; templates/base.html): -->
<script src="/static/vendor/freighter-api.js"></script>          <!-- = build/index.min.js -->
<script src="/static/vendor/stellar-sdk.min.js" defer></script>
```
(`stellar-sdk-axios.min.js` is an alternative build using axios instead of fetch; not needed.)

### 2.2 Browser: build → sign → submit

```js
const USDC = new StellarSdk.Asset("USDC", "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5");
const PASS = StellarSdk.Networks.TESTNET;                       // "Test SDF Network ; September 2015"
const horizon = new StellarSdk.Horizon.Server("https://horizon-testnet.stellar.org");

async function payUsdc(fromAddr, toAddr, amount /* "25.5" string, ≤7 dp */, memo /* ≤28 bytes */) {
  const account = await horizon.loadAccount(fromAddr);          // throws NotFoundError if unfunded
  const tx = new StellarSdk.TransactionBuilder(account, { fee: StellarSdk.BASE_FEE /* "100" */, networkPassphrase: PASS })
    .addOperation(StellarSdk.Operation.payment({ destination: toAddr, asset: USDC, amount }))
    .addMemo(StellarSdk.Memo.text(memo))
    .setTimeout(300)                                             // timebounds: now … now+300 s
    .build();
  const res = await freighterApi.signTransaction(tx.toXDR(), { networkPassphrase: PASS, address: fromAddr });
  if (res.error) throw new Error(res.error.message || String(res.error));   // {signedTxXdr, signerAddress, error?}
  const signed = StellarSdk.TransactionBuilder.fromXDR(res.signedTxXdr, PASS);
  try {
    const r = await horizon.submitTransaction(signed);          // {hash, ledger, successful, ...}
    return { hash: r.hash, link: `https://stellar.expert/explorer/testnet/tx/${r.hash}` };
  } catch (e) {
    const codes = e.response?.data?.extras?.result_codes;       // e.g. {transaction:"tx_failed", operations:["op_no_trust"]}
    throw new Error("Horizon rejected: " + JSON.stringify(codes || e.message));
  }
}
```
Result codes to expect: `op_no_trust` (receiver has no USDC trustline), `op_underfunded` (sender lacks USDC), `op_no_destination` (receiver account never funded by friendbot), `tx_bad_seq` (reload account and retry), `tx_bad_auth` (signed by another address).

### 2.3 Receiver adds the USDC trustline (changeTrust via Freighter)

```js
async function addUsdcTrustline(addr) {
  const account = await horizon.loadAccount(addr);
  const tx = new StellarSdk.TransactionBuilder(account, { fee: StellarSdk.BASE_FEE, networkPassphrase: PASS })
    .addOperation(StellarSdk.Operation.changeTrust({ asset: USDC }))   // limit defaults to max
    .setTimeout(300).build();
  const res = await freighterApi.signTransaction(tx.toXDR(), { networkPassphrase: PASS, address: addr });
  if (res.error) throw new Error(res.error.message);
  return horizon.submitTransaction(StellarSdk.TransactionBuilder.fromXDR(res.signedTxXdr, PASS));
}
// check: (await horizon.loadAccount(addr)).balances.some(b => b.asset_code === "USDC" && b.asset_issuer === USDC.issuer)
```
Alternatives: Freighter UI → *Manage assets → search "USDC"* (confirm issuer `GBBD47…FLA5`, Freighter is on Testnet); or Trustless Work `POST /helper/set-trustline` (§1.4).

### 2.4 Python (Django) builds the unsigned XDR, browser signs, either side submits

```python
# pip install stellar-sdk==16.1.1
from stellar_sdk import Asset, Keypair, Network, Server, TransactionBuilder, TransactionEnvelope
from stellar_sdk.exceptions import BadResponseError, NotFoundError

HORIZON = "https://horizon-testnet.stellar.org"
PASS = Network.TESTNET_NETWORK_PASSPHRASE
USDC = Asset("USDC", "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5")

def build_payment_xdr(from_addr: str, to_addr: str, amount: str, memo: str) -> str:
    server = Server(HORIZON)
    src = server.load_account(from_addr)                       # NotFoundError → account not funded
    tx = (TransactionBuilder(src, network_passphrase=PASS, base_fee=100)
          .append_payment_op(destination=to_addr, asset=USDC, amount=amount)   # amount as str, ≤7 dp
          .add_text_memo(memo[:28]).set_timeout(300).build())
    return tx.to_xdr()                                          # browser: freighterApi.signTransaction(xdr, {networkPassphrase, address})

def build_trustline_xdr(addr: str) -> str:
    src = Server(HORIZON).load_account(addr)
    return TransactionBuilder(src, PASS, 100).append_change_trust_op(asset=USDC).set_timeout(300).build().to_xdr()

def submit_signed(signed_xdr: str) -> dict:
    env = TransactionEnvelope.from_xdr(signed_xdr, PASS)        # server-side sanity: inspect env.transaction.operations
    try:
        r = Server(HORIZON).submit_transaction(env)             # dict with "hash", "ledger", "successful"
    except BadResponseError as e:
        raise RuntimeError(e.extras.get("result_codes") if e.extras else str(e))
    return {"hash": r["hash"], "link": f"https://stellar.expert/explorer/testnet/tx/{r['hash']}"}
```
Verified offline: XDR built by this code parses back in the JS SDK with the expected payment/changeTrust op. Before submitting, Django should check `env.transaction.source == session wallet` and the single op's destination/amount match the task — `payments.services._check_payment_xdr` does exactly that (plus the asset) before submitting.

### 2.5 Getting test funds

- **XLM:** `GET https://friendbot.stellar.org/?addr=G...` (creates + funds 10 000 XLM; 200 = ok, 400 if already funded). Also `https://lab.stellar.org/account/create` button.
- **USDC:** `https://faucet.circle.com` → network **Stellar Testnet** → paste the `G…` address (**trustline must exist first**, or the payment bounces) → ~10 USDC per request, one request per 24 h per address. Do this the day before the demo, for the company account and a spare. Circle's developer-console faucet also lists Stellar Testnet but needs a Circle account.
- No Trustless Work faucet exists; their docs point to Circle's.

---

## 3. Freighter specifics (`@stellar/freighter-api` 6.0.1, verified in package source)

- UMD build: `build/index.min.js`, global **`window.freighterApi`** (webpack `library: "freighterApi"`, target `umd`). Same functions as the ESM import. `window.freighter === true` when the extension is injected.
- **Every function resolves (never throws) with `{...result, error?}`**. `error` is typed as `FreighterApiError {code:number, message:string, ext?:string[]}` in source (older docs say `string`) — read it as `err.message ?? String(err)`. User-declined → `FreighterApiDeclinedError`; no extension/Node → `FreighterApiNodeError`.

| Function | Returns |
|---|---|
| `isConnected()` | `{isConnected: boolean}` — extension installed |
| `isAllowed()` / `setAllowed()` | `{isAllowed: boolean}` — site on allow-list / prompt to add |
| `requestAccess()` | `{address}` — prompts the first time; **use this for "Connect wallet"** |
| `getAddress()` | `{address}` — silent; `""` if not allowed yet |
| `getNetwork()` | `{network: "PUBLIC"\|"TESTNET"\|"FUTURENET"\|"STANDALONE", networkPassphrase}` |
| `getNetworkDetails()` | `{network, networkUrl /*horizon*/, networkPassphrase, sorobanRpcUrl?}` |
| `signTransaction(xdr, {networkPassphrase?, address?})` | `{signedTxXdr, signerAddress}` |
| `signMessage(message, {networkPassphrase?, address?})` | `{signedMessage: string\|null, signerAddress}` — base64 (v4+; v3 returned a Buffer) |
| `signAuthEntry(entryXdr, {networkPassphrase?, address?})` | `{signedAuthEntry: string\|null, signerAddress}` |
| `addToken({contractId, networkPassphrase?})` | `{contractId}` — shows the USDC SAC in the wallet |
| `new WatchWalletChanges(ms).watch(cb)` / `.stop()` | `cb({address, network, networkPassphrase})` on change (poll, default 3 s) |

**Wrong-network detection:** after connect, `const n = await freighterApi.getNetwork(); if (n.networkPassphrase !== "Test SDF Network ; September 2015") showBanner("Switch Freighter to Testnet")`, and keep a `WatchWalletChanges` running to react to switches. Belt and braces: always pass `networkPassphrase` to `signTransaction`; Freighter then blocks the signature itself with a network-mismatch error instead of producing an XDR that Horizon rejects. Pass `address` too — Freighter switches to that account or errors if the user doesn't have it.

**`signMessage` exact semantics (for the login flow), verified in extension source `extension/src/helpers/stellar.ts` + `handlers/signBlob.ts`:**
Freighter computes `sha256( "Stellar Signed Message:\n" ‖ utf8(message) )` and ed25519-signs **that 32-byte hash** (SEP-53). The result is the 64-byte signature **base64-encoded** (88 chars). It is a plain string message in, no XDR, no Buffer on the dApp side. Django verifies with python `stellar-sdk` (which implements the same SEP-53 hashing — confirmed by a local round trip):

```python
import base64, secrets
from stellar_sdk import Keypair
from stellar_sdk.exceptions import BadSignatureError
# login (as shipped, accounts/views.py): nonce = secrets.token_hex(16); message = f"TaskVault login {nonce} {issued}"
# browser: const {signedMessage, signerAddress, error} = await freighterApi.signMessage(message, {address, networkPassphrase})
def verify_login(address: str, message: str, signed_message_b64: str) -> bool:
    try:
        Keypair.from_public_key(address).verify_message(message, base64.b64decode(signed_message_b64))
        return True
    except (BadSignatureError, ValueError):
        return False
```
Store nonces single-use with a 5-minute TTL; bind the message to the address you got from `requestAccess()` and check `signerAddress == address`. As shipped: the challenge lives in the session for `WALLET_CHALLENGE_TTL_SECONDS` (300), and `accounts/signing.py` tries SEP-53, then the raw message bytes (pre-SEP-53 Freighter), then sha256(message), logging the matching `scheme=`.

Other notes: Freighter asks for the password at most once per 5 min; `signTransaction` opens a popup, so call it from a click handler; Freighter works on `http://localhost`. The `opts.network` name mentioned in old docs is not in the 6.x type — use `networkPassphrase`.

---

## 4. Plan C — our own Soroban escrow (one paragraph)

If Trustless Work is unusable, the nearest audited-ish starting point is `stellar/soroban-examples/timelock` (soroban-sdk 28, Rust 1.92): `deposit(from: Address, token: Address, amount: i128, claimants: Vec<Address>, time_bound: {kind: Before|After, timestamp: u64})` and `claim(claimant: Address)`. It has no approve step, so an escrow needs a fork adding `approve(company)` → `release()`; budget half a day of Rust. Deploy on testnet with the Stellar CLI: `stellar keys generate --global alice --network testnet --fund` · `stellar contract build` · `stellar contract deploy --wasm target/wasm32v1-none/release/soroban_timelock_contract.wasm --source alice --network testnet --alias escrow` · `stellar contract invoke --id escrow --source alice --network testnet -- deposit --from G<COMPANY> --token CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA --amount 250000000 --claimants '["G<FREELANCER>"]' --time_bound '{"kind":"After","timestamp":0}'` (amount in stroops, i128). From the browser the invoke XDR comes from `stellar-sdk`'s `rpc.Server.prepareTransaction` and is signed with Freighter like any other tx. Treat the CLI flags as from-memory; `stellar contract deploy --help` is authoritative.

---

## 5. Demo checklist (hackathon)

1. **Accounts** (Freighter, Testnet selected): `company`, `freelanceA`, `freelanceB`, plus `platform` (dispute resolver / fee address; a 4th Freighter account or a `Keypair.random()` kept in `.env`). Separate browser profiles make the live demo clearer than switching accounts.
2. **Fund XLM**: `curl "https://friendbot.stellar.org/?addr=$G"` for all four. Script it: testnet resets wipe everything.
3. **Trustlines**: add USDC (`GBBD47…FLA5`) on **all four** (platform needs it for fees; freelances to be paid, since `receiver` must hold it before the release; company to hold USDC) — §2.3 button or Freighter "Manage assets".
4. **USDC**: Circle faucet → `company` (≥ the price of the task you fund live; ask twice over two days or fund a second address and consolidate). Freelances start at 0.
5. **Trustless Work**: key from `dapp.trustlesswork.com` (Testnet) in `TRUSTLESS_WORK_API_KEY`; keep `LOWBID_PLATFORM_FEE=1`; set `LOWBID_PLATFORM_ADDRESS` to the `platform` account; run §6 smoke test once and keep the resulting `contractId` as a backup screenshot. `.env` is read at startup only: restart the server after any change.
6. **Where to look during the demo**: company Freighter balance (USDC drops at fund), `https://stellar.expert/explorer/testnet/contract/C<ESCROW>` (escrow holds the USDC), `https://stellar.expert/explorer/testnet/tx/<hash>` after release (shows the payout to the freelancer and the fee), freelancer Freighter balance (USDC appears), `https://stellar.expert/explorer/testnet/account/G<FREELANCER>`, asset page `https://stellar.expert/explorer/testnet/asset/USDC-GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5`.
7. **Kill switch**: `LOWBID_PAYMENT_MODE=escrow|direct` (empty = auto: `escrow` when `TRUSTLESS_WORK_API_KEY` is set, else `direct`), then restart. `direct` = §2 payment from the same task page: the panel title becomes "Direct payment USDC" with a "no escrow" badge, the delivery is a declaration without a transaction, and after "Validate + rate" the company signs one "Pay the freelancer" payment, with the same stellar.expert link. A task whose escrow is already deployed keeps escrow mode.

## 6. First-run smoke test (do this before building UI)

```bash
export TW=https://dev.api.trustlesswork.com KEY=...; C=G<COMPANY>; F=G<FREELANCER>; P=G<PLATFORM>
curl -s $TW/deployer/single-release -H "x-api-key: $KEY" -H 'content-type: application/json' -d "{\"signer\":\"$C\",\"engagementId\":\"smoke-1\",\"title\":\"smoke\",\"description\":\"smoke\",\"roles\":{\"approver\":\"$C\",\"serviceProvider\":\"$F\",\"receiver\":\"$F\",\"releaseSigner\":\"$C\",\"disputeResolver\":\"$P\",\"platformAddress\":\"$P\"},\"amount\":1,\"platformFee\":1,\"milestones\":[{\"description\":\"m\"}],\"trustline\":{\"address\":\"GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5\",\"symbol\":\"USDC\"}}"
# expect {"status":"SUCCESS","unsignedTransaction":"AAAA..."}; paste the XDR into https://lab.stellar.org (Sign transaction → Freighter) or the app, then:
curl -s $TW/helper/send-transaction -H "x-api-key: $KEY" -H 'content-type: application/json' -d '{"signedXdr":"<signed>"}'
# expect contractId; then GET $TW/escrow/single-release/get-escrow?contractId=C...&signer=$C and read back platformFee / flags.
```

## Confidence

| Item | Status | Basis |
|---|---|---|
| v1 base URLs, `x-api-key`, rate limit 50/60 s | from-docs (vendor skill repo 2026-09-26 + npm 3.0.5 source) | not curl-able from sandbox |
| v1 endpoint paths (`/deployer/single-release`, `/escrow/single-release/*`, `/helper/send-transaction`, `/helper/set-trustline`) | verified in `@trustless-work/escrow@3.0.5` dist source + vendor docs | |
| v1 request bodies / field types / who signs | from-docs + SDK `.d.ts` types (agree) | |
| `send-transaction` returns `contractId` on deploy | from-docs + SDK return type | |
| `platformFee` unit in v1 | **unsure** (bps vs percent) — use `1`, read back | |
| Protocol fee on testnet | unsure (0.3 % mainnet fact; testnet lineage parameterised) | |
| API key self-serve via dApp Settings → API Keys (Testnet) | from-docs | `dapp.dev.trustlesswork.com` unverified |
| Browser can call TW directly (CORS) | inferred from vendor's browser SDK design; proxy anyway | |
| v2 beta host/paths/shapes | from-docs (vendor v2 reference) | |
| USDC testnet issuer `GBBD47…FLA5`, 7 decimals | from-docs (Circle contract-address page via search, TW docs) | |
| USDC testnet SAC `CBIELTK…DAMA` | verified-offline (SDK `Asset.contractId(TESTNET)`), matches TW v2 example | |
| Circle faucet supports Stellar Testnet, 10 USDC / 24 h | from-docs (search snippets, not fetched) | |
| Friendbot URL / testnet passphrase / Horizon & RPC URLs | from-docs + SDK constants | |
| Freighter 6.0.1 function names, params, return shapes, UMD global `freighterApi` | verified-source (npm tarball) | |
| Freighter `signMessage` = SEP-53 (prefix + sha256) → base64 | verified-source (extension repo) | version where this started: unsure |
| Python `verify_message` matches Freighter | verified-offline round trip (stellar-sdk 16.1.1) | |
| stellar-sdk 17.3.0 UMD `dist/stellar-sdk.min.js`, global `StellarSdk` | verified-source | |
| Direct-mode JS/Python payment + trustline code | Python verified-offline (XDR parses in JS SDK); JS from SDK API, not executed in a browser | |
| Soroban timelock signatures | verified-source (`soroban-examples` clone); CLI flags from-memory | |

---

## 7. Payments modules — as shipped (task board)

Shipped and offline-tested: `payments/trustless_work.py`, `payments/stellar.py`, `payments/models.py` (`Escrow`, one per task), `payments/services.py` (the flow), `payments/views.py` + `payments/urls.py` (mounted at `/pay/`), the panel `templates/payments/_escrow_panel.html`, the project banner `templates/projects/_funding_panel.html`, `static/js/lowbid-pay.js`, and the tests `payments/tests.py` (clients, `requests` mocked, XDR round-tripped) and `payments/tests_flow.py` (HTTP flow, both modes). The e2e run drives the direct mode against a fake Horizon (`tests/e2e/fake-horizon.js`). **Nothing has hit the live testnet from this sandbox** (egress 403): the first real run must be the §6 smoke test, also runnable from a Django shell (docstring of `payments/trustless_work.py`).

### 7.1 Settings (`lowbid/settings.py`, `.env.example`)

| Setting | Default | Meaning |
|---|---|---|
| `TRUSTLESS_WORK_API_URL` / `TRUSTLESS_WORK_API_KEY` | `https://dev.api.trustlesswork.com` / `""` | v1 host + `x-api-key`. Empty key ⇒ every TW call short-circuits to `{"ok": False, "status": 0, "error": "The escrow service is not configured (Trustless Work API key missing)."}` without HTTP. |
| `LOWBID_PAYMENT_MODE` | `""` | **THE switch**: `escrow` \| `direct` \| empty = auto (`escrow` when the key is set, else `direct`). Read through `payments.stellar.payment_mode()`, never directly. A native-XLM asset forces `direct` (§9). |
| `LOWBID_PLATFORM_ADDRESS` | `""` | Platform wallet (G…) = `disputeResolver` + `platformAddress`. Must hold the asset trustline when the fee > 0. Empty ⇒ the company wallet takes both roles (warning logged, alert in the panel; TW may refuse it). |
| `LOWBID_PLATFORM_FEE` | `Decimal("1")` | v1 `platformFee` JSON number. Unit unverified (bps vs %); keep `1` until `get_escrow()` reads it back. |
| `STELLAR_ASSET_CODE` / `STELLAR_ASSET_ISSUER` | `USDC` / `GBBD47…FLA5` | The payment asset (§9). The legacy `STELLAR_USDC_CODE` / `STELLAR_USDC_ISSUER` are their defaults. |

### 7.2 Python API

Every network function returns the same envelope and **never raises** on HTTP/transport errors:
`{"ok": bool, "status": int, "data": dict, "error": str | None}` (`status == 0` ⇒ the request never left: transport error or missing key). Errors are English, user-facing; the API key is never logged.

`payments.trustless_work` (v1, all keyword-only; paths in the `PATH_*` constants):

| Function | Endpoint | Signs (Freighter) | Notes |
|---|---|---|---|
| `is_configured()` | — | — | key present |
| `deploy_single_release(signer, engagement_id, title, description, amount, approver, service_provider, receiver, release_signer, dispute_resolver, platform_address, platform_fee, milestone_description)` | `POST /deployer/single-release` | company | body exactly §1.3 (`roles{}`, numbers in asset units, `milestones:[{description}]`, `trustline` = `{address: STELLAR_ASSET_ISSUER, symbol: STELLAR_ASSET_CODE}`); title/description clipped to 100/500 |
| `fund_escrow(contract_id, signer, amount)` | `POST /escrow/single-release/fund-escrow` | company | |
| `change_milestone_status(contract_id, milestone_index="0", new_status="completed", evidence="", service_provider)` | `POST /escrow/single-release/change-milestone-status` | freelance | `milestoneIndex` sent as a string, `newEvidence` = the delivery link (≤ 280 chars) |
| `approve_milestone(contract_id, milestone_index="0", approver)` | `POST /escrow/single-release/approve-milestone` | company | |
| `release_funds(contract_id, release_signer)` | `POST /escrow/single-release/release-funds` | company | |
| `send_transaction(signed_xdr)` | `POST /helper/send-transaction` | — | `data["contractId"]` after a deploy; `status:"FAILED"` ⇒ `ok False` |
| `set_trustline(address)` | `POST /helper/set-trustline` | the user | optional alternative to `stellar.build_change_trust_xdr` (unused by the flow) |
| `get_escrow(contract_id, signer=None, validate_on_chain=False)` | `GET /escrow/single-release/get-escrow` | — | read back `platformFee` / `flags` / `balance` |

The unsigned XDR of every build is `env["data"]["unsignedTransaction"]`.

`payments.stellar` (direct mode + Horizon helpers, python `stellar_sdk`):

- `payment_mode() -> "escrow" | "direct"` — the switch (above, §9).
- `asset_code()`, `asset_issuer()`, `is_native()`, `asset() -> Asset` (§9); `network_passphrase()`; `horizon_url()`.
- `build_payment_xdr(*, source, destination, amount: Decimal, memo=None, sequence=None, base_fee=None) -> str` — one `payment` op of the configured asset, text memo trimmed to 28 UTF-8 bytes (`taskvault:task:<pk>`), timeout 300 s. `sequence=None` loads the account (and `/fee_stats`) from Horizon; passing `sequence` builds fully offline. Raises `StellarError` (English message) on bad amount, unfunded source (Horizon 404) or Horizon unreachable.
- `build_change_trust_xdr(*, source, sequence=None, base_fee=None) -> str` — asset trustline (limit max); refused for the native asset.
- `parse_payment_xdr(xdr) -> dict | None` — `{source, destination, amount, asset_code, asset_issuer, memo, hash, op_type}`; `services.confirm_direct_pay` uses it (`_check_payment_xdr`) to check the signed XDR matches the `Escrow` row (source = company, destination = chosen freelance, amount = task price, asset = configured) before submitting; a mismatch is refused as `tampered`.
- `submit_xdr(signed_xdr) -> envelope + "hash"` — `POST {Horizon}/transactions`; `hash` is computed locally so it is known even on 504 (`ERR_TIMEOUT`). Horizon `result_codes` → English messages (`op_no_trust`, `op_underfunded`, `op_no_destination`, `tx_bad_seq`, `tx_bad_auth`, …) via `explain_result_codes()`.
- `has_trustline(address) -> bool | None` (native ⇒ `True` without a call), `asset_balance(address) -> Decimal | None` (`None` only when Horizon is unreachable; 404 ⇒ `False` / `0`), `load_account`, `load_sequence`, `horizon_base_fee`.
- `transaction_status(hash) -> bool | None` — `True` applied, `False` unknown/failed, `None` Horizon down. Used by `prepare_direct_pay` to reconcile a payment whose submit timed out, without a second signature.
- `explorer_tx_url(hash)`, `explorer_account_url(addr)`, `explorer_contract_url(contract_id)` → stellar.expert (`testnet` unless `STELLAR_NETWORK == "public"`).

### 7.3 JS API (`static/js/lowbid-pay.js`, `window.Lowbid.pay`)

Loaded on every page by `templates/base.html` (`defer`, after `lowbid-wallet.js`; `vendor/stellar-sdk.min.js` is deferred too, `vendor/freighter-api.js` is not); `base.html` exposes `LOWBID.asset`, `LOWBID.paymentMode` and `LOWBID.urls.trustlinePrepare/trustlineSend`. Events are delegated on `document`, so buttons rendered later work.

- `Lowbid.pay.signAndSend({xdr, sendUrl, extra})` → `Lowbid.signTransaction(xdr, {networkPassphrase, address: LOWBID.walletAddress})` → `Lowbid.api(sendUrl, {method:"POST", body:{signed_xdr, ...extra}})`. A declined Freighter prompt ⇒ warning toast and a rejected promise with `.handled = true`.
- `Lowbid.pay.run({step, prepareUrl, body})` — one prepare → sign → send round trip; `Lowbid.pay.runChain(next, {stopAfter, onStep})` — follows the server's `next` while it is the viewer's own signature (deploy → fund, approve → release, direct_pay).
- `Lowbid.pay.runStep(button)` — bound to `[data-pay-step][data-prepare-url]` (+ optional `data-confirm-*`, `data-pay-body`, `data-no-reload`): runs the step, chains `next`, then follows `redirect` or reloads; errors go to the nearest `[data-pay-error]` and a toast.
- `Lowbid.pay.fundProject(button)` — bound to `[data-fund][data-pending-url]`: `GET /pay/project/<pk>/pending.json`, then `runChain(task.next, {stopAfter: ["fund"]})` for each pending task, with a progress label (`Task 1/2 "…": Lock the funds…`), then the toast `Project funded: N escrow(s) created and funded.`
- `Lowbid.pay.ensureTrustline(button?)` — bound to `[data-pay-trustline]`: `POST /pay/trustline/prepare/` → sign & send, or a toast when already present.
- `Lowbid.pay.watchBalance(el, {interval=5000, maxMs=900000})` → polls Horizon `/accounts/{addr}` (every 5 s for 2 min, then 15 s, up to 15 min) for every `[data-usdc-balance="<addr>"][data-watch]`; `fetchUsdcBalance(addr)` reads the configured asset; `explorerTxUrl` / `explorerAccountUrl` / `explorerContractUrl`; `toastTx(message, hash)`.

### 7.4 Wiring (views + urls + model)

One prepare/send pair per step, under `/pay/` (`payments:` namespace), `@require_POST` + `@wallet_required`, JSON in/out, every `signer` / role field taken from the `Escrow` row (itself built from the task: payer = `project.company`, payee = `task.assigned_to`), never from a form value. Role and state gates run in both halves; the authoritative state table is the docstring of `payments/services.py` (copied in `docs/ARCHITECTURE.md` → Payments).

| URL | View | Name |
|---|---|---|
| `POST /pay/prepare/<task_pk>/<step>/` (body `{delivery_link}` for `deliver`) | `views.prepare` | `payments:prepare` |
| `POST /pay/send/<task_pk>/<step>/` (body `{signed_xdr, ...extra}`) | `views.send` | `payments:send` |
| `POST /pay/trustline/prepare/` / `POST /pay/trustline/send/` | `views.trustline_prepare` / `trustline_send` | `payments:trustline_prepare` / `_send` |
| `GET /pay/project/<pk>/pending.json` | `views.project_pending` (company only) | `payments:project_pending` |
| `GET /pay/<task_pk>/` | `views.task_pay` → 302 to the task page `#paiement` | `payments:task_pay` |

**Escrow mode** (`Escrow.mode == "escrow"`, one single-release escrow per task, one milestone):

| step | button (UI) | session wallet | prepare builds | Escrow status | Task status | persisted |
|---|---|---|---|---|---|---|
| `deploy` | "Create the escrow" (or "Fund the project") | company | `tw.deploy_single_release(signer=company, engagement_id=f"taskvault-task-{pk}", title=task.title, description=task.description or project.title, amount=task.price, approver=release_signer=company, service_provider=receiver=chosen freelance, dispute_resolver=platform_address=LOWBID_PLATFORM_ADDRESS, platform_fee=LOWBID_PLATFORM_FEE, milestone_description=f"Delivery of task #{pk} — {title}"[:200])` | `created → deployed` | `taken` | `contract_id`, `deploy_tx_hash` |
| `fund` | "Lock the funds" | company | `tw.fund_escrow(contract_id, signer=company, amount)` | `deployed → funded` | `taken` | `fund_tx_hash`, `funded_at`; project `draft → funded` once every assigned task holds funds |
| `deliver` | "Declare the delivery" (+ link) | chosen freelance | `tw.change_milestone_status(contract_id, evidence=link[:280], service_provider=freelance)` | `funded → delivered` | `taken → delivered` | `deliver_tx_hash`, `delivered_at`, `delivery_note`; `Task.delivery_link` keeps the full link |
| (validate) | "Validate + rate" | company | nothing on chain: `POST /taches/<pk>/valider/` stores the Rating | — | `delivered` | `Rating` |
| `approve` | "Validate the delivery" (chained) | company | `tw.approve_milestone(contract_id, approver=company)` | `delivered → approved` | `delivered` | `approve_tx_hash` |
| `release` | "Release the funds" (chained) | company | `tw.release_funds(contract_id, release_signer=company)` | `approved → released` | `delivered → paid` | `release_tx_hash`, `released_at`; `projects.services.mark_paid` |

**Direct mode** (`Escrow.mode == "direct"` — no `deployed`, `funded` or `approved`):

| step | button (UI) | session wallet | prepare builds | Escrow status | Task status | persisted |
|---|---|---|---|---|---|---|
| `deliver` | "Declare the delivery" | chosen freelance | **nothing to sign**: prepare records the delivery and answers `{ok, redirect, message}` | `created → delivered` | `taken → delivered` | `delivered_at`, `delivery_note` |
| (validate) | "Validate + rate" | company | the Rating | — | `delivered` | `Rating` |
| `direct_pay` | "Pay the freelancer" (chained) | company | `stellar.build_payment_xdr(source=company, destination=freelance, amount=task.price, memo=f"taskvault:task:{pk}")`; send checks it with `parse_payment_xdr` then `submit_xdr` | `created`/`delivered → paid` | `delivered → paid` | `payment_tx_hash`, `released_at`; `mark_paid`; project `draft → funded` on the first payment |

`trustline` (no task): prepare checks `stellar.has_trustline(wallet)` → `{ok:true, message:"USDC trustline already present."}` (`<code> trustline already present.`) if present (or the native-asset message), else `stellar.build_change_trust_xdr(source=wallet)`; send checks the op (`change_trust`, source, issuer) and submits to Horizon; nothing persisted.

Response shapes: prepare → `{"ok": true, "xdr", "send_url", "extra"}`, or `{"ok": true, "redirect", "message", "next"}` when there is nothing to sign. send → `{"ok": true, "redirect", "status", "task_status", "tx_hash", "hash", "contract_id", "explorer_url", "message", "pending", "next"}`. **Business refusals are HTTP 200** `{"ok": false, "error", "message"}`; codes `not_chosen · forbidden · wrong_state · wrong_mode · unknown_step · tampered · provider · stellar · invalid · not_assigned`. A provider failure never flips the status; the TW/Horizon message is kept in `Escrow.last_error` and shown in the panel. A replayed send for a step already recorded with the same hash answers "Step already confirmed.".

Model: `Escrow` 1-1 with `projects.Task` (`related_name="escrow"`), created at the first prepare (deploy in escrow mode, deliver / direct_pay in direct mode) or by `on_task_validated`: `mode` (frozen from `stellar.payment_mode()`, re-frozen while still `created`), `amount`, `payer_address`, `payee_address`, `platform_address`, `contract_id`, `engagement_id`, one `*_tx_hash` per step, `status` (`created / deployed / funded / delivered / approved / released / paid`; `failed` exists in the choices but the flow never sets it), `delivery_note`, `last_error`, `funded_at / delivered_at / released_at`.

Before the demo: `LOWBID_PLATFORM_ADDRESS` set + funded + asset trustline; the chosen freelance has the asset trustline ("Add the USDC trustline" in the panel — the release fails on chain otherwise); the company holds at least the price of each task it funds (Circle faucet, §2.5).

### 7.5 Open risks

1. Nothing live-tested: TW field names/types follow the SDK sources, but a 400 on the first deploy is the most likely first failure → `env["error"]` carries the vendor message; the smoke test in the `trustless_work.py` docstring is step one on a real network.
2. `platformFee` unit (bps vs percent) — read it back with `get_escrow()`; `1` is safe either way. The freelance receives the task price minus the platform and protocol fees in escrow mode, the exact price in direct mode.
3. `send-transaction` success detection relies on HTTP 2xx + `status != "FAILED"`; if TW ever returns 200 with another failure marker, `ok` would be wrongly true — log the payload on the first live run.
4. `submit_xdr` 504: Horizon may have applied the tx; the response carries `hash`, so `confirm_direct_pay` stores it as *pending* (panel shows the explorer link) and the next `prepare_direct_pay` reconciles it. Trustless Work sends have no such reconciliation yet.
5. Each task costs 10 Trustless Work calls (deploy, fund, deliver, approve, release: one build + one send each) against a 50 req / 60 s rate limit. Fine for a demo project; on a large one, "Fund the project" (4 calls per task in a row) can hit HTTP 429 — retry after a minute, the steps already sent are kept.
6. `watchBalance` hits Horizon from the browser (public CORS, rate-limited ~3600 req/h per IP) — one watcher per page is fine, do not multiply.

---

## 8. Multi-release escrow — studied and rejected

Research 2026-10-24, before the per-task design was built. Same verification caveat as the rest of this file: the vendor API and docs were unreachable from the sandbox, so everything was checked against primary sources — the contract source `Trustless-Work/trustlesswork-smart-contract-stellar` (branches `multi-release-main@d5cfc2e` and `multi-release-develop@cd9bd58`, the testnet lineage), the npm client `@trustless-work/escrow@3.0.5` (endpoint paths and payload types), the vendor REST reference `Trustless-Work/trustlesswork-skill@80e2467`, and the v2 beta (`@trustless-work/escrow@5.0.0-beta.2`). Nothing was run against the live API.

### 8.1 What multi-release offers (v1)

```
POST /deployer/multi-release                          signer           (any account; the company in TaskVault)
POST /escrow/multi-release/fund-escrow                signer           (any depositor holding the asset + trustline)
POST /escrow/multi-release/change-milestone-status    serviceProvider  (ONE address per escrow)
POST /escrow/multi-release/approve-milestone          approver
POST /escrow/multi-release/release-milestone-funds    releaseSigner
PUT  /escrow/multi-release/update-escrow              platformAddress  (append milestones)
GET  /helper/get-escrow-by-contract-ids?contractIds=C…&validateOnChain=true
```

- **`receiver` is per milestone** (contract `Milestone { amount, receiver, flags }`; client type `MultiReleaseMilestone.receiver`): one escrow per project with one milestone per task, each paying a different freelance, is supported natively. `roles` has no `receiver`; `milestones` is 1 to 50 items of exactly `{description, amount, receiver}` (no flags at init); there is no top-level `amount`.
- Funding is **pooled**: any amount > 0, several partial fundings allowed; a release only checks `contract balance ≥ milestone.amount`, so it is not earmarked per milestone.
- Per task: `change-milestone-status` (serviceProvider) → `approve-milestone` (approver; refused while the milestone status is empty; moves no funds) → `release-milestone-funds` (releaseSigner; requires `approved`, otherwise `MilestoneNotCompleted`). The receiver gets `amount − 0.3 % protocol fee − platformFee` (basis points on chain).
- `milestoneIndex` is a 0-based **string**; amounts are JSON numbers in asset units.
- Vendor-reference inconsistencies resolved in favour of the client and the contract: there is no `complete-milestone` endpoint; approving does **not** release funds; the multi-release dispute endpoints are `dispute-milestone` / `resolve-milestone-dispute`; the path is unversioned (no `/v1/`).

### 8.2 Why TaskVault did not use it

1. **One `serviceProvider` for the whole escrow.** The contract rejects any other signer on `change-milestone-status` (`OnlyServiceProviderChangeMilstoneStatus`), and `approve-milestone` needs a non-empty status. With several freelances on one project, no freelance could sign their own delivery on chain: either the company marks the milestone for them (three company signatures per task: status, approve, release) or the platform signs it server-side with a secret key in `.env`. The task board's promise — the freelance declares the delivery from their own wallet, with the link as on-chain evidence — would be lost.
2. **Receivers must be known at deploy.** Tasks are attributed at different times. Deploying early means appending each milestone later with `update-escrow`, which is signed by **`platformAddress`** (a platform key or a fourth Freighter in the loop), and after funding existing milestones are frozen and must be copied back byte-for-byte. Deploying late means waiting until every task of the project is attributed before anything is locked.
3. **The pooled balance is not earmarked.** An under-funded project lets the first releases drain the pool; a per-task escrow holds exactly that task's price.
4. **Native XLM does not help either:** v1 wants `trustline: {address: <issuer G…>, symbol}`, and native XLM has no issuer (§9).

v2 (beta) would fix (1) with up to five `serviceProviders` and batched `approve-and-release-milestones`, but it is beta, testnet-only and shape-incompatible with v1.

### 8.3 Decision

**One v1 single-release escrow per task** (§1.2, `payments/services.py`): each freelance is `serviceProvider` + `receiver` of their own escrow and signs their own delivery; the escrow is deployed only once the company has chosen the freelance, so the receiver is right by construction; each escrow holds exactly one task's price. The costs, accepted: N deploys + N funds instead of one ("Fund the project" chains them, two signatures per task), and no single "project escrow" to show on stellar.expert — the project banner lists every task's contract and hashes instead. The other fallback considered — `receiver` = company followed by a plain transfer to the freelance — was rejected outright: the freelance would not be protected by the escrow, which would be misleading in a demo.

---

## 9. Payment asset configuration

| Setting | Default | Notes |
|---|---|---|
| `STELLAR_ASSET_CODE` | `STELLAR_USDC_CODE` → `USDC` | upper-cased |
| `STELLAR_ASSET_ISSUER` | `STELLAR_USDC_ISSUER` → `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` (Circle testnet USDC) | the issuer **G-address**, not the SAC `C…` id |

- Read through `payments.stellar.asset_code()`, `asset_issuer()`, `is_native()` and `asset()` (a `stellar_sdk.Asset`), never from settings directly. The legacy names `STELLAR_USDC_CODE` / `STELLAR_USDC_ISSUER` still work as defaults.
- The asset is used everywhere a payment touches the chain: the Trustless Work `trustline` field (`{address: issuer, symbol: code}`), the direct `payment` op, the signed-XDR check (`_check_payment_xdr` compares code **and** issuer), the `changeTrust` builder, Horizon balance and trustline reads (`_balance_entry`), the live balance in the browser (`LOWBID.asset`), and the unit printed by `{{ x|usdc }}` / `Lowbid.formatUsdc`.
- **Native XLM fallback:** `STELLAR_ASSET_CODE=XLM` with an **empty** `STELLAR_ASSET_ISSUER` selects the native asset (`Asset.native()`). Direct payments, balances (the `native` balance line) and trustline checks handle it (`has_trustline` answers `True`, `prepare_trustline` says "The native XLM asset needs no trustline.", `build_change_trust_xdr` refuses). Trustless Work v1 cannot escrow it (no issuer to put in `trustline`), so `payment_mode()` returns `direct` with a logged warning whatever `LOWBID_PAYMENT_MODE` says. The native SAC (`CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC` on testnet, inferred) would only be expressible in the v2 beta.
- Changing the asset needs a restart (`.env` is read at boot). Existing `Escrow` rows keep the asset they were deployed with on chain; only new steps use the new one, so switch assets between demos, not in the middle of a task.
