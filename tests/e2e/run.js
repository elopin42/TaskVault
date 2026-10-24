#!/usr/bin/env node
/* Lowbid end-to-end run — the whole user flow with a simulated Freighter (fake-freighter.js).
 *
 *   make e2e                      # fresh SQLite, runserver on a free port, this script, teardown
 *   E2E_BASE_URL=http://127.0.0.1:8000 node tests/e2e/run.js   # against a server you started
 *
 * Plain `playwright` library API (no @playwright/test). Three browser contexts (client, freelance1,
 * freelance2) at 1280x800, the key screens re-checked at 390x844. Screenshots land in
 * docs/screenshots/. Exit code 1 on the first failing step, on any unexpected console error or
 * uncaught page error. Nothing here reaches Horizon / Trustless Work: the only network step
 * exercised is the client's "Payer" button, which must fail gracefully (French message, no 500).
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const REPO = path.resolve(__dirname, "..", "..");
const StellarSdk = require(path.join(REPO, "node_modules", "@stellar", "stellar-sdk"));
const { installFakeFreighter } = require("./fake-freighter");

const BASE = (process.env.E2E_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const PASSPHRASE = "Test SDF Network ; September 2015";
const SHOTS = path.join(REPO, "docs", "screenshots");
const DESKTOP = { width: 1280, height: 800 };
const MOBILE = { width: 390, height: 844 };
const HEADLESS = !process.env.E2E_HEADED;

// --- tiny runner ---------------------------------------------------------------------------

const results = [];
function log(msg) { process.stdout.write(msg + "\n"); }
function assert(cond, msg) { if (!cond) throw new Error("Assertion failed: " + msg); }
async function step(name, fn) {
  const t0 = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - t0 });
    log(`PASS  ${name}  (${Date.now() - t0} ms)`);
  } catch (err) {
    results.push({ name, ok: false, ms: Date.now() - t0, error: err });
    log(`FAIL  ${name}: ${err && err.message}`);
    throw err;
  }
}

// --- console / page error collection ---------------------------------------------------------

const consoleErrors = []; // {who, text, source}
function isExpectedError(e) {
  // Horizon is unreachable from the sandbox: the balance watcher fails (3 times, then stops).
  if (/horizon/i.test(e.source) || /horizon/i.test(e.text)) return true;
  if (/ERR_TUNNEL_CONNECTION_FAILED|ERR_NAME_NOT_RESOLVED|ERR_CONNECTION_REFUSED|ERR_PROXY/.test(e.text) && !e.source.startsWith(BASE)) return true;
  // Business refusals are real 4xx answers from our own API (not_lower, forbidden, own_need …).
  if (/Failed to load resource: the server responded with a status of (400|401|403|404|409)/.test(e.text) && e.source.startsWith(BASE)) return true;
  return false;
}
function track(page, who) {
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const loc = m.location() || {};
    consoleErrors.push({ who, text: m.text(), source: loc.url || "" });
  });
  page.on("pageerror", (err) => consoleErrors.push({ who, text: "pageerror: " + (err && err.message), source: "page" }));
  page.on("dialog", (d) => d.accept());
  return page;
}

// --- actors / contexts ------------------------------------------------------------------------

function short(addr) { return addr.slice(0, 4) + "…" + addr.slice(-4); }
function actor(name) {
  const kp = StellarSdk.Keypair.random();
  return { name, secret: kp.secret(), address: kp.publicKey(), short: short(kp.publicKey()) };
}
async function newContext(browser, who, viewport, extra) {
  const ctx = await browser.newContext(Object.assign({ viewport, baseURL: BASE, locale: "fr-FR", timezoneId: "Europe/Paris" }, extra || {}));
  if (who) await ctx.addInitScript(installFakeFreighter, { secret: who.secret, address: who.address, passphrase: PASSPHRASE });
  ctx.setDefaultTimeout(10000);
  return ctx;
}
async function mobileClone(browser, ctx, who) {
  const state = await ctx.storageState();
  return newContext(browser, who, MOBILE, { storageState: state, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
}

// --- page helpers -----------------------------------------------------------------------------

async function csrf(page) {
  const cookies = await page.context().cookies(BASE);
  return (cookies.find((c) => c.name === "csrftoken") || {}).value || "";
}
/* JSON call as the page's wallet (same cookies). Returns {status, json}. */
async function api(page, url, body, method) {
  const res = await page.request.fetch(BASE + url, {
    method: method || "POST",
    data: body === undefined ? undefined : JSON.stringify(body),
    headers: { "Content-Type": "application/json", "X-CSRFToken": await csrf(page), "X-Requested-With": "fetch", Accept: "application/json", Referer: BASE + "/" },
  });
  let json = null;
  try { json = await res.json(); } catch (e) { json = null; }
  return { status: res.status(), json };
}
/* No leaked Django syntax ("{#", "{%", "{{") and no mojibake in the visible text. */
async function pageSane(page, label) {
  const text = await page.evaluate(() => document.body.innerText);
  const leak = text.match(/\{[#%{]|[#%}]\}/);
  assert(!leak, `${label}: template syntax leaked into the page near "${leak && text.slice(Math.max(0, leak.index - 30), leak.index + 40)}"`);
  const moji = text.match(/Ã.|â€./);
  assert(!moji, `${label}: mojibake "${moji && moji[0]}" in the page text`);
}
async function noHorizontalScroll(page, label) {
  await pageSane(page, label);
  const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth, bw: document.body.scrollWidth }));
  assert(m.sw <= m.iw && m.bw <= m.iw, `${label}: horizontal overflow (scrollWidth ${m.sw}/${m.bw} > innerWidth ${m.iw})`);
}
async function shot(page, name, opts) {
  await pageSane(page, "screenshot " + name);
  await page.waitForTimeout(250); // let countdowns / fonts settle
  await page.screenshot(Object.assign({ path: path.join(SHOTS, name + ".png"), fullPage: true }, opts || {}));
}
async function connect(page, who, selector) {
  await page.locator(selector || ".lb-nav [data-wallet-connect]").first().click();
  const btn = page.locator(".lb-wallet-btn.is-connected");
  await btn.waitFor({ state: "visible", timeout: 20000 });
  const text = (await btn.innerText()).trim();
  assert(text.includes(who.short), `navbar shows ${who.short}, got "${text}"`);
  const calls = await page.evaluate(() => (window.__fakeFreighter ? window.__fakeFreighter.calls.map((c) => c.name) : []));
  // The session cookie is what matters; the fake's call log is a bonus sanity check on the flow.
  if (calls.length) assert(calls.includes("signMessage"), `login used signMessage (calls: ${calls.join(",")})`);
}
async function postNeed(page, need) {
  await page.goto("/besoins/nouveau/" + (need.demo ? "?demo=1" : ""));
  await page.fill("#id_title", need.title);
  await page.fill("#id_description", need.description);
  await page.fill("#id_budget_max", String(need.budget));
  await page.fill("#id_delay_max_days", String(need.delay));
  await page.fill("#id_tags", need.tags);
  if (need.duration) await page.selectOption("#id_duration", need.duration);
  await Promise.all([page.waitForURL(/\/besoins\/\d+\/$/), page.click("#need-form button[type=submit]")]);
  return Number(page.url().match(/\/besoins\/(\d+)\//)[1]);
}
async function bidUI(page, needId, bid) {
  await page.goto(`/besoins/${needId}/`);
  await page.fill("#bid-price", String(bid.price));
  await page.fill("#bid-delay", String(bid.delay));
  await page.fill("#bid-tags", bid.tags);
  if (bid.message) await page.fill("#bid-message", bid.message);
  await page.click("[data-bid-submit]");
}
function usdc(n) { return Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " USDC"; }

async function waitForServer() {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(BASE + "/healthz/");
      if (res.ok) return;
    } catch (e) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`server not reachable at ${BASE}/healthz/ after 30 s`);
}

