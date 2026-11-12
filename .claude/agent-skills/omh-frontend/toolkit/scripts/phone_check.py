#!/usr/bin/env python3
"""Original OMH phone-viewport measuring helper; MIT, copyright 2026 OMH contributors.

Opens one page in a touch- and mobile-emulating Chromium context and prints
numbers as one JSON object. It carries no verdict words: the frontend skill's
references decide what a number means. Playwright is optional and imported only
when a page is actually measured, so `--help` works on a bare interpreter.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse

SCHEMA = "omh_phone_check/v1"
PHONE = {"width": 390, "height": 844, "device_scale_factor": 3}
DESKTOP = {"width": 1440, "height": 900, "device_scale_factor": 1}
PHONE_USER_AGENT = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
MIN_TARGET_PX = 44
MIN_INPUT_FONT_PX = 16
LIST_LIMIT = 20
DEFAULT_TIMEOUT_S = 30.0
MAX_TIMEOUT_S = 300.0
MIN_SIDE_PX, MAX_SIDE_PX = 200, 4000
DEFAULT_DATA_SELECTOR = "table tbody tr, [role=row], li, article"
TARGET_SELECTOR = "a, button, [role=button], input, select, summary"
FIELD_SELECTOR = "input, select, textarea"
ACTION_SELECTOR = "a[href], button"
# Input types that take no typed text, so focusing them never zooms the page.
NON_TEXT_INPUT_TYPES = ("checkbox", "radio", "button", "submit", "reset", "file", "image", "range",
                        "color", "hidden")
NO_DATA_HINT = "no row-like element found; pass --data '<css selector>' for the first data row"
PAST_EDGE_NOTE = ("an element clipped by an overflow:hidden ancestor can appear here; "
                  "the overflow number above is the verdict, this list only points")
PAST_LEFT_EDGE_NOTE = ("this page starts at its right edge and overflows to the left, so this lists elements "
                       "whose left edge lies left of page x 0, a document coordinate and not the screen's "
                       "left edge at load; " + PAST_EDGE_NOTE)

# One fixed script; every user string reaches it as a plain argument, never as code.
# It classifies every shown element in the page and returns a count over all of
# them; only the listed examples stop at `list_limit`, so output stays bounded.
PAGE_SCRIPT = """
async (opts) => {
  const doc = document.documentElement;
  const sx = window.scrollX, sy = window.scrollY;
  // The page's start side comes from the writing mode and direction of
  // <body>, the principal writing mode: <html dir="rtl"><body dir="ltr">
  // starts at the left, body{direction:rtl} at the right, a vertical-rl page
  // at the right. A page that starts at its right edge holds that edge at the
  // scrolling box's client width in page px, cannot scroll past it, and
  // overflows to the left instead (scrollX goes negative).
  const principal = getComputedStyle(document.body || doc);
  const startsRight = (style) => /^(vertical|sideways)-/.test(style.writingMode)
    ? style.writingMode.endsWith('-rl') : style.direction === 'rtl';
  const startRight = startsRight(principal);
  const scroller = document.scrollingElement || doc;
  const startEdge = scroller.clientWidth;
  const r1 = (v) => Math.round(v * 10) / 10;
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  const path = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      let part = node.localName;
      if (node.id) { parts.unshift(part + '#' + CSS.escape(node.id)); break; }
      const same = node.parentElement
        ? Array.from(node.parentElement.children).filter((c) => c.localName === node.localName) : [];
      if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(node) + 1) + ')';
      parts.unshift(part);
      if (node === document.body) break;
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const firstShown = (selector) => {
    for (const el of document.querySelectorAll(selector)) {
      if (shown(el)) return el;
    }
    return null;
  };
  // A box fixed to the viewport does not move with the page, so its place is
  // its viewport rectangle; adding the scroll offset would put a control parked
  // above the screen back inside the page once the page has scrolled.
  // `position: fixed` alone does not say that: under an ancestor with a
  // transform, a filter or paint containment the box is fixed to that ancestor
  // and scrolls with the page. Chromium gives such a box that ancestor as its
  // offsetParent and gives a box fixed to the viewport none, so the walk goes
  // on from the ancestor, which may itself be fixed to the viewport.
  const fixedToViewport = (el) => {
    let node = el;
    while (node && node.nodeType === 1) {
      if (getComputedStyle(node).position === 'fixed') {
        if (!node.offsetParent) return true;
        node = node.offsetParent;
      } else {
        node = node.parentElement;
      }
    }
    return false;
  };
  const top = (el) => {
    if (!el) return null;
    return r1(el.getBoundingClientRect().top + (fixedToViewport(el) ? 0 : sy));
  };
  // A box is on the page when it reaches below the top and past the start
  // edge, the two sides the page cannot scroll beyond. On a page that starts
  // at the right the start edge is the right one, at `startEdge` in page px;
  // the left, where such a page overflows, is reachable as far as the page
  // scrolls: `farEdge` is the left end of that range in page px, 0 on a page
  // that does not overflow. Paint alone does not widen it: content under
  // layout containment is drawn left of page x 0 and cannot be panned to. A
  // quirks-mode page can have no scrolling element, and then nothing in the
  // page reports how far it scrolls (the root's scrollWidth stays at the
  // client width while the page pans). The browser's own content width, read
  // by the caller before this runs, is used there; without it no far end is
  // applied. A box fixed to the
  // viewport is judged by its viewport box: the reader pans the screen over
  // the layout viewport, client x 0 to innerWidth, and the scroll position
  // cannot bring anything outside that band into view.
  const scrollRange = document.scrollingElement ? scroller.scrollWidth : opts.content_width;
  const farEdge = typeof scrollRange === 'number' ? startEdge - scrollRange : -Infinity;
  const onPageFromRight = (el, r) => {
    if (fixedToViewport(el)) return r.bottom > 0 && r.left < window.innerWidth && r.right > 0;
    return r.bottom + sy > 0 && r.left + sx < startEdge && r.right + sx > farEdge;
  };
  const onPage = (el) => {
    const r = el.getBoundingClientRect();
    if (startRight) return onPageFromRight(el, r);
    if (fixedToViewport(el)) return r.bottom > 0 && r.right > 0;
    return r.bottom + sy > 0 && r.right + sx > 0;
  };
  const firstOnPage = (selector) => {
    for (const el of document.querySelectorAll(selector)) {
      if (shown(el) && onPage(el)) return el;
    }
    return null;
  };
  // The edge test above is all a page that starts at the left gets. On a page
  // that starts at the right the far side is the left, where a site built
  // left-to-right parks its skip link (left: -9999px), so there a box counts
  // only when a scroll or a pan can put part of it on screen. Two things say
  // so, and neither is a list of properties that clip:
  // - IntersectionObserver reports the part of a box left after every
  //   ancestor's clip, wherever on the page that part is: the root margin
  //   takes the screen's own edges out of the answer.
  // - Content moves under the reader's hand only in a box that offers a
  //   scroll: `overflow` auto or scroll, and the viewport unless hidden or
  //   clip reached it from <html>, or from <body> when <html> leaves both axes
  //   visible. A page whose viewport is held reports the same scrollX,
  //   innerWidth and scrollWidth as one that scrolls; only the pan differs,
  //   and it stops at the layout viewport, client x 0 to innerWidth, the band
  //   a box fixed to the viewport is judged by.
  const offersScroll = (value) => value === 'auto' || value === 'scroll';
  const rootStyle = getComputedStyle(doc);
  const viewportFromBody = Boolean(document.body)
    && rootStyle.overflowX === 'visible' && rootStyle.overflowY === 'visible';
  const viewportOverflow = (viewportFromBody ? principal : rootStyle).overflowX;
  const pageScrolls = viewportOverflow === 'visible' || offersScroll(viewportOverflow);
  const anywhere = '10000000px';
  // One observer round takes a frame however many boxes it watches, so boxes
  // are asked about together, never one by one.
  const partLeft = (els, root, rootMargin) => new Promise((resolve) => {
    const observer = new IntersectionObserver((entries) => {
      observer.disconnect();
      resolve(new Map(entries.map((entry) => [entry.target, entry.intersectionRect])));
    }, {root, rootMargin});
    for (const el of els) observer.observe(el);
  });
  const hasArea = (rect) => Boolean(rect) && rect.width > 0 && rect.height > 0;
  // `part` is what is left of a box that scrolls with the page: where the
  // viewport scrolls it is held to the start edge like the box itself, and
  // where the viewport is held, to the band the screen pans over.
  const inReach = (el, part) => pageScrolls ? onPageFromRight(el, part)
    : part.bottom + sy > 0 && part.left < window.innerWidth && part.right > 0;
  // The nearest box at or above `node` that offers a scroll and has somewhere
  // to scroll to, with its scrollport grown by how far it still scrolls each
  // way: what the reader can bring into it. <body> is not such a box while
  // the viewport has taken its overflow.
  // How far a box still scrolls toward lower and toward higher positions. It
  // scrolls from 0 up to `d`, or from -`d` up to 0. Away from 0 the sign of
  // the position says which. At 0 the box's start corner does: a box scrolls
  // away from the corner its content starts in, which is block-start and
  // inline-start, or main-start and cross-start for a flex container, the
  // legacy `-webkit-box` included (CSS Overflow, on unreachable scrollable
  // overflow). This reads the box's
  // writing mode, direction and flex flow and moves nothing: scrolling the box
  // to ask runs the page's own scroll listeners in the middle of a
  // measurement, and what they add is then counted.
  const across = {left: 'right', right: 'left', top: 'bottom', bottom: 'top'};
  const startCorner = (style) => {
    const mode = style.writingMode;
    const rtl = style.direction === 'rtl';
    let block = 'top', inline = rtl ? 'right' : 'left';
    if (/^(vertical|sideways)-/.test(mode)) {
      block = mode.endsWith('-rl') ? 'right' : 'left';
      inline = (mode === 'sideways-lr') !== rtl ? 'bottom' : 'top';
    }
    let sides = [block, inline];
    const legacy = style.display === '-webkit-box' || style.display === '-webkit-inline-box';
    if (legacy || style.display === 'flex' || style.display === 'inline-flex') {
      const column = legacy ? style.webkitBoxOrient === 'vertical' : style.flexDirection.startsWith('column');
      const reverse = legacy ? style.webkitBoxDirection === 'reverse' : style.flexDirection.endsWith('-reverse');
      let main = column ? block : inline, cross = column ? inline : block;
      if (reverse) main = across[main];
      if (!legacy && style.flexWrap === 'wrap-reverse') cross = across[cross];
      sides = [main, cross];
    }
    return {right: sides.includes('right'), bottom: sides.includes('bottom')};
  };
  const travel = (at, d, fromEnd) => at > 0 ? [Math.min(d, at), Math.max(0, d - at)]
    : at < 0 ? [Math.max(0, d + at), Math.min(d, -at)]
    : fromEnd ? [d, 0] : [0, d];
  // Content the browser has not rendered yet (`content-visibility: auto`, off
  // screen) has no part an observer can report, though scrolling to it renders
  // it. The browser says which boxes those are. What clips such a box shows
  // only once it is rendered, and this script does not move the page to render
  // it. So it counts when its own box passes the edge test a page that starts
  // at the left gets, below the top and right of page x 0, unless the box that
  // skips it is known to stay off screen: that box cannot be reached and does
  // not paint past its own edge. A clip inside the skipped content is not seen.
  const rendered = (el) => typeof el.checkVisibility !== 'function'
    || el.checkVisibility({contentVisibilityAuto: true});
  const renderSkipped = (el) => typeof el.checkVisibility === 'function'
    && el.checkVisibility() && !rendered(el);
  const skippedBy = (el) => {
    let box = el.parentElement;
    while (box && !rendered(box)) box = box.parentElement;
    return box;
  };
  // A box with a positive `overflow-clip-margin` paints what it holds past
  // its own edge, and the browser renders it when that larger area comes on
  // screen, so where the box itself lies does not say whether its content can
  // be reached.
  const paintsPastItsEdge = (box) => {
    const margin = /(-?[0-9.]+)px/.exec(getComputedStyle(box).overflowClipMargin || '');
    return Boolean(margin) && parseFloat(margin[1]) > 0;
  };
  const pastTopAndLeft = (el) => {
    const r = el.getBoundingClientRect();
    return r.bottom + sy > 0 && r.right + sx > 0;
  };
  const scrollBoxAbove = (node) => {
    for (let box = node; box && box !== doc; box = box.parentElement) {
      if (box === document.body && viewportFromBody) continue;
      const style = getComputedStyle(box);
      const dx = offersScroll(style.overflowX) ? Math.max(0, box.scrollWidth - box.clientWidth) : 0;
      const dy = offersScroll(style.overflowY) ? Math.max(0, box.scrollHeight - box.clientHeight) : 0;
      if (!dx && !dy) continue;
      const corner = startCorner(style);
      const [left, right] = travel(box.scrollLeft, dx, corner.right);
      const [up, down] = travel(box.scrollTop, dy, corner.bottom);
      return {node: box, grown: [up, right, down, left].map((px) => px + 'px').join(' ')};
    }
    return null;
  };
  // A box clipped where it stands may still be brought in by an ancestor that
  // scrolls, when that ancestor is reachable itself; the grown scrollport
  // keeps every clip between the two.
  const reach = new Map();
  const settle = async (els) => {
    const moving = [];
    for (const el of els) {
      if (reach.has(el)) continue;
      if (fixedToViewport(el)) reach.set(el, onPage(el)); else moving.push(el);
    }
    if (!moving.length) return;
    const parts = await partLeft(moving, null, anywhere);
    let pending = [];
    const skipped = [];
    for (const el of moving) {
      const part = parts.get(el);
      if (hasArea(part) && inReach(el, part)) reach.set(el, true);
      else if (renderSkipped(el)) skipped.push({el, by: skippedBy(el)});
      else pending.push({el, box: scrollBoxAbove(el.parentElement)});
    }
    if (skipped.length) {
      await settle(Array.from(new Set(skipped.map((item) => item.by).filter(Boolean))));
      for (const {el, by} of skipped) {
        reach.set(el, Boolean(by) && (reach.get(by) === true || paintsPastItsEdge(by)) && pastTopAndLeft(el));
      }
    }
    while (pending.length) {
      const groups = new Map();
      for (const item of pending) {
        if (!item.box) { reach.set(item.el, false); continue; }
        if (!groups.has(item.box.node)) groups.set(item.box.node, {box: item.box, els: []});
        groups.get(item.box.node).els.push(item.el);
      }
      const batches = Array.from(groups.values());
      const seen = await Promise.all(batches.map((batch) => partLeft(batch.els, batch.box.node, batch.box.grown)));
      await settle(batches.filter((batch, i) => batch.els.some((el) => hasArea(seen[i].get(el))))
        .map((batch) => batch.box.node));
      pending = [];
      batches.forEach((batch, i) => {
        for (const el of batch.els) {
          if (hasArea(seen[i].get(el)) && reach.get(batch.box.node)) reach.set(el, true);
          else pending.push({el, box: scrollBoxAbove(batch.box.node.parentElement)});
        }
      });
    }
  };
  const firstReachable = async (selector) => {
    const els = Array.from(document.querySelectorAll(selector)).filter(shown);
    await settle(els);
    return els.find((el) => reach.get(el)) || null;
  };
  const textEntry = (el) => el.localName !== 'input' || !opts.non_text_types.includes(el.type);
  const out = {};
  const meta = document.querySelector('meta[name=viewport]');
  out.viewport_meta = meta ? meta.getAttribute('content') : null;
  // On a page that starts at its right edge the root's own scrollWidth misses
  // an absolutely placed box overflowing to the left; the scrolling element's
  // scrollWidth is the width the reader pans over. Left-to-right pages keep
  // the root's number.
  out.start_right = startRight;
  out.scroll_width = startRight ? scroller.scrollWidth : doc.scrollWidth;
  out.client_width = doc.clientWidth;
  out.inner_width = window.innerWidth;
  out.document_height = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0);

  out.past_right = [];
  out.past_right_total = 0;
  for (const el of document.querySelectorAll('body, body *')) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    if (startRight) {
      // Mirror of the rule below: the overflowing side is the left. At the
      // requested width such a page runs from page x 0 to the start edge, so
      // a box whose left edge is below page x 0 lies in the left overflow.
      const left = r.left + sx;
      if (left < -0.5) {
        out.past_right_total += 1;
        if (out.past_right.length < opts.list_limit) out.past_right.push({path: path(el), left: r1(left)});
      }
      continue;
    }
    const right = r.right + sx;
    if (right > opts.width + 0.5) {
      out.past_right_total += 1;
      if (out.past_right.length < opts.list_limit) out.past_right.push({path: path(el), right: r1(right)});
    }
  }

  const dataSelector = opts.data || opts.default_data;
  const data = firstShown(dataSelector);
  out.data_selector = dataSelector;
  out.first_data_y = top(data);
  out.first_action_y = top(startRight ? await firstReachable(opts.action_selector)
    : firstOnPage(opts.action_selector));

  out.targets_total = 0;
  out.small_targets_total = 0;
  out.small_targets = [];
  for (const el of document.querySelectorAll(opts.target_selector)) {
    if (el.localName === 'input' && el.type === 'hidden') continue;
    if (!shown(el)) continue;
    out.targets_total += 1;
    const r = el.getBoundingClientRect();
    if (r.width < opts.min_target_px || r.height < opts.min_target_px) {
      out.small_targets_total += 1;
      if (out.small_targets.length < opts.list_limit) {
        out.small_targets.push({path: path(el), width: r1(r.width), height: r1(r.height)});
      }
    }
  }

  out.fields_total = 0;
  out.small_inputs_total = 0;
  out.small_inputs = [];
  for (const el of document.querySelectorAll(opts.field_selector)) {
    if (!textEntry(el) || !shown(el)) continue;
    out.fields_total += 1;
    const font = parseFloat(getComputedStyle(el).fontSize);
    if (font < opts.min_input_font_px) {
      out.small_inputs_total += 1;
      if (out.small_inputs.length < opts.list_limit) out.small_inputs.push({path: path(el), font_px: font});
    }
  }

  out.measure = opts.measure.map((selector) => {
    const all = document.querySelectorAll(selector);
    const first = Array.from(all).find(shown) || null;
    return {selector, count: all.length, height_px: first ? r1(first.getBoundingClientRect().height) : null};
  });
  return out;
}
"""


# ---- pure helpers (no browser) -------------------------------------------------

def overflow_px(scroll_width, requested_width):
    """Horizontal overflow against the requested width, never below zero.

    `innerWidth` is the layout viewport, which a mobile-emulated page widens to
    fit its widest child, so it cannot be the reference.
    """
    value = round(max(0.0, float(scroll_width) - float(requested_width)), 1)
    return int(value) if value.is_integer() else value


def is_text_entry(local_name, input_type=""):
    """True for a control that takes typed text: the page script's field rule.

    Only these trigger focus zoom, so only these are checked for font size.
    """
    return local_name != "input" or input_type.lower() not in NON_TEXT_INPUT_TYPES


def starts_at_right(writing_mode, direction):
    """True when a page with this principal (body) writing mode starts at its right edge.

    Horizontal text starts at the right under `direction: rtl`; vertical text
    starts at the right in the `-rl` modes whatever the direction.
    """
    if writing_mode.startswith(("vertical-", "sideways-")):
        return writing_mode.endswith("-rl")
    return direction == "rtl"


def in_document_area(bottom, right, left=None, start_edge=None, fixed=False):
    """True when a box reaches into the area the reader can get to.

    A skip link parked above or before the page's start edge is not where the
    first action sits; the page script skips such controls. On a page that
    starts at the left the start edge is x 0 and the box must reach past it
    (`right > 0`). On a page that starts at the right, pass the box's `left`
    and the `start_edge` (the scrolling box's client width): the box must
    reach left of that edge, which the page cannot scroll past, while the
    left side it overflows to stays reachable. The box is in page
    coordinates, except for a control fixed to the viewport (`fixed`), whose
    box is its viewport rectangle whatever the scroll position. On a page that
    starts at the right such a box must lie across the band the reader pans
    over, client x 0 to the layout viewport width; pass that width as
    `start_edge`.

    On a page that starts at the right the page script applies this to the
    part of a box that its ancestors do not clip away, and to the same band
    (`fixed`) when the viewport itself cannot scroll sideways; a box with no
    such part counts only through an ancestor the reader can scroll. That
    needs the browser and has no mirror here.
    """
    if start_edge is not None:
        return bottom > 0 and left < start_edge and (not fixed or right > 0)
    return bottom > 0 and right > 0


def finding(total, examples, limit=LIST_LIMIT):
    """A count taken over every shown element, with at most `limit` examples.

    The page script counts in the page, so `total` covers the whole page even
    when it holds thousands of elements; only the example list is bounded.
    """
    return {"count": total, "first": list(examples)[:limit]}


def split_selectors(text):
    """Split a comma list at the top level so `:is(a, b)` and `[x="a,b"]` stay whole."""
    parts, depth, quote, current = [], 0, "", []
    for char in text:
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def system_alias(part):
    # macOS ships /etc, /tmp and /var (home of the default temp dir) as links
    # into /private. Only root can create a top-level entry, so trust exactly
    # those three, and only when the link names the same directory there.
    if sys.platform != "darwin" or part.parent != Path("/") or part.name not in ("etc", "tmp", "var"):
        return False
    try:
        return os.readlink(part) in ("private/" + part.name, "/private/" + part.name)
    except OSError:
        return False


def safe_path(value):
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("path traversal is not accepted")
    path = path.absolute()
    try:
        linked = any(part.is_symlink() and not system_alias(part) for part in (path, *path.parents))
    except OSError as exc:
        # A directory that cannot be searched cannot be checked either; refuse it as a bad path.
        raise ValueError(f"path could not be checked: {exc.strerror}") from exc
    if linked:
        raise ValueError("symlink paths are not accepted")
    return path


def resolve_target(value):
    """A http(s) URL, an .html file or a directory holding index.html, as a URL to load."""
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https"):
        if not parsed.netloc:
            raise ValueError("URL has no host")
        return {"kind": "url", "value": value}, value
    if len(parsed.scheme) > 1 and "://" in value:
        raise ValueError("only http(s) URLs, .html files and directories are accepted")
    path = safe_path(value)
    if path.is_dir():
        path = safe_path(path / "index.html")
    if not path.is_file():
        raise ValueError(f"target is not a file or a directory with index.html: {value}")
    if path.suffix.lower() not in (".html", ".htm"):
        raise ValueError("a file target must end in .html or .htm")
    return {"kind": "file", "value": str(path)}, path.as_uri()


def check_shot_path(value):
    path = safe_path(value)
    if os.path.lexists(path):
        raise ValueError("--shot must be a new path; refusing an existing file or link")
    if not path.parent.is_dir():
        raise ValueError("--shot parent directory must already exist")
    if path.suffix.lower() != ".png":
        raise ValueError("--shot must end in .png")
    return path


def parser():
    cli = argparse.ArgumentParser(
        description="Measure one page in a phone-sized, touch-emulating browser and print JSON numbers.")
    cli.add_argument("target", help="http(s) URL, .html file or directory holding index.html")
    cli.add_argument("--data", help="CSS selector of the first data row (default: a row-like guess)")
    cli.add_argument("--measure", help="comma-separated CSS selectors whose first block height is reported")
    cli.add_argument("--shot", help="new .png path; captures the first viewport only")
    cli.add_argument("--scroll", type=int, default=0, help="scroll this many px before --shot")
    cli.add_argument("--desktop", action="store_true", help="1440x900, no touch, no mobile emulation")
    cli.add_argument("--width", type=int, help="override the viewport width in px")
    cli.add_argument("--height", type=int, help="override the viewport height in px")
    cli.add_argument("--browser", help="Chromium executable to use instead of the Playwright one")
    cli.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                     help=f"seconds for page load and for the whole run (default {DEFAULT_TIMEOUT_S:g})")
    return cli


def validate(args):
    for name in ("width", "height"):
        value = getattr(args, name)
        if value is not None and not MIN_SIDE_PX <= value <= MAX_SIDE_PX:
            raise ValueError(f"--{name} must be between {MIN_SIDE_PX} and {MAX_SIDE_PX}")
    if not 0 < args.timeout <= MAX_TIMEOUT_S:
        raise ValueError(f"--timeout must be above 0 and at most {MAX_TIMEOUT_S:g}")
    if args.scroll < 0:
        raise ValueError("--scroll must be 0 or more")
    if args.scroll and not args.shot:
        raise ValueError("--scroll only applies to --shot")
    measure = split_selectors(args.measure) if args.measure is not None else []
    if args.measure is not None and not measure:
        raise ValueError("--measure needs at least one selector")
    if args.data is not None and not args.data.strip():
        raise ValueError("--data must not be empty")
    browser = None
    if args.browser:
        browser = Path(args.browser)
        if not browser.is_file() or not os.access(browser, os.X_OK):
            raise ValueError("--browser is not an executable file")
    target, url = resolve_target(args.target)
    shot = check_shot_path(args.shot) if args.shot else None
    return {"target": target, "url": url, "measure": measure, "shot": shot, "browser": browser}


def emulation(args):
    base = DESKTOP if args.desktop else PHONE
    return {"width": args.width or base["width"], "height": args.height or base["height"],
            "device_scale_factor": base["device_scale_factor"],
            "mobile": not args.desktop, "touch": not args.desktop,
            "user_agent": None if args.desktop else PHONE_USER_AGENT}


class RunError(Exception):
    """The page could not be measured; carries the exit-2 message."""


def can_hold_directory():
    """True where a file can be created relative to an already opened directory."""
    return (os.open in os.supports_dir_fd and os.unlink in os.supports_dir_fd
            and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"))


def open_directory_without_links(directory):
    """Open `directory` one component at a time and return its descriptor.

    Each step opens the next name relative to the directory already held and
    refuses a link, so a component swapped for a link after the path was
    checked cannot redirect the walk. macOS's own top-level aliases are the
    only links followed, as in `safe_path`.
    """
    plain = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    # Every descriptor this walk has open is in `owned` until it is closed or
    # handed back, so a refused step, or an interrupt that lands between two of
    # the walk's statements before it hands its result back, leaves none behind.
    owned = []
    try:
        owned.append(os.open(directory.anchor, plain))
        walked = Path(directory.anchor)
        for part in directory.parts[1:]:
            walked = walked / part
            flags = plain if system_alias(walked) else plain | os.O_NOFOLLOW
            owned.append(os.open(part, flags, dir_fd=owned[-1]))
            os.close(owned.pop(0))
        return owned.pop()
    finally:
        for descriptor in owned:
            os.close(descriptor)


def write_new_file(value, data):
    """Create `value` and write `data`, never replacing or following anything.

    The `--shot` check runs before the page loads, and loading can take long
    enough for a file or a link to appear at that path or above it. So the path
    is checked again here, its directory is opened component by component
    without following a link, and the file is created exclusively inside that
    held directory: a name that came to exist is refused and left untouched,
    and a directory swapped for a link cannot move the write elsewhere. Where
    the platform cannot hold a directory (Windows), the second check and the
    exclusive create are the whole guard.
    """
    try:
        path = safe_path(value)
    except ValueError as exc:
        raise RunError(f"--shot: {exc}") from exc
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0))
    held = None
    try:
        if can_hold_directory():
            try:
                held = open_directory_without_links(path.parent)
            except OSError as exc:
                raise RunError("--shot: symlink paths are not accepted; "
                               f"the directory could not be opened without following one ({exc.strerror})") from exc
        try:
            fd = os.open(path.name, flags, 0o644, dir_fd=held) if held is not None else os.open(path, flags, 0o644)
        except FileExistsError as exc:
            raise RunError("--shot path appeared while the page loaded; refusing to replace it") from exc
        except OSError as exc:
            raise RunError(f"--shot could not be created: {exc.strerror}") from exc
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            if held is not None:
                with contextlib.suppress(OSError):
                    os.unlink(path.name, dir_fd=held)
            else:
                path.unlink(missing_ok=True)
            raise RunError(f"--shot could not be written: {exc.strerror}") from exc
    finally:
        if held is not None:
            os.close(held)
    return path


def content_width(context, page, browser_error):
    """Width of the page's content as the browser lays it out, in CSS px, or None.

    Read over the DevTools protocol, which changes nothing on the page. The
    page script needs it only where the page has no scrolling element.
    """
    try:
        metrics = context.new_cdp_session(page).send("Page.getLayoutMetrics")
    except browser_error:
        return None
    width = metrics.get("cssContentSize", {}).get("width")
    return width if isinstance(width, (int, float)) and not isinstance(width, bool) else None


def measure_page(args, plan, emu):
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RunError("Playwright is not installed; run `pip install playwright` and "
                       "`playwright install chromium`, or pass --browser") from exc
    millis = int(args.timeout * 1000)
    errors = []
    try:
        with sync_playwright() as pw:
            launch = {"executable_path": str(plan["browser"])} if plan["browser"] else {}
            try:
                browser = pw.chromium.launch(timeout=millis, **launch)
            except PlaywrightError as exc:
                raise RunError("could not start Chromium (try `playwright install chromium` or "
                               f"--browser): {str(exc).splitlines()[0]}") from exc
            try:
                options = {"viewport": {"width": emu["width"], "height": emu["height"]},
                           "device_scale_factor": emu["device_scale_factor"],
                           "is_mobile": emu["mobile"], "has_touch": emu["touch"]}
                if emu["user_agent"]:
                    options["user_agent"] = emu["user_agent"]
                context = browser.new_context(**options)
                page = context.new_page()
                page.set_default_timeout(millis)
                page.on("console", lambda m: errors.append({"source": "console", "text": m.text[:300]})
                        if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append({"source": "pageerror", "text": str(e)[:300]}))
                try:
                    response = page.goto(plan["url"], wait_until="load", timeout=millis)
                except PlaywrightError as exc:
                    raise RunError(f"navigation failed: {str(exc).splitlines()[0]}") from exc
                if response is not None and response.status >= 400:
                    raise RunError(f"navigation failed: HTTP {response.status}")
                page.wait_for_timeout(300)
                try:
                    raw = page.evaluate(PAGE_SCRIPT, {
                        "content_width": content_width(context, page, PlaywrightError),
                        "width": emu["width"], "data": args.data, "default_data": DEFAULT_DATA_SELECTOR,
                        "action_selector": ACTION_SELECTOR, "target_selector": TARGET_SELECTOR,
                        "field_selector": FIELD_SELECTOR, "measure": plan["measure"], "list_limit": LIST_LIMIT,
                        "min_target_px": MIN_TARGET_PX, "min_input_font_px": MIN_INPUT_FONT_PX,
                        "non_text_types": list(NON_TEXT_INPUT_TYPES)})
                except PlaywrightError as exc:
                    raise RunError(f"measuring failed (check the selectors): {str(exc).splitlines()[0]}") from exc
                if plan["shot"] is not None:
                    if args.scroll:
                        page.evaluate("(y) => window.scrollTo(0, y)", args.scroll)
                        page.wait_for_timeout(100)
                    shot_bytes = page.screenshot(full_page=False)
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RunError(f"browser error: {str(exc).splitlines()[0]}") from exc
    if plan["shot"] is not None:
        write_new_file(plan["shot"], shot_bytes)
    return raw, errors


def build_report(args, plan, emu, raw, errors):
    first_data = raw["first_data_y"]
    report = {
        "schema": SCHEMA,
        "target": plan["target"],
        "viewport": {"width": emu["width"], "height": emu["height"],
                     "device_scale_factor": emu["device_scale_factor"]},
        "emulation": {"mobile": emu["mobile"], "touch": emu["touch"], "user_agent": emu["user_agent"]},
        "viewport_meta": raw["viewport_meta"],
        "horizontal_overflow_px": overflow_px(raw["scroll_width"], emu["width"]),
        "scroll_width": raw["scroll_width"],
        "client_width": raw["client_width"],
        "inner_width": raw["inner_width"],
        "elements_past_right_edge": {
            **finding(raw["past_right_total"], raw["past_right"]),
            "note": PAST_LEFT_EDGE_NOTE if raw.get("start_right") else PAST_EDGE_NOTE,
        },
        "data_selector": raw["data_selector"],
        "first_data_y": first_data if first_data is not None else "not_found",
        "first_action_y": raw["first_action_y"] if raw["first_action_y"] is not None else "not_found",
        "small_targets": {**finding(raw["small_targets_total"], raw["small_targets"]),
                          "minimum_px": MIN_TARGET_PX, "checked": raw["targets_total"]},
        "small_inputs": {**finding(raw["small_inputs_total"], raw["small_inputs"]),
                         "minimum_font_px": MIN_INPUT_FONT_PX, "checked": raw["fields_total"]},
        "console_errors": errors,
        "measure": raw["measure"],
        "document_height_px": raw["document_height"],
        "shot": str(plan["shot"]) if plan["shot"] is not None else None,
    }
    if first_data is None and args.data is None:
        report["first_data_hint"] = NO_DATA_HINT
    elif first_data is None:
        report["first_data_hint"] = "the --data selector matched no visible element"
    return report


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        plan = validate(args)
    except ValueError as exc:
        print(f"phone_check refused: {exc}", file=sys.stderr)
        return 2
    emu = emulation(args)

    def give_up():
        print(f"phone_check could not run: exceeded --timeout {args.timeout:g}s for the whole run",
              file=sys.stderr)
        os._exit(2)

    watchdog = threading.Timer(args.timeout + 10, give_up)
    watchdog.daemon = True
    watchdog.start()
    try:
        raw, errors = measure_page(args, plan, emu)
    except RunError as exc:
        print(f"phone_check could not run: {exc}", file=sys.stderr)
        return 2
    finally:
        watchdog.cancel()
    print(json.dumps(build_report(args, plan, emu, raw, errors), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
