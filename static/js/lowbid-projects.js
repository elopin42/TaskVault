/* Lowbid task board: shared helpers (tags, submit-once) + the project page (inline add-task,
   delete) + the task page (apply, candidates polling through Lowbid.poll, choose behind
   Lowbid.confirm, validate + rate → payment chain). Depends on lowbid-base.js + lowbid-ui.js and,
   for the payment chain, lowbid-pay.js (Lowbid.pay.runChain). Server-side values arrive through
   window.LOWBID_PROJECT (project_detail.html) and window.LOWBID_TASK (task_detail.html).

   Delegated actions (survive innerHTML swaps):
     [data-choose="<app_pk>"][data-choose-url]   company picks a candidate (project or task page)
     [data-task-delete="<task_pk>"]              company deletes an open task of a draft project
     [data-add-tag="x"][data-target="input-id"]  adds a suggested tag to the target input
   Forms: #task-form [data-task-add] · #apply-form [data-apply-submit] ·
          #validate-form[data-validate] [data-rate] radios + [data-validate-submit] (escrow panel).
   The deliver form (#deliver-form, #deliver-link) and the funding button ([data-fund]) are payment
   steps driven by lowbid-pay.js ([data-pay-step] / [data-fund]). */
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

  /* ---------- classic forms: one submission only (#project-form, profile name) ---------- */
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

  /* ---------- live "n / 3 compétences" helper under every tags input ---------- */
  document.querySelectorAll("[data-tags-help]").forEach(function (help) {
    var input = document.getElementById(help.getAttribute("data-tags-help"));
    if (!input) return;
    var base = help.innerHTML;
    function render() {
      var t = Lowbid.parseTags(input.value);
      if (!t.length) { help.innerHTML = base; help.classList.remove("ui-error"); return; }
      help.textContent = t.length + " / 3 compétence" + (t.length > 1 ? "s" : "") + " : " + t.join(", ");
      help.classList.toggle("ui-error", t.length > 3);
    }
    input.addEventListener("input", render);
  });

  function toastError(err, fallback) {
    var msg = (err && err.data && err.data.message) || (err && err.message) || fallback || "Action impossible.";
    if (err && err.status === 401) msg = "Connectez votre wallet pour continuer.";
    Lowbid.toast(msg, "error");
    return msg;
  }

  function fieldError(form, field, msg) {
    var el = form && form.querySelector('[data-error-for="' + field + '"]');
    if (!el) return false;
    el.textContent = msg || "";
    if (msg) el.removeAttribute("hidden"); else el.setAttribute("hidden", "");
    return true;
  }

  function clearErrors(form) {
    if (!form) return;
    form.querySelectorAll("[data-error-for]").forEach(function (el) { el.textContent = ""; el.setAttribute("hidden", ""); });
  }

  var setBusy = Lowbid.setBusy;

  /* ---------- delegated clicks: suggested tags, choose, delete ---------- */
  document.addEventListener("click", function (ev) {
    var chip = ev.target.closest("[data-add-tag]");
    if (chip) {
      var input = document.getElementById(chip.dataset.target || "apply-tags");
      if (!input) return;
      var tags = Lowbid.parseTags(input.value);
      if (tags.indexOf(chip.dataset.addTag) === -1 && tags.length < 3) tags.push(chip.dataset.addTag);
      input.value = tags.join(", ");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }

    var choose = ev.target.closest("[data-choose]");
    if (choose) {
      var url = choose.dataset.chooseUrl || (window.LOWBID_TASK && window.LOWBID_TASK.urls.choose.replace(/\/0\/$/, "/" + choose.dataset.choose + "/"));
      if (!url) return;
      Lowbid.confirm({
        title: "Choisir ce freelance ?",
        message: (choose.dataset.chooseLabel || "Ce candidat") + " sera chargé de la tâche. Les autres candidatures passeront en « Non retenu ».",
        confirmLabel: "Choisir", icon: "fa-user-check"
      }).then(function (ok) {
        if (!ok) return;
        setBusy(choose, true, "…");
        Lowbid.api(url, { method: "POST" }).then(function (data) {
          Lowbid.toast(data.message || "Freelance choisi.", "success", { title: "Choix" });
          setTimeout(function () { location.reload(); }, 500);
        }).catch(function (err) { setBusy(choose, false); toastError(err, "Choix impossible."); });
      });
      return;
    }

    var del = ev.target.closest("[data-task-delete]");
    if (del) {
      var cfgP = window.LOWBID_PROJECT;
      if (!cfgP) return;
      Lowbid.confirm({
        title: "Supprimer cette tâche ?",
        message: "« " + (del.dataset.taskTitle || "Tâche") + " » sera retirée du projet, avec ses candidatures.",
        confirmLabel: "Supprimer", cancelLabel: "Garder", danger: true
      }).then(function (ok) {
        if (!ok) return;
        setBusy(del, true, "…");
        Lowbid.api(cfgP.urls.deleteTask.replace(/\/0\/supprimer\/$/, "/" + del.dataset.taskDelete + "/supprimer/"), { method: "POST" }).then(function (data) {
          Lowbid.toast(data.message || "Tâche supprimée.", "success");
          setTimeout(function () { location.href = data.redirect || location.pathname; }, 400);
        }).catch(function (err) { setBusy(del, false); toastError(err, "Suppression impossible."); });
      });
    }
  });

  /* ---------- project page: inline add-task form ---------- */
  var project = window.LOWBID_PROJECT;
  var taskForm = document.getElementById("task-form");
  if (project && taskForm) {
    var TASK_FIELD = { invalid: "price", bad_tags: "tags" };
    var addingTask = false;
    taskForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (addingTask) return;
      clearErrors(taskForm);
      var title = document.getElementById("task-title"), price = document.getElementById("task-price");
      if (!title.value.trim()) { fieldError(taskForm, "title", "Donnez un titre à la tâche."); title.focus(); return; }
      if (!(parseFloat(price.value) > 0)) { fieldError(taskForm, "price", "Le prix doit être strictement positif."); price.focus(); return; }
      addingTask = true;
      var btn = taskForm.querySelector("[data-task-add]");
      setBusy(btn, true, "Ajout…");
      Lowbid.api(project.urls.addTask, {
        method: "POST",
        body: {
          title: title.value, description: document.getElementById("task-description").value,
          price: price.value, tags: Lowbid.parseTags(document.getElementById("task-tags").value)
        }
      }).then(function (data) {
        Lowbid.toast(data.message || "Tâche ajoutée.", "success", { title: "Tâche" });
        // Reload: the table, the KPI band and the total all change.
        setTimeout(function () { location.reload(); }, 350);
      }).catch(function (err) {
        addingTask = false;
        setBusy(btn, false);
        var code = err && err.data && err.data.error;
        var msg = toastError(err, "Tâche refusée.");
        var field = TASK_FIELD[code] || "_";
        if (code === "invalid" && /titre/i.test(msg)) field = "title";
        fieldError(taskForm, field, msg);
      });
    });
  }

  /* ---------- task page ---------- */
  var cfg = window.LOWBID_TASK;
  if (!cfg) return;

  var list = document.getElementById("candidates-list");

  /* ----- polling: swap the candidates when the server fingerprint changes ----- */
  var poller = null;
  function refresh() {
    return Lowbid.api(cfg.urls.candidates).then(function (data) {
      if (!data || !data.ok) return;
      if (data.status !== cfg.status) { location.reload(); return; }
      var dot = document.querySelector("[data-live-dot]"); if (dot) dot.removeAttribute("hidden");
      if (list && data.fingerprint !== list.dataset.fingerprint) {
        list.innerHTML = data.html;
        list.dataset.fingerprint = data.fingerprint;
        Lowbid.refreshUI(list);
        var count = document.querySelector("[data-kpi-count]"); if (count) count.textContent = String(data.count);
      }
    }).catch(function (err) {
      if (err && err.status === 404 && poller) { poller.stop(); }
      throw err; // Lowbid.poll backs off on errors
    });
  }
  if (cfg.status === "open") poller = Lowbid.poll(refresh, { interval: 5000, maxInterval: 60000 });

  /* ----- apply form ----- */
  var applyForm = document.getElementById("apply-form");
  if (applyForm) {
    var APPLY_FIELD = { bad_tags: "tags", invalid: "message" };
    var applying = false;
    applyForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (applying) return;
      clearErrors(applyForm);
      var tags = Lowbid.parseTags(document.getElementById("apply-tags").value);
      if (tags.length > 3) { fieldError(applyForm, "tags", "Au plus 3 compétences."); return; }
      applying = true;
      var btn = applyForm.querySelector("[data-apply-submit]");
      setBusy(btn, true, "Envoi…");
      Lowbid.api(cfg.urls.apply, { method: "POST", body: { message: document.getElementById("apply-message").value, tags: tags } }).then(function (data) {
        Lowbid.toast(data.message || "Candidature envoyée.", "success", { title: "Candidature" });
        setTimeout(function () { location.reload(); }, 500);
      }).catch(function (err) {
        applying = false;
        setBusy(btn, false);
        var code = err && err.data && err.data.error;
        var msg = toastError(err, "Candidature refusée.");
        fieldError(applyForm, APPLY_FIELD[code] || "_", msg);
        if (code === "wrong_state") setTimeout(function () { location.reload(); }, 1500);
      });
    });
  }

  /* ----- validate + rate form (company) → saves the Rating, then chains the payment signatures ----- */
  var validateForm = document.querySelector("form[data-validate]");
  if (validateForm) {
    var LABELS = { 1: "1/5 — insuffisant", 2: "2/5 — passable", 3: "3/5 — correct", 4: "4/5 — très bien", 5: "5/5 — excellent" };
    var help = validateForm.querySelector("[data-rate-help]");
    validateForm.querySelectorAll("[data-rate]").forEach(function (r) {
      r.addEventListener("change", function () { if (help) help.textContent = LABELS[r.value] || ""; });
    });
    var validating = false;
    var isDirect = (window.LOWBID && window.LOWBID.paymentMode) === "direct";

    /* After the rating is saved but a signature failed / was declined: swap the form for the pending
       step so the company can resume without a reload (the server keeps the same `next`). */
    function showResume(next, msg) {
      var panel = validateForm.closest("#validate-panel") || validateForm.parentNode;
      var box = document.createElement("div");
      box.innerHTML =
        '<div class="ui-alert ui-alert-ok mb-3"><i class="fa-solid fa-circle-check" aria-hidden="true"></i><span>Note enregistrée. ' +
        (next && next.mine ? "Il reste à signer « " + Lowbid.escapeHtml(next.label) + " » pour payer le freelance." : "") + "</span></div>" +
        (next && next.mine && next.prepare_url
          ? '<button type="button" class="ui-btn ui-btn-primary ui-btn-block" data-pay-step="' + Lowbid.escapeHtml(next.step) + '" data-prepare-url="' + Lowbid.escapeHtml(next.prepare_url) + '" data-loading-label="Signature…"><i class="fa-solid fa-money-bill-transfer" aria-hidden="true"></i> ' + Lowbid.escapeHtml(next.label) + "</button>"
          : "") +
        '<p class="ui-error mt-2" data-pay-error' + (msg ? "" : " hidden") + ">" + Lowbid.escapeHtml(msg || "") + "</p>";
      panel.replaceChild(box, validateForm);
    }

    validateForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (validating) return;
      clearErrors(validateForm);
      var checked = validateForm.querySelector("[data-rate]:checked");
      if (!checked) { fieldError(validateForm, "note", "Choisissez une note de 1 à 5."); return; }
      var note = parseInt(checked.value, 10);
      var btn = validateForm.querySelector("[data-validate-submit]");
      Lowbid.confirm({
        title: "Valider la livraison ?",
        message: "Note " + note + "/5. " + (isDirect
          ? "La note enregistrée, vous signez le paiement de la tâche dans Freighter."
          : "La note enregistrée, vous signez la validation puis la libération des fonds dans Freighter (deux signatures)."),
        confirmLabel: isDirect ? "Valider et payer" : "Valider et libérer", icon: "fa-circle-check"
      }).then(function (ok) {
        if (!ok) return;
        validating = true;
        setBusy(btn, true, "Validation…");
        var comment = document.getElementById("validate-comment");
        var url = validateForm.getAttribute("data-validate-url") || cfg.urls.validate;
        Lowbid.api(url, { method: "POST", body: { note: note, comment: comment ? comment.value : "" } }).then(function (data) {
          Lowbid.toast(data.message || "Tâche validée.", "success", { title: "Validation" });
          var next = data.next;
          if (!(next && next.mine && next.prepare_url && Lowbid.pay)) { setTimeout(function () { location.reload(); }, 500); return; }
          setBusy(btn, true, next.label + "…");
          return Lowbid.pay.runChain(next, {
            onStep: function (step) { setBusy(btn, true, step.label + "…"); }
          }).then(function () {
            setTimeout(function () { location.reload(); }, 700);
          }).catch(function (err) {
            validating = false;
            var pending = (err && err.pending) || next;
            var msg = err && err.handled ? "" : ((err && err.data && err.data.message) || (err && err.message) || "Signature impossible.");
            if (msg) Lowbid.toast(msg, "error", { title: "Paiement" });
            if (err && err.completed) { setTimeout(function () { location.reload(); }, 900); return; }
            showResume(pending, msg);
          });
        }).catch(function (err) {
          validating = false;
          setBusy(btn, false);
          var code = err && err.data && err.data.error;
          fieldError(validateForm, code === "invalid" ? "note" : "_", toastError(err, "Validation refusée."));
          if (code === "wrong_state" || code === "duplicate") setTimeout(function () { location.reload(); }, 1500);
        });
      });
    });
  }
})();
