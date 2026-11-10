/*!
 * Oh My Hermes - site runtime.
 * Language switch, theme toggle, copy buttons, and the demo pause control.
 * No dependencies, no network calls.
 */
(function () {
  "use strict";

  var LANG_KEY = "omh.lang";
  var THEME_KEY = "omh.theme";
  var FALLBACK = "en";
  var currentLang = FALLBACK;

  function readStore(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (err) {
      return null;
    }
  }

  function writeStore(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (err) {
      /* storage unavailable (private mode); the choice still applies to this page */
    }
  }

  /* =============================================================== i18n */

  var I18N = window.OMH_I18N || { meta: {}, strings: {} };
  var SUPPORTED = Object.keys(I18N.meta);

  function normalize(tag) {
    if (!tag) return null;
    var lower = String(tag).toLowerCase();
    if (lower.indexOf("zh") === 0) return SUPPORTED.indexOf("zh") > -1 ? "zh" : null;
    var base = lower.split("-")[0];
    return SUPPORTED.indexOf(base) > -1 ? base : null;
  }

  // English by default. Localization is an explicit choice (?lang= or the
  // header switch), never inferred from the browser or OS locale.
  function initialLang() {
    var fromQuery = new URLSearchParams(window.location.search).get("lang");
    return normalize(fromQuery) || normalize(readStore(LANG_KEY)) || FALLBACK;
  }

  function translate(key, lang) {
    var entry = I18N.strings[key];
    if (!entry) return null;
    return entry[lang] != null ? entry[lang] : entry[FALLBACK];
  }

  function applyLang(lang) {
    currentLang = lang;
    var meta = I18N.meta[lang] || I18N.meta[FALLBACK];
    document.documentElement.lang = (meta && meta.htmlLang) || lang;

    document.querySelectorAll("[data-i18n]").forEach(function (node) {
      var value = translate(node.getAttribute("data-i18n"), lang);
      if (value != null) node.textContent = value;
    });

    // Trusted, author-owned markup from i18n.js only.
    document.querySelectorAll("[data-i18n-html]").forEach(function (node) {
      var value = translate(node.getAttribute("data-i18n-html"), lang);
      if (value != null) node.innerHTML = value;
    });

    // "attr:key" pairs, comma separated.
    document.querySelectorAll("[data-i18n-attr]").forEach(function (node) {
      node.getAttribute("data-i18n-attr").split(",").forEach(function (pair) {
        var parts = pair.split(":");
        if (parts.length !== 2) return;
        var value = translate(parts[1].trim(), lang);
        if (value != null) node.setAttribute(parts[0].trim(), value);
      });
    });

    var current = document.querySelector("[data-lang-current]");
    if (current && meta) current.textContent = meta.short;

    document.querySelectorAll(".langswitch__menu [data-lang]").forEach(function (button) {
      var option = button.closest("[role='option']");
      if (option) option.setAttribute("aria-selected", String(button.dataset.lang === lang));
    });

    syncDemoLabel();
    renderCounts();
    writeStore(LANG_KEY, lang);
  }

  function initLangSwitch() {
    var root = document.querySelector("[data-lang-switch]");
    if (!root) return;

    var button = root.querySelector(".langswitch__button");
    var menu = root.querySelector(".langswitch__menu");
    if (!button || !menu) return;

    function close() {
      menu.hidden = true;
      button.setAttribute("aria-expanded", "false");
    }

    function open() {
      menu.hidden = false;
      button.setAttribute("aria-expanded", "true");
      var selected = menu.querySelector("[aria-selected='true'] button") || menu.querySelector("button");
      if (selected) selected.focus();
    }

    button.addEventListener("click", function (event) {
      event.stopPropagation();
      if (menu.hidden) open();
      else close();
    });

    menu.addEventListener("click", function (event) {
      var choice = event.target.closest("[data-lang]");
      if (!choice) return;
      applyLang(choice.dataset.lang);
      close();
      button.focus();
    });

    document.addEventListener("click", function (event) {
      if (!root.contains(event.target)) close();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || menu.hidden) return;
      close();
      button.focus();
    });

    menu.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      var items = Array.prototype.slice.call(menu.querySelectorAll("button"));
      var index = items.indexOf(document.activeElement);
      var next = event.key === "ArrowDown" ? index + 1 : index - 1;
      items[(next + items.length) % items.length].focus();
    });
  }

  /* ============================================================== theme */

  // With no saved choice the stylesheet follows prefers-color-scheme; the
  // toggle flips whatever is showing and remembers it.
  function shownTheme() {
    var set = document.documentElement.dataset.theme;
    if (set === "light" || set === "dark") return set;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function initTheme() {
    var toggle = document.querySelector("[data-theme-toggle]");
    if (!toggle) return;
    toggle.addEventListener("click", function () {
      var next = shownTheme() === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      writeStore(THEME_KEY, next);
    });
  }

  /* =============================================================== copy */

  function initCopy() {
    document.querySelectorAll("[data-copy]").forEach(function (button) {
      button.addEventListener("click", function () {
        var source = document.querySelector(button.getAttribute("data-copy"));
        if (!source || !navigator.clipboard) return;
        navigator.clipboard.writeText(source.textContent.trim()).then(function () {
          button.setAttribute("data-copied", "");
          button.textContent = "✓";
          window.setTimeout(function () {
            button.removeAttribute("data-copied");
            button.textContent = translate("hero.copy", currentLang) || "Copy";
          }, 1600);
        });
      });
    });
  }

  /* =============================================================== demo */

  var demo = document.querySelector("[data-demo]");
  var demoToggle = document.querySelector("[data-demo-toggle]");

  function syncDemoLabel() {
    if (!demo || !demoToggle) return;
    var paused = demo.paused;
    demoToggle.textContent = translate(paused ? "dag.play" : "dag.pause", currentLang) || (paused ? "Play" : "Pause");
  }

  function initDemo() {
    if (!demo || !demoToggle) return;
    // Reduced motion: keep the poster (the finished graph) until asked.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      demo.removeAttribute("autoplay");
      demo.pause();
    }
    demoToggle.addEventListener("click", function () {
      if (demo.paused) demo.play();
      else demo.pause();
    });
    demo.addEventListener("play", syncDemoLabel);
    demo.addEventListener("pause", syncDemoLabel);
    syncDemoLabel();
  }

  /* ========================================================== DAG graph */

  // The illustration of the demo run's graph. Hover or focus a lane to trace
  // what it waits on and what it feeds; Replay steps the layers through
  // waiting, running, and accepted. Reduced motion keeps the static view.
  function initDag() {
    var root = document.querySelector("[data-dag]");
    if (!root) return;
    var svg = root.querySelector("svg");
    var nodes = Array.prototype.slice.call(root.querySelectorAll(".dag-node"));
    var edges = Array.prototype.slice.call(root.querySelectorAll(".dag-edge"));
    var replay = root.querySelector("[data-dag-replay]");
    var live = root.querySelector("[data-dag-live]");

    function walk(start, key, other) {
      var seen = {};
      var queue = [start];
      while (queue.length) {
        var id = queue.shift();
        edges.forEach(function (edge) {
          if (edge.dataset[key] !== id) return;
          var next = edge.dataset[other];
          if (seen[next]) return;
          seen[next] = true;
          queue.push(next);
        });
      }
      return seen;
    }

    function trace(id) {
      var up = walk(id, "to", "from");
      var down = walk(id, "from", "to");
      svg.classList.add("is-tracing");
      nodes.forEach(function (node) {
        var nid = node.dataset.node;
        node.classList.toggle("is-active", nid === id);
        node.classList.toggle("is-lineage", nid === id || !!up[nid] || !!down[nid]);
      });
      edges.forEach(function (edge) {
        var from = edge.dataset.from;
        var to = edge.dataset.to;
        var upstream = (to === id || up[to]) && (up[from] || from === id);
        var downstream = (from === id || down[from]) && (down[to] || to === id);
        edge.classList.toggle("is-lineage", !!(upstream || downstream));
      });
    }

    function clear() {
      svg.classList.remove("is-tracing");
      nodes.forEach(function (node) {
        node.classList.remove("is-active", "is-lineage");
      });
      edges.forEach(function (edge) {
        edge.classList.remove("is-lineage");
      });
    }

    nodes.forEach(function (node) {
      node.addEventListener("pointerenter", function () { trace(node.dataset.node); });
      node.addEventListener("pointerleave", function () {
        if (document.activeElement === node) trace(node.dataset.node);
        else clear();
      });
      node.addEventListener("focus", function () { trace(node.dataset.node); });
      node.addEventListener("blur", clear);
    });

    if (!replay) return;
    var timers = [];
    var LAYERS = 4;
    var STEP = 1300;

    function say(key, layer) {
      var text = translate(key, currentLang) || "";
      if (live) live.textContent = text.replace("{n}", layer);
    }

    function setLayer(layer, state) {
      nodes.forEach(function (node) {
        if (Number(node.dataset.layer) === layer) node.dataset.state = state;
      });
      edges.forEach(function (edge) {
        var target = root.querySelector('.dag-node[data-node="' + edge.dataset.to + '"]');
        if (!target) return;
        if (target.dataset.state === "waiting") edge.dataset.state = "idle";
        else edge.removeAttribute("data-state");
      });
    }

    replay.addEventListener("click", function () {
      timers.forEach(window.clearTimeout);
      timers = [];
      replay.disabled = true;
      nodes.forEach(function (node) { node.dataset.state = "waiting"; });
      setLayer(0, "waiting");
      for (var layer = 1; layer <= LAYERS; layer += 1) {
        (function (k) {
          timers.push(window.setTimeout(function () {
            setLayer(k, "running");
            say("dag.graph.running", k);
          }, (k - 1) * STEP + 200));
          timers.push(window.setTimeout(function () {
            setLayer(k, "done");
            if (k === LAYERS) {
              say("dag.graph.done", k);
              replay.disabled = false;
            }
          }, k * STEP));
        })(layer);
      }
    });
  }

  /* ======================================================== star + installs */

  // The header shows the repository's stars and the npm package's all-time
  // downloads. Both come from public JSON APIs, are cached for an hour, and
  // fail quietly. The deploy bakes the real star count into every
  // [data-stars] / [data-star-count] element (tools/stamp_site_counts.py
  // writes data-stars="5311" and the compact text), so the number shows
  // before any request and a cached or fetched count only ever raises it.
  var COUNTS_KEY = "omh.counts";
  var COUNTS_TTL = 60 * 60 * 1000;
  // First npm publish of oh-my-hermes; the all-time range starts here.
  var NPM_FIRST_PUBLISH = "2026-08-14";
  var counts = { stars: null, installs: null };

  function compact(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (n >= 1e5) return Math.round(n / 1e3) + "k";
    if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  var STAR_SLOTS = "[data-stars], [data-star-count]";

  // The highest count the deploy baked into the page, or null.
  function bakedStars() {
    var best = null;
    Array.prototype.forEach.call(document.querySelectorAll(STAR_SLOTS), function (el) {
      var raw = el.getAttribute("data-stars") || el.getAttribute("data-star-count") || "";
      var n = /^\d+$/.test(raw) ? parseInt(raw, 10) : NaN;
      if (!isNaN(n) && (best === null || n > best)) best = n;
    });
    return best;
  }

  // Raise the shown star count; a lower figure (an old cache, a lagging
  // API answer) never replaces a higher one.
  function raiseStars(n) {
    if (typeof n !== "number" || isNaN(n)) return false;
    if (typeof counts.stars === "number" && n < counts.stars) return false;
    counts.stars = n;
    return true;
  }

  function renderCounts() {
    if (typeof counts.stars === "number") {
      Array.prototype.forEach.call(document.querySelectorAll("[data-stars]"), function (el) {
        el.textContent = compact(counts.stars);
      });
    }
    var star = document.querySelector("[data-gh-star]");
    var starCount = document.querySelector("[data-star-count]");
    if (star && starCount && typeof counts.stars === "number") {
      starCount.textContent = compact(counts.stars);
      starCount.hidden = false;
      var label = translate("nav.star.label", currentLang) || "Star oh-my-hermes on GitHub";
      var stars = (translate("nav.star.stars", currentLang) || "{n} stars").replace("{n}", compact(counts.stars));
      star.setAttribute("aria-label", label + ", " + stars);
    }
    var installs = document.querySelector("[data-installs]");
    var installsCount = document.querySelector("[data-installs-count]");
    if (installs && installsCount && typeof counts.installs === "number") {
      installsCount.textContent = compact(counts.installs);
      installs.hidden = false;
    }
  }

  function getJSON(url) {
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var timer = controller ? window.setTimeout(function () { controller.abort(); }, 6000) : 0;
    return window.fetch(url, { signal: controller ? controller.signal : undefined, headers: { Accept: "application/json" } })
      .then(function (response) {
        window.clearTimeout(timer);
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      });
  }

  function npmDownloads() {
    var today = new Date().toISOString().slice(0, 10);
    var base = "https://api.npmjs.org/downloads/point/";
    return getJSON(base + NPM_FIRST_PUBLISH + ":" + today + "/oh-my-hermes")
      .catch(function () {
        // The range API stops at 18 months; fall back to the last year.
        return getJSON(base + "last-year/oh-my-hermes");
      })
      .then(function (data) {
        if (typeof data.downloads !== "number") throw new Error("no downloads");
        return data.downloads;
      });
  }

  function initCounts() {
    var wantStars = !!document.querySelector(STAR_SLOTS);
    var wantInstalls = !!document.querySelector("[data-installs]");
    if (!wantStars && !wantInstalls) return;
    raiseStars(bakedStars());
    var cached = null;
    try {
      cached = JSON.parse(readStore(COUNTS_KEY) || "null");
    } catch (err) {
      cached = null;
    }
    if (cached) {
      if (typeof cached.stars === "number") raiseStars(cached.stars);
      counts.installs = typeof cached.installs === "number" ? cached.installs : null;
    }
    renderCounts();
    var fresh = cached && Date.now() - cached.t < COUNTS_TTL;
    var needStars = wantStars && !(fresh && typeof cached.stars === "number");
    var needInstalls = wantInstalls && !(fresh && typeof cached.installs === "number");
    if ((!needStars && !needInstalls) || typeof window.fetch !== "function") return;
    function save() {
      writeStore(COUNTS_KEY, JSON.stringify({ t: Date.now(), stars: counts.stars, installs: counts.installs }));
    }
    if (needStars) {
      getJSON("https://api.github.com/repos/rlaope/oh-my-hermes")
        .then(function (repo) {
          if (typeof repo.stargazers_count !== "number") return;
          raiseStars(repo.stargazers_count);
          renderCounts();
          save();
        })
        .catch(function () { /* keep the baked or cached number */ });
    }
    if (needInstalls) {
      npmDownloads()
        .then(function (downloads) {
          counts.installs = downloads;
          renderCounts();
          save();
        })
        .catch(function () { /* keep the install count hidden */ });
    }
  }

  /* =============================================================== aura */

  // The beam ends on the version badge, the pointer glow follows the cursor
  // inside the hero, and the hero aura fades as it scrolls away. A band that
  // leaves the viewport, or a hidden tab, pauses its animations.
  function initAura() {
    var bands = Array.prototype.slice.call(document.querySelectorAll("[data-aura]"));
    if (!bands.length) return;
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var hero = document.querySelector(".hero");
    var heroAura = hero && hero.querySelector("[data-aura]");
    var badge = hero && hero.querySelector(".hero__badge");

    function placeBeam() {
      if (!heroAura || !badge) return;
      heroAura.style.setProperty("--beam-h", Math.round(badge.offsetTop + badge.offsetHeight / 2) + "px");
    }
    placeBeam();
    window.addEventListener("resize", placeBeam);
    window.addEventListener("load", placeBeam);

    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) entry.target.removeAttribute("data-aura-paused");
          else entry.target.setAttribute("data-aura-paused", "");
        });
      });
      bands.forEach(function (aura) { observer.observe(aura.parentElement); });
    }
    document.addEventListener("visibilitychange", function () {
      bands.forEach(function (aura) {
        if (document.hidden) aura.parentElement.setAttribute("data-aura-paused", "");
      });
      if (document.hidden) return;
      placeBeam();
      bands.forEach(function (aura) {
        var box = aura.parentElement.getBoundingClientRect();
        if (box.bottom > 0 && box.top < window.innerHeight) aura.parentElement.removeAttribute("data-aura-paused");
      });
    });

    if (reduce || !hero || !heroAura) return;

    var spot = heroAura.querySelector("[data-aura-spot]");
    var frame = 0;
    var pointer = null;
    function paint() {
      frame = 0;
      if (spot && pointer) {
        spot.style.transform = "translate3d(" + pointer.x + "px, " + pointer.y + "px, 0)";
      }
      var fade = 1 - Math.min(window.scrollY / Math.max(hero.offsetHeight, 1), 1) * 0.7;
      heroAura.style.setProperty("--aura-fade", fade.toFixed(3));
    }
    function schedule() {
      if (!frame) frame = window.requestAnimationFrame(paint);
    }
    hero.addEventListener("pointermove", function (event) {
      if (event.pointerType === "touch") return;
      var box = hero.getBoundingClientRect();
      pointer = { x: event.clientX - box.left, y: event.clientY - box.top };
      if (spot) spot.classList.add("is-on");
      schedule();
    });
    hero.addEventListener("pointerleave", function () {
      if (spot) spot.classList.remove("is-on");
    });
    window.addEventListener("scroll", schedule, { passive: true });
  }

  initAura();
  initCounts();
  initDag();
  initDemo();
  initLangSwitch();
  initTheme();
  initCopy();
  applyLang(initialLang());
})();
