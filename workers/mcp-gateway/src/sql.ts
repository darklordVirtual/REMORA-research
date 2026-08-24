/**
 * Which SQL statements a read-only caller may run.
 *
 * Its own module, with no Cloudflare imports, so it can be unit-tested with
 * real statements. The first version lived in index.ts and could only be
 * tested by reading the source and asserting the shape of its regex — which
 * cannot catch a semantic bypass, and one shipped (see below).
 *
 * The authority domain needs to READ the graph: grounding signals, the state
 * index and the semantic bundle all query it to reach a decision. It must not
 * be able to WRITE it, or the container holding the private lease key can also
 * cause a graph effect, which is the single point of failure the custody split
 * exists to remove.
 *
 * Deliberately a strict allowlist rather than a denylist of mutating verbs: a
 * denylist has to anticipate every way to write, and it only has to be wrong
 * once.
 *
 * The first allowlist accepted a leading `WITH`, and was wrong exactly once —
 * which is what that sentence warns about. SQLite lets a common table
 * expression prefix a mutation:
 *
 *     WITH x AS (SELECT 1) INSERT INTO knowledge_facts SELECT * FROM x
 *
 * so `^(select|with)` admitted DML through the read-only route. `WITH` is now
 * refused outright rather than parsed: no query this deployment issues uses a
 * CTE, so the capability bought nothing and cost a bypass
 * (NEGATIVE_RESULTS §49).
 *
 * Known limit, stated because a regex is not a parser: this is a lexical guard
 * at the proxy, not engine-level enforcement. D1's binding exposes no
 * read-only connection mode, so this layer is what is available here. It is
 * one boundary among several — the registry module binds the tenant clause
 * into every statement and issues only parameterised reads — and it should be
 * replaced by engine-level enforcement if D1 ever offers it.
 */
export function isReadOnlySql(sql: string): boolean {
  const trimmed = sql.trim();
  // No statement chaining. A trailing semicolon is fine; an interior one is
  // refused, including inside a string literal — that fails closed, and no
  // query this deployment issues contains one.
  if (/;/.test(trimmed.replace(/;\s*$/, ""))) return false;
  return /^select\s/i.test(trimmed) || /^pragma\s+table_info\s*\(/i.test(trimmed);
}
