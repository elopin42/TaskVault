/* A tiny Horizon stand-in for the e2e run (tests/e2e/run.js) — the sandbox has no network.
 *
 * Django is pointed at it through STELLAR_HORIZON_URL (make e2e exports the same port to both sides),
 * the browser reaches it for the live balance ([data-usdc-balance]) — hence the CORS headers.
 * It keeps a toy ledger in memory: accounts exist only once `fund(address, {usdc})` was called
 * (friendbot semantics), a `payment` needs a funded source, a destination holding the asset
 * trustline and enough balance, a `change_trust` adds the trustline. Every rejection uses Horizon's
 * real `extras.result_codes` shape so payments.stellar translates it into the usual English message.
 *
 *   GET  /accounts/{id}           -> account JSON (sequence, balances) | 404
 *   GET  /fee_stats               -> {last_ledger_base_fee}
 *   GET  /transactions/{hash}     -> {hash, successful} | 404
 *   POST /transactions  (tx=XDR)  -> {hash, ledger, successful} | 400 {extras: {result_codes}}
 */
"use strict";

const http = require("http");
const path = require("path");

const REPO = path.resolve(__dirname, "..", "..");
const StellarSdk = require(path.join(REPO, "node_modules", "@stellar", "stellar-sdk"));

const PASSPHRASE = "Test SDF Network ; September 2015";
const USDC = { code: "USDC", issuer: "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5" };

function startFakeHorizon(port, opts) {
  opts = opts || {};
  const asset = opts.asset || USDC;
  const accounts = new Map(); // address -> {sequence: BigInt, xlm: number, lines: Map<"CODE:ISSUER", number>}
  const transactions = new Map(); // hash -> {hash, successful, ledger}
  const submitted = []; // every accepted {hash, type, source, destination, amount}
  let ledger = 1000;

  function key(a) { return a.code + ":" + a.issuer; }
  function fmt(n) { return Number(n).toFixed(7); }
  function accountJson(address, acc) {
    const balances = [];
    acc.lines.forEach((bal, k) => {
      const [code, issuer] = k.split(":");
      balances.push({ asset_type: code.length <= 4 ? "credit_alphanum4" : "credit_alphanum12", asset_code: code, asset_issuer: issuer, balance: fmt(bal), limit: "922337203685.4775807" });
    });
    balances.push({ asset_type: "native", balance: fmt(acc.xlm) });
    return { id: address, account_id: address, sequence: String(acc.sequence), balances };
  }
  function fund(address, o) {
    o = o || {};
    const acc = accounts.get(address) || { sequence: BigInt(ledger) << 32n, xlm: 10000, lines: new Map() }; // Horizon-style: ledger << 32
    if (o.usdc !== undefined) acc.lines.set(key(asset), Number(o.usdc));
    accounts.set(address, acc);
    return accountJson(address, acc);
  }
  function balanceOf(address) {
    const acc = accounts.get(address);
    return acc ? (acc.lines.get(key(asset)) || 0) : null;
  }

  function json(res, status, body, extra) {
    res.writeHead(status, Object.assign({
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    }, extra || {}));
    res.end(JSON.stringify(body));
  }
  function rejected(res, txCode, opCodes, title) {
    json(res, 400, {
      type: "https://stellar.org/horizon-errors/transaction_failed",
      title: title || "Transaction Failed",
      status: 400,
      extras: { result_codes: Object.assign({ transaction: txCode }, opCodes ? { operations: opCodes } : {}) },
    });
  }

  function apply(xdr, res) {
    let env;
    try { env = StellarSdk.TransactionBuilder.fromXDR(xdr, PASSPHRASE); } catch (e) { return json(res, 400, { title: "Bad Request", detail: "unparsable XDR" }); }
    const hash = env.hash().toString("hex");
    const source = env.source;
    const acc = accounts.get(source);
    if (!acc) return rejected(res, "tx_no_source_account");
    // sanity: the envelope must carry a signature from its source account
    const kp = StellarSdk.Keypair.fromPublicKey(source);
    const okSig = env.signatures.some((s) => {
      try { const sig = typeof s.signature === "function" ? s.signature() : s.signature; return kp.verify(env.hash(), sig); } catch (e) { return false; }
    });
    if (!okSig) return rejected(res, "tx_bad_auth");
    const ops = env.operations;
    for (const op of ops) {
      if (op.type === "payment") {
        const dest = accounts.get(op.destination);
        if (!dest) return rejected(res, "tx_failed", ["op_no_destination"]);
        if (op.asset.isNative()) {
          if (acc.xlm < Number(op.amount)) return rejected(res, "tx_failed", ["op_underfunded"]);
          acc.xlm -= Number(op.amount); dest.xlm += Number(op.amount);
        } else {
          const k = op.asset.code + ":" + op.asset.issuer;
          if (!dest.lines.has(k)) return rejected(res, "tx_failed", ["op_no_trust"]);
          if ((acc.lines.get(k) || 0) < Number(op.amount)) return rejected(res, "tx_failed", ["op_underfunded"]);
          acc.lines.set(k, (acc.lines.get(k) || 0) - Number(op.amount));
          dest.lines.set(k, dest.lines.get(k) + Number(op.amount));
        }
        submitted.push({ hash, type: "payment", source, destination: op.destination, amount: op.amount, asset: op.asset.isNative() ? "XLM" : op.asset.code });
      } else if (op.type === "changeTrust") {
        const a = op.line;
        if (a && a.code && a.issuer) acc.lines.set(a.code + ":" + a.issuer, acc.lines.get(a.code + ":" + a.issuer) || 0);
        submitted.push({ hash, type: "change_trust", source, asset: a && a.code });
      } else {
        return rejected(res, "tx_failed", ["op_not_supported"], "unsupported op in the fake Horizon: " + op.type);
      }
    }
    acc.sequence += 1n;
    ledger += 1;
    const record = { hash, ledger, successful: true, source_account: source };
    transactions.set(hash, record);
    return json(res, 200, record);
  }

  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    if (req.method === "OPTIONS") return json(res, 204, {});
    if (req.method === "GET" && url.pathname === "/fee_stats") return json(res, 200, { last_ledger_base_fee: "100", last_ledger: String(ledger) });
    if (req.method === "GET" && url.pathname.startsWith("/accounts/")) {
      const address = decodeURIComponent(url.pathname.slice("/accounts/".length));
      const acc = accounts.get(address);
      return acc ? json(res, 200, accountJson(address, acc)) : json(res, 404, { type: "https://stellar.org/horizon-errors/not_found", title: "Resource Missing", status: 404 });
    }
    if (req.method === "GET" && url.pathname.startsWith("/transactions/")) {
      const h = url.pathname.slice("/transactions/".length);
      const t = transactions.get(h);
      return t ? json(res, 200, t) : json(res, 404, { title: "Resource Missing", status: 404 });
    }
    if (req.method === "POST" && url.pathname === "/transactions") {
      let body = "";
      req.on("data", (c) => { body += c; });
      req.on("end", () => {
        let xdr = "";
        try { xdr = new URLSearchParams(body).get("tx") || JSON.parse(body).tx; } catch (e) { xdr = ""; }
        if (!xdr) return json(res, 400, { title: "Bad Request", detail: "missing tx" });
        apply(xdr, res);
      });
      return;
    }
    json(res, 404, { title: "Resource Missing", status: 404 });
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => {
      resolve({
        url: `http://127.0.0.1:${server.address().port}`,
        fund,
        balanceOf,
        accounts,
        transactions,
        submitted,
        close: () => new Promise((r) => server.close(() => r())),
      });
    });
  });
}

module.exports = { startFakeHorizon, USDC };
