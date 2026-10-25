/* Lowbid trust network: follow / unfollow and recommend / withdraw on a wallet profile (#network-panel).
   Depends on lowbid-base.js (Lowbid.api, Lowbid.toast) + lowbid-ui.js (Lowbid.confirm, Lowbid.setBusy).
   Every handler is delegated on document (survives innerHTML swaps). Endpoints answer
   {ok, following, followers_count, recommendation: {message}|null, recommendations_count, message};
   a refusal is {ok:false, error, message} (HTTP 400/404, or 401 when no wallet is connected).

   DOM contract:
     [data-follow]                 button; data-follow-url, data-unfollow-url, data-following="1|0", data-name.
                                   Follow = .ui-btn.ui-btn-primary; Following = .ui-btn.is-following (JS swaps both).
     [data-followers-count]        text = followers count (updated in place)
     [data-following-count]        text = following count (server-rendered only)
     [data-recommendations-count]  text = received recommendations count (updated in place)
     [data-recommend]              button; toggles #recommend-form; data-recommended="1|0" (label Recommend / Edit recommendation)
     #recommend-form               form.ui-network-form, `hidden` when the viewer has no recommendation yet
     #recommend-message            textarea maxlength=280 (prefilled with the viewer's current message)
     [data-recommend-counter]      "n / 280" live counter (.is-near from 250, .is-over above 280)
     [data-recommend-submit]       submit button; data-recommend-url (POST {message})
     [data-unrecommend]            button; data-unrecommend-url; `hidden` when no recommendation (behind Lowbid.confirm)
   After a successful recommend / withdraw the counters and buttons update, then the page reloads so the
   #recommendations list refreshes.

   Reference profile markup (agent B2: copy, keep every id / data-attribute; `net` = profile_network(...)):

   <section id="network-panel" class="ui-panel ui-network-panel">
     <ul class="ui-network-counts">
       <li class="ui-network-count"><span class="ui-network-count-value" data-followers-count>{{ net.followers_count }}</span><span class="ui-network-count-label">Followers</span></li>
       <li class="ui-network-count"><span class="ui-network-count-value" data-following-count>{{ net.following_count }}</span><span class="ui-network-count-label">Following</span></li>
       <li class="ui-network-count"><span class="ui-network-count-value" data-recommendations-count>{{ net.recommendations_count }}</span><span class="ui-network-count-label">Recommendations</span></li>
     </ul>
     {% include "components/network_badges.html" with signal=net.signal %}
     {% if net.known_followers %}<p class="ui-network-known" data-known-followers>Followed by {{ net.known_followers|length }} people you follow: <strong>{{ net.known_followers|join:", " }}</strong></p>{% endif %}
     {% if net.can_act %}
     <div class="ui-network-actions">
       <button type="button" class="ui-btn {% if net.viewer_follows %}is-following{% else %}ui-btn-primary{% endif %}" data-follow
               data-follow-url="{% url 'network:follow' profile.stellar_address %}" data-unfollow-url="{% url 'network:unfollow' profile.stellar_address %}"
               data-following="{{ net.viewer_follows|yesno:'1,0' }}" data-name="{{ profile }}" aria-pressed="{{ net.viewer_follows|yesno:'true,false' }}">
         {% if net.viewer_follows %}<i class="fa-solid fa-check" aria-hidden="true"></i> Following{% else %}<i class="fa-solid fa-user-plus" aria-hidden="true"></i> Follow{% endif %}
       </button>
       <button type="button" class="ui-btn" data-recommend data-recommended="{{ net.viewer_recommendation|yesno:'1,0' }}" aria-controls="recommend-form" aria-expanded="false">
         <i class="fa-solid fa-user-group" aria-hidden="true"></i> {% if net.viewer_recommendation %}Edit recommendation{% else %}Recommend{% endif %}
       </button>
       <button type="button" class="ui-btn ui-btn-ghost" data-unrecommend data-unrecommend-url="{% url 'network:unrecommend' profile.stellar_address %}" data-name="{{ profile }}"{% if not net.viewer_recommendation %} hidden{% endif %}>Withdraw</button>
     </div>
     <form id="recommend-form" class="ui-network-form" hidden>
       <label class="ui-label" for="recommend-message">Your recommendation (optional)</label>
       <textarea id="recommend-message" class="ui-textarea" maxlength="280" placeholder="What did they do well?">{{ net.viewer_recommendation.message|default:"" }}</textarea>
       <div class="ui-network-form-foot">
         <span class="ui-network-counter" data-recommend-counter>0 / 280</span>
         <button type="submit" class="ui-btn ui-btn-primary" data-recommend-submit data-recommend-url="{% url 'network:recommend' profile.stellar_address %}">Publish</button>
       </div>
     </form>
     {% endif %}
     <ol id="recommendations" class="ui-timeline"> … one .ui-timeline-item per recommendation (author wallet chip, .ui-network-quote message, [data-time-ago]) … </ol>
   </section>
*/
(function () {
  "use strict";

  var Lowbid = window.Lowbid || (window.Lowbid = {});
  var MAX = 280;
  var ICON = { follow: "fa-user-plus", following: "fa-check", recommend: "fa-user-group" };

  function setBusy(btn, on, label) {
    if (typeof Lowbid.setBusy === "function") Lowbid.setBusy(btn, on, label);
    else if (btn) btn.disabled = !!on;
  }

  function setLabel(btn, icon, text) {
    btn.innerHTML = '<i class="fa-solid ' + icon + '" aria-hidden="true"></i> ' + Lowbid.escapeHtml(text);
  }

  function setText(selector, value) {
    if (value === undefined || value === null) return;
    document.querySelectorAll(selector).forEach(function (el) { el.textContent = String(value); });
  }

  function refused(res) {
    Lowbid.toast((res && res.message) || "Action refused", "error");
  }

  function toastError(err) {
    if (err && err.status === 401) { Lowbid.toast("Connect your wallet to continue.", "error"); return; }
    refused(err && err.data);
  }

  function reloadSoon() { setTimeout(function () { location.reload(); }, 700); }

  /* ---------- follow toggle ---------- */
  function renderFollow(btn, following) {
    btn.dataset.following = following ? "1" : "0";
    btn.setAttribute("aria-pressed", following ? "true" : "false");
    btn.classList.toggle("is-following", following);
    btn.classList.toggle("ui-btn-primary", !following);
    btn.dataset.url = following ? (btn.dataset.unfollowUrl || "") : (btn.dataset.followUrl || "");
    setLabel(btn, following ? ICON.following : ICON.follow, following ? "Following" : "Follow");
  }

  function toggleFollow(btn) {
    var following = btn.dataset.following === "1";
    var url = following ? btn.dataset.unfollowUrl : btn.dataset.followUrl;
    url = url || btn.dataset.url;
    if (!url) return;
    setBusy(btn, true, "…");
    Lowbid.api(url, { method: "POST" }).then(function (res) {
      setBusy(btn, false);
      if (!res || res.ok === false) { refused(res); return; }
      var now = typeof res.following === "boolean" ? res.following : !following;
      document.querySelectorAll("[data-follow]").forEach(function (b) { renderFollow(b, now); });
      setText("[data-followers-count]", res.followers_count);
      var name = btn.dataset.name || "this wallet";
      Lowbid.toast(res.message || (now ? "Following " + name + "." : "You no longer follow " + name + "."), "success");
    }).catch(function (err) { setBusy(btn, false); toastError(err); });
  }

  /* ---------- recommend form ---------- */
  function form() { return document.getElementById("recommend-form"); }
  function textarea() { return document.getElementById("recommend-message"); }

  function renderCounter() {
    var ta = textarea();
    if (!ta) return;
    var n = ta.value.length;
    document.querySelectorAll("[data-recommend-counter]").forEach(function (el) {
      el.textContent = n + " / " + MAX;
      el.classList.toggle("is-near", n >= MAX - 30 && n <= MAX);
      el.classList.toggle("is-over", n > MAX);
    });
    ta.setAttribute("aria-invalid", n > MAX ? "true" : "false");
  }

  function renderRecommended(recommended) {
    document.querySelectorAll("[data-recommend]").forEach(function (b) {
      b.dataset.recommended = recommended ? "1" : "0";
      setLabel(b, ICON.recommend, recommended ? "Edit recommendation" : "Recommend");
    });
    document.querySelectorAll("[data-unrecommend]").forEach(function (b) {
      if (recommended) b.removeAttribute("hidden"); else b.setAttribute("hidden", "");
    });
  }

  function toggleForm(btn) {
    var f = form();
    if (!f) return;
    var open = f.hasAttribute("hidden");
    if (open) f.removeAttribute("hidden"); else f.setAttribute("hidden", "");
    document.querySelectorAll("[data-recommend]").forEach(function (b) { b.setAttribute("aria-expanded", open ? "true" : "false"); });
    if (open) {
      renderCounter();
      var ta = textarea();
      if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
    } else if (btn) {
      btn.focus();
    }
  }

  function submitRecommend(btn) {
    var f = form();
    btn = btn || (f && f.querySelector("[data-recommend-submit]")) || document.querySelector("[data-recommend-submit]");
    if (!btn || btn.disabled) return;
    var url = btn.dataset.recommendUrl || (f && f.dataset.recommendUrl);
    if (!url) return;
    var ta = textarea();
    var message = ta ? ta.value.trim() : "";
    if (message.length > MAX) {
      Lowbid.toast("Keep it under " + MAX + " characters.", "error");
      if (ta) ta.focus();
      return;
    }
    setBusy(btn, true, "Publishing…");
    Lowbid.api(url, { method: "POST", body: { message: message } }).then(function (res) {
      if (!res || res.ok === false) { setBusy(btn, false); refused(res); return; }
      setText("[data-recommendations-count]", res.recommendations_count);
      renderRecommended(true);
      Lowbid.toast(res.message || "Recommendation published.", "success");
      reloadSoon();
    }).catch(function (err) { setBusy(btn, false); toastError(err); });
  }

  function unrecommend(btn) {
    var url = btn.dataset.unrecommendUrl;
    if (!url) return;
    Lowbid.confirm({
      title: "Withdraw your recommendation?",
      message: "Your recommendation of " + (btn.dataset.name || "this wallet") + " will be removed from their profile.",
      confirmLabel: "Withdraw", cancelLabel: "Keep", danger: true
    }).then(function (ok) {
      if (!ok) return;
      setBusy(btn, true, "…");
      Lowbid.api(url, { method: "POST" }).then(function (res) {
        if (!res || res.ok === false) { setBusy(btn, false); refused(res); return; }
        setBusy(btn, false);
        setText("[data-recommendations-count]", res.recommendations_count);
        renderRecommended(false);
        var f = form(), ta = textarea();
        if (ta) ta.value = "";
        if (f) f.setAttribute("hidden", "");
        renderCounter();
        Lowbid.toast(res.message || "Recommendation withdrawn.", "success");
        reloadSoon();
      }).catch(function (err) { setBusy(btn, false); toastError(err); });
    });
  }

  /* ---------- delegation ---------- */
  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!(t instanceof Element)) return;
    var el = t.closest("[data-follow]");
    if (el) { ev.preventDefault(); toggleFollow(el); return; }
    el = t.closest("[data-recommend-submit]");
    if (el) { ev.preventDefault(); submitRecommend(el); return; }
    el = t.closest("[data-unrecommend]");
    if (el) { ev.preventDefault(); unrecommend(el); return; }
    el = t.closest("[data-recommend]");
    if (el) { ev.preventDefault(); toggleForm(el); }
  });

  // Enter in a field / implicit submission of #recommend-form goes through the same path (never a page POST).
  document.addEventListener("submit", function (ev) {
    if (ev.target && ev.target.id === "recommend-form") { ev.preventDefault(); submitRecommend(null); }
  });

  document.addEventListener("input", function (ev) {
    if (ev.target && ev.target.id === "recommend-message") renderCounter();
  });

  renderCounter();
})();
