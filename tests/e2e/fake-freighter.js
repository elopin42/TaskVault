/* Simulated Freighter for the e2e run (tests/e2e/run.js).
 *
 * Installed with `context.addInitScript(installFakeFreighter, cfg)` so it runs BEFORE any page
 * script. The vendored UMD (static/vendor/freighter-api.js) then tries `window.freighterApi = …`:
 * the property is an accessor whose setter is a no-op, so the fake survives.
 *
 * cfg = { secret, address, passphrase }. Signing needs window.StellarSdk, which base.html loads
 * `defer`, so the signing calls await it. Return shapes follow @stellar/freighter-api v4+ (what
 * static/js/lowbid-wallet.js expects):
 *   isConnected()            -> {isConnected}
 *   isAllowed()/setAllowed() -> {isAllowed}
 *   requestAccess()/getAddress() -> {address}
 *   getNetwork()/getNetworkDetails() -> {network, networkPassphrase[, networkUrl, sorobanRpcUrl]}
 *   signMessage(message, {address, networkPassphrase}) -> {signedMessage: base64, signerAddress}
 *        SEP-53: Ed25519 over sha256("Stellar Signed Message:\n" + utf8(message))
 *   signTransaction(xdr, {networkPassphrase, address}) -> {signedTxXdr, signerAddress}
 * Every call is recorded in window.__fakeFreighter.calls for assertions.
 */
function installFakeFreighter(cfg) {
  var calls = [];
  var kp = null;

  function record(name, args) { calls.push({ name: name, args: args === undefined ? null : args }); }
  function sdk() {
    return new Promise(function (resolve) {
      (function poll() {
        if (window.StellarSdk && window.StellarSdk.Keypair) resolve(window.StellarSdk);
        else setTimeout(poll, 20);
      })();
    });
  }
  function keypair(S) { if (!kp) kp = S.Keypair.fromSecret(cfg.secret); return kp; }
  function utf8(s) { return new TextEncoder().encode(String(s)); }
  function concat(a, b) { var out = new Uint8Array(a.length + b.length); out.set(a, 0); out.set(b, a.length); return out; }
  function b64(bytes) { var bin = ""; for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]); return btoa(bin); }

  var network = {
    network: "TESTNET",
    networkPassphrase: cfg.passphrase,
    networkUrl: "https://horizon-testnet.stellar.org",
    sorobanRpcUrl: "https://soroban-testnet.stellar.org"
  };

  var api = {
    isConnected: function () { record("isConnected"); return Promise.resolve({ isConnected: true }); },
    isAllowed: function () { record("isAllowed"); return Promise.resolve({ isAllowed: true }); },
    setAllowed: function () { record("setAllowed"); return Promise.resolve({ isAllowed: true }); },
    requestAccess: function () { record("requestAccess"); return Promise.resolve({ address: cfg.address }); },
    getAddress: function () { record("getAddress"); return Promise.resolve({ address: cfg.address }); },
    getUserInfo: function () { record("getUserInfo"); return Promise.resolve({ publicKey: cfg.address }); },
    getNetwork: function () {
      record("getNetwork");
      return Promise.resolve({ network: network.network, networkPassphrase: network.networkPassphrase });
    },
    getNetworkDetails: function () { record("getNetworkDetails"); return Promise.resolve(Object.assign({}, network)); },
    signMessage: function (message, opts) {
      record("signMessage", { message: message, opts: opts || null });
      return sdk().then(function (S) {
        if (opts && opts.address && opts.address !== cfg.address) {
          return { error: { message: "Address not in this wallet", code: -3 } };
        }
        var digest = S.hash(concat(utf8("Stellar Signed Message:\n"), utf8(message)));
        var sig = keypair(S).sign(digest);
        return { signedMessage: b64(sig), signerAddress: cfg.address };
      });
    },
    signTransaction: function (xdr, opts) {
      record("signTransaction", { opts: opts || null });
      return sdk().then(function (S) {
        var passphrase = (opts && opts.networkPassphrase) || cfg.passphrase;
        var tx = S.TransactionBuilder.fromXDR(xdr, passphrase);
        tx.sign(keypair(S));
        return { signedTxXdr: tx.toXDR(), signerAddress: cfg.address };
      });
    },
    signAuthEntry: function () { record("signAuthEntry"); return Promise.resolve({ error: { message: "signAuthEntry is not simulated", code: -1 } }); },
    signBlob: function () { record("signBlob"); return Promise.resolve({ error: { message: "signBlob is not simulated", code: -1 } }); },
    addToken: function () { record("addToken"); return Promise.resolve({ contractId: "" }); }
  };

  try {
    Object.defineProperty(window, "freighterApi", {
      configurable: false,
      enumerable: true,
      get: function () { return api; },
      set: function () { /* the vendored UMD assigns the real extension shim here: ignore it */ }
    });
  } catch (e) {
    window.freighterApi = api;
  }
  window.__fakeFreighter = { address: cfg.address, calls: calls };
}

if (typeof module !== "undefined" && module.exports) module.exports = { installFakeFreighter };
