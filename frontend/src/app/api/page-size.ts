/**
 * The largest `limit` the paginated endpoints accept.
 *
 * **One definition, checked against the contract.** Every catalogue endpoint declares
 * `limit` as `ge=1, le=200`; three pages had been sending 300 and 400, so every load was a
 * 422 and the page rendered "Could not load…". The suite could not see it: the page tests
 * mock `CatalogueService`, so the request that violates the contract is never made.
 *
 * `page-size.spec.ts` reads the committed `openapi.json` and fails if this and the schema
 * disagree, which is the only kind of check that survives someone raising the server's cap.
 */
export const MAX_PAGE_LIMIT = 200;
