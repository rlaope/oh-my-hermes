/*!
 * Oh My Hermes - Start Guide runtime.
 * Reveal on scroll, header auto-hide, section rail, copy buttons, the dag-ulw
 * graph walk-through and the TUI film. No dependencies, no network calls.
 * Language, star count and the language switch come from ../app.js.
 */
(function () {
  "use strict";

  var RM = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function lang() {
    var l = (document.documentElement.lang || "en").toLowerCase();
    return l.indexOf("zh") === 0 ? "zh" : l.split("-")[0];
  }
  function tr(key) {
    var e = window.OMH_I18N && window.OMH_I18N.strings[key];
    if (!e) return null;
    return e[lang()] != null ? e[lang()] : e.en;
  }

  /* header: hide on scroll down, progress bar */
  var top = $("[data-top]"), prog = $("[data-prog]"), lastY = 0;
  window.addEventListener("scroll", function () {
    var y = window.scrollY;
    if (top) top.classList.toggle("hide", y > 160 && y > lastY);
    lastY = y;
    if (prog) prog.style.transform = "scaleX(" + y / Math.max(1, document.documentElement.scrollHeight - window.innerHeight) + ")";
  }, { passive: true });

  /* reveal */
  if (RM || !("IntersectionObserver" in window)) {
    $$(".rv").forEach(function (el) { el.classList.add("in"); });
  } else {
    var rv = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add("in");
        rv.unobserve(e.target);
      });
    }, { threshold: 0.12 });
    $$(".rv").forEach(function (el) { rv.observe(el); });
  }

  /* the rail shows once the hero is behind */
  var railNav = $(".rail"), hero = $(".g-hero");
  if (railNav && hero) {
    var syncRail = function () { railNav.classList.toggle("is-on", hero.getBoundingClientRect().bottom < window.innerHeight * 0.4); };
    window.addEventListener("scroll", syncRail, { passive: true });
    syncRail();
  }

  /* rail scroll-spy */
  var rail = $$(".rail a");
  if (rail.length && "IntersectionObserver" in window) {
    var spy = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        rail.forEach(function (a) { a.classList.toggle("on", a.getAttribute("href") === "#" + e.target.id); });
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    $$("main section[id]").forEach(function (s) { spy.observe(s); });
  }

  /* card glow follows the pointer */
  $$(".g-card").forEach(function (card) {
    card.addEventListener("pointermove", function (e) {
      var b = card.getBoundingClientRect();
      card.style.setProperty("--mx", e.clientX - b.left + "px");
      card.style.setProperty("--my", e.clientY - b.top + "px");
    });
  });

  /* copy */
  $$("[data-copy-text]").forEach(function (button) {
    button.addEventListener("click", function () {
      var text = button.getAttribute("data-copy-text");
      var done = function () {
        button.setAttribute("data-copied", "");
        button.textContent = "✓";
        window.setTimeout(function () {
          button.removeAttribute("data-copied");
          button.textContent = tr("hero.copy") || "Copy";
        }, 1600);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done);
      else done();
    });
  });

  /* dag-ulw graph: layer by layer, then loop (a wide and a phone layout share the walk) */
  $$("[data-gdag]").forEach(function (graph) {
    var nodes = {};
    $$(".n", graph).forEach(function (n) { nodes[n.getAttribute("data-n")] = n; });
    var edges = {};
    $$(".e", graph).forEach(function (e) { edges[e.getAttribute("data-e")] = e; });
    var LAYERS = [["read", "repro"], ["fix"], ["test"], ["verify"]];
    var IN = { fix: ["read-fix", "repro-fix"], test: ["fix-test"], verify: ["test-verify"] };

    var set = function (id, state) {
      var n = nodes[id];
      n.classList.remove("run", "done");
      if (state !== "wait") n.classList.add(state);
      var st = $(".st", n);
      var key = "guide.dag." + state;
      st.setAttribute("data-i18n", key);
      st.textContent = tr(key) || state;
      (IN[id] || []).forEach(function (eid) { edges[eid].classList.toggle("on", state === "run"); });
    };
    var reset = function () { Object.keys(nodes).forEach(function (id) { set(id, "wait"); }); };

    if (RM || !("IntersectionObserver" in window)) {
      Object.keys(nodes).forEach(function (id) { set(id, "done"); });
      return;
    }
    var timer = 0, step = 0, running = false;
    var tick = function () {
      var layer = Math.floor(step / 2), phase = step % 2;
      if (layer >= LAYERS.length) {
        step = 0;
        timer = window.setTimeout(function () { reset(); timer = window.setTimeout(tick, 900); }, 2200);
        return;
      }
      LAYERS[layer].forEach(function (id) { set(id, phase === 0 ? "run" : "done"); });
      step += 1;
      timer = window.setTimeout(tick, phase === 0 ? 1500 : 450);
    };
    reset();
    new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting && !running) { running = true; timer = window.setTimeout(tick, 500); }
        if (!e.isIntersecting && running) { running = false; window.clearTimeout(timer); step = 0; reset(); }
      });
    }, { threshold: 0.35 }).observe(graph);
  });

  /* TUI film plays only while it is on screen */
  var vid = $("[data-gvid]");
  if (vid && !RM && "IntersectionObserver" in window) {
    new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting) { var p = vid.play(); if (p && p.catch) p.catch(function () {}); }
        else vid.pause();
      });
    }, { threshold: 0.3 }).observe(vid);
  }
})();
