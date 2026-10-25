/* Lowbid wallet module — Freighter (browser extension) as identity.
 *
 * Depends on window.Lowbid (lowbid-base.js), window.LOWBID (base.html) and the
 * vendored UMD global `freighterApi` (static/vendor/freighter-api.js).
 *
 * Login flow:  requestAccess -> POST /auth/challenge/ -> freighterApi.signMessage(message)
 *              -> POST /auth/verify/ {address, signature(base64)} -> reload / ?next=
 * Freighter >= 5.34 signs per SEP-53 (sha256("Stellar Signed Message:\n" + msg));
 * the server also accepts the older raw-message scheme. signedMessage arrives as a
 * base64 string (API v4+) or a Buffer-like object (older) — both are normalised here.
 *
 * Public API (for the projects / payments pages):
 *   Lowbid.wallet.connect(next?)          -> Promise<address>   (full login)
 *   Lowbid.wallet.disconnect()            -> Promise (server logout + reload)
 *   Lowbid.wallet.getAddress()            -> Promise<address|"">  (no prompt)
 *   Lowbid.wallet.ensureNetwork()         -> Promise<{network, networkPassphrase}> rejects on mismatch
 *   Lowbid.signTransaction(xdr, opts?)    -> Promise<signedXdr>  (Freighter prompt)
 *   Lowbid.wallet.isInstalled()           -> Promise<boolean>
 */
