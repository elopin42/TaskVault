/* Lowbid pay module — sign-and-send driver for the escrow (Trustless Work) and direct-payment steps.
 *
 * Depends on window.Lowbid (lowbid-base.js: api/toast), Lowbid.signTransaction
 * (lowbid-wallet.js: Freighter) and window.LOWBID (base.html: asset, urls). View-agnostic: the
 * payments views only have to answer two JSON shapes.
 *
 *   prepare  POST <data-prepare-url>  -> {ok, xdr, send_url, extra?} | {ok, redirect, message, next}   (ok:false -> {error, message})
 *   send     POST <send_url>          {signed_xdr, ...extra} -> {ok, hash?, contract_id?, redirect?, message?, next?, error?}
 *
 * `next` = the viewer's following step ({step, label, prepare_url, mine, evidence, no_tx} or null): the
 * driver chains it when it is a plain signature (deploy → fund, approve → release), so a validation
 * needs no reload between the two Freighter prompts.
 *
 * Markup:
 *   <button data-pay-step="fund" data-prepare-url="/pay/prepare/<task>/fund/" [data-send-url] [data-pay-body='{"k":1}']
 *           [data-loading-label="Signing…"] [data-no-reload]
 *           [data-confirm-title data-confirm-message data-confirm-label]>Lock the funds</button>
 *   <form data-pay-form> … </form>                 (its fields join the prepare/send body, e.g. delivery_link)
 *   <p data-pay-error hidden></p>                       (nearest ancestor's one gets the server error)
 *   <button data-pay-trustline>Add the trustline</button>      (uses LOWBID.urls.trustlinePrepare)
 *   <button data-fund data-pending-url="/pay/project/<pk>/pending.json">Fund the project</button>
 *   <span data-usdc-balance="G…" data-watch>…</span>     (polled from Horizon: 5 s for 2 min, then 15 s, up to 15 min)
 *
 * Public API:
 *   Lowbid.pay.signAndSend({xdr, sendUrl, extra})  -> Promise<serverJson>
 *   Lowbid.pay.run({step, prepareUrl, body})       -> Promise<serverJson>      one step, no reload
 *   Lowbid.pay.runChain(next, {stopAfter})         -> Promise<{completed, last, next}>  follows `next` while it is mine
 *   Lowbid.pay.runStep(button)                     -> Promise<serverJson|undefined>   button driver (+ chain, then reload)
 *   Lowbid.pay.fundProject(button)                 -> Promise                 deploy + fund every pending task
 *   Lowbid.pay.ensureTrustline(button?)            -> Promise<serverJson>
 *   Lowbid.pay.watchBalance(el, {interval, maxMs}) -> stop()
 *   Lowbid.pay.fetchUsdcBalance(address)           -> Promise<string|null>   balance of the configured asset
 *   Lowbid.pay.explorerTxUrl(hash) / explorerAccountUrl(addr) / explorerContractUrl(id)
 *   Lowbid.pay.toastTx(message, hash)              toast with a stellar.expert link
 */
