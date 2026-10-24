/* Lowbid auctions: countdowns on every page + the need-detail behaviour
   (bid form, 5 s polling of encheres.json, client sliders, choose / close / cancel).
   Server-side values arrive through window.LOWBID_NEED (set in need_detail.html). */
(function () {
  "use strict";

  var Lowbid = window.Lowbid || (window.Lowbid = {});

  /* ---------- tags: same normalisation as services.clean_tags (display only) ---------- */
  Lowbid.parseTags = function (raw) {
    var out = [];
    String(raw || "").toLowerCase().split(/[,\s;]+/).forEach(function (p) {
      p = p.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
      if (p && out.indexOf(p) === -1) out.push(p);
    });
    return out;
  };

  /* ---------- countdown: <span class="ui-countdown" data-ends-at="ISO" data-status="open"> ---------- */
  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function formatRemaining(ms) {
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400); s -= d * 86400;
    var h = Math.floor(s / 3600); s -= h * 3600;
    var m = Math.floor(s / 60); s -= m * 60;
    if (d > 0) return d + " j " + pad(h) + ":" + pad(m) + ":" + pad(s);
    if (h > 0) return pad(h) + ":" + pad(m) + ":" + pad(s);
    return pad(m) + ":" + pad(s);
  }

  function tickCountdowns() {
    var now = Date.now();
    document.querySelectorAll(".ui-countdown[data-ends-at]").forEach(function (el) {
      var status = el.getAttribute("data-status") || "open";
      if (status !== "open") {
        el.textContent = "Terminé";
        el.classList.remove("is-urgent");
        return;
      }
      var ends = Date.parse(el.getAttribute("data-ends-at"));
      if (isNaN(ends)) { el.textContent = "—"; return; }
      var left = ends - now;
      if (left <= 0) {
        if (!el.dataset.ended) {
          el.dataset.ended = "1";
          el.textContent = "Terminé";
          el.classList.add("is-urgent");
          el.dispatchEvent(new CustomEvent("lowbid:countdown-end", { bubbles: true }));
        }
        return;
      }
      el.textContent = formatRemaining(left);
      el.classList.toggle("is-urgent", left < 10 * 60 * 1000);
    });
  }
  tickCountdowns();
  setInterval(tickCountdowns, 1000);

  /* ---------- classic forms: one submission only (#need-form) ---------- */
  document.querySelectorAll("form[data-submit-once]").forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      if (f.dataset.submitted === "1") { ev.preventDefault(); return; }
      f.dataset.submitted = "1";
      f.querySelectorAll('button[type="submit"]').forEach(function (b) {
        b.classList.add("is-loading"); b.setAttribute("aria-busy", "true");
        // disabled buttons are dropped from the POST body; the form has none named, so this is safe
        setTimeout(function () { b.disabled = true; }, 0);
      });
    });
  });

  /* ---------- need detail page ---------- */
  var cfg = window.LOWBID_NEED;
  if (!cfg) return;

  var list = document.getElementById("bids-list");
  var W = cfg.weights.slice();
  var AWARD_URL = cfg.urls.award; // ends with /choisir/0/ → replace the 0

  function toastError(err, fallback) {
    var msg = (err && err.data && err.data.message) || (err && err.message) || fallback || "Action impossible.";
    if (err && err.status === 401) msg = "Connectez votre wallet pour continuer.";
    Lowbid.toast(msg, "error");
    return msg;
  }

  function setBusy(btn, on, label) {
    if (!btn) return;
    if (on) {
      btn.dataset.label = btn.innerHTML; btn.disabled = true; btn.classList.add("is-loading");
      btn.innerHTML = '<i class="fa-solid fa-spinner" aria-hidden="true"></i> ' + (label || "…");
    } else {
      btn.disabled = false; btn.classList.remove("is-loading");
      if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
    }
  }

  /* ----- client-side re-ranking from the data-* ratios (no round-trip) ----- */
  function applyWeights() {
    if (!list) return;
    var container = list.querySelector("[data-bids]");
    if (!container) return;
    var rows = Array.prototype.slice.call(container.querySelectorAll(".bid-row"));
    if (!rows.length) return;
    var scored = rows.map(function (row) {
      var p = parseFloat(row.dataset.priceRatio) || 0, d = parseFloat(row.dataset.delayRatio) || 0, s = parseFloat(row.dataset.skillsRatio) || 0;
      var parts = [W[0] * p, W[1] * d, W[2] * s];
      return { row: row, parts: parts, total: parts[0] + parts[1] + parts[2], price: parseFloat(row.dataset.price) || 0, created: parseInt(row.dataset.created, 10) || 0, id: parseInt(row.dataset.bidId, 10) || 0 };
    });
    scored.sort(function (a, b) {
      if (Math.abs(a.total - b.total) > 1e-6) return b.total - a.total;
      if (a.price !== b.price) return a.price - b.price;
      if (a.created !== b.created) return a.created - b.created;
      return a.id - b.id;
    });
    scored.forEach(function (item, i) {
      var row = item.row;
      container.appendChild(row);
      var rank = row.querySelector("[data-rank]"); if (rank) rank.textContent = String(i + 1);
      var score = row.querySelector("[data-score]"); if (score) score.textContent = item.total.toFixed(1);
      ["p", "d", "s"].forEach(function (k, j) {
        var seg = row.querySelector('[data-seg="' + k + '"]'); if (seg) seg.style.width = Math.max(0, item.parts[j]).toFixed(1) + "%";
      });
      var badge = row.querySelector("[data-recommended]");
      if (badge) { if (i === 0) badge.removeAttribute("hidden"); else badge.setAttribute("hidden", ""); }
    });
  }

  /* ----- sliders: keep the sum at 100 by redistributing pro-rata onto the two others ----- */
  function redistribute(changed, value) {
    value = Math.max(0, Math.min(100, Math.round(value)));
    var others = [0, 1, 2].filter(function (i) { return i !== changed; });
    var rest = 100 - value;
    var a = W[others[0]], b = W[others[1]], sum = a + b;
    var na = sum === 0 ? Math.floor(rest / 2) : Math.round(a * rest / sum);
    na = Math.max(0, Math.min(rest, na));
    W[changed] = value; W[others[0]] = na; W[others[1]] = rest - na;
  }

  function renderWeights() {
    document.querySelectorAll("[data-weight]").forEach(function (input) {
      var i = parseInt(input.dataset.weight, 10);
      input.value = W[i];
      var out = document.querySelector('[data-weight-out="' + i + '"]'); if (out) out.textContent = String(W[i]);
    });
    try {
      var url = new URL(location.href);
      url.searchParams.set("wp", W[0]); url.searchParams.set("wd", W[1]); url.searchParams.set("ws", W[2]);
      history.replaceState(null, "", url.toString());
    } catch (e) { /* ignore */ }
  }

  document.querySelectorAll("[data-weight]").forEach(function (input) {
    input.addEventListener("input", function () {
      redistribute(parseInt(input.dataset.weight, 10), parseInt(input.value, 10));
      renderWeights();
      applyWeights();
    });
  });
  var reset = document.querySelector("[data-weights-reset]");
  if (reset) reset.addEventListener("click", function () { W = [40, 30, 30]; renderWeights(); applyWeights(); });

  /* ----- polling: swap the list when the server fingerprint changes ----- */
  var polling = true;
  function refresh() {
    if (!polling || document.hidden) return Promise.resolve();
    var url = cfg.urls.bids + "?wp=" + W[0] + "&wd=" + W[1] + "&ws=" + W[2];
    return Lowbid.api(url).then(function (data) {
      if (!data || !data.ok) return;
      if (data.status !== cfg.status) { location.reload(); return; }
      var dot = document.querySelector("[data-live-dot]"); if (dot) dot.removeAttribute("hidden");
      if (list && data.fingerprint !== list.dataset.fingerprint) {
        list.innerHTML = data.html;
        list.dataset.fingerprint = data.fingerprint;
        applyWeights();
        var count = document.querySelector("[data-kpi-count]"); if (count) count.textContent = String(data.count);
        var best = document.querySelector("[data-kpi-best]");
        if (best && data.best_price) best.innerHTML = Lowbid.escapeHtml(Lowbid.formatUsdc(data.best_price, "")) + '<span class="ui-price-unit">USDC</span>';
        updatePriceCap(data.best_price || data.budget_max);
      }
    }).catch(function (err) {
      if (err && err.status === 404) { polling = false; }
    });
  }
  setInterval(refresh, 5000);
  document.addEventListener("lowbid:countdown-end", function (ev) {
    if (ev.target.hasAttribute("data-countdown-main")) setTimeout(refresh, 1200);
  });

  /* ----- bid form ----- */
  var form = document.getElementById("bid-form");
  var priceCap = cfg.bestPrice || cfg.budgetMax;

  function updatePriceCap(value) {
    priceCap = value;
    var cap = document.querySelector("[data-price-cap]"); if (cap) cap.textContent = Lowbid.formatUsdc(value);
    var price = document.getElementById("bid-price"); if (price) price.max = value;
    validatePrice();
  }

  function showError(field, msg) {
    var el = form && form.querySelector('[data-error-for="' + field + '"]');
    if (!el) return;
    el.textContent = msg || "";
    if (msg) el.removeAttribute("hidden"); else el.setAttribute("hidden", "");
  }

  function validatePrice() {
    var price = document.getElementById("bid-price");
    if (!price || !price.value) { showError("price", ""); return true; }
    var v = parseFloat(price.value), cap = parseFloat(priceCap);
    var ok = v > 0 && (!isFinite(cap) || v < cap);
    showError("price", ok ? "" : "Doit être strictement inférieur à " + Lowbid.formatUsdc(priceCap) + ".");
    price.setAttribute("aria-invalid", ok ? "false" : "true");
    return ok;
  }

  if (form) {
    var priceInput = document.getElementById("bid-price");
    if (priceInput) priceInput.addEventListener("input", validatePrice);

    document.querySelectorAll("[data-add-tag]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var input = document.getElementById("bid-tags");
        var tags = Lowbid.parseTags(input.value);
        if (tags.indexOf(chip.dataset.addTag) === -1 && tags.length < 3) tags.push(chip.dataset.addTag);
        input.value = tags.join(", ");
        showError("tags", tags.length > 3 ? "Au plus 3 compétences." : "");
      });
    });

    var CODE_FIELD = { not_lower: "price", over_budget: "price", over_delay: "delay_days", bad_tags: "tags", invalid: "price" };

    var submitting = false;
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (submitting) return; // Enter pressed twice / double click while the request is in flight
      ["price", "delay_days", "tags", "_"].forEach(function (f) { showError(f, ""); });
      if (!validatePrice()) return;
      submitting = true;
      var body = {
        price: document.getElementById("bid-price").value,
        delay_days: document.getElementById("bid-delay").value,
        tags: Lowbid.parseTags(document.getElementById("bid-tags").value),
        message: document.getElementById("bid-message").value
      };
      var btn = form.querySelector("[data-bid-submit]");
      setBusy(btn, true, "Envoi…");
      Lowbid.api(cfg.urls.bid, { method: "POST", body: body }).then(function (data) {
        Lowbid.toast(data.message || "Offre enregistrée.", "success", { title: "Enchère" });
        // Reload: the panel title / "votre offre actuelle" line and the list all change.
        // The button stays disabled until then so a second click cannot post twice.
        setTimeout(function () { location.reload(); }, 500);
      }).catch(function (err) {
        submitting = false;
        setBusy(btn, false);
        var code = err && err.data && err.data.error;
        var msg = toastError(err, "Offre refusée.");
        showError(CODE_FIELD[code] || "_", msg);
        if (code === "closed") setTimeout(function () { location.reload(); }, 1500);
        if (code === "not_lower") refresh();
      });
    });
  }

  /* ----- client actions: choose / close / cancel (event delegation: the list gets swapped) ----- */
  document.addEventListener("click", function (ev) {
    var choose = ev.target.closest("[data-choose]");
    if (choose) {
      var label = choose.dataset.chooseLabel || "cette offre";
      if (!window.confirm("Retenir l’offre " + label + " ?\nLes autres offres passeront en « Non retenue ».")) return;
      setBusy(choose, true, "…");
      Lowbid.api(AWARD_URL.replace(/\/0\/$/, "/" + choose.dataset.choose + "/"), { method: "POST" }).then(function (data) {
        Lowbid.toast(data.message || "Offre retenue.", "success", { title: "Choix" });
        setTimeout(function () { location.reload(); }, 500);
      }).catch(function (err) { setBusy(choose, false); toastError(err, "Choix impossible."); });
      return;
    }
    var close = ev.target.closest("[data-need-close]");
    if (close) {
      if (!window.confirm("Clôturer les enchères maintenant ? Plus aucune offre ne sera acceptée.")) return;
      setBusy(close, true, "Clôture…");
      Lowbid.api(cfg.urls.close, { method: "POST" }).then(function (data) {
        Lowbid.toast(data.message || "Enchères clôturées.", "success");
        setTimeout(function () { location.reload(); }, 400);
      }).catch(function (err) { setBusy(close, false); toastError(err, "Clôture impossible."); });
      return;
    }
    var cancel = ev.target.closest("[data-need-cancel]");
    if (cancel) {
      if (!window.confirm("Annuler ce besoin ? Cette action est définitive.")) return;
      setBusy(cancel, true, "Annulation…");
      Lowbid.api(cfg.urls.cancel, { method: "POST" }).then(function (data) {
        Lowbid.toast(data.message || "Besoin annulé.", "success");
        setTimeout(function () { location.reload(); }, 400);
      }).catch(function (err) { setBusy(cancel, false); toastError(err, "Annulation impossible."); });
    }
  });

  applyWeights();
})();
