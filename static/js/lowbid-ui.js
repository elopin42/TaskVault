/* Lowbid UI runtime (v2 component layer) — loaded on every page right after lowbid-base.js.
 *
 *   Lowbid.confirm({title, message, confirmLabel, cancelLabel, danger, icon}) -> Promise<boolean>
 *       Accessible replacement for window.confirm(), backed by <dialog id="lb-confirm"> (partials/modal.html).
 *   Lowbid.modal.open(el | "#id") / Lowbid.modal.close(el)
 *   Lowbid.identicon(address) -> {hue, cells}  mirrored 5×5 pixel grid; painted on every [data-identicon] as an SVG background
 *   Lowbid.timeAgo(isoOrDate) -> "3 min ago" / "in 3 min" / "just now"; every [data-time-ago="ISO"] is refreshed each minute
 *   Lowbid.sparkline(el)      builds the SVG of <svg class="ui-sparkline" data-points="500,450,400" [data-cap="500"]>
 *   Lowbid.poll(fn, {interval, maxInterval}) -> {stop, now}   visibility-aware polling with backoff on errors
 *   Lowbid.refreshUI(root)    re-run identicons / sparklines / time-ago inside a freshly swapped fragment
 *   Lowbid.setBusy(btn, on, label)
 *
 * Declarative wiring (event delegation, survives innerHTML swaps):
 *   [data-share="URL"]           navigator.share() or copy-to-clipboard fallback
 *   [data-confirm="message"]     on a <form>: asks Lowbid.confirm before submitting (data-confirm-title, data-confirm-danger)
 *   details.ui-menu              closes on outside click / Escape
 *   [data-search-clear]          clears the sibling input and submits its form
 *   [data-auto-submit]           a <select>/<input> that submits its form on change
 */
