#!/usr/bin/env node
/* TaskVault end-to-end run — the task-board demo scenario with a simulated Freighter
 * (fake-freighter.js) and a fake Horizon (fake-horizon.js) for the DIRECT payment mode.
 *
 *   make e2e                      # fresh SQLite, runserver (direct mode, STELLAR_HORIZON_URL = the fake), this script
 *   E2E_SHOTS_DIR=data/e2e-shots  # screenshots elsewhere than docs/screenshots/ (what `make all` does)
 *   E2E_BASE_URL=http://127.0.0.1:8000 E2E_HORIZON_PORT=8100 node tests/e2e/run.js
 *                                 # against a server you started with LOWBID_PAYMENT_MODE=direct
 *                                 # STELLAR_HORIZON_URL=http://127.0.0.1:8100
 *
 * Plain `playwright` library API (no @playwright/test). Three browser contexts (company,
 * freelance A, freelance B) at 1280x800, the key screens re-checked at 390x844. Screenshots land in
 * docs/screenshots/. Exit code 1 on the first failing step, on any unexpected console error or
 * uncaught page error. Nothing here reaches the real network.
 *
 * Scenario: company creates a project + 3 tasks (inline) → A and B apply to T1 → company chooses A
 * → A delivers a link (direct mode: DB only) → company validates with note 5: the Rating is saved,
 * the chained payment FAILS gracefully (company account unknown on Horizon → error message in
 * [data-pay-error], HTTP 200 {ok:false}) → the fake Horizon "friendbots" the wallets, A adds the
 * USDC trustline, the company resumes the payment from the panel button → T1 paid, hash + explorer
 * link shown → A and B apply to T2 → A is top with "Validated" + "Recommended" (90 vs 20). Plus the
 * kanban, dashboard, profile, list filters, mobile (no horizontal scroll), dark-only theme and logout.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const REPO = path.resolve(__dirname, "..", "..");
const StellarSdk = require(path.join(REPO, "node_modules", "@stellar", "stellar-sdk"));
const { installFakeFreighter } = require("./fake-freighter");
const { startFakeHorizon } = require("./fake-horizon");

const BASE = (process.env.E2E_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const HORIZON_PORT = Number(process.env.E2E_HORIZON_PORT || 0);
let horizon = null; // the fake Horizon handle (fund / balanceOf / submitted)
const PASSPHRASE = "Test SDF Network ; September 2015";
// E2E_SHOTS_DIR keeps a verification run (`make all`) from rewriting the committed pitch images.
const SHOTS = process.env.E2E_SHOTS_DIR ? path.resolve(REPO, process.env.E2E_SHOTS_DIR) : path.join(REPO, "docs", "screenshots");
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
  // Horizon reads of an unknown account answer 404 (the fake one included); a sandbox without network must not fail the run.
  if (/horizon/i.test(e.source) || /horizon/i.test(e.text)) return true;
  if (horizon && (e.source.startsWith(horizon.url) || e.text.includes(horizon.url))) return true;
  if (/ERR_TUNNEL_CONNECTION_FAILED|ERR_NAME_NOT_RESOLVED|ERR_CONNECTION_REFUSED|ERR_PROXY/.test(e.text) && !e.source.startsWith(BASE)) return true;
  // Business refusals are real 4xx answers from our own API (own_task, forbidden, duplicate …).
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
  const ctx = await browser.newContext(Object.assign({ viewport, baseURL: BASE, locale: "en-US", timezoneId: "Europe/Paris" }, extra || {}));
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
  await page.waitForTimeout(250); // let fonts / transitions settle
  // Phone shots are viewport-only: a full-page capture would paint the fixed tab bar / sticky
  // action bar in the middle of the image instead of at the bottom of the screen.
  const vp = page.viewportSize() || DESKTOP;
  await page.screenshot(Object.assign({ path: path.join(SHOTS, name + ".png"), fullPage: vp.width > 600 }, opts || {}));
}
/* The app confirms every decision in its own <dialog id="lb-confirm"> (Lowbid.confirm), not window.confirm. */
async function acceptConfirm(page, label) {
  const dlg = page.locator("#lb-confirm[open]");
  await dlg.waitFor({ timeout: 5000 });
  const body = (await dlg.locator("[data-modal-body]").innerText()).trim();
  assert(body.length > 0, `${label}: confirm dialog has a message`);
  await dlg.locator("[data-modal-ok]").click();
  await page.locator("#lb-confirm[open]").waitFor({ state: "detached", timeout: 5000 }).catch(() => {});
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
async function createProject(page, project) {
  await page.goto("/projets/nouveau/");
  await page.fill("#id_title", project.title);
  await page.fill("#id_description", project.description);
  await Promise.all([page.waitForURL(/\/projets\/\d+\/$/), page.click("#project-form button[type=submit]")]);
  return Number(page.url().match(/\/projets\/(\d+)\//)[1]);
}
/* Inline add-task form on the project page: fills, submits through Lowbid.api, waits for the reload. */
async function addTaskUI(page, task, expectedCount) {
  await page.fill("#task-title", task.title);
  await page.fill("#task-description", task.description || "");
  await page.fill("#task-price", String(task.price));
  await page.fill("#task-tags", task.tags);
  await page.click("[data-task-add]");
  await page.locator(`[data-tasks][data-count="${expectedCount}"]`).waitFor({ timeout: 10000 });
}
async function applyUI(page, taskId, app) {
  await page.goto(`/taches/${taskId}/`);
  if (app.message) await page.fill("#apply-message", app.message);
  await page.fill("#apply-tags", app.tags);
  await page.click("[data-apply-submit]");
  await page.locator("#my-application").waitFor({ timeout: 10000 });
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

const PROJECT = {
  title: "Booking platform for a yoga studio",
  description: "Class booking site (schedule, memberships, USDC payment via Freighter) for a 3-room studio. Figma mockups provided, deployment on our VPS. Split into three fixed-price tasks.",
};
const TASKS = [
  { title: "Landing page", description: "Responsive home page (Django + Tailwind) from the mockup, contact form.", price: 300, tags: "django, ui" },
  { title: "Freighter integration", description: "Wallet login, SEP-53 signature and USDC payment of a membership from the browser.", price: 500, tags: "stellar, js" },
  { title: "Dashboard", description: "Studio dashboard: occupancy rate, USDC revenue, CSV export.", price: 400, tags: "django, charts" },
];
const EXTRA_PROJECT = {
  title: "Brand refresh and showcase website for a bakery",
  description: "Vector logo, mini brand guide (colours, typefaces) and a 5-page showcase site with opening hours and menu. Photos need light retouching, hosting already in place.",
  tasks: [
    { title: "Logo and brand guide", description: "Vector logo, 2 variants, mini brand guide.", price: 250, tags: ["design", "figma"] },
    { title: "WordPress showcase site", description: "5 pages, custom theme, green Core Web Vitals.", price: 600, tags: ["wordpress", "seo"] },
    { title: "Photo retouching", description: "30 product photos: clipping, colour grading, web exports.", price: 120, tags: ["photo"] },
  ],
};

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  if (HORIZON_PORT) {
    horizon = await startFakeHorizon(HORIZON_PORT);
    log(`fake horizon: ${horizon.url}`);
  } else {
    log("E2E_HORIZON_PORT not set: the payment steps will fail gracefully (no Horizon) and the paid-task assertions are skipped");
  }
  await waitForServer();
  const browser = await chromium.launch({ headless: HEADLESS });

  const company = actor("company");
  const fa = actor("freelanceA");
  const fb = actor("freelanceB");
  const ctx = {
    company: await newContext(browser, company, DESKTOP),
    fa: await newContext(browser, fa, DESKTOP),
    fb: await newContext(browser, fb, DESKTOP),
    anon: await newContext(browser, null, DESKTOP),
  };
  const cp = track(await ctx.company.newPage(), "company");
  const pa = track(await ctx.fa.newPage(), "freelanceA");
  const pb = track(await ctx.fb.newPage(), "freelanceB");
  const pn = track(await ctx.anon.newPage(), "anon");
  let projectId = null;
  const taskIds = []; // T1, T2, T3
  let extraProjectId = null;

  try {
    // 1 ------------------------------------------------------------------------------------------
    await step("1. landing renders, Freighter login round-trip, navbar shows G…XXXX", async () => {
      await cp.goto("/");
      assert((await cp.title()).includes("TaskVault"), "title contains TaskVault");
      await cp.locator(".lb-hero-title").waitFor();
      assert(await cp.locator(".lb-hero [data-wallet-connect]").count() === 1, "hero has the connect button");
      const body = await cp.evaluate(() => document.body.innerText);
      assert(!/ench[eè]r|auction/i.test(body), "landing copy is about the task board");
      await connect(cp, company, ".lb-hero [data-wallet-connect]");
      await cp.waitForURL(/\/tableau-de-bord\/$/, { timeout: 10000 });
      await cp.locator("#todo").waitFor();
      assert(await cp.locator("#activity").count() === 1, "dashboard has the activity section");
      assert(await cp.locator(".lb-tabbar").count() === 1, "signed-in pages carry the mobile tab bar markup");
      await cp.goto("/");
      assert((await cp.locator(".lb-hero a.ui-btn-primary").innerText()).includes("New project"), "hero CTA switches to New project");
      assert(await cp.locator("[data-landing-stats]").count() === 1, "landing shows the live stats line");
    });

    await step("1b. ?next= after connect (wallet_required redirect) and off-site next dropped", async () => {
      await pa.goto("/taches/");
      assert(new URL(pa.url()).pathname === "/" && new URL(pa.url()).searchParams.get("next") === "/taches/", `redirected to /?next=…, got ${pa.url()}`);
      await pa.locator(".lb-hero .ui-alert", { hasText: "/taches/" }).waitFor();
      await connect(pa, fa, ".lb-hero [data-wallet-connect]");
      await pa.waitForURL(/\/taches\/$/);
      assert(await pa.locator(".kanban-col[data-col]").count() === 4, "kanban has 4 columns");
      await pa.locator('.kanban-col[data-col="open"] .kanban-empty').waitFor();

      await pb.goto("/?next=https://evil.example/");
      assert(await pb.locator(".lb-hero .ui-alert").count() === 0, "off-site next is not advertised");
      await connect(pb, fb, ".lb-hero [data-wallet-connect]");
      await pb.waitForTimeout(600);
      assert(pb.url().startsWith(BASE + "/"), `stayed on ${BASE}, got ${pb.url()}`);
    });

    // 2 ------------------------------------------------------------------------------------------
    await step("2. company creates the project and adds 3 tasks inline (300 / 500 / 400 USDC)", async () => {
      projectId = await createProject(cp, PROJECT);
      await cp.locator(".ui-alert-ok", { hasText: "Project created" }).waitFor();
      assert((await cp.locator("[data-status-badge]").innerText()).trim() === "Draft", "status Draft");
      await cp.locator('[data-tasks][data-count="0"]').waitFor();
      assert(await cp.locator("#task-form").count() === 1, "company sees the inline add-task form");
      assert(await cp.locator("[data-fund]").count() === 0, "no Fund button without a task");
      for (let i = 0; i < TASKS.length; i++) await addTaskUI(cp, TASKS[i], i + 1);
      const rows = cp.locator(".task-row");
      assert(await rows.count() === 3, "3 task rows");
      for (let i = 0; i < 3; i++) {
        taskIds.push(Number(await rows.nth(i).getAttribute("data-task-id")));
        assert((await rows.nth(i).getAttribute("data-status")) === "open", `task ${i + 1} is open`);
      }
      assert((await cp.locator("[data-kpi-total]").innerText()).replace(/\s+/g, " ").startsWith("1,200.00"), "KPI total = 1,200.00");
      assert(await cp.locator("[data-task-delete]").count() === 3, "every open task can be deleted");
      // direct payment mode (no Trustless Work key): no funding button, the panel says so
      assert(await cp.locator("[data-fund]").count() === 0, "no Fund button in direct mode");
      assert(await cp.locator("#funding-panel[data-mode=direct]").count() === 1, "funding banner in direct mode");
      assert(/Direct payment|Direct USDC payment/i.test(await cp.locator("#funding-panel").innerText()), "direct-mode note is displayed");
      // server-side validation surfaces under the right field
      await cp.fill("#task-title", "Invalid task"); await cp.fill("#task-price", "10"); await cp.fill("#task-tags", "a, b, c, d");
      await cp.click("[data-task-add]");
      const err = cp.locator('[data-error-for="tags"]:not([hidden])');
      await err.waitFor();
      assert(/At most 3/i.test(await err.innerText()), `tags error, got "${await err.innerText()}"`);
      assert(!(await cp.locator("[data-task-add]").isDisabled()), "submit button re-enabled after a refusal");
      await cp.goto(`/projets/${projectId}/`);
      await cp.locator('[data-tasks][data-count="3"]').waitFor();
    });

    await step("2b. a second project (API) for the list / kanban screenshots; freelances cannot add tasks", async () => {
      extraProjectId = await createProject(cp, EXTRA_PROJECT);
      for (const t of EXTRA_PROJECT.tasks) {
        const r = await api(cp, `/projets/${extraProjectId}/taches/ajouter/`, t);
        assert(r.status === 201, `add task on #${extraProjectId}: HTTP ${r.status} ${JSON.stringify(r.json)}`);
      }
      const forbidden = await api(pa, `/projets/${projectId}/taches/ajouter/`, { title: "Hack", price: 1, tags: [] });
      assert(forbidden.status === 403 && forbidden.json.error === "forbidden", `freelance cannot add a task (got ${forbidden.status})`);
      await pn.goto("/"); // the anonymous context needs the CSRF cookie before its first POST
      const anon = await api(pn, `/projets/${projectId}/taches/ajouter/`, { title: "Hack", price: 1, tags: [] });
      assert(anon.status === 401 && anon.json.error === "wallet_required", `anonymous → 401 wallet_required, got ${anon.status}`);
      await cp.goto(`/projets/${projectId}/`);
    });

    // 3 ------------------------------------------------------------------------------------------
    await step("3. A and B apply to T1 (A: django,ui · B: django); company cannot apply; duplicates refused", async () => {
      await applyUI(pa, taskIds[0], { message: "Django + Tailwind every day, I deliver in 5 days including deployment.", tags: "django, ui" });
      assert((await pa.locator("#my-application").innerText()).includes("20.0"), "A's score is 20.0 (tags only, no history)");
      await applyUI(pb, taskIds[0], { message: "Clean build from Figma, 2 iterations included.", tags: "django" });
      assert((await pb.locator("#my-application").innerText()).includes("10.0"), "B's score is 10.0");
      assert(await pb.locator('[data-candidates][data-count="2"]').count() === 1, "B sees 2 candidates");
      const dup = await api(pa, `/taches/${taskIds[0]}/postuler/`, { message: "again", tags: ["django"] });
      assert(dup.status === 409 && dup.json.error === "duplicate", `second application refused with duplicate, got ${dup.status} ${JSON.stringify(dup.json)}`);
      const own = await api(cp, `/taches/${taskIds[0]}/postuler/`, { message: "me", tags: [] });
      assert(own.status === 403 && own.json.error === "own_task", `own_task refused, got ${own.status}`);
      assert(/own task/i.test(own.json.message), `English own_task message, got "${own.json.message}"`);
      await pa.goto(`/taches/${taskIds[0]}/`);
      assert(await pa.locator("[data-choose]").count() === 0, "a freelancer has no Choose button");
    });

    await step("3b. company's task page updates by polling (2 candidates, Recommended on A, Choose on EVERY row)", async () => {
      await cp.goto(`/taches/${taskIds[0]}/`);
      let navs = 0;
      cp.on("framenavigated", (f) => { if (f === cp.mainFrame()) navs++; });
      // B's application landed before this page load; A's and B's rows are already there. Add a third
      // candidate through the API and watch the list refresh without a reload.
      const fc = actor("freelanceC");
      const cctx = await newContext(browser, fc, DESKTOP);
      const pc = track(await cctx.newPage(), "freelanceC");
      await pc.goto("/");
      await connect(pc, fc, ".lb-hero [data-wallet-connect]");
      const r = await api(pc, `/taches/${taskIds[0]}/postuler/`, { message: "Available right away.", tags: ["ui"] });
      assert(r.status === 201, `C applies: HTTP ${r.status}`);
      const t0 = Date.now();
      await cp.locator('[data-candidates][data-count="3"]').waitFor({ timeout: 8000 });
      log(`      polling delivered the list in ${Date.now() - t0} ms`);
      assert(navs === 0, `no navigation on the company page (saw ${navs})`);
      assert((await cp.locator("[data-kpi-count]").innerText()).trim() === "3", "KPI count = 3");
      assert(await cp.locator("[data-live-dot]:not([hidden])").count() === 1, "live dot shown");
      assert(await cp.locator("[data-choose]").count() === 3, "a Choose button on EVERY candidate");
      const rec = cp.locator("[data-recommended]");
      assert(await rec.count() === 1, "exactly one Recommended badge");
      const recRow = cp.locator(".cand-row:has([data-recommended])");
      assert((await recRow.getAttribute("data-freelancer")) === fa.address, "A (20.0) is recommended");
      assert((await recRow.locator("[data-score]").innerText()).trim() === "20.0", "A scores 20.0");
      assert(await cp.locator(".badge-validated").count() === 0, "nobody is Validated yet");
      // C withdraws nothing — just drop them from the demo by letting the company pick A below.
      await cctx.close();
      await shot(cp, "04-tache-candidats");
      await noHorizontalScroll(cp, "desktop task candidates");
    });

    // 4 ------------------------------------------------------------------------------------------
    await step("4. company chooses A → Taken, others Not selected; B cannot deliver; A delivers a link", async () => {
      const rowA = cp.locator(`.cand-row[data-freelancer="${fa.address}"]`);
      await rowA.locator("[data-choose]").click();
      await acceptConfirm(cp, "choose A");
      await cp.locator("[data-status-badge]", { hasText: "Taken" }).waitFor({ timeout: 15000 });
      assert(await cp.locator("[data-choose]").count() === 0, "no more Choose buttons");
      assert(await cp.locator(".cand-row.is-chosen").count() === 1, "chosen row highlighted");
      assert((await cp.locator(".cand-row.is-chosen").getAttribute("data-freelancer")) === fa.address, "A is the chosen one");
      assert(await cp.locator(".cand-row.is-rejected").count() === 2, "the two others are Not selected");
      assert(await cp.locator(".cand-row.is-rejected .ui-badge", { hasText: "Not selected" }).count() === 2, "Not selected badges");

      const notB = await api(pb, `/taches/${taskIds[0]}/livrer/`, { delivery_link: "https://example.com/pr" });
      assert(notB.status === 403 && notB.json.error === "not_assigned", `B cannot deliver (got ${notB.status})`);

      await pa.goto(`/taches/${taskIds[0]}/`);
      await pa.locator("#escrow-panel[data-mode=direct]").waitFor();
      await pa.locator("#deliver-panel").waitFor();
      assert(/Direct payment USDC|Direct USDC payment/i.test(await pa.locator("#escrow-panel").innerText()), "panel announces the direct mode");
      assert(await pa.locator("#escrow-panel [data-pay-trustline]").count() === 1, "trustline helper offered to the freelance");
      await pa.fill("#deliver-link", "not-a-link");
      await pa.click("[data-deliver]");
      await acceptConfirm(pa, "deliver (bad link)");
      const err = pa.locator("#deliver-panel [data-pay-error]:not([hidden])");
      await err.waitFor();
      assert(/http/.test(await err.innerText()), `link validation message mentions http, got "${await err.innerText()}"`);
      assert(!(await pa.locator("[data-deliver]").isDisabled()), "deliver button re-enabled after a refusal");
      await pa.fill("#deliver-link", "https://github.com/studio-nova/booking/pull/1");
      await pa.click("[data-deliver]");
      await acceptConfirm(pa, "deliver");
      await pa.locator("[data-status-badge]", { hasText: "Delivered" }).waitFor({ timeout: 15000 });
      assert(await pa.locator("[data-delivery-link]").count() === 1, "delivery link displayed");
      assert(await pa.locator("#deliver-panel").count() === 0, "deliver form is gone");
      assert((await pa.locator("#escrow-panel").getAttribute("data-escrow-status")) === "delivered", "escrow row is delivered");
      await shot(pa, "05-tache-livree-freelance");
    });

    // 5 ------------------------------------------------------------------------------------------
    await step("5. company validates with note 5: rating saved, the chained payment fails gracefully (account unknown on Horizon)", async () => {
      await cp.goto(`/projets/${projectId}/`);
      await cp.locator(".task-row[data-status=delivered]").waitFor();
      assert(await cp.locator(".task-row[data-status=delivered] a", { hasText: /Validate \+ rate/i }).count() === 1, "project page offers Validate + rate");
      await cp.goto(`/taches/${taskIds[0]}/`);
      await cp.locator("#validate-panel").waitFor();
      assert(await cp.locator("[data-validate] [data-rate]").count() === 5, "5 star radios");
      const refused = await api(pa, `/taches/${taskIds[0]}/valider/`, { note: 5 });
      assert(refused.status === 403 && refused.json.error === "forbidden", `freelance cannot validate (got ${refused.status})`);
      const bad = await api(cp, `/taches/${taskIds[0]}/valider/`, { note: 7 });
      assert(bad.status === 400 && bad.json.error === "invalid", `note 7 refused with invalid (got ${bad.status})`);
      const early = await api(cp, `/pay/prepare/${taskIds[0]}/direct_pay/`, {});
      assert(early.status === 200 && early.json.ok === false && early.json.error === "wrong_state", `paying before rating is refused with HTTP 200 {ok:false}: ${JSON.stringify(early.json)}`);
      await cp.check('[data-rate="5"]', { force: true });
      assert(await cp.isChecked('[data-rate="5"]'), "note 5 checked");
      await cp.fill("#validate-comment", "Flawless, pixel-perfect and ahead of schedule.");
      await shot(cp, "06-valider-noter");
      await cp.click("[data-validate-submit]");
      await acceptConfirm(cp, "validate");
      // The Rating is stored, then lowbid-projects.js chains direct_pay: the company account does not exist
      // on (the fake) Horizon yet → prepare answers HTTP 200 {ok:false, error:"stellar"} with an error message.
      const payErr = cp.locator("#escrow-panel [data-pay-error]:not([hidden])");
      await payErr.waitFor({ timeout: 15000 });
      const payMsg = (await payErr.innerText()).trim();
      assert(/Stellar account not found|account not found|fund it|friendbot|Horizon/i.test(payMsg), `payment error shown, got "${payMsg}"`);
      assert(await cp.locator("#validate-form").count() === 0, "the rating form is gone (rating saved)");
      const resume = cp.locator('#escrow-panel [data-pay-step="direct_pay"]');
      assert(await resume.count() === 1, "a resume button \"Pay the freelancer\" replaces the form");
      assert((await cp.locator("[data-status-badge]").innerText()).trim() === "Delivered", "task is still Delivered (nothing paid)");
      const dup = await api(cp, `/taches/${taskIds[0]}/valider/`, { note: 4 });
      assert(dup.status === 409 && dup.json.error === "duplicate", `second validation refused (got ${dup.status} ${dup.json && dup.json.error})`);
      const fail = await api(cp, `/pay/prepare/${taskIds[0]}/direct_pay/`, {});
      assert(fail.status === 200 && fail.json.ok === false && fail.json.error === "stellar", `prepare fails gracefully: ${JSON.stringify(fail.json)}`);
      await cp.reload();
      await cp.locator('#escrow-panel [data-pay-step="direct_pay"]').waitFor();
      assert(/Stellar account not found|account not found|fund it|friendbot/i.test(await cp.locator("#escrow-panel").innerText()), "last_error persisted in the panel after a reload");
      assert(await cp.locator("#escrow-panel [data-last-error]").count() === 1, "last_error alert");
      await shot(cp, "13-paiement-echec");
      // dashboard: the pending payment step surfaces for both roles
      await cp.goto("/tableau-de-bord/");
      assert(await cp.locator("[data-todo-list] .ui-next-card.act", { hasText: /Pay "Landing page"|Pay .Landing page./ }).count() === 1, "company to-do: pay the task");
      await pa.goto("/tableau-de-bord/");
      assert(await pa.locator("[data-todo-list] .ui-next-card", { hasText: /payment pending|pending payment/i }).count() === 1, "freelance to-do: payment pending");
    });

    await step("5b. wallets funded on Horizon, A adds the USDC trustline, the company resumes → T1 Paid with its explorer link", async () => {
      if (!horizon) { log("      skipped (no fake Horizon)"); return; }
      horizon.fund(company.address, { usdc: 1000 });
      horizon.fund(fa.address); // XLM only: the trustline comes from the UI
      await pa.goto(`/taches/${taskIds[0]}/`);
      await pa.locator("#escrow-panel [data-pay-trustline]").click();
      await pa.locator(".lb-toast", { hasText: /Trustline USDC added|USDC trustline added/i }).waitFor({ timeout: 15000 });
      assert(horizon.submitted.some((t) => t.type === "change_trust" && t.source === fa.address), "changeTrust reached Horizon");
      assert(horizon.balanceOf(fa.address) === 0, "A holds the trustline with a 0 balance");
      const again = await api(pa, "/pay/trustline/prepare/", {});
      assert(again.json.ok && !again.json.xdr && /already/i.test(again.json.message), `second trustline call says already present: ${JSON.stringify(again.json)}`);

      await cp.goto(`/taches/${taskIds[0]}/`);
      await cp.locator('#escrow-panel [data-pay-step="direct_pay"]').click();
      await cp.locator("[data-status-badge]", { hasText: "Paid" }).waitFor({ timeout: 20000 });
      const payment = horizon.submitted.find((t) => t.type === "payment");
      assert(payment && payment.source === company.address && payment.destination === fa.address && Number(payment.amount) === 300 && payment.asset === "USDC", `payment submitted to Horizon: ${JSON.stringify(payment)}`);
      assert(horizon.balanceOf(fa.address) === 300 && horizon.balanceOf(company.address) === 700, "ledger moved 300 USDC");
      assert(await cp.locator('[data-rating="5"]').count() === 1, "rating 5 displayed");
      assert(/Task paid/i.test(await cp.locator("main").innerText()), "Task paid panel");
      const link = cp.locator(`#escrow-panel [data-explorer-links] a[href*="stellar.expert/explorer/testnet/tx/${payment.hash}"]`);
      assert(await link.count() === 1, "the payment hash links to stellar.expert");
      assert(await cp.locator("#escrow-panel [data-last-error]").count() === 0, "last_error cleared");
      assert(await cp.locator("#escrow-panel [data-pay-step]").count() === 0, "nothing left to sign");
      const balance = cp.locator(`[data-usdc-balance="${fa.address}"]`);
      await cp.waitForFunction((el) => /300\.00/.test(el.textContent), await balance.elementHandle(), { timeout: 15000 });
      await shot(cp, "14-paiement-tache");
      const replay = await api(cp, `/pay/prepare/${taskIds[0]}/direct_pay/`, {});
      assert(replay.status === 200 && replay.json.ok === false && replay.json.error === "wrong_state", `paying twice is refused: ${JSON.stringify(replay.json)}`);
      await cp.goto(`/projets/${projectId}/`);
      await cp.locator("#funding-panel").waitFor();
      const banner = await cp.locator("#funding-panel").innerText();
      assert(/300\.00 USDC/.test(banner) && /Paid/.test(banner), `banner lists T1 as paid: "${banner.slice(0, 200)}"`);
      assert(await cp.locator(`#funding-panel a[href*="/tx/${payment.hash}"]`).count() === 1, "banner carries the explorer link");
      assert((await cp.locator("[data-status-badge]").first().innerText()).trim() === "Funded", "project is Funded after the first direct payment");
      await shot(cp, "15-financement-projet");
    });

    await step("5c. kanban + dashboard reflect the paid task", async () => {
      if (!horizon) { log("      skipped (no fake Horizon)"); return; }

      await pa.goto("/taches/");
      assert(await pa.locator(`.kanban-col[data-col="paid"] .kanban-card[data-task-id="${taskIds[0]}"]`).count() === 1, "T1 sits in A's Paid column");
      assert(await pa.locator(".kanban-col[data-col=open] .kanban-card").count() >= 2, "open tasks of the company are in A's Open column");
      assert(await pa.locator(`.kanban-col[data-col="open"] .kanban-card[data-task-id="${taskIds[0]}"]`).count() === 0, "T1 is no longer open");
      await shot(pa, "07-tableau-kanban");
      await noHorizontalScroll(pa, "desktop kanban");
    });

    // 6 ------------------------------------------------------------------------------------------
    await step("6. A and B apply to T2 → A is TOP with Validated + Recommended (90.0 vs 20.0)", async () => {
      if (!horizon) { log("      skipped (no fake Horizon: T1 is not paid)"); return; }
      await applyUI(pa, taskIds[1], { message: "I have already wired Freighter and Horizon into a Django back office.", tags: "stellar" });
      assert((await pa.locator("#my-application").innerText()).includes("90.0"), "A's score is 90.0 (40 + 5×8 + 20×½)");
      await applyUI(pb, taskIds[1], { message: "Stellar/JS specialist: SEP-53, trustlines, Soroban.", tags: "stellar, js" });
      assert((await pb.locator("#my-application").innerText()).includes("20.0"), "B's score is 20.0 (tags only)");

      await cp.goto(`/taches/${taskIds[1]}/`);
      await cp.locator('[data-candidates][data-count="2"]').waitFor();
      const rows = cp.locator(".cand-row");
      assert((await rows.nth(0).getAttribute("data-freelancer")) === fa.address, "A ranks first");
      assert((await rows.nth(0).locator("[data-score]").innerText()).trim() === "90.0", "A = 90.0");
      assert((await rows.nth(1).locator("[data-score]").innerText()).trim() === "20.0", "B = 20.0");
      assert(await rows.nth(0).locator('[data-badge="valide"]').count() === 1, "A carries Validated");
      assert(await rows.nth(0).locator("[data-recommended]").count() === 1, "A carries Recommended");
      assert(await rows.nth(1).locator('[data-badge="valide"]').count() === 0, "B is not Validated");
      assert(await rows.nth(1).locator("[data-recommended]").count() === 0, "B is not Recommended");
      assert(await cp.locator("[data-choose]").count() === 2, "Choose on both candidates (the company stays free to pick B)");
      const json = await api(cp, `/taches/${taskIds[1]}/candidats.json`, undefined, "GET");
      assert(json.status === 200 && json.json.candidates[0].score === "90.0" && json.json.candidates[0].validated === true && json.json.candidates[0].recommended === true, `candidats.json ranks A first with the badges: ${JSON.stringify(json.json.candidates)}`);
      await shot(cp, "08-tache-valide-recommande");
      await noHorizontalScroll(cp, "desktop task T2");

      // the project page shows the same candidates block with Choose buttons
      await cp.goto(`/projets/${projectId}/`);
      await cp.locator(`#candidates-${taskIds[1]}`).waitFor();
      assert(await cp.locator(`#candidates-${taskIds[1]} [data-choose]`).count() === 2, "project page: Choose on every candidate of T2");
      assert(await cp.locator(`#candidates-${taskIds[1]} [data-badge="valide"]`).count() === 1, "project page: Validated badge");
      assert(await cp.locator(".task-row[data-status=paid]").count() === 1, "T1 row is Paid");
      // One escrow per task: the project is Funded but only the still-open tasks (T2, T3) can be deleted; T1 (paid) cannot.
      assert(await cp.locator("[data-task-delete]").count() === 2, "project is Funded: only the two open tasks keep a delete button");
      assert(await cp.locator("#task-title").count() === 1, "project is Funded: the add-task form is still there");
      await shot(cp, "03-projet-entreprise");
      await noHorizontalScroll(cp, "desktop project company");

      const mc = await mobileClone(browser, ctx.company, company);
      const mcp = track(await mc.newPage(), "mobile company");
      await mcp.goto(`/taches/${taskIds[1]}/`);
      await mcp.locator('[data-candidates][data-count="2"]').waitFor();
      await noHorizontalScroll(mcp, "mobile task T2");
      await shot(mcp, "mobile-tache-candidats");
      await mcp.goto(`/projets/${projectId}/`);
      await mcp.locator('[data-tasks][data-count="3"]').waitFor();
      await noHorizontalScroll(mcp, "mobile project company");
      await shot(mcp, "mobile-projet");
      // tap targets: every button in the candidates block is at least 32 px tall on the phone
      const small = await mcp.locator(`#candidates-${taskIds[1]} button, #candidates-${taskIds[1]} a.ui-btn`).evaluateAll((els) => els.filter((e) => e.offsetParent !== null && e.getBoundingClientRect().height < 32).map((e) => e.outerHTML.slice(0, 80)));
      assert(small.length === 0, `mobile tap targets under 32 px: ${small.join(" | ")}`);
      await mc.close();
    });

    // 7 ------------------------------------------------------------------------------------------
    await step("7. list / search / tag chips, My projects, dashboard to-do + KPIs, public profile (note 5.0, name edit)", async () => {
      await pn.goto("/projets/");
      assert(await pn.locator(".project-card").count() === 2, "list shows the 2 projects");
      await shot(pn, "02-liste-projets");
      await noHorizontalScroll(pn, "desktop list");
      await pn.goto("/projets/?tab=all&q=Freighter");
      assert(await pn.locator(".project-card").count() === 1, "search matches a task title");
      await pn.goto("/projets/?tab=all&q=zzzzqqqq");
      assert(await pn.locator(".empty-state").count() === 1, "no match → empty state");
      await pn.goto("/projets/?sort=budget");
      assert(await pn.locator('select[name="sort"]').inputValue() === "budget", "sort select reflects the query");
      assert(await pn.locator(".ui-chip-row .ui-tag").count() >= 1, "popular tag chips rendered");
      await pn.locator(".ui-chip-row .ui-tag").first().click();
      assert(new URL(pn.url()).searchParams.get("tag"), "chip click filters by tag");
      await noHorizontalScroll(pn, "desktop filtered list");
      await pn.goto("/");
      await pn.locator(".project-card").first().waitFor();
      await shot(pn, "01-landing");
      await noHorizontalScroll(pn, "desktop landing");

      await cp.goto("/mes-projets/");
      const row = cp.locator("tbody tr", { hasText: PROJECT.title.slice(0, 30) });
      assert(await row.count() === 1, "the project is listed in My projects");
      assert(await row.locator(".ui-badge", { hasText: horizon ? "Funded" : "Draft" }).count() === 1, "project status badge in My projects");
      assert(/Choose/.test(await row.innerText()), "row CTA says Choose (candidates waiting on T2)");
      assert(await cp.locator("tbody tr").count() === 2, "both company projects listed");
      await shot(cp, "09-mes-projets");
      await noHorizontalScroll(cp, "desktop my projects");

      await cp.goto("/tableau-de-bord/");
      await cp.locator("#todo").waitFor();
      const todo = cp.locator("[data-todo-list] .ui-next-card");
      assert(await todo.count() >= 1, "company has at least one to-do");
      assert(await cp.locator("[data-todo-list] .ui-next-card.act", { hasText: /Choose a freelancer/i }).count() >= 1, "to-do: choose a freelancer for T2");
      assert(await cp.locator(".ui-kpi-tile").count() >= 4, "dashboard KPI tiles");
      assert(await cp.locator("#activity .ui-timeline-item").count() >= 1, "activity timeline has entries");
      if (horizon) assert(/Payment sent/i.test(await cp.locator("#activity").innerText()), "activity mentions the payment of T1");
      await shot(cp, "10-tableau-de-bord");
      await noHorizontalScroll(cp, "desktop dashboard");

      await pa.goto("/tableau-de-bord/");
      await pa.locator("#todo").waitFor();
      assert(/5\.0\/5/.test(await pa.locator("[data-avg-note]").innerText()), "A's average note is 5.0/5 on the dashboard");
      if (horizon) assert(await pa.locator("[data-todo-list] .ui-next-card", { hasText: "Freighter integration" }).count() >= 1, "A's to-do lists the pending application");

      await pa.goto(`/profil/${fa.address}/`);
      await pa.locator("#edit-name").waitFor();
      await pa.fill("#edit-name input#display_name", "Yanis");
      await pa.locator("#edit-name button[type=submit]").click();
      await pa.locator(".ui-alert-ok").waitFor();
      assert((await pa.locator(".ui-wallet-name").first().innerText()).includes("Yanis"), "display name updated on the profile");
      assert((await pa.locator('[data-avg-note="5.0"]').count()) === 1, "public profile shows the 5.0 average");
      assert(/Ratings received|Received ratings/i.test(await pa.locator("main").innerText()), "ratings section rendered");
      await shot(pa, "11-profil");
      await noHorizontalScroll(pa, "desktop profil");
      await pb.goto(`/profil/${fa.address}/`);
      assert(await pb.locator("#edit-name").count() === 0, "another wallet cannot edit the name");
      assert((await pb.locator(".ui-wallet-name").first().innerText()).includes("Yanis"), "public profile shows the new name");
      const unknown = await pb.goto("/profil/GUNKNOWN/");
      assert(unknown.status() === 404, `unknown wallet → 404, got ${unknown.status()}`);
    });

    // 8 ------------------------------------------------------------------------------------------
    await step("8. mobile: kanban, list, form, dashboard, landing — no horizontal scroll, menu toggles", async () => {
      const ma = await mobileClone(browser, ctx.fa, fa);
      const map = track(await ma.newPage(), "mobile A");
      await map.goto("/taches/");
      await map.locator(".kanban-col[data-col=open]").waitFor();
      await noHorizontalScroll(map, "mobile kanban");
      await shot(map, "mobile-kanban");
      await map.goto("/projets/");
      await noHorizontalScroll(map, "mobile list");
      await shot(map, "mobile-liste");
      await map.goto("/projets/nouveau/");
      await noHorizontalScroll(map, "mobile form");
      await map.goto("/tableau-de-bord/");
      await map.locator("#todo").waitFor();
      assert(await map.locator(".lb-tabbar").isVisible(), "mobile tab bar visible on the phone");
      await noHorizontalScroll(map, "mobile dashboard");
      await shot(map, "mobile-tableau-de-bord");
      await map.click("[data-nav-toggle]");
      assert(await map.locator("#lb-mobile-nav:not([hidden])").count() === 1, "mobile nav opens");
      await map.click("[data-nav-toggle]");
      assert(await map.locator("#lb-mobile-nav[hidden]").count() === 1, "mobile nav closes");
      await ma.close();

      const mn = await newContext(browser, null, MOBILE, { isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
      const mnp = track(await mn.newPage(), "mobile anon");
      await mnp.goto("/");
      await noHorizontalScroll(mnp, "mobile landing");
      await shot(mnp, "mobile-landing");
      await mnp.goto(`/taches/${taskIds[2]}/`);
      await noHorizontalScroll(mnp, "mobile task anon");
      assert(await mnp.locator("[data-wallet-connect][data-next]").count() >= 1, "anonymous task page offers connect with next");
      await mn.close();
    });

    // 9 ------------------------------------------------------------------------------------------
    await step("9. dark-only theme (dark shot), logout clears the navbar, 404 on unknown task", async () => {
      await cp.goto(`/taches/${taskIds[1]}/`);
      assert((await cp.getAttribute("html", "data-theme")) === "dark", "html[data-theme=dark] on every page");
      assert(await cp.locator("[data-theme-toggle]").count() === 0, "no theme toggle");
      await cp.locator("#candidates-panel").waitFor();
      await shot(cp, "12-tache-dark");
      const contrast = await cp.locator("#candidates-panel").evaluate((el) => {
        const cs = getComputedStyle(el);
        return { bg: cs.backgroundColor, text: getComputedStyle(el.querySelector(".ui-panel-title")).color };
      });
      assert(contrast.bg !== contrast.text, `panel text differs from its background (${JSON.stringify(contrast)})`);

      await cp.click("details.lb-wallet-menu summary");
      await cp.locator("details.lb-wallet-menu[open]").waitFor();
      await Promise.all([cp.waitForURL((u) => new URL(u).pathname === "/"), cp.click('details.lb-wallet-menu button[type="submit"]')]);
      assert(await cp.locator(".lb-wallet-btn.is-connected").count() === 0, "no connected address in the navbar");
      assert(await cp.locator(".lb-nav [data-wallet-connect]").count() === 1, "connect button is back");
      await cp.goto("/mes-projets/");
      assert(new URL(cp.url()).pathname === "/" && new URL(cp.url()).searchParams.get("next") === "/mes-projets/", "session really gone (wallet_required redirect)");
      const r404 = await cp.request.get(BASE + "/taches/999999/");
      assert(r404.status() === 404, `unknown task → 404 (got ${r404.status()})`);
      const p404 = await cp.request.get(BASE + "/projets/999999/");
      assert(p404.status() === 404, `unknown project → 404 (got ${p404.status()})`);
    });
  } finally {
    await browser.close().catch(() => {});
    if (horizon) await horizon.close().catch(() => {});
  }

  // --- verdict -----------------------------------------------------------------------------
  const unexpected = consoleErrors.filter((e) => !isExpectedError(e));
  const expected = consoleErrors.length - unexpected.length;
  log("");
  log(`console: ${consoleErrors.length} error message(s), ${expected} expected (API 4xx), ${unexpected.length} unexpected`);
  for (const e of unexpected) log(`  UNEXPECTED [${e.who}] ${e.text}  (${e.source})`);
  const failed = results.filter((r) => !r.ok);
  log(`steps: ${results.length - failed.length}/${results.length} passed`);
  log(`screenshots: ${fs.readdirSync(SHOTS).filter((f) => f.endsWith(".png")).sort().join(", ")}`);
  if (unexpected.length) throw new Error(`${unexpected.length} unexpected console/page error(s)`);
  if (failed.length) throw new Error(`${failed.length} step(s) failed`);
  log(`actors: company=${short(company.address)} A=${short(fa.address)} B=${short(fb.address)} project=#${projectId} tasks=${taskIds.join(",")} extra=#${extraProjectId}`);
}

main().then(
  () => { log("E2E OK"); process.exit(0); },
  (err) => { log("E2E FAILED: " + (err && err.stack || err)); process.exit(1); }
);
