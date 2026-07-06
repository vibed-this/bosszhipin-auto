---
name: page-layout-analyzer
description: Analyze QWebEngineView page DOM structure to find scrollable containers and element selectors. Use this whenever you need to understand a page's layout — finding the right scroll container, figuring out where lazy loading happens, determining which DOM elements are at specific coordinates, or debugging why clicks/scrolling aren't working. Also use when building page objects (pages/) or flows (flows/) that interact with new page sections.
---

# Page Layout Analyzer

Analyze a Boss直聘 (or any QWebEngineView) page's DOM structure to determine scrollable containers, element selectors, and interaction strategies. Uses `BrowserManager` + `eval_js` to inspect the live DOM.

## Analysis workflow

### 1. Write a temp script to probe DOM

```python
"""dump_<page>.py — 页面布局探查"""
from __future__ import annotations

import asyncio
import logging
import sys

import qasync
from PySide6.QtWidgets import QApplication

from bzauto.browser import BrowserManager
from bzauto.browser.manager import _set_browser_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dump")

accounts = [{"id": "main", "name": "main"}]

async def main():
    bm = BrowserManager(accounts)
    _set_browser_manager(bm)
    bm.show()

    session = bm.get_session("main")
    await session.ensure_tab("https://www.zhipin.com/web/geek/chat", timeout=60)
    await session.activate()
    await asyncio.sleep(5)

    # ... JS probes here ...

    await asyncio.sleep(2)
    bm.close()

app = QApplication(sys.argv)
loop = qasync.QEventLoop(app)
asyncio.set_event_loop(loop)
loop.create_task(main())
with loop:
    loop.run_forever()
```

### 2. Run JS probes via `eval_js`

**Find scrollable container** — trace element ancestry to locate `overflowY: auto/scroll` + `scrollHeight > clientHeight`:

```javascript
// Trace ancestry of a target element
(function() {
  var el = document.querySelector('li[role="listitem"]');
  var parts = [];
  var depth = 0;
  while (el && depth < 10) {
    var tag = el.tagName.toLowerCase();
    var cls = el.className || '';
    var rect = el.getBoundingClientRect();
    var style = window.getComputedStyle(el);
    parts.push(
      depth + '. <' + tag + ' class=' + cls.slice(0, 80) + '>'
      + ' rect=' + Math.round(rect.width) + 'x' + Math.round(rect.height)
      + ' scrollH=' + el.scrollHeight + ' clientH=' + el.clientHeight
      + ' overflowY=' + style.overflowY
      + (el.scrollHeight > el.clientHeight ? ' ← HAS_SCROLL' : '')
    );
    el = el.parentElement;
    depth++;
  }
  return parts.join('\n');
})()
```

**Find all scrollable containers** — useful when you don't know the target element:

```javascript
(function() {
  var all = document.querySelectorAll('*');
  var scrollable = [];
  all.forEach(function(el) {
    var style = window.getComputedStyle(el);
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
      if (el.scrollHeight > el.clientHeight + 5) {
        scrollable.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || '').slice(0, 80),
          w: Math.round(rect.width),
          h: Math.round(rect.height),
          scrollH: el.scrollHeight,
          clientH: el.clientHeight,
        });
      }
    }
  });
  return scrollable;
})()
```

### 3. Verify selector with `bbox()`

Once you have the target selector, confirm it's valid:

```python
bbox = await session.bbox(select=".user-list-content")
log.info("bbox: %s", bbox)  # should have cx > 0, cy > 0
```

## Scrolling strategy reference

Read `references/api.md` for the available scrolling APIs in `BrowserSession`.

### Decision matrix

| Situation | Method | Why |
|-----------|--------|-----|
| Page uses lazy loading (loads items on scroll) | `scroll_pagedown` (Qt key event) | Page can't distinguish from real user — triggers `scroll` listeners |
| Need to scroll at exact coordinates | `scroll_wheel` (Qt wheel event) | Targets specific position; requires `bbox` first |
| Just need to position viewport (no lazy loading) | JS `scrollTop` / `scrollBy` | Fast, no Qt dependency, but won't trigger lazy loading |

### Triggering lazy loading (recommended sequence)

```
1. JS scrollTop = scrollHeight     — position to bottom (no trigger)
2. mouse_move to coords            — hover/focus the container
3. scroll_pagedown(presses=N)      — real Qt event triggers lazy load
4. await sleep(timeout)            — wait for items to render
```

`scroll_pagedown` sends `Qt.Key_PageDown` key events to the QWebEngineView's focused widget. When the container is focused (via prior `mouse_move`), the PageDown goes to the correct scrollable container.

## Key principles

- **Real events only trigger lazy loading**: JS `scrollTop/scrollBy` and `dispatchEvent` won't work because the page can detect programmatic scrolls. Always use Qt event simulation (`events.py`) for content loads.
- **Coordinates are logical pixels**: `getBoundingClientRect()` returns CSS/viewport pixels. `events.send_click/mousemove` use the same coordinate space. No DPR conversion needed.
- **Hover before keyboard/wheel**: QWebEngineView routes keyboard events to the currently focused DOM element. `mouse_move` at the container's center ensures the PageDown goes to the right place.
- **`max_scrolls` vs `stale_rounds`**: `max_scrolls` limits total scroll attempts. `stale_rounds` stops early if no new data appears after N consecutive scrolls. Remove or increase `stale_rounds` if the page has a finite item set and premature stopping is an issue.
