/** Cookie names shared by middleware (edge runtime) and server code.
 *
 *  Separate from `session.ts` because that module is `server-only` and importing
 *  it from middleware would fail to build.
 */
export const ACCESS_COOKIE = "scv_access";
export const REFRESH_COOKIE = "scv_refresh";
