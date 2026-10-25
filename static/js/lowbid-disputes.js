/* TaskVault disputes desk (/litiges/, arbiter wallet only): the live split preview of every
   resolution form. The signature itself is a regular payment step driven by lowbid-pay.js
   ([data-pay-step="resolve"] inside form[data-pay-form]: the range value `freelance_pct` joins the
   prepare body; the server reads the on-chain balance and builds the distributions).

   Markup (templates/projects/disputes.html):
     form#resolve-form-<task>[data-resolve-form][data-amount="<locked amount>"]
       input[type=range][data-freelance-pct]            0–100, step 1
       [data-split-freelance-pct] [data-split-company-pct] [data-split-freelance] [data-split-company]
       button[data-pay-step="resolve"][data-confirm-message]   the message is refreshed with the current split

   Depends on lowbid-base.js (Lowbid.formatUsdc). */
(function () {
  "use strict";

  var Lowbid = window.Lowbid || (window.Lowbid = {});

  /* Same rounding as payments.services.split_amounts: the freelance share is rounded DOWN to a stroop
     (7 decimals), the company gets the exact remainder. Preview only — the server recomputes on the
     real balance. */
  Lowbid.splitAmounts = function (amount, pct) {
    var total = Number(amount);
    var p = Math.max(0, Math.min(100, parseInt(pct, 10) || 0));
    if (!isFinite(total)) return { freelance: 0, company: 0, pct: p };
    var freelance = Math.floor(total * p / 100 * 1e7) / 1e7;
    var company = Math.round((total - freelance) * 1e7) / 1e7;
    return { freelance: freelance, company: company, pct: p };
  };

  function wire(form) {
    var range = form.querySelector("[data-freelance-pct]");
    var btn = form.querySelector('[data-pay-step="resolve"]');
    if (!range) return;
    var amount = form.getAttribute("data-amount") || "0";
    var out = {
      fp: form.querySelector("[data-split-freelance-pct]"),
      cp: form.querySelector("[data-split-company-pct]"),
      fa: form.querySelector("[data-split-freelance]"),
      ca: form.querySelector("[data-split-company]")
    };
    function render() {
      var s = Lowbid.splitAmounts(amount, range.value);
      range.style.setProperty("--range-pct", s.pct + "%");
      range.setAttribute("aria-valuetext", s.pct + "% to the freelancer, " + (100 - s.pct) + "% to the company");
      if (out.fp) out.fp.textContent = s.pct + "%";
      if (out.cp) out.cp.textContent = (100 - s.pct) + "%";
      if (out.fa) out.fa.textContent = Lowbid.formatUsdc ? Lowbid.formatUsdc(s.freelance) : String(s.freelance);
      if (out.ca) out.ca.textContent = Lowbid.formatUsdc ? Lowbid.formatUsdc(s.company) : String(s.company);
      if (btn) {
        btn.setAttribute("data-confirm-message", "Split " + s.pct + "% / " + (100 - s.pct) + "%, signed in Freighter. " +
          "The freelancer receives " + (Lowbid.formatUsdc ? Lowbid.formatUsdc(s.freelance) : s.freelance) +
          ", the company " + (Lowbid.formatUsdc ? Lowbid.formatUsdc(s.company) : s.company) +
          " (before the proportional fees). The decision is final.");
      }
    }
    range.addEventListener("input", render);
    range.addEventListener("change", render);
    render();
  }

  document.querySelectorAll("form[data-resolve-form]").forEach(wire);
})();
