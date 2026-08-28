/**
 * Decide where to send someone after a successful sign-in.
 *
 * The `next` value comes from the middleware redirect, which means it is
 * ultimately attacker-controllable: anyone can send a café manager a link to
 * `/login?next=https://evil.example`. Only same-origin relative paths are
 * honoured, so a crafted link cannot bounce them off-site with a fresh session.
 */
export function safeRedirectTarget(next: string | null, fallback = "/dashboard"): string {
  if (!next) return fallback;

  // Must be a path on this origin.
  if (!next.startsWith("/")) return fallback;

  // "//evil.example" is protocol-relative and leaves the site.
  if (next.startsWith("//")) return fallback;

  // "/\evil.example" is treated as protocol-relative by some browsers.
  if (next.startsWith("/\\")) return fallback;

  // A scheme smuggled in after the slash, e.g. "/javascript:alert(1)".
  if (/^\/\s*[a-z][a-z0-9+.-]*:/i.test(next)) return fallback;

  return next;
}
