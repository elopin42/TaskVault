/* Lowbid pay module — sign-and-send driver for escrow (Trustless Work) and direct USDC steps.
 *
 * Depends on window.Lowbid (lowbid-base.js: api/toast), Lowbid.signTransaction
 * (lowbid-wallet.js: Freighter) and window.LOWBID (base.html). View-agnostic: the
 * payments views only have to answer two JSON shapes.
 *
 *   prepare  POST <data-prepare-url>  -> {ok, xdr, send_url, extra?}   (ok:false -> {error})
 *   send     POST <send_url>          {signed_xdr, ...extra} -> {ok, hash?, contract_id?, redirect?, message?, error?}
 *
 * Markup:
 *   <button data-pay-step="fund" data-prepare-url="/pay/..../prepare/" [data-send-url] [data-pay-body='{"k":1}']
 *           [data-loading-label="Signature…"] [data-no-reload]>Financer</button>
 *   <p data-pay-error hidden></p>                       (nearest ancestor's one gets the server error)
 *   <button data-pay-trustline>Ajouter la trustline USDC</button>   (uses LOWBID.urls.trustlinePrepare)
 *   <span data-usdc-balance="G…" data-watch>0.00 USDC</span>          (polled from Horizon for 2 min)
 *
 * Public API:
 *   Lowbid.pay.signAndSend({xdr, sendUrl, extra})  -> Promise<serverJson>
 *   Lowbid.pay.runStep(button)                     -> Promise<serverJson|undefined>
 *   Lowbid.pay.ensureTrustline(button?)            -> Promise<serverJson>
 *   Lowbid.pay.watchBalance(el, {interval, maxMs}) -> stop()
 *   Lowbid.pay.fetchUsdcBalance(address)           -> Promise<string|null>
 *   Lowbid.pay.explorerTxUrl(hash) / explorerAccountUrl(addr) / explorerContractUrl(id)
 */