// --- the scenario ------------------------------------------------------------------------------

const EXTRA_NEEDS = [
  { title: "Refonte du site vitrine d’une boulangerie", description: "Site vitrine 5 pages (accueil, nos pains, pâtisseries, commandes, contact) avec horaires et carte. Charte fournie, photos à retoucher légèrement, hébergement déjà en place.", budget: 900, delay: 21, tags: "wordpress, design, seo", duration: "120", bids: [["f1", 820, 18, ["wordpress", "seo"], "Thème sur mesure, optimisation Core Web Vitals incluse."], ["f2", 780, 20, ["design"], "Maquettes Figma puis intégration, 2 allers-retours."]] },
  { title: "Intégration paiement USDC sur une app Django", description: "Ajouter un paiement USDC (Stellar) au tunnel de commande existant : trustline, signature Freighter, webhook de confirmation, page de reçu. Tests inclus.", budget: 1200, delay: 14, tags: "django, stellar, api", duration: "120", bids: [["f2", 1100, 12, ["django", "stellar"], "J’ai déjà branché Horizon et Freighter sur un back-office Django."], ["f1", 990, 14, ["django", "api"], "Backend + tests, front minimal."]] },
  { title: "Application mobile de réservation pour un salon de coiffure", description: "Prise de rendez-vous, rappels SMS, gestion des créneaux par coiffeur, paiement d’acompte. iOS + Android, publication sur les stores comprise.", budget: 2500, delay: 30, tags: "flutter, firebase, ui", duration: "1440", bids: [["f1", 2300, 28, ["flutter", "firebase"], "Flutter + Firebase, livraison store-ready."]] },
  { title: "Migration d’une boutique PrestaShop vers Shopify", description: "1 200 produits, 3 langues, redirections SEO, thème équivalent. Import clients et historique de commandes.", budget: 1500, delay: 20, tags: "shopify, liquid, seo", duration: "4320", bids: [] },
];

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  await waitForServer();
  const browser = await chromium.launch({ headless: HEADLESS });

  const client = actor("client");
  const f1 = actor("freelance1");
  const f2 = actor("freelance2");
  const ctx = {
    client: await newContext(browser, client, DESKTOP),
    f1: await newContext(browser, f1, DESKTOP),
    f2: await newContext(browser, f2, DESKTOP),
    anon: await newContext(browser, null, DESKTOP),
  };
  const cp = track(await ctx.client.newPage(), "client");
  const p1 = track(await ctx.f1.newPage(), "freelance1");
  const p2 = track(await ctx.f2.newPage(), "freelance2");
  const pa = track(await ctx.anon.newPage(), "anon");
  const bidder = { f1: p1, f2: p2 };
  let needId = null;
  let winner = null;
  let loser = null;

  try {
    // 1 ------------------------------------------------------------------------------------------
    await step("1. landing renders, Freighter login round-trip, navbar shows G…XXXX", async () => {
      await cp.goto("/");
      assert((await cp.title()).includes("Lowbid"), "title contains Lowbid");
      await cp.locator(".lb-hero-title").waitFor();
      assert(await cp.locator(".lb-hero [data-wallet-connect]").count() === 1, "hero has the connect button");
      await connect(cp, client, ".lb-hero [data-wallet-connect]");
      assert(new URL(cp.url()).pathname === "/", "stays on the landing after connect");
      assert((await cp.locator(".lb-hero a.ui-btn-primary").innerText()).includes("Poster un besoin"), "hero CTA switches to Poster un besoin");
    });

    await step("1b. ?next= after connect (wallet_required redirect) and off-site next dropped", async () => {
      await p1.goto("/mes-encheres/");
      assert(new URL(p1.url()).pathname === "/" && new URL(p1.url()).searchParams.get("next") === "/mes-encheres/", `redirected to /?next=…, got ${p1.url()}`);
      await p1.locator(".lb-hero .ui-alert", { hasText: "/mes-encheres/" }).waitFor();
      await connect(p1, f1, ".lb-hero [data-wallet-connect]");
      await p1.waitForURL(/\/mes-encheres\/$/);
      await p1.locator(".empty-state-title", { hasText: "Aucune enchère" }).waitFor();

      await p2.goto("/?next=https://evil.example/");
      assert(await p2.locator(".lb-hero .ui-alert").count() === 0, "off-site next is not advertised");
      await connect(p2, f2, ".lb-hero [data-wallet-connect]");
      await p2.waitForTimeout(600);
      assert(p2.url().startsWith(BASE + "/"), `stayed on ${BASE}, got ${p2.url()}`);
    });

    // 2 ------------------------------------------------------------------------------------------
    await step("2. client posts the need (500 USDC, 10 j, django/stellar/ui, démo 5 min)", async () => {
      needId = await postNeed(cp, {
        title: "Landing page Django + paiement Stellar",
        description: "Une landing page pour notre PME (12 salariés) : présentation, formulaire de contact et un bouton de paiement USDC via Freighter. Maquette fournie, déploiement sur notre VPS.",
        budget: 500, delay: 10, tags: "django, stellar, ui", duration: "5", demo: true,
      });
      await cp.locator(".ui-alert-ok", { hasText: "Besoin publié" }).waitFor();
      assert((await cp.locator("[data-status-badge]").innerText()).trim() === "Ouvert", "status Ouvert");
      assert(await cp.locator("#bid-form").count() === 0, "client has no bid form on their own need");
      await cp.locator("[data-countdown-main]", { hasText: /^0[0-4]:[0-5]\d$/ }).waitFor();
    });

    await step("2b. extra needs + bids (realistic list for the screenshots)", async () => {
      for (const n of EXTRA_NEEDS) {
        n.id = await postNeed(cp, n);
        for (const [who, price, delay, tags, message] of n.bids) {
          const r = await api(bidder[who], `/besoins/${n.id}/encherir/`, { price, delay_days: delay, tags, message });
          assert(r.status === 201, `${who} bid ${price} on #${n.id}: HTTP ${r.status} ${JSON.stringify(r.json)}`);
        }
      }
      await cp.goto(`/besoins/${needId}/`); // the client watches their need from now on (polling)
    });

    // 3 ------------------------------------------------------------------------------------------
    let clientNavs = 0;
    cp.on("framenavigated", (f) => { if (f === cp.mainFrame()) clientNavs++; });

    await step("3. descending bids: 450 → 420 → 430 refused (not_lower) → 400 replaces", async () => {
      await bidUI(p1, needId, { price: 450, delay: 8, tags: "django, stellar", message: "Django + Tailwind, déploiement compris." });
      await p1.locator("#bid-form-panel .ui-panel-sub", { hasText: `Votre offre actuelle : ${usdc(450)}` }).waitFor();
      assert((await p1.locator("#bid-form-panel .ui-panel-title").innerText()).includes("Améliorer mon offre"), "panel title switches to Améliorer mon offre");

      await bidUI(p2, needId, { price: 420, delay: 9, tags: "ui", message: "Spécialiste UI, intégration Freighter incluse." });
      await p2.locator("#bid-form-panel .ui-panel-sub", { hasText: `Votre offre actuelle : ${usdc(420)}` }).waitFor();

      // Server-side rule R1 through the API (deterministic, regardless of polling timing).
      const refused = await api(p1, `/besoins/${needId}/encherir/`, { price: 430, delay_days: 8, tags: ["django", "stellar"] });
      assert(refused.status === 400 && refused.json.error === "not_lower", `430 refused with not_lower, got ${refused.status} ${JSON.stringify(refused.json)}`);
      assert(/strictement inférieur à 420 USDC/.test(refused.json.message), `French not_lower message, got "${refused.json.message}"`);

      // Same attempt through the form: the message lands under the price field (client or server side).
      await p1.goto(`/besoins/${needId}/`);
      assert((await p1.locator("[data-price-cap]").innerText()).trim() === usdc(420), "price hint shows the current best (420) after refresh");
      assert((await p1.locator("#bid-price").getAttribute("max")) === "420", "input max is the plain decimal 420");
      await p1.fill("#bid-price", "430"); await p1.fill("#bid-delay", "8"); await p1.fill("#bid-tags", "django, stellar");
      await p1.click("[data-bid-submit]");
      const err = p1.locator('[data-error-for="price"]:not([hidden])');
      await err.waitFor();
      assert(/inférieur à 420/.test(await err.innerText()), `price error mentions 420, got "${await err.innerText()}"`);
      assert(!(await p1.locator("[data-bid-submit]").isDisabled()), "submit button re-enabled after a refusal");

      await p1.fill("#bid-price", "400");
      await p1.click("[data-bid-submit]");
      await p1.locator("#bid-form-panel .ui-panel-sub", { hasText: `Votre offre actuelle : ${usdc(400)}` }).waitFor();
      assert(await p1.locator(".bid-row").count() === 2, "f1's 450 was replaced, 2 rows remain");
      assert(await p1.locator(".bid-row", { hasText: "450.00" }).count() === 0, "the superseded 450 is gone");
    });

    await step("3b. client's page updates by polling (2 bids, Meilleur prix on 400, no reload)", async () => {
      const t0 = Date.now();
      await cp.locator('[data-bids][data-count="2"]').waitFor({ timeout: 8000 });
      await cp.locator(".bid-row", { hasText: "400.00" }).locator(".ui-badge", { hasText: "Meilleur prix" }).waitFor({ timeout: 8000 });
      const elapsed = Date.now() - t0;
      assert(clientNavs === 0, `no navigation on the client page (saw ${clientNavs})`);
      assert((await cp.locator("[data-kpi-count]").innerText()).trim() === "2", "KPI count = 2");
      const bestTile = (await cp.locator("[data-kpi-best]").innerText()).replace(/\s+/g, " ").trim();
      assert(bestTile.startsWith("400.00"), `KPI best = 400.00 (got "${bestTile}")`);
      assert((bestTile.match(/USDC/g) || []).length === 1, `KPI best tile has exactly one USDC unit (got "${bestTile}")`);
      assert(await cp.locator("[data-live-dot]:not([hidden])").count() === 1, "live dot shown");
      log(`      polling delivered the list in ${elapsed} ms`);
    });

    await step("3c. screenshots: enchères ouvertes (desktop + mobile), liste, landing", async () => {
      await p1.goto(`/besoins/${needId}/`);
      await p1.locator('[data-bids][data-count="2"]').waitFor();
      await shot(p1, "04-detail-encheres-ouvertes");
      await noHorizontalScroll(p1, "desktop detail open");
      const m1 = await mobileClone(browser, ctx.f1, f1);
      const mp = track(await m1.newPage(), "mobile f1");
      await mp.goto(`/besoins/${needId}/`);
      await mp.locator('[data-bids][data-count="2"]').waitFor();
      await noHorizontalScroll(mp, "mobile detail open");
      await shot(mp, "09-mobile");
      await mp.goto("/besoins/");
      await noHorizontalScroll(mp, "mobile liste");
      await shot(mp, "10-mobile-liste");
      await mp.goto("/besoins/nouveau/");
      await noHorizontalScroll(mp, "mobile formulaire");
      await shot(mp, "mobile-poster-besoin");
      // mobile menu opens and closes
      await mp.click("[data-nav-toggle]");
      assert(await mp.locator("#lb-mobile-nav:not([hidden])").count() === 1, "mobile nav opens");
      await mp.click("[data-nav-toggle]");
      assert(await mp.locator("#lb-mobile-nav[hidden]").count() === 1, "mobile nav closes");
      await m1.close();

      await cp.bringToFront();
      const lp = track(await ctx.client.newPage(), "client-list");
      await lp.goto("/besoins/nouveau/?demo=1");
      await lp.fill("#id_title", "Refonte du site vitrine d’une boulangerie");
      await lp.fill("#id_description", "Site vitrine 5 pages avec horaires, carte et formulaire de commande. Charte fournie.");
      await lp.fill("#id_budget_max", "9"); await lp.fill("#id_delay_max_days", "21"); await lp.fill("#id_tags", "wordpress, design, seo");
      await lp.locator("[data-tags-help]", { hasText: "3 / 3 compétences" }).waitFor();
      await shot(lp, "03-poster-besoin");
      await noHorizontalScroll(lp, "desktop formulaire");
      await lp.goto("/besoins/");
      assert(await lp.locator(".need-card").count() >= 5, "list shows the 5 open needs");
      await shot(lp, "02-liste-besoins");
      await noHorizontalScroll(lp, "desktop liste");
      await lp.close();

      await pa.goto("/");
      await pa.locator(".need-card").first().waitFor();
      await shot(pa, "01-landing");
      await noHorizontalScroll(pa, "desktop landing");
      const ma = await newContext(browser, null, MOBILE, { isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
      const map = track(await ma.newPage(), "mobile anon");
      await map.goto("/");
      await noHorizontalScroll(map, "mobile landing");
      await shot(map, "mobile-landing");
      await map.goto(`/besoins/${needId}/`);
      await noHorizontalScroll(map, "mobile detail anon");
      assert(await map.locator("[data-wallet-connect][data-next]").count() >= 1, "anonymous detail offers connect with next");
      await ma.close();
    });

    // 4 ------------------------------------------------------------------------------------------
    await step("4. client cannot bid on own need; freelance cannot close", async () => {
      assert(await cp.locator("#bid-form").count() === 0, "no bid form for the client");
      const own = await api(cp, `/besoins/${needId}/encherir/`, { price: 300, delay_days: 5, tags: ["django"] });
      assert(own.status === 400 && own.json.error === "own_need", `own_need refused, got ${own.status} ${JSON.stringify(own.json)}`);
      assert(await p1.locator("[data-need-close]").count() === 0, "no close button for a freelance");
      const close = await api(p1, `/besoins/${needId}/cloturer/`, {});
      assert(close.status === 403 && close.json.error === "forbidden", `close forbidden for a freelance, got ${close.status}`);
      const anon = await api(pa, `/besoins/${needId}/encherir/`, { price: 300, delay_days: 5, tags: [] });
      assert(anon.status === 401 && anon.json.error === "wallet_required", `anonymous bid → 401 wallet_required, got ${anon.status}`);
    });

    // 5 ------------------------------------------------------------------------------------------
    await step("5. client closes bidding → Terminé, Recommandé on the best score, 3 sliders", async () => {
      await cp.locator("[data-need-close]").first().click(); // confirm() auto-accepted
      await cp.locator("[data-status-badge]", { hasText: "Terminé" }).waitFor({ timeout: 15000 });
      assert((await cp.locator("[data-countdown-main]").innerText()).trim() === "Terminé", "countdown reads Terminé");
      assert(await cp.locator("[data-weight]").count() === 3, "3 sliders");
      const rec = cp.locator("[data-recommended]:not([hidden])");
      assert(await rec.count() === 1, "exactly one Recommandé badge");
      const recRow = cp.locator(".bid-row:has([data-recommended]:not([hidden]))");
      assert((await recRow.innerText()).includes("400.00"), "the recommended bid is the 400 (score 34.0 vs 19.4)");
      assert((await recRow.locator("[data-score]").innerText()).trim() === "34.0", "score 34.0 at 40/30/30");
      assert(await cp.locator("[data-choose]").count() === 2, "a Choisir button on EVERY bid row");
      await shot(cp, "05-detail-cloture-sliders");
      await noHorizontalScroll(cp, "desktop detail closed");
      const mc = await mobileClone(browser, ctx.client, client);
      const mcp = track(await mc.newPage(), "mobile client");
      await mcp.goto(`/besoins/${needId}/`);
      await mcp.locator("[data-weight]").first().waitFor();
      await noHorizontalScroll(mcp, "mobile detail closed");
      await shot(mcp, "mobile-detail-cloture-sliders");
      await mc.close();
    });

    await step("5b. sliders: 70/10/20 re-scores client-side, sum stays 100; server honours ?wp=&wd=&ws=", async () => {
      const before = await cp.locator("[data-score]").allInnerTexts();
      async function slide(i, v) {
        await cp.locator(`[data-weight="${i}"]`).evaluate((el, value) => { el.value = String(value); el.dispatchEvent(new Event("input", { bubbles: true })); }, v);
      }
      await slide(2, 20); await slide(1, 10); await slide(0, 70);
      const outs = (await cp.locator("[data-weight-out]").allInnerTexts()).map(Number);
      assert(outs.reduce((a, b) => a + b, 0) === 100, `weights sum to 100 (${outs.join("/")})`);
      assert(outs[0] === 70, `price weight is 70 (${outs.join("/")})`);
      const after = await cp.locator("[data-score]").allInnerTexts();
      assert(after.join() !== before.join(), `scores update (${before.join()} → ${after.join()})`);
      assert(await cp.locator("[data-recommended]:not([hidden])").count() === 1, "still one Recommandé badge");
      assert(new URL(cp.url()).searchParams.get("wp") === "70", "URL carries wp=70 (shareable weights)");
      await cp.goto(`/besoins/${needId}/?wp=70&wd=10&ws=20`);
      assert((await cp.locator("[data-weight-out]").allInnerTexts()).join("/") === "70/10/20", "server renders 70/10/20");
      assert((await cp.locator(".bid-row", { hasText: "400.00" }).locator("[data-score]").innerText()).trim() === "29.3", "400 scores 29.3 at 70/10/20");
      assert((await cp.locator(".bid-row", { hasText: "420.00" }).locator("[data-score]").innerText()).trim() === "18.9", "420 scores 18.9 at 70/10/20");
    });

    await step("5c. client deliberately chooses the NON-recommended bid → winner card, Non retenue, #paiement", async () => {
      const other = cp.locator(".bid-row:not(:has([data-recommended]:not([hidden])))");
      assert(await other.count() === 1, "one non-recommended row");
      const label = await other.locator("[data-choose]").getAttribute("data-choose-label");
      assert(label.includes(f2.short) && label.includes("420.00"), `non-recommended is f2 at 420 (${label})`);
      await other.locator("[data-choose]").click(); // confirm() auto-accepted
      await cp.locator("[data-status-badge]", { hasText: "Attribué" }).waitFor({ timeout: 15000 });
      winner = f2; loser = f1;
      assert(await cp.locator(".bid-row.is-won").count() === 1, "winner row highlighted");
      assert((await cp.locator(".bid-row.is-won").innerText()).includes("420.00"), "winner row is the 420");
      assert(await cp.locator(".bid-row.is-lost .ui-badge", { hasText: "Non retenue" }).count() === 1, "other row says Non retenue");
      assert(await cp.locator("[data-choose]").count() === 0, "no more Choisir buttons");
      assert((await cp.locator(".ui-panel", { hasText: "Offre retenue" }).innerText()).includes(f2.short), "Offre retenue card names f2");
      await cp.locator("#paiement").waitFor({ state: "attached" });
      assert(await cp.locator("#escrow-panel").isVisible(), "escrow panel visible");
      const payBtn = cp.locator('#escrow-panel [data-pay-step="direct_pay"]');
      assert(await payBtn.count() === 1, "client sees the pay button");
      assert(/Payer/.test(await payBtn.innerText()), `pay button says Payer… (${await payBtn.innerText()})`);
      assert(await cp.locator("#escrow-panel [data-pay-error]").count() === 1, "an error slot exists for the pay button");
      await cp.locator("#escrow-panel [data-usdc-balance]").waitFor();
      await shot(cp, "06-detail-gagnant-paiement");
      await noHorizontalScroll(cp, "desktop detail awarded");

      // Winner: delivery form. Loser: read-only panel.
      // a #fragment-only goto would be a same-document navigation (no reload): use the plain URL
      await p2.goto(`/besoins/${needId}/`);
      await p2.locator("#escrow-panel").waitFor();
      assert(await p2.locator('#escrow-panel [data-pay-step="deliver"]').count() === 1, "winner sees Déclarer la livraison");
      assert(/Déclarer la livraison/.test(await p2.locator('#escrow-panel [data-pay-step="deliver"]').innerText()), "winner button label");
      assert(await p2.locator("#pay-evidence").isVisible(), "winner has the delivery note textarea");
      assert(await p2.locator("#bid-form").count() === 0, "no bid form once awarded");
      await p1.goto(`/besoins/${needId}/`);
      assert(await p1.locator("#escrow-panel").isVisible(), "loser still sees the panel");
      assert(await p1.locator("#escrow-panel [data-pay-step]").count() === 0, "loser has no action button (read-only)");
      assert((await p1.locator("#escrow-panel [data-pay-action]").innerText()).includes("En attente"), "loser sees the waiting copy");
      assert(await p1.locator("#escrow-panel [data-pay-trustline]").count() === 0, "trustline helper is for the two parties only");
      await pa.goto(`/besoins/${needId}/`);
      assert(await pa.locator("#escrow-panel [data-pay-step]").count() === 0, "anonymous: read-only panel");

      const mc = await mobileClone(browser, ctx.client, client);
      const mcp = track(await mc.newPage(), "mobile client");
      await mcp.goto(`/besoins/${needId}/#paiement`);
      await mcp.locator("#escrow-panel").waitFor();
      await noHorizontalScroll(mcp, "mobile detail awarded");
      await shot(mcp, "mobile-detail-gagnant-paiement");
      // tap targets: every button/link in the panel is at least 36 px tall on the phone
      const small = await mcp.locator("#escrow-panel button, #escrow-panel a.ui-btn").evaluateAll((els) => els.filter((e) => e.offsetParent !== null && e.getBoundingClientRect().height < 32).map((e) => e.outerHTML.slice(0, 80)));
      assert(small.length === 0, `mobile tap targets under 32 px in the panel: ${small.join(" | ")}`);
      await mc.close();
    });

    // 6 ------------------------------------------------------------------------------------------
    await step("6. Mes enchères (Gagnée / Non retenue) and Mes besoins (Attribué)", async () => {
      await p2.goto("/mes-encheres/");
      const wonRow = p2.locator("tbody tr", { hasText: "Landing page Django" });
      assert(await wonRow.locator(".ui-badge", { hasText: "Gagnée" }).count() === 1, "f2's bid is Gagnée");
      assert(await wonRow.locator("a", { hasText: "Voir le paiement" }).count() === 1, "payment link on the won row");
      await shot(p2, "07-mes-encheres");
      await noHorizontalScroll(p2, "desktop mes enchères");
      await p1.goto("/mes-encheres/");
      const lostRow = p1.locator("tbody tr", { hasText: "Landing page Django" });
      assert(await lostRow.locator(".ui-badge", { hasText: "Non retenue" }).count() === 1, "f1's bid is Non retenue");
      assert(await p1.locator("tbody tr", { hasText: "450.00" }).locator(".ui-badge", { hasText: "Remplacée" }).count() === 1, "f1's superseded 450 is Remplacée");
      await cp.goto("/mes-besoins/");
      const needRow = cp.locator("tbody tr", { hasText: "Landing page Django" });
      assert(await needRow.locator(".ui-badge", { hasText: "Attribué" }).count() === 1, "need is Attribué in Mes besoins");
      assert(await cp.locator("tbody tr").count() === 1 + EXTRA_NEEDS.length, "all the client's needs are listed");
      await noHorizontalScroll(cp, "desktop mes besoins");
      await shot(cp, "08-mes-besoins");

      const m2 = await mobileClone(browser, ctx.f2, f2);
      const m2p = track(await m2.newPage(), "mobile f2");
      await m2p.goto("/mes-encheres/");
      await m2p.locator("tbody tr").first().waitFor();
      await noHorizontalScroll(m2p, "mobile mes enchères");
      await shot(m2p, "mobile-mes-encheres");
      await m2p.goto("/mes-besoins/");
      await noHorizontalScroll(m2p, "mobile mes besoins (empty)");
      await m2.close();
      const mc = await mobileClone(browser, ctx.client, client);
      const mcp = track(await mc.newPage(), "mobile client");
      await mcp.goto("/mes-besoins/");
      await mcp.locator("tbody tr").first().waitFor();
      await noHorizontalScroll(mcp, "mobile mes besoins");
      await mc.close();
    });

    // 7 ------------------------------------------------------------------------------------------
    await step("7. Payer with no network → French error in [data-pay-error], HTTP 200 {ok:false}, no 500", async () => {
      await cp.goto(`/besoins/${needId}/`);
      await cp.locator("#escrow-panel").waitFor();
      const btn = cp.locator('#escrow-panel [data-pay-step="direct_pay"]');
      const waitPrepare = cp.waitForResponse((r) => r.url().includes("/pay/prepare/"), { timeout: 30000 });
      await btn.click();
      const resp = await waitPrepare;
      assert(resp.status() === 200, `prepare answers 200, got ${resp.status()}`);
      const body = await resp.json();
      assert(body.ok === false && typeof body.message === "string" && body.message.length > 0, `prepare refuses with a message: ${JSON.stringify(body)}`);
      assert(["stellar", "provider"].includes(body.error), `error code stellar/provider, got ${body.error}`);
      const slot = cp.locator("#escrow-panel [data-pay-error]:not([hidden])");
      await slot.waitFor();
      const text = (await slot.innerText()).trim();
      assert(text === body.message, `panel shows the server message ("${text}")`);
      assert(/[éèêàç]/.test(text), `message is French: "${text}"`);
      await cp.waitForTimeout(300);
      assert(!(await btn.isDisabled()), "pay button is usable again (retry)");
      assert(await cp.evaluate(() => !!(window.__fakeFreighter && !window.__fakeFreighter.calls.some((c) => c.name === "signTransaction"))), "Freighter was not asked to sign (nothing to sign)");
      await cp.reload();
      const persisted = cp.locator("#escrow-panel .ui-alert-attn", { hasText: text });
      assert(await persisted.count() === 1, "last_error persisted on the escrow row and shown after reload");
      assert((await cp.locator("#escrow-panel .ui-badge").first().innerText()).length > 0, "escrow status badge rendered");
      const my = await cp.locator("#escrow-panel [data-usdc-balance]").innerText();
      assert(my.trim() === "—" || my.trim() === "…" || /USDC/.test(my), `balance slot degrades gracefully ("${my}")`);
    });

    // 8 ------------------------------------------------------------------------------------------
    await step("8. theme toggle persists, light-mode escrow panel, logout clears the navbar", async () => {
      await cp.click("[data-theme-toggle]");
      assert((await cp.getAttribute("html", "data-theme")) === "light", "html[data-theme=light]");
      await cp.reload();
      assert((await cp.getAttribute("html", "data-theme")) === "light", "light theme survives a reload (no flash to dark)");
      await cp.locator("#escrow-panel").waitFor();
      await shot(cp, "11-detail-gagnant-paiement-light");
      const contrast = await cp.locator("#escrow-panel").evaluate((el) => {
        const cs = getComputedStyle(el);
        const bg = cs.backgroundColor;
        const text = getComputedStyle(el.querySelector(".ui-panel-title")).color;
        return { bg, text };
      });
      assert(contrast.bg !== contrast.text, `panel text differs from its background (${JSON.stringify(contrast)})`);
      await cp.click("[data-theme-toggle]");
      assert((await cp.getAttribute("html", "data-theme")) === "dark", "back to dark");

      await cp.click("details.lb-wallet-menu summary");
      await cp.locator("details.lb-wallet-menu[open]").waitFor();
      await Promise.all([cp.waitForURL((u) => new URL(u).pathname === "/"), cp.click('details.lb-wallet-menu button[type="submit"]')]);
      assert(await cp.locator(".lb-wallet-btn.is-connected").count() === 0, "no connected address in the navbar");
      assert(await cp.locator(".lb-nav [data-wallet-connect]").count() === 1, "connect button is back");
      await cp.goto("/mes-besoins/");
      assert(new URL(cp.url()).pathname === "/" && new URL(cp.url()).searchParams.get("next") === "/mes-besoins/", "session really gone (wallet_required redirect)");
      const r404 = await cp.request.get(BASE + "/besoins/999999/");
      assert(r404.status() === 404, `unknown need → 404 (got ${r404.status()})`);
    });
  } finally {
    await browser.close().catch(() => {});
  }

  // --- verdict -----------------------------------------------------------------------------
  const unexpected = consoleErrors.filter((e) => !isExpectedError(e));
  const expected = consoleErrors.length - unexpected.length;
  log("");
  log(`console: ${consoleErrors.length} error message(s), ${expected} expected (Horizon unreachable / API 4xx), ${unexpected.length} unexpected`);
  for (const e of unexpected) log(`  UNEXPECTED [${e.who}] ${e.text}  (${e.source})`);
  const horizonErrors = consoleErrors.filter((e) => /horizon/i.test(e.source) || /ERR_TUNNEL|ERR_NAME_NOT_RESOLVED/.test(e.text));
  log(`console: ${horizonErrors.length} Horizon failure(s) across all awarded-page loads (watcher stops after 3 per page)`);
  const failed = results.filter((r) => !r.ok);
  log(`steps: ${results.length - failed.length}/${results.length} passed`);
  log(`screenshots: ${fs.readdirSync(SHOTS).filter((f) => f.endsWith(".png")).sort().join(", ")}`);
  if (unexpected.length) throw new Error(`${unexpected.length} unexpected console/page error(s)`);
  if (failed.length) throw new Error(`${failed.length} step(s) failed`);
  if (winner && loser) log(`actors: client=${short(client.address)} winner=${short(winner.address)} loser=${short(loser.address)}`);
}

main().then(
  () => { log("E2E OK"); process.exit(0); },
  (err) => { log("E2E FAILED: " + (err && err.stack || err)); process.exit(1); }
);
