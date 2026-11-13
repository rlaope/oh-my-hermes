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
import errno
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
(opts) => {
  const doc = document.documentElement;
  const sx = window.scrollX, sy = window.scrollY;
  // The page's start side comes from the writing mode and direction of
  // <body>, the principal writing mode: <html dir="rtl"><body dir="ltr">
  // starts at the left, body{direction:rtl} at the right, a vertical-rl page
  // at the right. A page that starts at its right edge holds that edge at the
  // scrolling box's client width in page px, cannot scroll past it, and
  // overflows to the left instead (scrollX goes negative).
  // Markup alone can shadow a built-in: <form name="scrollingElement"> makes
  // `document.scrollingElement` that form, with no script on the page, and
  // a form control's name does the same on its <form>. What decides how
  // a right-start page is read is taken through the interface prototypes,
  // which a named element cannot shadow, and so is every step up the tree:
  // <input name="parentElement"> makes its <form> answer with that input,
  // whose parent is the form again, and a walk that trusts it never ends.
  // The other reads shared with the left-start path are as they always were.
  const own = (proto, name) => {
    const get = Object.getOwnPropertyDescriptor(proto, name).get;
    return (node) => get.call(node);
  };
  const pageRoot = own(Document.prototype, 'documentElement')(document);
  const pageBody = own(Document.prototype, 'body')(document);
  const pageScroller = own(Document.prototype, 'scrollingElement')(document);
  const parentOf = own(Node.prototype, 'parentElement');
  const kindOf = own(Node.prototype, 'nodeType');
  // Only an HTML element has an offsetParent; anything else keeps its own
  // answer (none), and has no named controls to shadow it.
  const htmlOffsetParent = own(HTMLElement.prototype, 'offsetParent');
  const offsetParentOf = (node) => node instanceof HTMLElement ? htmlOffsetParent(node) : node.offsetParent;
  const principal = getComputedStyle(pageBody || pageRoot);
  const startsRight = (style) => /^(vertical|sideways)-/.test(style.writingMode)
    ? style.writingMode.endsWith('-rl') : style.direction === 'rtl';
  const startRight = startsRight(principal);
  // A quirks-mode page can have no scrolling element (`overflow-x` auto,
  // scroll or hidden on both <html> and <body> is one way to get there); the
  // root then stands in for the width reported below.
  const scroller = pageScroller || pageRoot;
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
    while (node && kindOf(node) === 1 && parts.length < 5) {
      let part = node.localName;
      if (node.id) { parts.unshift(part + '#' + CSS.escape(node.id)); break; }
      const above = parentOf(node);
      const same = above ? Array.from(above.children).filter((c) => c.localName === node.localName) : [];
      if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(node) + 1) + ')';
      parts.unshift(part);
      if (node === document.body) break;
      node = above;
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
    while (node && kindOf(node) === 1) {
      if (getComputedStyle(node).position === 'fixed') {
        const holder = offsetParentOf(node);
        if (!holder) return true;
        node = holder;
      } else {
        node = parentOf(node);
      }
    }
    return false;
  };
  const top = (el) => {
    if (!el) return null;
    return r1(el.getBoundingClientRect().top + (fixedToViewport(el) ? 0 : sy));
  };
  // The edge test: a box is on the page when it reaches below the top and
  // right of page x 0, the two sides a page that starts at the left cannot
  // scroll beyond. A box fixed to the viewport is judged by its viewport box.
  const onPage = (el) => {
    const r = el.getBoundingClientRect();
    if (fixedToViewport(el)) return r.bottom > 0 && r.right > 0;
    return r.bottom + sy > 0 && r.right + sx > 0;
  };
  const firstOnPage = (selector) => {
    for (const el of document.querySelectorAll(selector)) {
      if (shown(el) && onPage(el)) return el;
    }
    return null;
  };
  // A page that starts at the right overflows to the left, where the edge
  // test skips everything, a real first control included. Whether a reader
  // gets to such a control is not inferred from layout: every rule that tried
  // met a page it could not see. The browser is asked instead. A control the
  // edge test skips is the first action when part of it is on screen as the
  // page loads and a hit test there returns it, so a tap lands on it. Under
  // the phone emulation an overflowing right-start page loads already panned
  // into its left overflow. Nothing is scrolled to look further: a control
  // that needs a scroll or a pan first is not added, and the answer is the
  // edge test's. A control the edge test counts is never dropped.
  const fromPoint = Document.prototype.elementFromPoint;
  const holds = Node.prototype.contains;
  const tapLands = (el) => {
    const vv = window.visualViewport
      || {offsetLeft: 0, offsetTop: 0, width: window.innerWidth, height: window.innerHeight};
    const r = el.getBoundingClientRect();
    const x0 = Math.max(r.left, vv.offsetLeft), x1 = Math.min(r.right, vv.offsetLeft + vv.width);
    const y0 = Math.max(r.top, vv.offsetTop), y1 = Math.min(r.bottom, vv.offsetTop + vv.height);
    if (x1 - x0 < 1 || y1 - y0 < 1) return false;
    for (const fx of [0.5, 0.15, 0.85]) {
      for (const fy of [0.5, 0.15, 0.85]) {
        const at = fromPoint.call(document, x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy);
        if (at && (at === el || holds.call(el, at))) return true;
      }
    }
    return false;
  };
  const firstFromRight = (selector) => {
    for (const el of document.querySelectorAll(selector)) {
      if (shown(el) && (onPage(el) || tapLands(el))) return el;
    }
    return null;
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
  out.first_action_y = top(startRight ? firstFromRight(opts.action_selector)
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


def in_document_area(bottom, right):
    """True when a box reaches into the area the reader can get to.

    A skip link parked above or left of the page (negative top and left) is
    not where the first action sits; the page script skips such controls. The
    box is in page coordinates, except for a control fixed to the viewport,
    whose box is its viewport rectangle whatever the scroll position. On a
    page that starts at the right the page script also counts a control this
    test skips when a tap lands on it as the page loads; that needs the
    browser and has no mirror here.
    """
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


def is_link(part):
    # From Python 3.14, Path.is_symlink() swallows every OSError, so an entry
    # under a directory that cannot be searched reads as "not a link". lstat it
    # first: a missing entry is fine, any other error means it cannot be checked.
    try:
        os.lstat(part)
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.ENOTDIR):
            raise
    return part.is_symlink()


def safe_path(value):
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("path traversal is not accepted")
    path = path.absolute()
    try:
        linked = any(is_link(part) and not system_alias(part) for part in (path, *path.parents))
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
