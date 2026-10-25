/* TaskVault publication deposit — the #deposit-panel of the project page (templates/payments/_deposit_panel.html).
 *
 * Depends on lowbid-base.js (Lowbid.api, toast), lowbid-ui.js (Lowbid.confirm, setBusy) and lowbid-pay.js
 * (Lowbid.pay.run: prepare -> Freighter -> send, looked up at click time since lowbid-pay.js is deferred).
 *
 *   [data-publish][data-pending-url]     company: GET pending.json, then chain the deposit steps (deploy -> fund)
 *                                        with Lowbid.pay.run, one after the other, following each answer's `next`
 *   [data-deposit-refund][data-url]      company: "Reclaim my deposit" (confirm, POST; the server keys sign)
 *   [data-deposit-report][data-url]      any wallet: "Report a ghost listing" (confirm, POST; the server keys sign)
 *   [data-project-cancel][data-url]      company: confirm (body = data-confirm-message, says refund / forfeit), POST
 *   [data-deposit-error]                 error slot ([data-deposit-error-text])
 * A [data-no-confirm] button (the Retry of a failed settlement) skips the dialog.
 */
(function () {
  "use strict";

  var Lowbid = window.Lowbid || (window.Lowbid = {});
  var DEPOSIT_STEPS = { deploy: 1, fund: 1 };

  function toast(msg, type, opts) {
    if (typeof Lowbid.toast === "function") Lowbid.toast(msg, type, opts);
  }

  function messageOf(err, fallback) {
    if (err && err.data && err.data.message) return err.data.message;
    if (err && err.message && !/^HTTP \d/.test(err.message)) return err.message;
    if (err && err.status === 401) return "Connect your wallet to continue.";
    return fallback;
  }

  function showError(msg) {
    var box = document.querySelector("[data-deposit-error]");
    if (!box) return;
    var text = box.querySelector("[data-deposit-error-text]") || box;
    text.textContent = msg || "";
    if (msg) box.removeAttribute("hidden"); else box.setAttribute("hidden", "");
  }

  function reload(delay) {
    setTimeout(function () { window.location.reload(); }, delay || 900);
  }

  function busy(btn, on) {
    if (typeof Lowbid.setBusy === "function") Lowbid.setBusy(btn, on, btn.getAttribute("data-loading-label") || "Working…");
  }

  /* Run the deposit steps one after the other while the server says the next one is mine. */
  function chain(next, done) {
    if (!next || !next.mine || !next.prepare_url || !DEPOSIT_STEPS[next.step]) return Promise.resolve(done);
    if (!Lowbid.pay || typeof Lowbid.pay.run !== "function") return Promise.reject(new Error("The payment module is not loaded yet, try again."));
    return Lowbid.pay.run({ step: next.step, prepareUrl: next.prepare_url }).then(function (res) {
      if (!res || res.ok === false) {
        var e = new Error((res && res.message) || "The deposit step failed."); e.data = res || {}; throw e;
      }
      return chain(res.next, done + 1);
    }).catch(function (err) {
      if (err && err.completed === undefined) err.completed = done;
      throw err;
    });
  }

  function publish(btn) {
    if (btn.dataset.busy === "1") return;
    btn.dataset.busy = "1";
    showError("");
    busy(btn, true);
    Lowbid.api(btn.getAttribute("data-pending-url")).then(function (data) {
      if (!data || data.ok === false) {
        var e = new Error((data && data.message) || "Could not prepare the deposit."); e.data = data || {}; throw e;
      }
      if (!data.next) { toast("No deposit is due.", "info", { title: "Deposit" }); return 0; }
      return chain(data.next, 0);
    }).then(function (done) {
      if (done) {
        toast("Deposit locked: the project is published.", "success", { title: "Deposit" });
        reload();
      } else {
        delete btn.dataset.busy; busy(btn, false);
      }
    }).catch(function (err) {
      delete btn.dataset.busy; busy(btn, false);
      if (err && err.handled) { if (err.completed) reload(); return; } // declined in Freighter: already toasted
      var msg = messageOf(err, "The deposit could not be locked.");
      showError(msg);
      toast(msg, "error", { title: "Deposit" });
      console.warn("lowbid-deposit: publish failed", err);
      if (err && err.completed) reload(2500); // a signature went through: refresh the panel
    });
  }

  function post(btn, opts) {
    var ask = btn.hasAttribute("data-no-confirm") || typeof Lowbid.confirm !== "function"
      ? Promise.resolve(true)
      : Lowbid.confirm(opts);
    return ask.then(function (ok) {
      if (!ok || btn.dataset.busy === "1") return;
      btn.dataset.busy = "1";
      showError("");
      busy(btn, true);
      return Lowbid.api(btn.getAttribute("data-url"), { method: "POST" }).then(function (res) {
        if (!res || res.ok === false) {
          var e = new Error((res && res.message) || "Refused."); e.data = res || {}; throw e;
        }
        toast(res.message || opts.done, "success", { title: opts.title });
        reload();
      }).catch(function (err) {
        delete btn.dataset.busy; busy(btn, false);
        var msg = messageOf(err, "Something went wrong, try again.");
        showError(msg);
        toast(msg, "error", { title: opts.title });
        console.warn("lowbid-deposit: action failed", err);
      });
    });
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-publish], [data-deposit-refund], [data-deposit-report], [data-project-cancel]");
    if (!btn || btn.disabled) return;
    ev.preventDefault();
    var amount = btn.getAttribute("data-amount") || "the deposit";
    if (btn.hasAttribute("data-publish")) {
      publish(btn);
    } else if (btn.hasAttribute("data-deposit-refund")) {
      post(btn, {
        title: "Reclaim my deposit",
        message: "TaskVault signs the refund of " + amount + " to your wallet (three transactions on Stellar).",
        confirmLabel: "Reclaim",
        icon: "fa-rotate-left",
        done: "Deposit refunded."
      });
    } else if (btn.hasAttribute("data-deposit-report")) {
      post(btn, {
        title: "Report a ghost listing",
        message: "Candidates waited and nobody was chosen: the deposit of " + amount + " is sent to the guarantee fund.",
        confirmLabel: "Report",
        icon: "fa-ghost",
        done: "Deposit sent to the guarantee fund."
      });
    } else {
      post(btn, {
        title: "Cancel the project",
        message: btn.getAttribute("data-confirm-message") || "The project stops taking applications.",
        confirmLabel: "Cancel the project",
        cancelLabel: "Keep it",
        danger: btn.getAttribute("data-confirm-danger") === "1",
        icon: "fa-ban",
        done: "Project cancelled."
      });
    }
  });
})();
