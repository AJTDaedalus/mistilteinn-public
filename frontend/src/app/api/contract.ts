import spec from '../../../openapi.json';

/**
 * The committed OpenAPI contract, for tests that check the client against it.
 *
 * Imported once here so no spec has to spell out its own depth of `../` — the first attempt
 * at a second one got that wrong, which is a compile error today and a silently skipped file
 * in a less strict setup.
 *
 * This is the same file `npm run codegen` builds `api.types.ts` from, and
 * `test_openapi_contract_is_current.py` keeps it matching the app. So a check against it is a
 * check against the server, one regeneration removed.
 *
 * Typed loosely on purpose: TypeScript infers the JSON as a wall of literal types, and these
 * tests look things up by path and schema name rather than asserting against that shape.
 */
export const CONTRACT = spec as unknown as {
  paths: Record<string, Record<string, { parameters?: { name: string; schema?: { maximum?: number } }[] }>>;
  components: { schemas: Record<string, { properties?: Record<string, unknown> }> };
};