(function () {
  "use strict";

  var Lowbid = window.Lowbid = window.Lowbid || {};
  var CFG = window.LOWBID || {};
  var ASSET = CFG.asset || CFG.usdc || {};

  var DECLINED_CODE = -4; // FreighterApiDeclinedError
  var BALANCE_INTERVAL_MS = 5000;        // first 2 minutes
  var BALANCE_SLOW_AFTER_MS = 120000;
  var BALANCE_SLOW_INTERVAL_MS = 15000;  // then, until BALANCE_MAX_MS — the release moment must not be missed
  var BALANCE_MAX_MS = 15 * 60 * 1000;
  var BALANCE_MAX_FAILURES = 3; // consecutive Horizon failures before a watcher gives up
  var balanceWarned = false;
  // Steps the chain may run without a form: everything but deliver (needs the link) and validate (rating).
  var CHAINABLE = { deploy: 1, fund: 1, approve: 1, release: 1, direct_pay: 1 };

  /* ---------- helpers ---------- */
  function toast(msg, type, opts) {
    if (typeof Lowbid.toast === "function") return Lowbid.toast(msg, type, opts);
    return null;
  }

  function errorMessage(err) {
    if (!err) return "Unknown error.";
    if (err.data && typeof err.data.message === "string" && err.data.message) return err.data.message;
    if (err.data && typeof err.data.error === "string" && err.data.error) return err.data.error;
    var msg = err.message || String(err);
    if (msg === "freighter_missing") return "Install the Freighter extension, then reload the page.";
    if (/^HTTP 401/.test(msg)) return "Connect your wallet to continue.";
    if (/^HTTP 403/.test(msg)) return "This wallet is not allowed to do this.";
    if (/^HTTP 5\d\d/.test(msg)) return "Server error, try again in a moment.";
    if (/Failed to fetch|NetworkError/i.test(msg)) return "Network unavailable, try again.";
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

  function setLoading(btn, on, label) {
    if (!btn) return;
    if (on) {
      if (btn.dataset.busy === "1") { if (label) setLoadingLabel(btn, label); return; }
      btn.dataset.busy = "1";
      btn.dataset.label = btn.innerHTML;
      btn.classList.add("is-loading");
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
      setLoadingLabel(btn, label || btn.getAttribute("data-loading-label") || "Signing…");
    } else {
      delete btn.dataset.busy;
      btn.classList.remove("is-loading");
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
    }
  }
  function setLoadingLabel(btn, label) {
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i> <span>' + Lowbid.escapeHtml(label) + "</span>";
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
    var slot = btn && btn.matches && btn.matches("[data-pay-error]") ? btn : errorSlot(btn);
    if (!slot) return;
    slot.textContent = msg || "";
    if (msg) slot.removeAttribute("hidden"); else slot.setAttribute("hidden", "");
  }

  /* data-pay-body JSON, plus the fields of the enclosing <form data-pay-form> (e.g. the delivery link). */
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
      var target = new URL(result.redirect, window.location.href);
      if (target.pathname === window.location.pathname && target.search === window.location.search) {
        // Same page, only the #anchor differs: assigning href would not reload — do it explicitly.
        if (target.hash) window.location.hash = target.hash;
        setTimeout(function () { window.location.reload(); }, 600);
      } else {
        window.location.href = result.redirect;
      }
      return;
    }
    if (btn && btn.hasAttribute("data-no-reload")) return;
    setTimeout(function () { window.location.reload(); }, 900);
  }

  function failed(res, fallback) {
    var e = new Error((res && (res.message || res.error)) || fallback);
    e.data = res || {};
    return e;
  }

  function chainable(next) {
    return !!(next && next.mine && next.prepare_url && CHAINABLE[next.step] && !next.evidence);
  }

  /* ---------- core ---------- */
  var pay = {
    explorerTxUrl: function (hash) { return explorerBase() + "/tx/" + encodeURIComponent(hash || ""); },
    explorerAccountUrl: function (addr) { return explorerBase() + "/account/" + encodeURIComponent(addr || ""); },
    explorerContractUrl: function (id) { return explorerBase() + "/contract/" + encodeURIComponent(id || ""); },

    /* Success toast carrying the tx hash and its stellar.expert link (the toast body is text-only by design). */
    toastTx: function (message, hash, opts) {
      var t = toast(message + (hash ? " (" + Lowbid.shortAddr(hash, 6) + ")" : ""), "success", Object.assign({ title: "Confirmed", duration: 9000 }, opts || {}));
      if (t && t.el && hash) {
        var body = t.el.querySelector(".lb-toast-message");
        if (body) {
          var a = document.createElement("a");
          a.href = pay.explorerTxUrl(hash); a.target = "_blank"; a.rel = "noopener"; a.className = "ui-link";
          a.textContent = "view on stellar.expert";
          body.appendChild(document.createTextNode(" — "));
          body.appendChild(a);
        }
      }
      return t;
    },

    /* Freighter signs `xdr` with the session wallet, the signed XDR goes to `sendUrl`.
       Resolves with the server JSON. Rejects with an Error; `.handled` is set when a toast
       was already shown (user declined). */
    signAndSend: function (opts) {
      opts = opts || {};
      if (!opts.xdr) return Promise.reject(new Error("Missing transaction to sign."));
      if (!opts.sendUrl) return Promise.reject(new Error("Missing send URL."));
      if (typeof Lowbid.signTransaction !== "function") return Promise.reject(new Error("freighter_missing"));

      toast("Confirm the transaction in Freighter.", "info", { title: "Signature requested", duration: 6000 });
      return Lowbid.signTransaction(opts.xdr, {
        networkPassphrase: CFG.networkPassphrase,
        address: CFG.walletAddress || undefined
      }).catch(function (err) {
        if (isDeclined(err)) {
          toast("Signature declined in Freighter — nothing was sent.", "warning", { title: "Cancelled" });
          var e = new Error("declined"); e.code = "declined"; e.handled = true; e.cause = err;
          throw e;
        }
        throw err;
      }).then(function (signedXdr) {
        toast("Sending to the Stellar network…", "info", { title: "Sending", duration: 8000 });
        var body = Object.assign({ signed_xdr: signedXdr }, opts.extra || {});
        return Lowbid.api(opts.sendUrl, { method: "POST", body: body });
      }).then(function (res) {
        if (!res || res.ok === false) throw failed(res, "Transaction rejected by the network.");
        pay.toastTx(res.message || "Transaction confirmed.", res.hash);
        return res;
      });
    },

    /* One step, no page effect: prepare -> (sign -> send). Resolves with the server JSON of the last
       call (the prepare answer when the server completed the step itself, e.g. direct-mode deliver). */
    run: function (desc) {
      desc = desc || {};
      if (!desc.prepareUrl) return Promise.reject(new Error("Misconfigured button (data-prepare-url missing)."));
      var body = Object.assign({}, desc.body || {});
      body.step = desc.step || body.step || "";
      return Lowbid.api(desc.prepareUrl, { method: "POST", body: body }).then(function (prep) {
        if (!prep || prep.ok === false) throw failed(prep, "Could not prepare the transaction.");
        if (!prep.xdr) {
          if (prep.message) toast(prep.message, "success", { title: "Saved" });
          return prep; // nothing to sign: the server completed the step itself
        }
        return pay.signAndSend({
          xdr: prep.xdr,
          sendUrl: prep.send_url || desc.sendUrl,
          extra: Object.assign({ step: body.step }, prep.extra || {})
        });
      });
    },

    /* Follow `next` while it is a signature of mine (deploy → fund, approve → release, direct_pay).
       opts.stopAfter: array of steps after which the chain stops (e.g. ["fund"] for project funding).
       opts.onStep(next, index): called before each step (progress label). Resolves {completed, last, next};
       rejects with the step error carrying .completed and .pending (the step that failed). */
    runChain: function (next, opts) {
      opts = opts || {};
      var completed = 0, last = null;
      function loop(cur) {
        if (!chainable(cur)) return Promise.resolve({ completed: completed, last: last, next: cur });
        if (typeof opts.onStep === "function") opts.onStep(cur, completed);
        return pay.run({ step: cur.step, prepareUrl: cur.prepare_url, body: opts.body }).then(function (res) {
          completed += 1; last = res;
          var following = res && res.next;
          if (opts.stopAfter && opts.stopAfter.indexOf(cur.step) !== -1 && !(following && opts.stopAfter.indexOf(following.step) !== -1)) {
            return { completed: completed, last: last, next: following };
          }
          return loop(following);
        }).catch(function (err) {
          if (err && err.completed === undefined) { err.completed = completed; err.pending = cur; }
          throw err;
        });
      }
      return loop(next);
    },

    /* Generic [data-pay-step] driver: (confirm) -> prepare -> sign -> send -> chain `next` -> reload/redirect. */
    runStep: function (btn) {
      if (!btn || btn.dataset.busy === "1" || btn.dataset.pending === "1") return Promise.resolve();
      var prepareUrl = btn.getAttribute("data-prepare-url");
      if (!prepareUrl) {
        showError(btn, "Misconfigured button (data-prepare-url missing).");
        return Promise.resolve();
      }
      var ask = Promise.resolve(true);
      if (btn.hasAttribute("data-confirm-message") && typeof Lowbid.confirm === "function") {
        ask = Lowbid.confirm({
          title: btn.getAttribute("data-confirm-title") || "Confirm?",
          message: btn.getAttribute("data-confirm-message"),
          confirmLabel: btn.getAttribute("data-confirm-label") || "Confirm",
          icon: "fa-truck-fast"
        });
      }
      btn.dataset.pending = "1"; // a second click while the confirm dialog is open must not start a second run
      return ask.then(function (ok) {
        delete btn.dataset.pending;
        if (!ok) return;
        showError(btn, "");
        setLoading(btn, true);
        var step = btn.getAttribute("data-pay-step") || "";
        return pay.run({ step: step, prepareUrl: prepareUrl, body: parseBody(btn), sendUrl: btn.getAttribute("data-send-url") }).then(function (res) {
          if (res && chainable(res.next)) {
            setLoading(btn, true, res.next.label + "…");
            return pay.runChain(res.next).then(function (chain) { return chain.last || res; });
          }
          return res;
        }).then(function (res) {
          finish(res, btn);
          return res;
        }).catch(function (err) {
          setLoading(btn, false);
          if (err && err.handled) { if (err.completed) finish(null, btn); return; }
          var msg = errorMessage(err);
          showError(btn, msg);
          toast(msg, "error", { title: "Payment" });
          console.warn("lowbid-pay: step failed", err);
          if (err && err.completed) finish(null, btn); // a signature went through: refresh the panel
        });
      });
    },

    /* "Fund the project": deploy + fund every assigned, unfunded task, one after the other. */
    fundProject: function (btn) {
      var url = (btn && btn.getAttribute("data-pending-url")) || (window.LOWBID_PROJECT && window.LOWBID_PROJECT.urls && window.LOWBID_PROJECT.urls.fund);
      if (!url) return Promise.resolve();
      if (btn && btn.dataset.busy === "1") return Promise.resolve();
      var status = document.querySelector("[data-pay-status]");
      function say(text) { if (status) status.textContent = text; }
      if (btn) { showError(btn, ""); setLoading(btn, true, "Funding…"); }
      var done = 0;
      return Lowbid.api(url).then(function (data) {
        if (!data || data.ok === false) throw failed(data, "Could not fund the project.");
        var tasks = data.tasks || [];
        if (!tasks.length) { toast(data.hint || "Nothing to fund.", "info", { title: "Funding" }); if (btn) setLoading(btn, false); return null; }
        var i = 0;
        function nextTask() {
          if (i >= tasks.length) return Promise.resolve();
          var t = tasks[i++];
          return pay.runChain(t.next, {
            stopAfter: ["fund"],
            onStep: function (step) {
              var label = "Task " + i + "/" + tasks.length + " \"" + t.title + "\": " + step.label + "…";
              say(label); if (btn) setLoading(btn, true, label);
            }
          }).then(function () { done += 1; return nextTask(); });
        }
        return nextTask().then(function () {
          say(done + " task" + (done > 1 ? "s" : "") + " funded. Reloading…");
          toast("Project funded: " + done + " escrow" + (done > 1 ? "s" : "") + " created and funded.", "success", { title: "Funding" });
          finish(null, btn);
        });
      }).catch(function (err) {
        if (btn) setLoading(btn, false);
        var msg = errorMessage(err);
        if (!(err && err.handled)) {
          showError(btn || status, msg);
          toast(msg, "error", { title: "Funding" });
          console.warn("lowbid-pay: funding failed", err);
        }
        if (done || (err && err.completed)) finish(null, btn); // some signatures went through: refresh the banner
      });
    },

    /* Asset trustline for the session wallet (freelance onboarding). Needs LOWBID.urls.trustlinePrepare. */
    ensureTrustline: function (btn) {
      var urls = CFG.urls || {};
      var prepareUrl = (btn && btn.getAttribute("data-prepare-url")) || urls.trustlinePrepare;
      if (!prepareUrl) {
        var e = new Error("Trustline not available on this page.");
        if (btn) showError(btn, e.message);
        return Promise.reject(e);
      }
      if (btn && btn.dataset.busy === "1") return Promise.resolve();
      if (btn) { showError(btn, ""); setLoading(btn, true); }
      return Lowbid.api(prepareUrl, { method: "POST", body: { address: CFG.walletAddress || "" } }).then(function (prep) {
        if (!prep || prep.ok === false) throw failed(prep, "Could not prepare the transaction.");
        if (!prep.xdr) {
          // Already has the trustline (or native asset): the server says so without an XDR.
          toast(prep.message || "The trustline is already in place.", "info");
          if (btn) setLoading(btn, false);
          return prep;
        }
        return pay.signAndSend({
          xdr: prep.xdr,
          sendUrl: prep.send_url || urls.trustlineSend || (btn && btn.getAttribute("data-send-url")),
          extra: prep.extra || {}
        }).then(function (res) {
          if (btn) setLoading(btn, false);
          return res;
        });
      }).catch(function (err) {
        if (btn) setLoading(btn, false);
        if (err && err.handled) throw err;
        var msg = errorMessage(err);
        if (btn) showError(btn, msg);
        toast(msg, "error", { title: "Trustline" });
        console.warn("lowbid-pay: trustline failed", err);
        throw err;
      });
    },

    /* Horizon /accounts/{addr} (public CORS) -> balance string of the configured asset ("0" without
       trustline, the XLM line for the native asset), null on failure. */
    fetchUsdcBalance: function (address) {
      if (!address || !CFG.horizonUrl) return Promise.resolve(null);
      return fetch(CFG.horizonUrl.replace(/\/$/, "") + "/accounts/" + encodeURIComponent(address), {
        headers: { "Accept": "application/json" }
      }).then(function (res) {
        if (res.status === 404) return "0";
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json().then(function (acc) {
          var list = (acc && acc.balances) || [];
          for (var i = 0; i < list.length; i++) {
            if (ASSET.native) { if (list[i].asset_type === "native") return list[i].balance; }
            else if (list[i].asset_code === ASSET.code && list[i].asset_issuer === ASSET.issuer) return list[i].balance;
          }
          return "0";
        });
      }).catch(function (err) {
        if (!balanceWarned) {
          balanceWarned = true;
          console.warn("lowbid-pay: balance fetch failed (Horizon unreachable?) — further failures are silent", err);
        }
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
      var failures = 0;

      function nodesFor() {
        return document.querySelectorAll('[data-usdc-balance="' + address.replace(/"/g, "") + '"]');
      }

      function renderUnavailable() {
        nodesFor().forEach(function (n) {
          if (n.getAttribute("data-balance")) return; // keep the last good value
          n.textContent = "—";
          n.title = "Balance unavailable (Horizon unreachable).";
        });
      }

      function render(balance) {
        var nodes = nodesFor();
        var text = Lowbid.formatUsdc ? Lowbid.formatUsdc(balance, ASSET.code) : balance + " " + (ASSET.code || "USDC");
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
          if (balance === null) {
            failures += 1;
            if (failures >= BALANCE_MAX_FAILURES) {
              // Horizon is down or blocked: stop polling instead of logging a network error every 5 s.
              renderUnavailable();
              stop();
              return;
            }
          } else {
            failures = 0;
          }
          if (balance !== null) {
            if (balance !== last) {
              render(balance);
              if (last !== null && Number(balance) > Number(last) && typeof opts.onIncrease === "function") {
                opts.onIncrease(balance, last);
              }
              last = balance;
            }
          }
          var elapsed = Date.now() - started;
          if (elapsed < maxMs) timer = setTimeout(tick, elapsed < BALANCE_SLOW_AFTER_MS ? interval : Math.max(interval, BALANCE_SLOW_INTERVAL_MS));
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
    var fundBtn = ev.target.closest("[data-fund]");
    if (fundBtn && !fundBtn.disabled) {
      ev.preventDefault();
      pay.fundProject(fundBtn);
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
