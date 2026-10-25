/* TaskVault reputation — company rating (task page) and the GitHub proof (profile page).
 *
 * Depends on window.Lowbid (lowbid-base.js, lowbid-ui.js, lowbid-wallet.js). URLs ride on the
 * elements as data-url; the signing address is the session wallet (window.LOWBID.walletAddress).
 *
 *   form[data-rate-company][data-url]   [data-company-rate] radios, #rate-company-comment, [data-rate-company-submit]
 *   #github-verify                      [data-github-sign][data-url] → #github-proof (+ [data-github-copy]),
 *                                       #github-gist + [data-github-submit][data-url], [data-github-unlink][data-url]
 *
 * Gist format (see reputation/services.py): line 1 `lowbid:<G…>`, line 2 `signature: <base64>`.
 */
(function () {
  "use strict";

  var Lowbid = window.Lowbid || {};
  var CFG = window.LOWBID || {};

  function message(err, fallback) {
    return (err && err.data && err.data.message) || (err && err.message) || fallback;
  }

  function fieldError(root, field, msg) {
    var el = root.querySelector('[data-error-for="' + field + '"]');
    if (!el) return;
    el.textContent = msg || "";
    el.hidden = !msg;
  }

  /* ----- the freelancer rates the company (task page) ----- */
  var rateForm = document.querySelector("form[data-rate-company]");
  if (rateForm) {
    var LABELS = { 1: "1/5 — poor", 2: "2/5 — fair", 3: "3/5 — good", 4: "4/5 — very good", 5: "5/5 — excellent" };
    var help = rateForm.querySelector("[data-company-rate-help]");
    rateForm.querySelectorAll("[data-company-rate]").forEach(function (r) {
      r.addEventListener("change", function () { if (help) help.textContent = LABELS[r.value] || ""; });
    });
    var rating = false;
    rateForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (rating) return;
      fieldError(rateForm, "note", ""); fieldError(rateForm, "_", "");
      var checked = rateForm.querySelector("[data-company-rate]:checked");
      if (!checked) { fieldError(rateForm, "note", "Choose a rating from 1 to 5."); return; }
      var note = parseInt(checked.value, 10);
      var btn = rateForm.querySelector("[data-rate-company-submit]");
      Lowbid.confirm({
        title: "Rate the company " + note + "/5?",
        message: "Your rating is public and final: one rating per task.",
        confirmLabel: "Rate the company", icon: "fa-star"
      }).then(function (ok) {
        if (!ok) return;
        rating = true;
        Lowbid.setBusy(btn, true, "Saving…");
        var comment = document.getElementById("rate-company-comment");
        return Lowbid.api(rateForm.getAttribute("data-url"), {
          method: "POST", body: { note: note, comment: comment ? comment.value : "" }
        }).then(function (data) {
          Lowbid.toast(data.message || "Rating saved.", "success", { title: "Company rated" });
          setTimeout(function () { location.reload(); }, 600);
        }).catch(function (err) {
          rating = false;
          Lowbid.setBusy(btn, false);
          var code = err && err.data && err.data.error;
          var msg = message(err, "Rating rejected.");
          fieldError(rateForm, code === "invalid" ? "note" : "_", msg);
          Lowbid.toast(msg, "error", { title: "Rating" });
          if (code === "duplicate" || code === "wrong_state") setTimeout(function () { location.reload(); }, 1500);
        });
      });
    });
  }

  /* ----- GitHub proof (profile page, owner only) ----- */
  var panel = document.getElementById("github-verify");
  if (!panel) return;

  var signBtn = panel.querySelector("[data-github-sign]");
  var proof = document.getElementById("github-proof");
  var copyBtn = panel.querySelector("[data-github-copy]");
  if (signBtn && proof) {
    signBtn.addEventListener("click", function () {
      var address = signBtn.getAttribute("data-address") || CFG.walletAddress || "";
      if (!Lowbid.wallet || !Lowbid.wallet.signMessage) { Lowbid.toast("The wallet module is not loaded.", "error"); return; }
      Lowbid.setBusy(signBtn, true, "Signing…");
      Lowbid.wallet.isInstalled().then(function (installed) {
        if (!installed) throw new Error("Install the Freighter extension, then reload the page.");
        return Lowbid.api(signBtn.getAttribute("data-url"));
      }).then(function (data) {
        return Lowbid.wallet.signMessage(data.message, address).then(function (s) {
          if (s.signerAddress && address && s.signerAddress !== address) {
            throw new Error("Freighter signed with " + Lowbid.shortAddr(s.signerAddress) + ": switch to the account of this profile.");
          }
          return data.message + "\nsignature: " + s.signature;
        });
      }).then(function (text) {
        proof.value = text;
        if (copyBtn) { copyBtn.setAttribute("data-copy", text); copyBtn.hidden = false; }
        Lowbid.setBusy(signBtn, false);
        Lowbid.toast("Paste the two lines into a public gist, then give its URL below.", "success", { title: "Proof signed" });
      }).catch(function (err) {
        Lowbid.setBusy(signBtn, false);
        var msg = message(err, "Could not sign.");
        if (/User declined|rejected|denied|refus/i.test(msg)) msg = "Signature declined in Freighter.";
        Lowbid.toast(msg, "error", { title: "Wallet" });
      });
    });
  }

  var submitBtn = panel.querySelector("[data-github-submit]");
  var gistInput = document.getElementById("github-gist");
  if (submitBtn && gistInput) {
    var verifying = false;
    var verify = function () {
      if (verifying) return;
      fieldError(panel, "gist", "");
      var gist = gistInput.value.trim();
      if (!gist) { fieldError(panel, "gist", "Paste the URL of your public gist."); return; }
      verifying = true;
      Lowbid.setBusy(submitBtn, true, "Checking…");
      Lowbid.api(submitBtn.getAttribute("data-url"), { method: "POST", body: { gist: gist } }).then(function (data) {
        Lowbid.toast(data.message || "GitHub account linked.", "success", { title: "Verified GitHub" });
        setTimeout(function () { location.reload(); }, 600);
      }).catch(function (err) {
        verifying = false;
        Lowbid.setBusy(submitBtn, false);
        var msg = message(err, "Verification failed.");
        fieldError(panel, "gist", msg);
        Lowbid.toast(msg, "error", { title: "GitHub" });
      });
    };
    submitBtn.addEventListener("click", verify);
    gistInput.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); verify(); } });
  }

  var unlinkBtn = panel.querySelector("[data-github-unlink]");
  if (unlinkBtn) {
    unlinkBtn.addEventListener("click", function () {
      Lowbid.confirm({
        title: "Unlink the GitHub account?",
        message: "The \"Verified GitHub\" badge disappears from your profile. You can link an account again later.",
        confirmLabel: "Unlink", danger: true, icon: "fa-link-slash"
      }).then(function (ok) {
        if (!ok) return;
        Lowbid.setBusy(unlinkBtn, true, "Unlinking…");
        return Lowbid.api(unlinkBtn.getAttribute("data-url"), { method: "POST" }).then(function (data) {
          Lowbid.toast(data.message || "GitHub account unlinked.", "success", { title: "GitHub" });
          setTimeout(function () { location.reload(); }, 500);
        }).catch(function (err) {
          Lowbid.setBusy(unlinkBtn, false);
          Lowbid.toast(message(err, "Could not unlink."), "error", { title: "GitHub" });
        });
      });
    });
  }
})();
