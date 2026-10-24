/* Lowbid shared runtime: theme toggle, toasts, CSRF-aware fetch, small DOM helpers.
   Loaded on every page BEFORE the vendor bundles and lowbid-wallet.js. No template
   tags here — per-request values arrive through window.LOWBID (set in base.html). */
(function () {
  "use strict";

  var Lowbid = window.Lowbid || {};
  window.Lowbid = Lowbid;

  /* ---------- helpers ---------- */
  Lowbid.escapeHtml = function (s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  };

  Lowbid.csrf = function () {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  };

  Lowbid.shortAddr = function (addr, keep) {
    keep = keep || 4;
    addr = String(addr || "");
    return addr.length > keep * 2 + 1 ? addr.slice(0, keep) + "…" + addr.slice(-keep) : addr;
  };

  /* Lowbid.formatUsdc(value, code?) -> "1,234.50 USDC". Pass code = "" for the bare number
     (callers that render their own <span class="ui-price-unit">). */
  Lowbid.formatUsdc = function (value, code) {
    var n = Number(value);
    if (!isFinite(n)) return "—";
    var num = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (code === "") return num;
    return num + " " + (code || (window.LOWBID && window.LOWBID.usdc && window.LOWBID.usdc.code) || "USDC");
  };

  /* Lowbid.api(url, {method, body}) -> parsed JSON. Sends CSRF + JSON, marks itself
     as a fetch caller so wallet_required answers 401 JSON instead of a redirect.
     Rejects with an Error carrying .status and .data on non-2xx. */
  Lowbid.api = function (url, opts) {
    opts = opts || {};
    var method = (opts.method || "GET").toUpperCase();
    var headers = { "Accept": "application/json", "X-Requested-With": "fetch" };
    var body;
    if (method !== "GET" && method !== "HEAD") {
      headers["X-CSRFToken"] = Lowbid.csrf();
      if (opts.body !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(opts.body);
      }
    }
    return fetch(url, { method: method, headers: headers, body: body, credentials: "same-origin" }).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
        if (!res.ok) {
          var err = new Error((data && data.error) || ("HTTP " + res.status));
          err.status = res.status; err.data = data;
          throw err;
        }
        return data;
      });
    });
  };

  /* ---------- theme ---------- */
  Lowbid.toggleTheme = function () {
    var current = document.documentElement.getAttribute("data-theme") || "dark";
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("lowbid_theme", next); } catch (e) { /* private mode */ }
  };

  /* ---------- toasts ---------- */
  var ICONS = { success: "fa-circle-check", error: "fa-circle-xmark", warning: "fa-triangle-exclamation", info: "fa-circle-info" };
  var TITLES = { success: "Succès", error: "Erreur", warning: "Attention", info: "Info" };

  /* Lowbid.toast(message, type = "info", {title, duration = 4500}) — XSS-safe (textContent). */
  Lowbid.toast = function (message, type, opts) {
    type = ICONS[type] ? type : "info";
    opts = opts || {};
    var container = document.getElementById("lb-toasts");
    if (!container) return null;

    var toast = document.createElement("div");
    toast.className = "lb-toast";
    toast.setAttribute("data-type", type);
    toast.setAttribute("role", type === "error" ? "alert" : "status");

    var icon = document.createElement("div");
    icon.className = "lb-toast-icon";
    icon.innerHTML = '<i class="fa-solid ' + ICONS[type] + '" aria-hidden="true"></i>';

    var body = document.createElement("div");
    body.className = "lb-toast-body";
    var title = document.createElement("div");
    title.className = "lb-toast-title";
    title.textContent = opts.title || TITLES[type];
    var msg = document.createElement("div");
    msg.className = "lb-toast-message";
    msg.textContent = message || "";
    body.appendChild(title); body.appendChild(msg);

    var close = document.createElement("button");
    close.type = "button"; close.className = "lb-toast-close"; close.setAttribute("aria-label", "Fermer");
    close.innerHTML = '<i class="fa-solid fa-xmark" aria-hidden="true"></i>';

    function dismiss() {
      if (toast.classList.contains("is-leaving")) return;
      toast.classList.add("is-leaving");
      setTimeout(function () { toast.remove(); }, 260);
    }
    close.addEventListener("click", dismiss);

    toast.appendChild(icon); toast.appendChild(body); toast.appendChild(close);
    container.appendChild(toast);
    var duration = opts.duration === undefined ? 4500 : opts.duration;
    if (duration > 0) setTimeout(dismiss, duration);
    return { el: toast, dismiss: dismiss };
  };

  /* ---------- shell wiring ---------- */
  document.addEventListener("click", function (ev) {
    var t = ev.target.closest("[data-theme-toggle]");
    if (t) { Lowbid.toggleTheme(); return; }

    var nav = ev.target.closest("[data-nav-toggle]");
    if (nav) {
      var panel = document.getElementById(nav.getAttribute("aria-controls"));
      if (panel) {
        var open = panel.hasAttribute("hidden");
        if (open) panel.removeAttribute("hidden"); else panel.setAttribute("hidden", "");
        nav.setAttribute("aria-expanded", String(open));
      }
      return;
    }

    var copy = ev.target.closest("[data-copy]");
    if (copy && navigator.clipboard) {
      navigator.clipboard.writeText(copy.getAttribute("data-copy")).then(function () {
        Lowbid.toast("Adresse copiée dans le presse-papiers.", "success");
      }, function () {
        Lowbid.toast("Impossible de copier.", "error");
      });
    }

    // Close an open wallet <details> menu when clicking elsewhere.
    document.querySelectorAll("details.lb-wallet-menu[open]").forEach(function (d) {
      if (!d.contains(ev.target)) d.removeAttribute("open");
    });
  });
})();
