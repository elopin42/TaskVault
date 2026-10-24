# Lowbid — Stellar / Trustless Work / Freighter integration notes

Research spike, 2026-10-24. Target: **Stellar testnet only**. Stack: Django builds/proxies, vanilla JS + Freighter signs in the browser.

> **How this was verified.** The research sandbox could not open HTTPS to `horizon-testnet.stellar.org`, `friendbot.stellar.org`, `*.trustlesswork.com` or `docs.freighter.app` (egress policy 403), so nothing below is "curl-verified against the live API". Instead every claim was checked against **primary source code**: the npm tarballs of `@stellar/freighter-api@6.0.1`, `@stellar/stellar-sdk@17.3.0`, `@trustless-work/escrow@3.0.5` (latest tag), the PyPI wheel `stellar-sdk==16.1.1`, a clone of `Trustless-Work/trustlesswork-skill` (commit `80e2467`, 2026-09-26 — the vendor's own REST reference), and a clone of `stellar/freighter` (extension source, `b1e795c`). The Confidence table at the end says which is which. **First thing to do on a real network: run the smoke test in §6.**

---

## TL;DR — the 3 calls (Trustless Work v1, testnet)

```
BASE = https://dev.api.trustlesswork.com        header: x-api-key: <key>   (+ Content-Type: application/json)
Every write returns {"status":"SUCCESS","unsignedTransaction":"<XDR>"}  →  Freighter signs  →
POST /helper/send-transaction {"signedXdr": "<XDR>"}  →  {"status":"SUCCESS","message":"..."}  (deploy also returns contractId + escrow)

1. CLIENT creates escrow   POST /deployer/single-release            signer = client wallet       → contractId (from send-transaction response)
2. CLIENT funds it         POST /escrow/single-release/fund-escrow   {contractId, signer: client, amount: 25}      (client must hold USDC + trustline)
3. CLIENT releases         POST /escrow/single-release/release-funds {contractId, releaseSigner: client}           (only after every milestone approved)
   between 2 and 3:  FREELANCER  POST /escrow/single-release/change-milestone-status {contractId, milestoneIndex:"0", newStatus:"completed", newEvidence:"<url>", serviceProvider: freelancer}
                     CLIENT      POST /escrow/single-release/approve-milestone       {contractId, milestoneIndex:"0", approver: client}
```

Amounts are **JSON numbers in USDC units** (`25`, not `"25"` and not stroops). `milestoneIndex` is a **string**. Trustline = `{"address": "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5", "symbol": "USDC"}` (issuer G-address, not the C-contract). Plan B (no escrow) is one `payment` op signed by Freighter — §2.

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

### 1.2 Escrow type and role mapping for Lowbid

Use **single-release** with **one milestone** (one payout to one `receiver` after all milestones are approved). Multi-release is for per-milestone payouts — not needed.

| TW role | Lowbid | Notes |
|---|---|---|
| `signer` (deploy) | client wallet | pays the deploy tx fee; gains no role |
| `approver` | client | approves the milestone |
| `serviceProvider` | winning freelancer | marks milestone done |
| `receiver` | winning freelancer | receives the payout — **needs USDC trustline** |
| `releaseSigner` | client (simplest demo) or Lowbid platform wallet | signs release-funds |
| `disputeResolver` | Lowbid platform wallet (admin Freighter) | **cannot** be a party that raises disputes; contract rejects a resolver disputing |
| `platformAddress` | Lowbid platform wallet | receives `platformFee`; **needs USDC trustline if fee > 0** |

v1 allows the same address in several roles (client = approver = releaseSigner is fine). Keep `disputeResolver` distinct from client/freelancer.

### 1.3 Lifecycle, endpoint by endpoint (v1, `Content-Type: application/json`, `x-api-key`)

Every write below returns `{"status":"SUCCESS","unsignedTransaction":"AAAAAg..."}` (400 with `message` on validation errors, 401 bad key, 429, 500). The named wallet signs that XDR with Freighter and the signed XDR goes to `POST /helper/send-transaction`.

**Deploy — `POST /deployer/single-release` — signs: `signer` (client)**
```json
{
  "signer": "G<CLIENT>",
  "engagementId": "lowbid-42",
  "title": "Landing page redesign",
  "description": "Reverse-auction job #42, winning bid 25 USDC",
  "roles": {
    "approver": "G<CLIENT>", "serviceProvider": "G<FREELANCER>", "receiver": "G<FREELANCER>",
    "releaseSigner": "G<CLIENT>", "disputeResolver": "G<PLATFORM>", "platformAddress": "G<PLATFORM>"
  },
  "amount": 25,
  "platformFee": 1,
  "milestones": [ { "description": "Deliver the landing page" } ],
  "trustline": { "address": "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5", "symbol": "USDC" }
}
```
Constraints: `amount > 0`; 1–50 milestones, each **only** `description` (no `status`/`approved` or it 400s); title ≤ 100, description ≤ 500 chars; `platformFee` ≤ "99 %". **Unit of `platformFee` in v1 is not stated by the docs** — all v1 examples use `100`, v2 docs say "integer percent, scaled to basis points on-chain", and the v1 contract divides by 10 000 (so `100` = 1 %). `1` is harmless under either reading (0.01 % or 1 %); read it back after the first deploy (§1.4) before choosing anything bigger.
`POST /helper/send-transaction` for a deploy returns `{"status":"SUCCESS","message":"...","contractId":"C...","escrow":{...}}` — **persist `contractId`**; it is the escrow's identity for every later call.

**Fund — `POST /escrow/single-release/fund-escrow` — signs: `signer` (client, must hold ≥ amount USDC + trustline)**
```json
{ "contractId": "C<ESCROW>", "signer": "G<CLIENT>", "amount": 25 }
```
Fund the configured `amount` (fees are taken from it at release, not on top). Partial/extra funding is accepted by the contract but release requires balance ≥ amount.

**Mark done — `POST /escrow/single-release/change-milestone-status` — signs: `serviceProvider` (freelancer)**
```json
{ "contractId": "C<ESCROW>", "milestoneIndex": "0", "newStatus": "completed",
  "newEvidence": "https://lowbid.app/jobs/42/delivery", "serviceProvider": "G<FREELANCER>" }
```
`newEvidence` is required by the v1 reference (send `""` if nothing). Status is free text.

**Approve — `POST /escrow/single-release/approve-milestone` — signs: `approver` (client)**
```json
{ "contractId": "C<ESCROW>", "milestoneIndex": "0", "approver": "G<CLIENT>" }
```
400 if already approved or if the milestone status is still empty (so the freelancer must change status first).

**Release — `POST /escrow/single-release/release-funds` — signs: `releaseSigner`**
```json
{ "contractId": "C<ESCROW>", "releaseSigner": "G<CLIENT>" }
```
Requires every milestone approved, no open dispute, balance ≥ amount. Pays `amount − platformFee − protocolFee` to `receiver` in one transfer. 400 messages: "The escrow must be completed to release earnings", "Escrow has been opened for dispute resolution", "The escrow funds have been released".

**Dispute (optional) — `POST /escrow/single-release/dispute-escrow` — signs: `signer` = any role except disputeResolver**
```json
{ "contractId": "C<ESCROW>", "signer": "G<CLIENT or FREELANCER>" }
```

**Resolve (optional) — `POST /escrow/single-release/resolve-dispute` — signs: `disputeResolver` (platform)**
```json
{ "contractId": "C<ESCROW>", "disputeResolver": "G<PLATFORM>",
  "distributions": [ { "address": "G<FREELANCER>", "amount": 15 }, { "address": "G<CLIENT>", "amount": 10 } ] }
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

1. **Trustlines**: the funder (client) needs USDC + trustline to fund; `receiver`, `platformAddress` (if fee > 0) and every resolve-dispute address need the USDC trustline *before* funds move, or the release tx fails on chain. Approve/release/resolve signers only need XLM for fees. Each trustline locks 0.5 XLM; accounts need ≥ 1 XLM base reserve (friendbot gives 10 000).
2. **Types**: `amount` number (USDC units, up to 7 decimals), `milestoneIndex` string `"0"`, `platformFee` number, addresses `G…`/`C…` strings.
3. **The `signer`/role field in the body is caller-supplied and the API trusts it** — the contract enforces authorization on chain, but Django must still set it from the session wallet, never from the form.
4. **Who submits**: the XDR built by TW is a Soroban invoke with the user's account as source; Freighter must sign it with **exactly** the address named in the body (pass `address:` to `signTransaction`). A different signer → `send-transaction` returns FAILED (`tx_bad_auth`).
5. **CORS / key exposure**: TW's own React SDK calls the API from the browser with a `NEXT_PUBLIC_` key, so the API does allow browser origins. We still **proxy through Django** (`POST /pay/prepare/<need_pk>/<step>/` then `POST /pay/send/<need_pk>/<step>/`, §7.4): key stays in `settings`, Django pins `signer` to the logged-in wallet, stores `contractId`, and `send-transaction` is called by Django so the result lands in the DB regardless of the browser.
6. **Network mismatch**: the XDR embeds the testnet passphrase; Freighter on PUBLIC refuses to sign if you pass `networkPassphrase`. Always pass it (§3).
7. **Testnet resets** (SDF resets testnet periodically): escrows, USDC balances and API-key-bound data vanish; keep the funding script from §5 handy.
8. **Indexer lag**: `get-escrow` may trail the chain by seconds; poll or use `validateOnChain=true`.
9. **No React required**: the SDK is just axios over the paths above (verified in `@trustless-work/escrow` dist). Raw HTTP works.

### 1.6 Plan A′ — v2 beta, if v1 fails

Same key header, host `https://beta.api.trustlesswork.com`, paths `POST /escrow/single-release/v2/{deploy|fund|change-milestone-status|approve-milestones|release-funds|dispute|resolve-dispute}`, submit `POST /stellar/send-transaction`. Payload differences: `roles: {approvers:[G], serviceProviders:[G], releaseSigners:[G], disputeResolvers:[G], platform: G, admin: G, receiver: G}`, `platformFee` is **integer percent**, `change-milestone-status` takes `updates:[{index:0,newStatus,newEvidence}]`, `approve-milestones` takes `milestoneIndexes:[0]`, dispute needs `reason`. Responses: `{unsignedXdr, txHash, contractId?}`; submit returns `{txHash, ledger, code}` where `STELLAR_TX_SUBMITTED_INDEXER_LAGGING` is **success** (do not retry). v2 pre-checks receiver trustlines (422 `ESCROW_RECEIVER_TRUSTLINE_MISSING`) and funder trustline (422 `TOKEN_TRUSTLINE_MISSING`).

### 1.7 Django proxy skeleton (v1)

Research-time sketch, kept for the payload shape. The shipped client is `payments/trustless_work.py` (§7.2): same calls, but it returns an `{ok, status, data, error}` envelope instead of raising, and reads the real settings `TRUSTLESS_WORK_API_URL`, `TRUSTLESS_WORK_API_KEY`, `LOWBID_PLATFORM_ADDRESS`, `LOWBID_PLATFORM_FEE` (§7.1).

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

def build_deploy(job, client_addr, freelancer_addr):
    return tw_post("/deployer/single-release", {
        "signer": client_addr, "engagementId": f"lowbid-{job.id}",
        "title": job.title[:100], "description": job.summary[:500],
        "roles": {"approver": client_addr, "serviceProvider": freelancer_addr, "receiver": freelancer_addr,
                  "releaseSigner": client_addr, "disputeResolver": settings.LOWBID_PLATFORM_ADDRESS,
                  "platformAddress": settings.LOWBID_PLATFORM_ADDRESS},
        "amount": float(job.winning_bid), "platformFee": float(settings.LOWBID_PLATFORM_FEE),   # start with 1
        "milestones": [{"description": "Deliver the job"}], "trustline": USDC_TESTNET,
    })["unsignedTransaction"]

def submit(signed_xdr: str) -> dict:
    return tw_post("/helper/send-transaction", {"signedXdr": signed_xdr})   # deploy → also contractId, escrow
```
Flow per step (as shipped): `POST /pay/prepare/<need_pk>/<step>/` → Django builds → JSON `{ok, xdr, send_url}` → browser `freighterApi.signTransaction(xdr, {networkPassphrase, address})` → `POST /pay/send/<need_pk>/<step>/ {signed_xdr}` → Django `tw.send_transaction` → saves `contract_id` / tx hash / status on the `Escrow` row. Timeouts: TW builds a Soroban simulation, allow 20 s.

---

## 2. Plan B — direct USDC payment (no escrow)

Assets: **USDC testnet** = code `USDC`, issuer `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` (Circle's listed Stellar-testnet issuer; also what Trustless Work expects), 7 decimals. Its Soroban SAC id (derived deterministically with the SDK, matches TW's v2 docs example) is `CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA` — only needed for Soroban calls / Freighter `addToken`. Mainnet for reference: issuer `GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN`, SAC `CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75`. Passphrase `Test SDF Network ; September 2015`. Horizon `https://horizon-testnet.stellar.org`, RPC `https://soroban-testnet.stellar.org`.

### 2.1 Vendored browser bundles (no CDN needed)

```
npm pack @stellar/stellar-sdk@17.3.0   → package/dist/stellar-sdk.min.js   (827 KB, UMD global `StellarSdk`)
npm pack @stellar/freighter-api@6.0.1  → package/build/index.min.js        (11 KB, UMD global `freighterApi`)
<script src="/static/vendor/stellar-sdk.min.js"></script>
<script src="/static/vendor/freighter-api.min.js"></script>
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
Verified offline: XDR built by this code parses back in the JS SDK with the expected payment/changeTrust op. Before submitting, Django should check `env.transaction.source == session wallet` and the single op's destination/amount match the job.

### 2.5 Getting test funds

- **XLM:** `GET https://friendbot.stellar.org/?addr=G...` (creates + funds 10 000 XLM; 200 = ok, 400 if already funded). Also `https://lab.stellar.org/account/create` button.
- **USDC:** `https://faucet.circle.com` → network **Stellar Testnet** → paste the `G…` address (**trustline must exist first**, or the payment bounces) → ~10 USDC per request, one request per 24 h per address. Do this the day before the demo, for the client account and a spare. Circle's developer-console faucet also lists Stellar Testnet but needs a Circle account.
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
# login: nonce = secrets.token_hex(16); message = f"Lowbid login\naddress: {addr}\nnonce: {nonce}\nts: {iso}"
# browser: const {signedMessage, signerAddress, error} = await freighterApi.signMessage(message, {address, networkPassphrase})
def verify_login(address: str, message: str, signed_message_b64: str) -> bool:
    try:
        Keypair.from_public_key(address).verify_message(message, base64.b64decode(signed_message_b64))
        return True
    except (BadSignatureError, ValueError):
        return False
```
Store nonces single-use with a 5-minute TTL; bind the message to the address you got from `requestAccess()` and check `signerAddress == address`. Fallback if verification fails on an old Freighter (pre-SEP-53 builds signed the raw bytes): try `kp.verify(message.encode(), sig)` once and log it.

Other notes: Freighter asks for the password at most once per 5 min; `signTransaction` opens a popup, so call it from a click handler; Freighter works on `http://localhost`. The `opts.network` name mentioned in old docs is not in the 6.x type — use `networkPassphrase`.

---

## 4. Plan C — our own Soroban escrow (one paragraph)

If Trustless Work is unusable, the nearest audited-ish starting point is `stellar/soroban-examples/timelock` (soroban-sdk 28, Rust 1.92): `deposit(from: Address, token: Address, amount: i128, claimants: Vec<Address>, time_bound: {kind: Before|After, timestamp: u64})` and `claim(claimant: Address)`. It has no approve step, so an escrow needs a fork adding `approve(client)` → `release()`; budget half a day of Rust. Deploy on testnet with the Stellar CLI: `stellar keys generate --global alice --network testnet --fund` · `stellar contract build` · `stellar contract deploy --wasm target/wasm32v1-none/release/soroban_timelock_contract.wasm --source alice --network testnet --alias escrow` · `stellar contract invoke --id escrow --source alice --network testnet -- deposit --from G<CLIENT> --token CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA --amount 250000000 --claimants '["G<FREELANCER>"]' --time_bound '{"kind":"After","timestamp":0}'` (amount in stroops, i128). From the browser the invoke XDR comes from `stellar-sdk`'s `rpc.Server.prepareTransaction` and is signed with Freighter like any other tx. Treat the CLI flags as from-memory; `stellar contract deploy --help` is authoritative.

---

## 5. Demo checklist (hackathon)

1. **Accounts** (Freighter, Testnet selected): `client`, `freelance1`, `freelance2`, plus `platform` (dispute resolver / fee address; a 4th Freighter account or a `Keypair.random()` kept in `.env`). Separate browser profiles make the live demo clearer than switching accounts.
2. **Fund XLM**: `curl "https://friendbot.stellar.org/?addr=$G"` for all four. Script it: testnet resets wipe everything.
3. **Trustlines**: add USDC (`GBBD47…FLA5`) on **all four** (platform needs it for fees; freelancers for payout; client to hold USDC) — §2.3 button or Freighter "Manage assets".
4. **USDC**: Circle faucet → `client` (≥ 10 USDC; ask twice over two days or fund a second address and consolidate). Freelancers start at 0.
5. **Trustless Work**: key from `dapp.trustlesswork.com` (Testnet) in `TRUSTLESS_WORK_API_KEY`; keep `LOWBID_PLATFORM_FEE=1`; set `LOWBID_PLATFORM_ADDRESS` to the `platform` account; run §6 smoke test once and keep the resulting `contractId` as a backup screenshot. `.env` is read at startup only: restart the server after any change.
6. **Where to look during the demo**: client Freighter balance (USDC drops at fund), `https://stellar.expert/explorer/testnet/contract/C<ESCROW>` (escrow holds the USDC), `https://stellar.expert/explorer/testnet/tx/<hash>` after release (shows the payout to the freelancer and the fee), freelancer Freighter balance (USDC appears), `https://stellar.expert/explorer/testnet/account/G<FREELANCER>`, asset page `https://stellar.expert/explorer/testnet/asset/USDC-GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5`.
7. **Kill switch**: `LOWBID_PAYMENT_MODE=escrow|direct` (empty = auto: `escrow` when `TRUSTLESS_WORK_API_KEY` is set, else `direct`), then restart. `direct` = §2 payment on the same need page: the panel title becomes "Paiement direct USDC" with a "Plan B" badge and the client gets one button ("Payer le freelance", or "Valider et payer" after the freelancer declared delivery), with the same stellar.expert link. A need whose escrow is already deployed keeps escrow mode.

## 6. First-run smoke test (do this before building UI)

```bash
export TW=https://dev.api.trustlesswork.com KEY=...; C=G<CLIENT>; F=G<FREELANCER>; P=G<PLATFORM>
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
| Plan B JS/Python payment + trustline code | Python verified-offline (XDR parses in JS SDK); JS from SDK API, not executed in a browser | |
| Soroban timelock signatures | verified-source (`soroban-examples` clone); CLI flags from-memory | |

---

## 7. Payments modules (waves 1 + 2 — built 2026-10-24, offline-tested)

Wave 1 shipped: `payments/trustless_work.py`, `payments/stellar.py`, `static/js/lowbid-pay.js`, `payments/tests.py` (`requests` mocked, XDR round-tripped through `TransactionEnvelope.from_xdr`). Wave 2 (also shipped, §7.4) added `payments/models.py` (`Escrow`), `payments/services.py` (the flow), `payments/views.py` + `payments/urls.py` (mounted at `/pay/`), the panel `templates/payments/_escrow_panel.html` and `payments/tests_flow.py`. **Nothing has hit the live testnet from this sandbox** (egress 403): the first real run must be the §6 smoke test, now runnable from a Django shell (docstring of `payments/trustless_work.py`).

### 7.1 Settings (`lowbid/settings.py`, `.env.example`)

| Setting | Default | Meaning |
|---|---|---|
| `TRUSTLESS_WORK_API_URL` / `TRUSTLESS_WORK_API_KEY` | `https://dev.api.trustlesswork.com` / `""` | v1 host + `x-api-key`. Empty key ⇒ every TW call short-circuits to `{"ok": False, "status": 0, "error": "…clé API…"}` without HTTP. |
| `LOWBID_PAYMENT_MODE` | `""` | **THE Plan B switch**: `escrow` \| `direct` \| empty = auto (`escrow` when the key is set, else `direct`). Read through `payments.stellar.payment_mode()`, never directly. |
| `LOWBID_PLATFORM_ADDRESS` | `""` | Platform wallet (G…) = `disputeResolver` + `platformAddress`. Must hold a USDC trustline when the fee > 0. |
| `LOWBID_PLATFORM_FEE` | `Decimal("1")` | v1 `platformFee` JSON number. Unit unverified (bps vs %); keep `1` until `get_escrow()` reads it back. |

### 7.2 Python API

Every network function returns the same envelope and **never raises** on HTTP/transport errors:
`{"ok": bool, "status": int, "data": dict, "error": str | None}` (`status == 0` ⇒ the request never left: transport error or missing key). Errors are French, user-facing; the API key is never logged.

`payments.trustless_work` (v1, all keyword-only):

| Function | Endpoint | Signs (Freighter) | Notes |
|---|---|---|---|
| `is_configured()` | — | — | key present |
| `deploy_single_release(signer, engagement_id, title, description, amount, approver, service_provider, receiver, release_signer, dispute_resolver, platform_address, platform_fee, milestone_description)` | `POST /deployer/single-release` | client | body exactly §1.3 (`roles{}`, numbers in USDC units, `milestones:[{description}]`, `trustline` from `STELLAR_USDC_*`); title/description clipped to 100/500 |
| `fund_escrow(contract_id, signer, amount)` | `POST /escrow/single-release/fund-escrow` | client | |
| `change_milestone_status(contract_id, milestone_index="0", new_status="completed", evidence="", service_provider)` | `POST /escrow/single-release/change-milestone-status` | freelancer | `milestoneIndex` sent as a string, `newEvidence` `""` when empty |
| `approve_milestone(contract_id, milestone_index="0", approver)` | `POST /escrow/single-release/approve-milestone` | client | |
| `release_funds(contract_id, release_signer)` | `POST /escrow/single-release/release-funds` | client | |
| `send_transaction(signed_xdr)` | `POST /helper/send-transaction` | — | `data["contractId"]` after a deploy; `status:"FAILED"` ⇒ `ok False` |
| `set_trustline(address)` | `POST /helper/set-trustline` | the user | optional alternative to `stellar.build_change_trust_xdr` |
| `get_escrow(contract_id, signer=None, validate_on_chain=False)` | `GET /escrow/single-release/get-escrow` | — | read back `platformFee` / `flags` / `balance` |

The unsigned XDR of every build is `env["data"]["unsignedTransaction"]`.

`payments.stellar` (Plan B + Horizon helpers, python `stellar_sdk` 16):

- `payment_mode() -> "escrow" | "direct"` — the switch (above).
- `usdc_asset() -> Asset`; `network_passphrase()`; `horizon_url()`.
- `build_payment_xdr(*, source, destination, amount: Decimal, memo=None, sequence=None, base_fee=None) -> str` — one USDC `payment` op, text memo trimmed to 28 UTF-8 bytes (`lowbid:<need_id>`), timeout 300 s. `sequence=None` loads the account (and `/fee_stats`) from Horizon; passing `sequence` builds fully offline with base fee 100. Raises `StellarError` (French message) on bad amount, unfunded source (Horizon 404) or Horizon unreachable (any other non-200).
- `build_change_trust_xdr(*, source, sequence=None, base_fee=None) -> str` — USDC trustline (limit max).
- `parse_payment_xdr(xdr) -> dict | None` — `{source, destination, amount, asset_code, asset_issuer, memo, hash, op_type}`; **`services.confirm_direct_pay` uses it (`_check_payment_xdr`) to check the signed XDR matches the Escrow row** (source = payer, destination = winner, amount = winning bid, asset = USDC) before submitting; a mismatch is refused as `tampered`.
- `submit_xdr(signed_xdr) -> envelope + "hash"` — `POST {Horizon}/transactions`; `hash` is computed locally so it is known even on 504 (`ERR_TIMEOUT`) → show the explorer link instead of retrying blindly. Horizon `result_codes` → French (`op_no_trust`, `op_underfunded`, `op_no_destination`, `tx_bad_seq`, `tx_bad_auth`, …) via `explain_result_codes()`.
- `has_usdc_trustline(address) -> bool | None`, `usdc_balance(address) -> Decimal | None` (`None` only when Horizon is unreachable; 404 ⇒ `False` / `0`), `load_account`, `load_sequence`, `horizon_base_fee`.
- `transaction_status(hash) -> bool | None` — Horizon `/transactions/{hash}`: `True` applied, `False` unknown/failed, `None` Horizon down. Used by `prepare_direct_pay` to reconcile a payment whose submit timed out, without a second signature.
- `explorer_tx_url(hash)`, `explorer_account_url(addr)`, `explorer_contract_url(contract_id)` → stellar.expert (`testnet` unless `STELLAR_NETWORK == "public"`).

### 7.3 JS API (`static/js/lowbid-pay.js`, `window.Lowbid.pay`)

Loaded on every page by `templates/base.html`, after `lowbid-wallet.js` (`<script src="{% static 'js/lowbid-pay.js' %}?v={{ LOWBID_ASSET_VERSION }}" defer></script>`); `base.html` also exposes `LOWBID.urls.trustlinePrepare`. Same IIFE style as the wallet module, events delegated on `document`, so buttons rendered later work.

- `Lowbid.pay.signAndSend({xdr, sendUrl, extra})` → `Lowbid.signTransaction(xdr, {networkPassphrase: LOWBID.networkPassphrase, address: LOWBID.walletAddress})` → `Lowbid.api(sendUrl, {method:"POST", body:{signed_xdr, ...extra}})` → resolves with the server JSON. Toasts: *Signature demandée* → *Envoi* → *Confirmé (hash)*. Freighter decline ⇒ warning toast and a rejected promise with `.handled = true` (no error toast).
- `Lowbid.pay.runStep(button)` — bound to `[data-pay-step]`: `POST data-prepare-url` (body = `data-pay-body` JSON + `step`) expecting `{ok, xdr, send_url, extra?}` (or `{ok:true, redirect}` with no `xdr` when the server did it alone) → `signAndSend` → on `{ok:true}` follows `redirect` or reloads (unless `data-no-reload`). Sets `.is-loading` / `disabled` / `aria-busy`, blocks double clicks, writes the server `message` (falling back to `error`) into the nearest `[data-pay-error]` and toasts it.
- `Lowbid.pay.ensureTrustline(button?)` — bound to `[data-pay-trustline]`: `POST LOWBID.urls.trustlinePrepare` (or the button's `data-prepare-url`) with `{address}` → same `{ok, xdr, send_url}` contract (`{ok:true, message}` without `xdr` = already has it) → sign & send.
- `Lowbid.pay.watchBalance(el, {interval=5000, maxMs=900000, onIncrease})` → polls Horizon `/accounts/{addr}` with `fetch` (public CORS): every 5 s for the first 2 min, then every 15 s, up to 15 min; stops and shows « — » after 3 consecutive Horizon failures. Refreshes every `[data-usdc-balance="<addr>"]` (adds `.is-bumped` for 1.2 s on change); auto-started for elements that also carry `data-watch`. Returns `stop()`.
- `Lowbid.pay.fetchUsdcBalance(addr)`, `explorerTxUrl(hash)`, `explorerAccountUrl(addr)`, `explorerContractUrl(id)`.

Markup contract the templates follow (the real one is `templates/payments/_escrow_panel.html`, which renders one button for the current step with the label from `services.FLOW`):

```html
<button class="ui-btn ui-btn-primary" data-pay-step="fund" data-prepare-url="{% url 'payments:prepare' need.pk 'fund' %}"
        data-loading-label="Signature…">Bloquer les fonds</button>
<p class="ui-error" data-pay-error hidden></p>
<button class="ui-btn ui-btn-ghost" data-pay-trustline data-prepare-url="{% url 'payments:trustline_prepare' %}">Ajouter la trustline USDC</button>
<span class="ui-num" data-usdc-balance="{{ payee }}" data-watch>…</span>
```

### 7.4 Wave 2 wiring (views + urls + model) — as shipped

One prepare/send pair per step, all under `/pay/` (`payments:` namespace, `payments/urls.py`), all `@require_POST` + `@wallet_required`, JSON in/out, every `signer`/role field pinned to the **session wallet** (`accounts.identity.get_wallet(request)`), never to a form value. Role and state gates run in both halves (`payments/services.py`, whose docstring holds the authoritative state table).

| URL | View | Name |
|---|---|---|
| `POST /pay/prepare/<need_pk>/<step>/` (body `{evidence?}` for `deliver`) | `views.prepare` | `payments:prepare` |
| `POST /pay/send/<need_pk>/<step>/` (body `{signed_xdr, ...extra}`) | `views.send` | `payments:send` |
| `POST /pay/trustline/prepare/` | `views.trustline_prepare` (also `LOWBID.urls.trustlinePrepare`) | `payments:trustline_prepare` |
| `POST /pay/trustline/send/` (body `{signed_xdr}`) | `views.trustline_send` | `payments:trustline_send` |
| `GET /pay/<need_pk>/` | `views.need_pay` → 302 to the need page `#paiement` | `payments:need_pay` |

**Escrow mode** (`Escrow.mode == "escrow"`, Trustless Work single-release, one milestone):

| step | button (UI) | session wallet must be | prepare builds | send does | Escrow status | Need status | persisted |
|---|---|---|---|---|---|---|---|
| `deploy` | « Créer l’escrow » | client | `tw.deploy_single_release(signer=client, engagement_id=f"lowbid-{need_pk}", amount=winning bid, approver=release_signer=client, service_provider=receiver=winner, dispute_resolver=platform_address=LOWBID_PLATFORM_ADDRESS, platform_fee=LOWBID_PLATFORM_FEE, milestone_description=f"Livraison du besoin #{need_pk}")` | `tw.send_transaction` → `data["contractId"]` | `created → deployed` | `awarded` (unchanged) | `contract_id`, `deploy_tx_hash` |
| `fund` | « Bloquer les fonds » | client | `tw.fund_escrow(contract_id, signer=client, amount)` | `tw.send_transaction` | `deployed → funded` | `awarded → funded` | `fund_tx_hash`, `funded_at` |
| `deliver` | « Déclarer la livraison » (+ note ≤ 280 chars) | **winner** | `tw.change_milestone_status(contract_id, evidence=<note>, service_provider=winner)` | `tw.send_transaction` | `funded → delivered` | `funded → delivered` | `deliver_tx_hash`, `delivered_at`, `delivery_note` |
| `approve` | « Valider la livraison » | client | `tw.approve_milestone(contract_id, approver=client)` | `tw.send_transaction` | `delivered → approved` | `delivered` (unchanged) | `approve_tx_hash` |
| `release` | « Libérer les fonds » | client | `tw.release_funds(contract_id, release_signer=client)` | `tw.send_transaction` | `approved → released` | `delivered → released` | `release_tx_hash`, `released_at` |

**Direct mode** (`Escrow.mode == "direct"`, Plan B — no `funded`, no `approved`):

| step | button (UI) | session wallet must be | prepare builds | send does | Escrow status | Need status | persisted |
|---|---|---|---|---|---|---|---|
| `deliver` (optional) | « Déclarer la livraison » | winner | **nothing to sign**: prepare records it and returns `{ok:true, redirect}` | — | `created → delivered` | `awarded → delivered` | `delivered_at`, `delivery_note` |
| `direct_pay` | « Payer le freelance », or « Valider et payer » once delivered | client | `stellar.build_payment_xdr(source=client, destination=winner, amount=bid, memo=f"lowbid:{need_pk}")` | `stellar.parse_payment_xdr` check (source / destination / amount / issuer, else `tampered`) → `stellar.submit_xdr` | `created`/`delivered → paid` | `awarded`/`delivered → released` | `payment_tx_hash`, `released_at` |

`trustline` (no need id): prepare checks `stellar.has_usdc_trustline(wallet)` → `{ok:true, message:"Trustline USDC déjà présente."}` if present, else `stellar.build_change_trust_xdr(source=wallet)`; send → `stellar.submit_xdr`; nothing persisted (Horizon is re-read). Any signed-in wallet may call it; the panel shows the button to both parties.

In direct mode the client may pay before the freelancer declares delivery (deliberate MVP choice, see `docs/ARCHITECTURE.md`); in escrow mode the release needs deliver + approve first.

Response shapes (`payments/views.py`): prepare → `{"ok": true, "xdr": "...", "send_url": "...", "extra": {...}}`, or `{"ok": true, "redirect": "<need>#paiement", "message": "..."}` when there is nothing to sign. send → `{"ok": true, "redirect", "status", "tx_hash", "hash", "contract_id", "explorer_url", "message", "pending"}`. **Business refusals are HTTP 200** `{"ok": false, "error": "<code>", "message": "<French>"}` so `Lowbid.api` resolves and the JS shows `message`; codes are `not_awarded · forbidden · wrong_state · wrong_mode · unknown_step · tampered · provider · stellar`. Anonymous callers get the `@wallet_required` 401 JSON. A provider failure never flips the status (the user retries); the TW/Horizon message is kept in `Escrow.last_error` and shown in the panel.

Model: an `Escrow` row 1-1 with `Need` (`payments/models.py`, `related_name="escrow"`), created at the first prepare: `mode` (`escrow`/`direct`, frozen from `stellar.payment_mode()`, re-frozen while still `created` so switching to Plan B after a failed deploy works), `amount`, `payer_address`, `payee_address`, `platform_address`, `contract_id`, `engagement_id`, one `*_tx_hash` per step (`deploy / fund / deliver / approve / release / payment`), `status` (`created / deployed / funded / delivered / approved / released / paid`; `failed` exists in the choices but the flow never sets it), `delivery_note`, `last_error`, `funded_at / delivered_at / released_at`. Idempotency: a replayed `send` for a step already recorded with the same hash returns « Étape déjà confirmée. » instead of failing the state gate.

Before the demo: `LOWBID_PLATFORM_ADDRESS` set + funded + USDC trustline (when empty the client wallet is used as `disputeResolver` + `platformAddress` and Trustless Work may refuse it); winner has the USDC trustline (« Ajouter la trustline USDC » in the panel — release fails on chain otherwise); client holds ≥ bid USDC (Circle faucet, §2.5; keep demo amounts ≤ 10 USDC).

### 7.5 Open risks

1. Nothing live-tested: TW field names/types follow the SDK sources, but a 400 on the first deploy is the most likely first failure → `env["error"]` carries the vendor message; the smoke test in the `trustless_work.py` docstring is step one on a real network.
2. `platformFee` unit (bps vs percent) — read it back with `get_escrow()`; `1` is safe either way.
3. `send-transaction` success detection relies on HTTP 2xx + `status != "FAILED"`; if TW ever returns 200 with another failure marker, `ok` would be wrongly true — log the payload on the first live run.
4. `submit_xdr` 504: Horizon may have applied the tx; the response carries `hash`, so `confirm_direct_pay` stores it as *pending* (panel shows the explorer link) and the next `prepare_direct_pay` reconciles it with `stellar.transaction_status(hash)` instead of asking for a second signature. Trustless Work sends have no such reconciliation yet.
5. `watchBalance` hits Horizon from the browser (public CORS, rate-limited ~3600 req/h per IP) — one watcher per page is fine, do not multiply.
