"""Cross-engine DOM probe for fork #352 drag-merge text-selection fix.

Logs in to cwn-local as cwng84test, then for both WebKit (Safari engine) and
Chromium asserts:

* grid view `/`:
  - .book cards do NOT carry draggable=true (Safari text-selection unblocked)
  - .cover element inside each card DOES carry draggable=true (drag source moved)
  - card class includes `drag-merge-enabled` (init still ran on grid)
  - title element is text-selectable: Range.toString() returns the title text
    after programmatically selecting it
* detail view `/book/<id>`:
  - script does NOT mark any element with `drag-merge-enabled` (selector
    `.book.session` does not match detail-page `.book`)
  - title text is selectable

Run:
  CWN_TEST_PW=cwng-test-84 python3 scripts/manual/probe_352_drag_merge.py
"""

MEASURE_JS = r"""
() => {
  const grid = Array.from(document.querySelectorAll('.book.session'));
  const out = grid.slice(0, 4).map(b => {
    const cover = b.querySelector('.cover');
    const title = b.querySelector('.meta .title');
    // Programmatically select the title text and read what was selected.
    let selected = null;
    if (title) {
      const range = document.createRange();
      range.selectNodeContents(title);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      selected = sel.toString();
      sel.removeAllRanges();
    }
    return {
      cardDraggable: b.getAttribute('draggable'),
      cardHasMergeEnabled: b.classList.contains('drag-merge-enabled'),
      coverDraggable: cover ? cover.getAttribute('draggable') : null,
      titleText: title ? title.textContent.trim().slice(0, 40) : null,
      titleSelected: selected ? selected.trim().slice(0, 40) : null,
    };
  });
  return { count: grid.length, books: out };
}
"""

DETAIL_JS = r"""
() => {
  const any = document.querySelectorAll('.drag-merge-enabled');
  const title = document.querySelector('h2#title') || document.querySelector('.book-detail-meta h2');
  let titleSelected = null;
  if (title) {
    const range = document.createRange();
    range.selectNodeContents(title);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    titleSelected = sel.toString().trim().slice(0, 80);
    sel.removeAllRanges();
  }
  return {
    mergeEnabledCount: any.length,
    titleSelected,
  };
}
"""


def _login(pg, base, user, pw):
    pg.goto(f"{base}/login", wait_until="networkidle")
    pg.fill('#username', user)
    pg.fill('#password', pw)
    pg.press('#password', 'Enter')
    pg.wait_for_load_state("networkidle")


def _run(engine_name, browser_type, viewport, base, user, pw):
    b = browser_type.launch(headless=True)
    ctx = b.new_context(viewport=viewport)
    pg = ctx.new_page()
    _login(pg, base, user, pw)
    pg.goto(f"{base}/", wait_until="networkidle"); pg.wait_for_timeout(600)
    grid = pg.evaluate(MEASURE_JS)
    print(f"\n===== {engine_name} grid ({viewport['width']}x{viewport['height']}) =====")
    print(f"  card count: {grid['count']}")
    for i, b_ in enumerate(grid['books']):
        ok_card = b_['cardDraggable'] is None and b_['cardHasMergeEnabled'] is True
        ok_cover = b_['coverDraggable'] == 'true'
        ok_sel = b_['titleSelected'] == b_['titleText']
        flag = "✓" if (ok_card and ok_cover and ok_sel) else "✗"
        print(f"  [{i}] {flag} card.draggable={b_['cardDraggable']!s:>5} "
              f"card.mergeEnabled={b_['cardHasMergeEnabled']} "
              f"cover.draggable={b_['coverDraggable']!s:>5} "
              f"title=\"{b_['titleText']}\" selected=\"{b_['titleSelected']}\"")
    # detail page
    if grid['books']:
        # Need a book id — grab the first card's link
        bid = pg.evaluate("() => document.querySelector('.book.session .book-cover-link')?.getAttribute('data-book-id')")
        if bid:
            pg.goto(f"{base}/book/{bid}", wait_until="networkidle"); pg.wait_for_timeout(600)
            detail = pg.evaluate(DETAIL_JS)
            ok_no_merge = detail['mergeEnabledCount'] == 0
            print(f"  detail: drag-merge-enabled count={detail['mergeEnabledCount']} "
                  f"{'✓' if ok_no_merge else '✗'} (must be 0); "
                  f"titleSelected=\"{detail['titleSelected']}\"")
    b.close()


def main():
    import os, sys
    from playwright.sync_api import sync_playwright
    base = os.getenv("CWN_TEST_BASE", "http://localhost:8086")
    user = os.getenv("CWN_TEST_USER", "cwng84test")
    pw = os.getenv("CWN_TEST_PW")
    if not pw:
        sys.exit("Set CWN_TEST_PW before running.")
    with sync_playwright() as p:
        _run("WebKit/Safari desktop", p.webkit, {"width": 1440, "height": 900}, base, user, pw)
        _run("Chromium desktop", p.chromium, {"width": 1440, "height": 900}, base, user, pw)
        _run("WebKit/Safari mobile", p.webkit, {"width": 390, "height": 844}, base, user, pw)


if __name__ == "__main__":
    main()