(function () {
  "use strict";

  var Lowbid = window.Lowbid || (window.Lowbid = {});

  /* ---------- busy buttons ---------- */
  Lowbid.setBusy = function (btn, on, label) {
    if (!btn) return;
    if (on) {
      if (!btn.dataset.label) btn.dataset.label = btn.innerHTML;
      btn.disabled = true; btn.classList.add("is-loading"); btn.setAttribute("aria-busy", "true");
      btn.innerHTML = '<i class="fa-solid fa-spinner" aria-hidden="true"></i> ' + Lowbid.escapeHtml(label || "…");
    } else {
      btn.disabled = false; btn.classList.remove("is-loading"); btn.removeAttribute("aria-busy");
      if (btn.dataset.label) { btn.innerHTML = btn.dataset.label; delete btn.dataset.label; }
    }
  };

  /* ---------- modal ---------- */
  function resolveEl(el) { return typeof el === "string" ? document.querySelector(el) : el; }
  var modal = {
    open: function (el) {
      el = resolveEl(el);
      if (!el) return;
      if (typeof el.showModal === "function") { if (!el.open) el.showModal(); }
      else el.setAttribute("open", "");
      var focus = el.querySelector("[data-autofocus]") || el.querySelector("button, [href], input, select, textarea");
      if (focus) setTimeout(function () { focus.focus(); }, 30);
    },
    close: function (el, value) {
      el = resolveEl(el);
      if (!el) return;
      if (typeof el.close === "function" && el.open) el.close(value);
      else el.removeAttribute("open");
    }
  };
  Lowbid.modal = modal;

  var ICONS = { info: "fa-circle-question", danger: "fa-triangle-exclamation", success: "fa-circle-check" };
  var pending = null;

  Lowbid.confirm = function (opts) {
    opts = typeof opts === "string" ? { message: opts } : (opts || {});
    var dlg = document.getElementById("lb-confirm");
    if (!dlg || typeof dlg.showModal !== "function") {
      return Promise.resolve(window.confirm(opts.message || "Confirm?"));
    }
    if (pending) pending(false);
    return new Promise(function (resolve) {
      pending = resolve;
      dlg.classList.toggle("is-danger", !!opts.danger);
      dlg.querySelector("[data-modal-title]").textContent = opts.title || (opts.danger ? "Confirm the action" : "Confirm");
      dlg.querySelector("[data-modal-body]").textContent = opts.message || "";
      dlg.querySelector("[data-modal-icon] i").className = "fa-solid " + (opts.icon || (opts.danger ? ICONS.danger : ICONS.info));
      var ok = dlg.querySelector("[data-modal-ok]");
      ok.textContent = opts.confirmLabel || "Confirm";
      ok.className = "ui-btn " + (opts.danger ? "ui-btn-danger-solid" : "ui-btn-primary");
      dlg.querySelector("[data-modal-cancel]").textContent = opts.cancelLabel || "Cancel";
      dlg.returnValue = "";
      var onClose = function () {
        dlg.removeEventListener("close", onClose);
        var r = pending; pending = null;
        if (r) r(dlg.returnValue === "ok");
      };
      dlg.addEventListener("close", onClose);
      modal.open(dlg);
    });
  };

  /* ---------- identicon: a mirrored 5×5 pixel grid (blockies-like), Signal yellow + one hue from the address ---------- */
  Lowbid.identicon = function (address) {
    var s = String(address || ""), h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    var hue = h % 360, cells = [];
    for (var y = 0; y < 5; y++) {
      var row = [];
      for (var x = 0; x < 3; x++) {
        h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
        row.push(h % 3); // 0 empty · 1 hue · 2 signal
      }
      cells.push(row[0], row[1], row[2], row[1], row[0]);
    }
    return { hue: hue, cells: cells };
  };
  function identiconSvg(address) {
    var signal = getComputedStyle(document.documentElement).getPropertyValue("--brand-500").trim();
    var id = Lowbid.identicon(address), fill = ["", "hsl(" + id.hue + " 58% 46%)", signal], rects = "";
    id.cells.forEach(function (c, i) {
      if (c) rects += '<rect x="' + (i % 5) + '" y="' + Math.floor(i / 5) + '" width="1" height="1" fill="' + fill[c] + '"/>';
    });
    return 'url("data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5 5" shape-rendering="crispEdges">' + rects + "</svg>") + '")';
  }
  function applyIdenticons(root) {
    (root || document).querySelectorAll("[data-identicon]").forEach(function (el) {
      if (el.dataset.identiconDone) return;
      var target = el.querySelector(".ui-identicon") || el;
      target.style.backgroundImage = identiconSvg(el.getAttribute("data-identicon"));
      el.dataset.identiconDone = "1";
    });
  }

  /* ---------- relative time ---------- */
  Lowbid.timeAgo = function (value) {
    var t = value instanceof Date ? value.getTime() : Date.parse(value);
    if (isNaN(t)) return "";
    var diff = Math.round((Date.now() - t) / 1000);
    var future = diff < 0; diff = Math.abs(diff);
    var out;
    if (diff < 45) return future ? "in a few seconds" : "just now";
    if (diff < 3600) out = Math.max(1, Math.round(diff / 60)) + " min";
    else if (diff < 86400) out = Math.round(diff / 3600) + " h";
    else if (diff < 86400 * 30) out = Math.round(diff / 86400) + " d";
    else out = Math.round(diff / (86400 * 30)) + " mo";
    return future ? "in " + out : out + " ago";
  };
  function tickTimeAgo(root) {
    (root || document).querySelectorAll("[data-time-ago]").forEach(function (el) {
      el.textContent = Lowbid.timeAgo(el.getAttribute("data-time-ago"));
      if (!el.getAttribute("title")) {
        var d = new Date(el.getAttribute("data-time-ago"));
        if (!isNaN(d.getTime())) el.setAttribute("title", d.toLocaleString("en-US"));
      }
    });
  }
  setInterval(function () { tickTimeAgo(); }, 60000);

  /* ---------- sparkline ---------- */
  var SVG = "http://www.w3.org/2000/svg";
  function node(name, attrs) {
    var n = document.createElementNS(SVG, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }
  Lowbid.sparkline = function (el) {
    if (!el) return;
    var pts = String(el.getAttribute("data-points") || "").split(",").map(parseFloat).filter(isFinite);
    var cap = parseFloat(el.getAttribute("data-cap"));
    var W = 240, H = 56, P = 6;
    el.setAttribute("viewBox", "0 0 " + W + " " + H);
    el.setAttribute("preserveAspectRatio", "none");
    while (el.firstChild) el.removeChild(el.firstChild);
    if (!pts.length) return;
    var all = pts.slice(); if (isFinite(cap)) all.push(cap);
    var min = Math.min.apply(null, all), max = Math.max.apply(null, all);
    if (max === min) { max = min + 1; }
    var x = function (i) { return pts.length === 1 ? W / 2 : P + (i * (W - 2 * P)) / (pts.length - 1); };
    var y = function (v) { return H - P - ((v - min) / (max - min)) * (H - 2 * P); };
    if (isFinite(cap)) el.appendChild(node("line", { "class": "sl-cap", x1: 0, x2: W, y1: y(cap), y2: y(cap) }));
    var d = pts.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); }).join(" ");
    if (pts.length > 1) {
      el.appendChild(node("path", { "class": "sl-area", d: d + " L" + x(pts.length - 1).toFixed(1) + " " + (H - P) + " L" + x(0).toFixed(1) + " " + (H - P) + " Z" }));
      el.appendChild(node("path", { "class": "sl-line", d: d }));
    }
    el.appendChild(node("circle", { "class": "sl-dot", cx: x(pts.length - 1).toFixed(1), cy: y(pts[pts.length - 1]).toFixed(1), r: 3.5 }));
  };
  function applySparklines(root) {
    (root || document).querySelectorAll("svg.ui-sparkline[data-points]").forEach(Lowbid.sparkline);
  }

  /* ---------- polling helper ---------- */
  Lowbid.poll = function (fn, opts) {
    opts = opts || {};
    var base = opts.interval || 5000, max = opts.maxInterval || 60000, current = base, timer = null, stopped = false, running = false;
    function schedule(ms) { clearTimeout(timer); if (!stopped) timer = setTimeout(run, ms); }
    function run() {
      if (stopped || running) return;
      if (document.hidden) { schedule(base); return; }
      running = true;
      Promise.resolve().then(fn).then(function () { current = base; }, function () { current = Math.min(max, current * 2); })
        .then(function () { running = false; schedule(current); });
    }
    document.addEventListener("visibilitychange", function () { if (!document.hidden) { current = base; schedule(150); } });
    window.addEventListener("online", function () { current = base; schedule(150); });
    schedule(base);
    return { stop: function () { stopped = true; clearTimeout(timer); }, now: function () { current = base; schedule(0); } };
  };

  /* ---------- refresh hook for swapped fragments ---------- */
  Lowbid.refreshUI = function (root) { applyIdenticons(root); applySparklines(root); tickTimeAgo(root); };

  /* ---------- delegated behaviours ---------- */
  document.addEventListener("click", function (ev) {
    var share = ev.target.closest("[data-share]");
    if (share) {
      ev.preventDefault();
      var url = share.getAttribute("data-share") || location.href;
      if (navigator.share) {
        navigator.share({ title: document.title, url: url }).catch(function () { /* cancelled */ });
      } else if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(function () { Lowbid.toast("Link copied.", "success"); });
      }
      return;
    }
    var clear = ev.target.closest("[data-search-clear]");
    if (clear) {
      var input = clear.parentElement && clear.parentElement.querySelector("input");
      if (input) { input.value = ""; if (input.form) input.form.requestSubmit ? input.form.requestSubmit() : input.form.submit(); }
      return;
    }
    document.querySelectorAll("details.ui-menu[open]").forEach(function (d) { if (!d.contains(ev.target)) d.removeAttribute("open"); });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") document.querySelectorAll("details.ui-menu[open]").forEach(function (d) { d.removeAttribute("open"); });
  });
  document.addEventListener("change", function (ev) {
    var el = ev.target.closest("[data-auto-submit]");
    if (el && el.form) { el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit(); }
  });
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-confirm") || form.dataset.confirmed === "1") return;
    ev.preventDefault();
    Lowbid.confirm({ message: form.getAttribute("data-confirm"), title: form.getAttribute("data-confirm-title") || "", danger: form.hasAttribute("data-confirm-danger") })
      .then(function (ok) { if (ok) { form.dataset.confirmed = "1"; form.requestSubmit ? form.requestSubmit() : form.submit(); } });
  });

  Lowbid.refreshUI(document);
})();