(function () {
  "use strict";

  var Lowbid = window.Lowbid = window.Lowbid || {};
  var CFG = window.LOWBID || {};

  var DECLINED_CODE = -4; // FreighterApiDeclinedError
  var BALANCE_INTERVAL_MS = 5000;
  var BALANCE_MAX_MS = 120000;

  /* ---------- helpers ---------- */
  function toast(msg, type, opts) {
    if (typeof Lowbid.toast === "function") return Lowbid.toast(msg, type, opts);
    return null;
  }

  function errorMessage(err) {
    if (!err) return "Erreur inconnue.";
    if (err.data && typeof err.data.message === "string" && err.data.message) return err.data.message;
    if (err.data && typeof err.data.error === "string" && err.data.error) return err.data.error;
    var msg = err.message || String(err);
    if (msg === "freighter_missing") return "Installez l’extension Freighter puis rechargez la page.";
    if (/^HTTP 401/.test(msg)) return "Connectez votre wallet pour continuer.";
    if (/^HTTP 403/.test(msg)) return "Ce wallet n’est pas autorisé à faire cette action.";
    if (/^HTTP 5\d\d/.test(msg)) return "Erreur serveur, réessayez dans un instant.";
    if (/Failed to fetch|NetworkError/i.test(msg)) return "Réseau indisponible, réessayez.";
    return msg;
  }

  function isDeclined(err) {
    if (!err) return false;
    var cause = err.cause || err;
    if (cause && cause.code === DECLINED_CODE) return true;
    var msg = (err.message || "") + " " + ((cause && cause.message) || "");
    return /declined|rejected|refus|cancel|denied/i.test(msg);
  }

  function explorerBase() {
    return "https://stellar.expert/explorer/" + (CFG.network === "public" ? "public" : "testnet");
  }

  function setLoading(btn, on) {
    if (!btn) return;
    if (on) {
      if (btn.dataset.busy === "1") return;
      btn.dataset.busy = "1";
      btn.dataset.label = btn.innerHTML;
      btn.classList.add("is-loading");
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
      var label = btn.getAttribute("data-loading-label") || "Signature…";
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i> <span>' + Lowbid.escapeHtml(label) + "</span>";
    } else {
      delete btn.dataset.busy;
      btn.classList.remove("is-loading");
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
    }
  }

  /* Nearest [data-pay-error]: walk up until an ancestor contains one, else the first on the page. */
  function errorSlot(btn) {
    var node = btn;
    while (node && node !== document) {
      var found = node.matches && node.matches("[data-pay-error]") ? node : (node.querySelector ? node.querySelector("[data-pay-error]") : null);
      if (found) return found;
      node = node.parentNode;
    }
    return document.querySelector("[data-pay-error]");
  }

  function showError(btn, msg) {
    var slot = errorSlot(btn);
    if (!slot) return;
    slot.textContent = msg || "";
    if (msg) slot.removeAttribute("hidden"); else slot.setAttribute("hidden", "");
  }

  /* data-pay-body JSON, plus the fields of the enclosing <form data-pay-form> (e.g. the delivery note). */
  function parseBody(btn) {
    var body = {};
    var raw = btn.getAttribute("data-pay-body");
    if (raw) {
      try { body = JSON.parse(raw) || {}; } catch (e) { console.warn("lowbid-pay: data-pay-body is not JSON", e); }
    }
    var form = btn.closest ? btn.closest("form[data-pay-form]") : null;
    if (form && window.FormData) {
      new FormData(form).forEach(function (value, key) { body[key] = value; });
    }
    return body;
  }

  function finish(result, btn) {
    if (result && result.redirect) {
      window.location.href = result.redirect;
      return;
    }
    if (btn && btn.hasAttribute("data-no-reload")) return;
    setTimeout(function () { window.location.reload(); }, 900);
  }

  /* ---------- core ---------- */
  var pay = {
    explorerTxUrl: function (hash) { return explorerBase() + "/tx/" + encodeURIComponent(hash || ""); },
    explorerAccountUrl: function (addr) { return explorerBase() + "/account/" + encodeURIComponent(addr || ""); },
    explorerContractUrl: function (id) { return explorerBase() + "/contract/" + encodeURIComponent(id || ""); },

    /* Freighter signs `xdr` with the session wallet, the signed XDR goes to `sendUrl`.
       Resolves with the server JSON. Rejects with an Error; `.handled` is set when a toast
       was already shown (user declined). */
    signAndSend: function (opts) {
      opts = opts || {};
      if (!opts.xdr) return Promise.reject(new Error("Transaction à signer manquante."));
      if (!opts.sendUrl) return Promise.reject(new Error("URL d’envoi manquante."));
      if (typeof Lowbid.signTransaction !== "function") return Promise.reject(new Error("freighter_missing"));

      toast("Confirmez la transaction dans Freighter.", "info", { title: "Signature demandée", duration: 6000 });
      return Lowbid.signTransaction(opts.xdr, {
        networkPassphrase: CFG.networkPassphrase,
        address: CFG.walletAddress || undefined
      }).catch(function (err) {
        if (isDeclined(err)) {
          toast("Signature refusée dans Freighter — rien n’a été envoyé.", "warning", { title: "Annulé" });
          var e = new Error("declined"); e.code = "declined"; e.handled = true; e.cause = err;
          throw e;
        }
        throw err;
      }).then(function (signedXdr) {
        toast("Envoi sur le réseau Stellar…", "info", { title: "Envoi", duration: 8000 });
        var body = Object.assign({ signed_xdr: signedXdr }, opts.extra || {});
        return Lowbid.api(opts.sendUrl, { method: "POST", body: body });
      }).then(function (res) {
        if (!res || res.ok === false) {
          var e = new Error((res && (res.message || res.error)) || "Transaction refusée par le réseau.");
          e.data = res || {};
          throw e;
        }
        var msg = res.message || "Transaction confirmée.";
        if (res.hash) msg += " (" + Lowbid.shortAddr(res.hash, 6) + ")";
        toast(msg, "success", { title: "Confirmé", duration: 7000 });
        return res;
      });
    },

    /* Generic [data-pay-step] driver: prepare -> sign -> send -> reload/redirect. */
    runStep: function (btn) {
      if (!btn || btn.dataset.busy === "1") return Promise.resolve();
      var prepareUrl = btn.getAttribute("data-prepare-url");
      if (!prepareUrl) {
        showError(btn, "Bouton mal configuré (data-prepare-url manquant).");
        return Promise.resolve();
      }
      showError(btn, "");
      setLoading(btn, true);
      var body = parseBody(btn);
      body.step = btn.getAttribute("data-pay-step") || body.step || "";

      return Lowbid.api(prepareUrl, { method: "POST", body: body }).then(function (prep) {
        if (!prep || prep.ok === false) {
          var e = new Error((prep && (prep.message || prep.error)) || "Préparation impossible.");
          e.data = prep || {};
          throw e;
        }
        if (!prep.xdr) {
          // Nothing to sign (server completed the step itself) — just follow it.
          finish(prep, btn);
          return prep;
        }
        return pay.signAndSend({
          xdr: prep.xdr,
          sendUrl: prep.send_url || btn.getAttribute("data-send-url"),
          extra: Object.assign({ step: body.step }, prep.extra || {})
        }).then(function (res) {
          finish(res, btn);
          return res;
        });
      }).catch(function (err) {
        setLoading(btn, false);
        if (err && err.handled) return;
        var msg = errorMessage(err);
        showError(btn, msg);
        toast(msg, "error", { title: "Paiement" });
        console.error("lowbid-pay: step failed", err);
      });
    },

    /* USDC trustline for the session wallet (freelancer onboarding). Needs LOWBID.urls.trustlinePrepare. */
    ensureTrustline: function (btn) {
      var urls = CFG.urls || {};
      var prepareUrl = (btn && btn.getAttribute("data-prepare-url")) || urls.trustlinePrepare;
      if (!prepareUrl) {
        var e = new Error("Trustline non disponible sur cette page.");
        if (btn) showError(btn, e.message);
        return Promise.reject(e);
      }
      if (btn && btn.dataset.busy === "1") return Promise.resolve();
      if (btn) { showError(btn, ""); setLoading(btn, true); }
      return Lowbid.api(prepareUrl, { method: "POST", body: { address: CFG.walletAddress || "" } }).then(function (prep) {
        if (!prep || prep.ok === false) {
          var err = new Error((prep && (prep.message || prep.error)) || "Préparation impossible.");
          err.data = prep || {};
          throw err;
        }
        if (!prep.xdr) {
          // Already has the trustline: the server says so without an XDR.
          toast(prep.message || "La trustline USDC est déjà en place.", "info");
          if (btn) setLoading(btn, false);
          return prep;
        }
        return pay.signAndSend({
          xdr: prep.xdr,
          sendUrl: prep.send_url || urls.trustlineSend || (btn && btn.getAttribute("data-send-url")),
          extra: prep.extra || {}
        }).then(function (res) {
          finish(res, btn);
          return res;
        });
      }).catch(function (err) {
        if (btn) setLoading(btn, false);
        if (err && err.handled) throw err;
        var msg = errorMessage(err);
        if (btn) showError(btn, msg);
        toast(msg, "error", { title: "Trustline" });
        console.error("lowbid-pay: trustline failed", err);
        throw err;
      });
    },

    /* Horizon /accounts/{addr} (public CORS) -> USDC balance string ("0" without trustline), null on failure. */
    fetchUsdcBalance: function (address) {
      if (!address || !CFG.horizonUrl) return Promise.resolve(null);
      var usdc = CFG.usdc || {};
      return fetch(CFG.horizonUrl.replace(/\/$/, "") + "/accounts/" + encodeURIComponent(address), {
        headers: { "Accept": "application/json" }
      }).then(function (res) {
        if (res.status === 404) return "0";
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json().then(function (acc) {
          var list = (acc && acc.balances) || [];
          for (var i = 0; i < list.length; i++) {
            if (list[i].asset_code === usdc.code && list[i].asset_issuer === usdc.issuer) return list[i].balance;
          }
          return "0";
        });
      }).catch(function (err) {
        console.warn("lowbid-pay: balance fetch failed", err);
        return null;
      });
    },

    /* Poll Horizon every 5 s for up to 2 min and refresh every [data-usdc-balance="<addr>"].
       The address comes from `el`'s attribute (or opts.address). Returns a stop() function. */
    watchBalance: function (el, opts) {
      opts = opts || {};
      var address = opts.address || (el && el.getAttribute && el.getAttribute("data-usdc-balance"));
      if (!address) return function () {};
      var interval = opts.interval || BALANCE_INTERVAL_MS;
      var maxMs = opts.maxMs || BALANCE_MAX_MS;
      var started = Date.now();
      var last = null;
      var timer = null;
      var stopped = false;

      function render(balance) {
        var nodes = document.querySelectorAll('[data-usdc-balance="' + address.replace(/"/g, "") + '"]');
        var text = Lowbid.formatUsdc ? Lowbid.formatUsdc(balance, (CFG.usdc || {}).code) : balance + " USDC";
        nodes.forEach(function (n) {
          var changed = n.textContent.trim() !== text;
          n.textContent = text;
          n.setAttribute("data-balance", balance);
          if (changed && last !== null) {
            n.classList.add("is-bumped");
            setTimeout(function () { n.classList.remove("is-bumped"); }, 1200);
          }
        });
      }

      function stop() {
        stopped = true;
        if (timer) clearTimeout(timer);
      }

      function tick() {
        if (stopped) return;
        pay.fetchUsdcBalance(address).then(function (balance) {
          if (stopped) return;
          if (balance !== null) {
            if (balance !== last) {
              render(balance);
              if (last !== null && Number(balance) > Number(last) && typeof opts.onIncrease === "function") {
                opts.onIncrease(balance, last);
              }
              last = balance;
            }
          }
          if (Date.now() - started < maxMs) timer = setTimeout(tick, interval);
        });
      }
      tick();
      return stop;
    }
  };

  Lowbid.pay = pay;

  /* ---------- delegated UI wiring ---------- */
  document.addEventListener("click", function (ev) {
    var stepBtn = ev.target.closest("[data-pay-step]");
    if (stepBtn) {
      ev.preventDefault();
      pay.runStep(stepBtn);
      return;
    }
    var trustBtn = ev.target.closest("[data-pay-trustline]");
    if (trustBtn) {
      ev.preventDefault();
      pay.ensureTrustline(trustBtn).catch(function () { /* already reported */ });
    }
  });

  function autoWatch() {
    var seen = {};
    document.querySelectorAll("[data-usdc-balance][data-watch]").forEach(function (el) {
      var addr = el.getAttribute("data-usdc-balance");
      if (!addr || seen[addr]) return;
      seen[addr] = true;
      pay.watchBalance(el);
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", autoWatch);
  else autoWatch();
})();