(function () {
  "use strict";

  var Lowbid = window.Lowbid = window.Lowbid || {};
  var CFG = window.LOWBID || {};
  var FREIGHTER_URL = "https://www.freighter.app/";

  function api() {
    var f = window.freighterApi;
    if (f && f.default && !f.signMessage) f = f.default;
    return f || null;
  }

  function fail(err) {
    // Freighter returns {error: {message, code}} or {error: "string"}; normalise to Error.
    if (err instanceof Error) return err;
    var msg = (err && (err.message || err.error)) || String(err || "Wallet error");
    if (msg && msg.message) msg = msg.message;
    var e = new Error(msg);
    e.cause = err;
    return e;
  }

  function toBase64(signed) {
    if (signed == null) return "";
    if (typeof signed === "string") return signed;                       // API v4+: base64 string
    var bytes = null;
    if (signed instanceof Uint8Array) bytes = signed;
    else if (signed && Array.isArray(signed.data)) bytes = Uint8Array.from(signed.data); // serialised Buffer
    else if (signed && typeof signed.length === "number") bytes = Uint8Array.from(signed);
    if (!bytes) return "";
    var bin = "";
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }

  var wallet = {
    isInstalled: function () {
      var f = api();
      if (!f) return Promise.resolve(false);
      return f.isConnected().then(function (r) { return !!(r && r.isConnected); }, function () { return false; });
    },

    getAddress: function () {
      var f = api();
      if (!f) return Promise.resolve("");
      return f.getAddress().then(function (r) { return (r && !r.error && r.address) || ""; }, function () { return ""; });
    },

    requestAccess: function () {
      var f = api();
      if (!f) return Promise.reject(new Error("freighter_missing"));
      return f.requestAccess().then(function (r) {
        if (!r || r.error) throw fail(r && r.error);
        if (!r.address) throw new Error("Access denied in Freighter.");
        return r.address;
      });
    },

    ensureNetwork: function () {
      var f = api();
      if (!f) return Promise.reject(new Error("freighter_missing"));
      return f.getNetwork().then(function (r) {
        if (!r || r.error) throw fail(r && r.error);
        if (CFG.networkPassphrase && r.networkPassphrase !== CFG.networkPassphrase) {
          var e = new Error("Freighter is on \"" + r.network + "\"; switch to " + (CFG.network || "testnet").toUpperCase() + ".");
          e.code = "network_mismatch"; e.details = r;
          throw e;
        }
        return r;
      });
    },

    signMessage: function (message, address) {
      var f = api();
      return f.signMessage(message, { address: address, networkPassphrase: CFG.networkPassphrase }).then(function (r) {
        if (!r || r.error) throw fail(r && r.error);
        var sig = toBase64(r.signedMessage);
        if (!sig) throw new Error("Empty signature returned by Freighter.");
        return { signature: sig, signerAddress: r.signerAddress || address };
      });
    },

    /* Full login. Resolves with the address once the session is established. */
    connect: function (next) {
      var self = this;
      return self.isInstalled().then(function (installed) {
        if (!installed) {
          var e = new Error("Freighter is not installed."); e.code = "freighter_missing"; throw e;
        }
        return self.ensureNetwork();
      }).then(function () {
        return self.requestAccess();
      }).then(function (address) {
        return Lowbid.api(CFG.urls.challenge, { method: "POST" }).then(function (ch) {
          return self.signMessage(ch.message, address).then(function (s) {
            return Lowbid.api(CFG.urls.verify, {
              method: "POST",
              body: { address: s.signerAddress || address, signature: s.signature, next: next || "" }
            });
          });
        });
      }).then(function (res) {
        // The server validates `next` (same host, relative): remember its answer for the redirect.
        wallet.lastNext = typeof res.next === "string" ? res.next : "";
        return res.address;
      });
    },

    disconnect: function () {
      return Lowbid.api(CFG.urls.logout, { method: "POST" }).then(function () {
        window.location.href = CFG.urls.landing || "/";
      });
    }
  };

  Lowbid.wallet = wallet;

  /* Lowbid.signTransaction(xdr, {networkPassphrase?, address?}) -> signed XDR string. */
  Lowbid.signTransaction = function (xdr, opts) {
    var f = api();
    if (!f) return Promise.reject(new Error("freighter_missing"));
    opts = opts || {};
    return f.signTransaction(xdr, {
      networkPassphrase: opts.networkPassphrase || CFG.networkPassphrase,
      address: opts.address || CFG.walletAddress || undefined
    }).then(function (r) {
      if (!r || r.error) throw fail(r && r.error);
      if (!r.signedTxXdr) throw new Error("Transaction not signed.");
      return r.signedTxXdr;
    });
  };

  /* ---------- UI wiring: [data-wallet-connect] / [data-wallet-logout] ---------- */
  function setLoading(btn, on) {
    if (!btn) return;
    if (on) {
      btn.dataset.label = btn.innerHTML;
      btn.classList.add("is-loading"); btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner" aria-hidden="true"></i> <span>Signing…</span>';
    } else {
      btn.classList.remove("is-loading"); btn.disabled = false;
      if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
    }
  }

  function explain(err) {
    var msg = (err && err.message) || "Could not connect.";
    if (err && err.code === "freighter_missing") {
      Lowbid.toast("Install the Freighter extension, then reload the page.", "warning", { title: "Freighter missing", duration: 8000 });
      window.open(FREIGHTER_URL, "_blank", "noopener");
      return;
    }
    if (err && err.status === 400 && err.data) {
      var map = {
        bad_signature: "The signature does not match the address.",
        challenge_expired: "The challenge expired, try again.",
        no_challenge: "Session expired, try again.",
        invalid_address: "Invalid Stellar address.",
        invalid_signature_encoding: "Unreadable signature returned by the wallet."
      };
      msg = map[err.data.error] || msg;
    }
    if (/User declined|rejected|denied|refus/i.test(msg)) msg = "Signature declined in Freighter.";
    Lowbid.toast(msg, "error", { title: "Wallet" });
  }

  document.addEventListener("click", function (ev) {
    var connectBtn = ev.target.closest("[data-wallet-connect]");
    if (connectBtn) {
      ev.preventDefault();
      var next = connectBtn.getAttribute("data-next") || new URLSearchParams(location.search).get("next") || "";
      setLoading(connectBtn, true);
      wallet.connect(next).then(function (address) {
        Lowbid.toast("Connected as " + Lowbid.shortAddr(address) + ".", "success", { title: "Wallet" });
        var target = wallet.lastNext || window.location.pathname;
        setTimeout(function () { window.location.href = target; }, 350);
      }).catch(function (err) {
        setLoading(connectBtn, false);
        explain(err);
      });
      return;
    }
    var logoutBtn = ev.target.closest("[data-wallet-logout]");
    if (logoutBtn) {
      ev.preventDefault();
      wallet.disconnect().catch(explain);
    }
  });

  /* If the extension switches account while signed in, tell the user (no auto-logout). */
  (function watchAccount() {
    var f = api();
    if (!f || !f.WatchWalletChanges || !CFG.walletAddress) return;
    try {
      var watcher = new f.WatchWalletChanges(3000);
      watcher.watch(function (r) {
        if (r && r.address && r.address !== CFG.walletAddress && !watchAccount.warned) {
          watchAccount.warned = true;
          Lowbid.toast("Freighter now uses " + Lowbid.shortAddr(r.address) + " — log out to switch accounts.", "warning", { duration: 8000 });
        }
      });
    } catch (e) { /* older API without watcher */ }
  })();
})();
