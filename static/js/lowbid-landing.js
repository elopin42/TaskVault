/* Lowbid landing: the scroll story — the CSS 3D « project cube » of templates/core/landing.html, scrubbed
   by anime.js v4 (static/vendor/anime.umd.min.js, global `anime`, loaded right before this file).
   One timeline of four 1000-unit chapters, its playhead bound to the scroll position of
   [data-story-grid] (onScroll, sync: true — no timer, nothing runs when the page does not scroll):
     01 Split    the cube turns and its four task slabs pull apart: one project, four parts to take
     02 Bid      three offers slide in beside every task, the chosen one stays, the others step back
     03 Lock     the slabs close ranks, every task gets its Signal frame and padlock (escrow funded)
     04 Release  the cube turns to its side: RELEASED · deliver · approve · release
   The step cards ([data-story-step]) and the caption follow the active chapter.
   prefers-reduced-motion: the timeline is parked on the locked pose and never moves.
   Without the vendor bundle (or the section) nothing runs: the CSS pose stays as is.
   Only transforms and opacity are animated, on .lb-cube, .lb-slab, .lb-bid and the [data-face-*] spans. */
(function () {
  "use strict";

  var story = document.querySelector("[data-story]");
  var A = window.anime;
  if (!story || !A || typeof A.createTimeline !== "function" || typeof A.onScroll !== "function") return;

  function all(sel) { return Array.prototype.slice.call(story.querySelectorAll(sel)); }

  var track = story.querySelector("[data-story-grid]");
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
  if (!track || !cube || !slabs.length) return;

  var CHAPTER = 1000;                               // timeline units per chapter
  var CHAPTERS = ["Split", "Bid", "Lock", "Deliver, release"];
  var SPREAD = 30;                                  // px between two slabs when the cube is pulled apart
  var reduced = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var current = -1;

  function setChapter(i) {
    if (i === current) return;
    current = i;
    steps.forEach(function (el, k) { el.classList.toggle("is-active", k === i); });
    if (captionNo) captionNo.textContent = "0" + (i + 1);
    if (caption) caption.textContent = CHAPTERS[i] || "";
  }

  /* Tweens that start later in the timeline do not apply their "from" value up front: park those
     parts on their chapter-01 state before the first render (the CSS pose stays the no-JS fallback). */
  if (A.utils && typeof A.utils.set === "function") {
    A.utils.set(titles, { opacity: 0 });
    A.utils.set(glows, { opacity: 0 });
    A.utils.set(locks, { scale: 0 });
    A.utils.set(releases, { opacity: 0 });
  }

  var tl = A.createTimeline({
    defaults: { ease: "inOut(2)" },
    autoplay: reduced ? false : A.onScroll({ target: track, enter: "top+=80 top", leave: "bottom bottom", sync: true }),
    onUpdate: function (self) {
      setChapter(Math.max(0, Math.min(CHAPTERS.length - 1, Math.floor(self.currentTime / CHAPTER))));
    }
  });

  /* 01 Split — turn, then pull the slabs apart around the cube's centre */
  tl.add(cube, { rotateY: [-34, 16], rotateX: [14, 10], duration: CHAPTER }, 0)
    .add(slabs, { y: function (_, i, targets) { return [0, (i - (targets.length - 1) / 2) * SPREAD]; }, duration: 700 }, 150)
    .add(titles, { opacity: [0, 1], x: [-8, 0], duration: 350, delay: A.stagger(70) }, 350)
  /* 02 Bid — twelve offers slide in (done by 1685), then the two losers step back and the chosen one grows */
    .add(bids, { x: [40, 0], opacity: [0, 1], duration: 300, delay: A.stagger(35) }, CHAPTER)
    .add(others, { opacity: 0.3, x: 8, duration: 250 }, 1720)
    .add(chosen, { scale: [1, 1.08], duration: 250 }, 1720)
  /* 03 Lock — losers gone, slabs close ranks, Signal frame + padlock on every task */
    .add(others, { opacity: 0, duration: 200 }, 2 * CHAPTER)
    .add(cube, { rotateY: -8, rotateX: 9, duration: 900 }, 2 * CHAPTER)
    .add(slabs, { y: 0, duration: 600 }, 2 * CHAPTER + 50)
    .add(chosen, { scale: 1, duration: 300 }, 2 * CHAPTER + 450)
    .add(glows, { opacity: [0, 1], duration: 300, delay: A.stagger(80) }, 2 * CHAPTER + 450)
    .add(locks, { scale: [0, 1], duration: 350, ease: "outBack(2)", delay: A.stagger(80) }, 2 * CHAPTER + 500)
  /* 04 Release — the cube turns to its right face: RELEASED · deliver · approve · release */
    .add(chosen, { opacity: 0, x: 12, duration: 250 }, 3 * CHAPTER)
    .add(cube, { rotateY: -82, rotateX: 8, duration: 900 }, 3 * CHAPTER + 50)
    .add(releases, { opacity: [0, 1], x: [10, 0], duration: 250, delay: A.stagger(50) }, 3 * CHAPTER + 400);

  story.classList.add("is-live");
  if (reduced) {
    tl.seek(3 * CHAPTER - 1);                       // the locked pose, parked
    setChapter(2);
  } else {
    setChapter(0);
  }
})();
