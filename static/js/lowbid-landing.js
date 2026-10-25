/* TaskVault landing: the scroll story — the CSS 3D « project cube » that sits in the hero band of
   templates/core/landing.html (pinned on the right), scrubbed by anime.js v4
   (static/vendor/anime.umd.min.js, global `anime`, loaded right before this file).
   Four timelines, one per chapter, each bound to the scroll position of its own trigger
   (onScroll, sync: true — no timer, nothing runs when the page does not scroll):
     01 Split    trigger: the hero copy scrolling out — the cube turns, its four task slabs pull apart
     02 Apply    trigger: step card 2 — three applications slide in beside every task, the chosen one stays
     03 Lock     trigger: step card 3 — the slabs close ranks, Signal frame + padlock on every task
     04 Release  trigger: step card 4 — the cube turns to its side: RELEASED · deliver · approve · release
   A card's window runs from its top entering the viewport bottom to its centre reaching the viewport
   centre (under 1024px: to its top reaching 55% of the viewport, below the pinned scene); the cards
   are spaced so the windows never overlap (.lb-story-steps gap). Every tween carries explicit from/to
   values so the chapters stay independent (composition "none": the latest scrubbed timeline wins the
   cube). The step cards ([data-story-step]) and the caption follow the chapter being scrubbed.
   prefers-reduced-motion: chapters 01-03 are parked at their end (the locked pose), nothing moves.
   Without the vendor bundle (or the section) nothing runs: the CSS pose stays as is.
   Only transforms and opacity are animated, on .lb-cube, .lb-slab, .lb-bid and the [data-face-*] spans. */
(function () {
  "use strict";

  var story = document.querySelector("[data-story]");
  var A = window.anime;
  if (!story || !A || typeof A.createTimeline !== "function" || typeof A.onScroll !== "function") return;

  function all(sel) { return Array.prototype.slice.call(story.querySelectorAll(sel)); }

  var hero = story.querySelector("[data-story-hero]");
  var cube = story.querySelector("[data-cube]");
  var slabs = all("[data-slab]");
  var titles = all("[data-face-title]");
  var glows = all("[data-face-glow]");
  var locks = all("[data-face-lock]");
  var releases = all("[data-face-release]");
  var bids = all("[data-bid]");
  var chosen = all('[data-bid="chosen"]');
  var others = all('[data-bid="other"]');
  var steps = all("[data-story-step]");
  var captionNo = story.querySelector("[data-scene-no]");
  var caption = story.querySelector("[data-scene-caption]");
  if (!hero || !cube || !slabs.length || steps.length < 4) return;

  /* Caption = the step card titles (they follow the payment mode: Lock / Work, Deliver, release / pay) */
  var CHAPTERS = steps.map(function (el) {
    var t = el.querySelector(".lb-step-title");
    return t ? t.textContent.trim() : "";
  });
  var SPREAD = 30;                                  // px between two slabs when the cube is pulled apart
  var reduced = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var narrow = !!(window.matchMedia && window.matchMedia("(max-width: 1023.98px)").matches);
  var current = -1;

  function setChapter(i) {
    if (i === current) return;
    current = i;
    steps.forEach(function (el, k) { el.classList.toggle("is-active", k === i); });
    if (captionNo) captionNo.textContent = "0" + (i + 1);
    if (caption) caption.textContent = CHAPTERS[i] || "";
  }

  function spread(_, i, targets) { return (i - (targets.length - 1) / 2) * SPREAD; }

  /* One scrubbed timeline per chapter: `enter` / `leave` are "container target" thresholds. */
  function chapter(i, target, enter, leave) {
    return A.createTimeline({
      defaults: { ease: "inOut(2)", composition: "none" },   // none: four timelines share the cube, the latest scrubbed one wins (default "replace" would cancel the others)
      autoplay: reduced ? false : A.onScroll({ target: target, enter: enter, leave: leave, sync: true }),
      onUpdate: function () { setChapter(i); }
    });
  }

  var cardLeave = narrow ? "top+=55% top" : "center center";

  /* 02 Apply — twelve applications slide in (done by 685), then the two losers step back and the chosen one grows */
  var bid = chapter(1, steps[1], "bottom top", cardLeave)
    .add(bids, { x: [40, 0], opacity: [0, 1], duration: 300, delay: A.stagger(35) }, 0)
    .add(others, { opacity: [1, 0.3], x: [0, 8], duration: 250 }, 720)
    .add(chosen, { scale: [1, 1.08], duration: 250 }, 720);

  /* 03 Lock — losers gone, slabs close ranks, Signal frame + padlock on every task */
  var lock = chapter(2, steps[2], "bottom top", cardLeave)
    .add(others, { opacity: [0.3, 0], duration: 200 }, 1)
    .add(cube, { rotateY: [16, -8], rotateX: [10, 9], duration: 900 }, 1)
    .add(slabs, { y: function (el, i, targets) { return [spread(el, i, targets), 0]; }, duration: 600 }, 50)
    .add(chosen, { scale: [1.08, 1], duration: 300 }, 450)
    .add(glows, { opacity: [0, 1], duration: 300, delay: A.stagger(80) }, 450)
    .add(locks, { scale: [0, 1], duration: 350, ease: "outBack(2)", delay: A.stagger(80) }, 500);

  /* 04 Release — the cube turns to its right face: RELEASED · deliver · approve · release */
  chapter(3, steps[3], "bottom top", cardLeave)
    .add(chosen, { opacity: [1, 0], x: [0, 12], duration: 250 }, 1)
    .add(cube, { rotateY: [-8, -82], rotateX: [9, 8], duration: 900 }, 50)
    .add(releases, { opacity: [0, 1], x: [10, 0], duration: 250, delay: A.stagger(50) }, 400);

  /* 01 Split — while the hero copy scrolls out: turn, then pull the slabs apart around the centre */
  /* Created last so its opening render is the one that sticks; its window opens exactly at scroll 0
     (the hero top sits `heroTop` px under the viewport top at load) and closes when the hero is out. */
  var heroTop = Math.max(0, Math.round(hero.getBoundingClientRect().top + window.scrollY));
  var split = chapter(0, hero, "top+=" + heroTop + " top", "top bottom")
    .add(cube, { rotateY: [-34, 16], rotateX: [14, 10], duration: 1000 }, 0)
    .add(slabs, { y: function (el, i, targets) { return [0, spread(el, i, targets)]; }, duration: 700 }, 150)
    .add(titles, { opacity: [0, 1], x: [-8, 0], duration: 350, delay: A.stagger(70) }, 350);

  /* The engine's first tick renders every timeline at time 0: the tweens placed AT 0 paint their "from"
     value, later ones do not. So chapters 02-04 place at position 1 any tween whose "from" is not the
     opening state (others at 0.3, chosen at 1, the cube), and Split is created last so its opening pose
     wins the cube. The sets below cover the parts no timeline paints at time 0 (the CSS pose stays the
     no-JS fallback). */
  if (A.utils && typeof A.utils.set === "function") {
    A.utils.set(cube, { rotateX: 14, rotateY: -34 });
    A.utils.set(titles, { opacity: 0 });
    A.utils.set(glows, { opacity: 0 });
    A.utils.set(locks, { scale: 0 });
    A.utils.set(releases, { opacity: 0 });
  }

  story.classList.add("is-live");
  if (reduced) {
    [split, bid, lock].forEach(function (tl) { tl.seek(tl.duration); });   // the locked pose, parked
    setChapter(2);
  } else {
    setChapter(0);
  }
})();
