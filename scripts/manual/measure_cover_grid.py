"""Cross-engine layout probe for fork #343 (Safari cover misalignment).

Launches BOTH webkit (Safari engine) and chromium against a running
cwn-local, logs in, loads the books grid, and measures the cover-image /
title / hover-overlay box model for the first few books. Prints the
cover-bottom -> title-top gap (negative = the title overlaps the cover).

This is a DEV harness, not a pytest. It lives under scripts/manual/ (not
tests/) on purpose: pytest's `testpaths = tests` imports every module it
finds during collection, and this file drives a real browser + reads
credentials from the environment — neither belongs in unit-test
collection. Everything is guarded under main() so importing the module is
a pure no-op even if something ever does scan this path.

Run:
  CWN_TEST_PW=... [CWN_TEST_USER=cwng84test] \
    /Users/acoundou/.pyenv/versions/3.12.7/bin/python3 scripts/manual/measure_cover_grid.py

Requires: `playwright install webkit chromium` on the host.
"""

MEASURE_JS = r"""
() => {
  const books = Array.from(document.querySelectorAll('.book')).slice(0, 4);
  return books.map((b, i) => {
    const a = b.querySelector('.cover > a');
    const img = b.querySelector('.cover img');
    const title = b.querySelector('.meta .title');
    const r = el => { if (!el) return null; const x = el.getBoundingClientRect();
      return {x: Math.round(x.x), y: Math.round(x.y), w: Math.round(x.width),
              h: Math.round(x.height), bottom: Math.round(x.bottom), top: Math.round(x.top)}; };
    const imgBox = r(img), titleBox = r(title), aBox = r(a);
    return {
      index: i, img: imgBox, title: titleBox, a: aBox,
      cover_to_title_gap: (imgBox && titleBox) ? (titleBox.top - imgBox.bottom) : null,
      a_vs_img_w_delta: (aBox && imgBox) ? (aBox.w - imgBox.w) : null,
      a_vs_img_h_delta: (aBox && imgBox) ? (aBox.h - imgBox.h) : null,
      a_vs_img_x_delta: (aBox && imgBox) ? (aBox.x - imgBox.x) : null,
      a_vs_img_y_delta: (aBox && imgBox) ? (aBox.y - imgBox.y) : null,
    };
  });
}
"""


def _login(pg, base, user, pw):
    pg.goto(f"{base}/login", wait_until="networkidle")
    pg.fill('#username', user)
    pg.fill('#password', pw)
    pg.press('#password', 'Enter')
    pg.wait_for_load_state("networkidle")


def _run(engine_name, browser_type, viewport, base, user, pw):
    browser = browser_type.launch(headless=True)
    ctx = browser.new_context(viewport=viewport)
    pg = ctx.new_page()
    _login(pg, base, user, pw)
    pg.goto(f"{base}/", wait_until="networkidle")
    pg.wait_for_timeout(800)
    data = pg.evaluate(MEASURE_JS)
    print(f"\n===== {engine_name} (viewport {viewport['width']}x{viewport['height']}) =====")
    for d in data:
        print(f" book[{d['index']}] img={d['img']}")
        print(f"           title={d['title']}")
        print(f"           cover_to_title_gap={d['cover_to_title_gap']}px "
              f"(NEGATIVE = title overlaps cover)")
        print(f"           a_vs_img deltas: w={d['a_vs_img_w_delta']} h={d['a_vs_img_h_delta']} "
              f"x={d['a_vs_img_x_delta']} y={d['a_vs_img_y_delta']} "
              f"(non-zero = hover overlay misaligned)")
    browser.close()


def main():
    import os
    import sys
    from playwright.sync_api import sync_playwright

    base = os.getenv("CWN_TEST_BASE", "http://localhost:8086")
    user = os.getenv("CWN_TEST_USER", "cwng84test")
    pw = os.getenv("CWN_TEST_PW")
    if not pw:
        sys.exit("Set CWN_TEST_PW (and optionally CWN_TEST_USER) before running this harness.")

    with sync_playwright() as p:
        _run("WEBKIT/Safari desktop", p.webkit, {"width": 1440, "height": 900}, base, user, pw)
        _run("CHROMIUM desktop", p.chromium, {"width": 1440, "height": 900}, base, user, pw)
        _run("WEBKIT/Safari mobile", p.webkit, {"width": 390, "height": 844}, base, user, pw)


if __name__ == "__main__":
    main()
