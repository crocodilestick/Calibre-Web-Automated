# Reader native-menu suppression — design + platform reality (task #30)

**Goal:** in the web reader, suppress the browser's native long-press / right-click
menu so the in-app highlight popup (shipped in #349) is the affordance for
selecting text to highlight.

## What ships

In `cps/static/js/reading/epub.js` — `suppressReaderNativeMenu()`, re-applied on
every section render (epub.js swaps the iframe document per spine item):

- `-webkit-touch-callout: none` injected into the epub content via the rendition
  theme override — kills the iOS long-press **callout** (for links/images).
- a `contextmenu` → `preventDefault` listener on each rendered section's document
  — swallows the right-click (desktop) and long-press context menu (Android) so
  the custom popup is the only menu that shows.

Text stays selectable (`user-select` is **not** disabled) because the highlight
feature needs a real selection. The custom popup is untouched — it fires on
epub.js's `selected` event, independent of `contextmenu`. Keyboard copy (Ctrl/⌘-C)
still works.

## The iOS limitation (honest scope)

iOS Safari shows a **text-selection edit menu** (Copy / Look Up / Translate /
Share) *after* a selection is made. That is native UI, not a DOM `contextmenu`
event, and **cannot be suppressed from a web context** without setting
`user-select: none` — which would disable the very selection highlighting needs.
So on iOS Safari the native edit menu **coexists** with the custom popup.

Options considered and rejected for iOS:
- `user-select: none` + reimplement selection by hand (long-press → manual range):
  fragile across iOS versions, breaks VoiceOver/accessibility, large surface area.
  Not worth it for a reader.
- Overlay tricks to cover the native menu: it renders above page content and
  can't be reliably covered.

Conclusion: the web-suppressible parts (callout + contextmenu) ship and help
Android + desktop; the iOS text-selection edit menu is a documented platform
constraint. Removing it would require a native app shell — out of scope.

## Verification

- contextmenu suppression: dispatch a `contextmenu` event in the rendered content
  iframe and assert `defaultPrevented` (Playwright, desktop) — OBSERVED.
- callout CSS applied to content; text still selectable; custom popup still
  appears on selection — OBSERVED.
- iOS edit-menu coexistence: needs a real iPhone (operator / household device) —
  ASSUMED to behave as analysed above; it is expected behaviour, not a regression.
