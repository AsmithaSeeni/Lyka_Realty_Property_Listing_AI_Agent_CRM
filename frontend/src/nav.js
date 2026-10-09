// Lightweight in-app history tracking.
//
// `navigate(-1)` silently does nothing when a page has no previous entry in
// this tab's SPA history — e.g. the property page opened via the agent CRM's
// "Open listing ↗" (new tab), after a hard refresh, or typed directly.
// App.jsx reports every route change here, so pages can decide between a true
// back-navigation and a sensible fallback destination.

let current = null
let previous = null

/** Called by the router on every location change. */
export function trackPath(path) {
  if (path !== current) {
    previous = current
    current = path
  }
}

/** True when this tab has navigated between at least two in-app routes. */
export function hasInAppHistory() {
  return previous !== null
}
