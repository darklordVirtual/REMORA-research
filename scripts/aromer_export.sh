#!/usr/bin/env bash
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
# aromer_export.sh — eksporter verdifulle data fra D1 "aromer-episodes",
# og (valgfritt) rydd bort tomgangslogg eller riv ned hele aromer.
#
# Bruk (fra en mappe der du er logget inn med `npx wrangler login`):
#   ./aromer_export.sh                 # kun eksport (ingenting slettes)
#   ./aromer_export.sh --prune-remote  # eksport + slett dupliserte logg-rader i D1
#   ./aromer_export.sh --teardown      # eksport + slett worker, D1 og KV helt
#
# Krever: node/npx (wrangler) og python3.
set -euo pipefail

DB_NAME="aromer-episodes"
WORKER_NAME="aromer"
KV_ID="6e84acea1ed4488a9b32cef6181900b2"   # AROMER_STATE
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="aromer-export-${STAMP}"
MODE="${1:-export}"

case "$MODE" in
  export|--prune-remote|--teardown) ;;
  *) echo "Ukjent valg: $MODE (bruk ingen, --prune-remote eller --teardown)"; exit 1 ;;
esac

for bin in npx python3; do
  command -v "$bin" >/dev/null || { echo "Mangler $bin"; exit 1; }
done

mkdir -p "$OUT"
echo "==> 1/4 Full SQL-backup av $DB_NAME (sikkerhetsnett)"
npx wrangler d1 export "$DB_NAME" --remote --output="$OUT/aromer-full-backup.sql"

echo "==> 2/4 Bygger lokal SQLite-kopi"
python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.executescript(open(sys.argv[2],encoding='utf-8').read()); c.commit()" \
  "$OUT/aromer-full.db" "$OUT/aromer-full-backup.sql"

echo "==> 3/4 Trekker ut forskningsdata"
python3 - "$OUT" <<'PY'
import csv, hashlib, json, os, re, sqlite3, sys

out = sys.argv[1]
src = sqlite3.connect(os.path.join(out, "aromer-full.db"))
src.row_factory = sqlite3.Row
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T")

def cols(t):
    return [r["name"] for r in src.execute(f"PRAGMA table_info({t})")]

def tables():
    return [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'")]

def ts_col(t):
    c = cols(t)
    for name in ("timestamp", "created_at", "started_at", "ts", "time"):
        if name in c:
            return name
    row = src.execute(f"SELECT * FROM {t} LIMIT 1").fetchone()
    if row:
        for name in c:
            v = row[name]
            if isinstance(v, str) and ISO.match(v):
                return name
    raise SystemExit(f"Fant ingen tidskolonne i {t}")

FULL = ["episodes", "world_model_priors", "oracle_bandit_state"]
DAILY = ["intelligence_scores", "adaptation_cycles"]
present = set(tables())

dst_path = os.path.join(out, "aromer-research.db")
if os.path.exists(dst_path):
    os.remove(dst_path)
dst = sqlite3.connect(dst_path)

manifest = {"source_db": "aromer-episodes", "tables": {}, "daily_dedup": {}}

for t in FULL + DAILY:
    if t not in present:
        print(f"   (hopper over {t}: finnes ikke)")
        continue
    ddl = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0]
    dst.execute(ddl)
    c = cols(t)
    placeholders = ",".join("?" * len(c))
    sel = ",".join(f'"{x}"' for x in c)   # eksplisitt: hopper over genererte kolonner
    if t in DAILY:
        tc = ts_col(t)
        manifest["daily_dedup"][t] = tc
        rows = src.execute(
            f"SELECT {sel} FROM {t} WHERE rowid IN "
            f"(SELECT MAX(rowid) FROM {t} GROUP BY substr({tc},1,10)) ORDER BY {tc}")
    else:
        rows = src.execute(f"SELECT {sel} FROM {t}")
    data = [tuple(r) for r in rows]
    dst.executemany(f"INSERT INTO {t} ({sel}) VALUES ({placeholders})", data)
    total = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    manifest["tables"][t] = {"kept": len(data), "source_rows": total}
    print(f"   {t}: {len(data)} av {total} rader beholdt")
dst.commit()

# Lesbare eksporter
dst.row_factory = sqlite3.Row
def dump_jsonl(t, fn):
    with open(os.path.join(out, fn), "w", encoding="utf-8") as f:
        for r in dst.execute(f"SELECT * FROM {t}"):
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")

def dump_csv(t, fn):
    cur = dst.execute(f"SELECT * FROM {t}")
    with open(os.path.join(out, fn), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([d[0] for d in cur.description])
        w.writerows(cur)

for t in manifest["tables"]:
    dump_jsonl(t, f"{t}.jsonl")
for t in ("world_model_priors", "intelligence_scores", "oracle_bandit_state"):
    if t in manifest["tables"]:
        dump_csv(t, f"{t}.csv")

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

manifest["files"] = {fn: sha(os.path.join(out, fn))
                     for fn in sorted(os.listdir(out)) if fn != "manifest.json"}
with open(os.path.join(out, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)

# SQL for å rydde dupliserte logg-rader i D1 (brukes bare med --prune-remote)
with open(os.path.join(out, "prune-remote.sql"), "w") as f:
    for t, tc in manifest["daily_dedup"].items():
        f.write(f"DELETE FROM {t} WHERE rowid NOT IN "
                f"(SELECT MAX(rowid) FROM {t} GROUP BY substr({tc},1,10));\n")
print("   manifest.json og prune-remote.sql skrevet")
PY

# Sjekk at eksporten faktisk inneholder episodene før noe slettes
count_ep() { python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('SELECT COUNT(*) FROM episodes').fetchone()[0])" "$1"; }
EP_KEPT=$(count_ep "$OUT/aromer-research.db")
EP_SRC=$(count_ep "$OUT/aromer-full.db")
[ "$EP_KEPT" = "$EP_SRC" ] && [ "$EP_KEPT" -gt 0 ] || {
  echo "Avbryter: episodes i eksport ($EP_KEPT) != kilde ($EP_SRC)"; exit 1; }
echo "==> Verifiserer mot referanseverdier lest direkte fra D1 (2026-11-03 21:30)"
python3 - "$OUT/aromer-full.db" "$OUT/aromer-research.db" <<'PY'
import sqlite3, sys
full, res = (sqlite3.connect(p) for p in sys.argv[1:3])
q = lambda c, s: c.execute(s).fetchone()[0]
checks = [
  # (beskrivelse, faktisk, forventet, eksakt?)
  ("episodes totalt",              q(full,"SELECT COUNT(*) FROM episodes"), 21864, True),
  ("episodes ground_truth=unknown",q(full,"SELECT COUNT(*) FROM episodes WHERE ground_truth='unknown'"), 738, True),
  ("episodes merket",              q(full,"SELECT COUNT(*) FROM episodes WHERE ground_truth IN ('harmful','benign')"), 21126, True),
  ("episodes kritisert",           q(full,"SELECT COUNT(*) FROM episodes WHERE critique_text IS NOT NULL AND critique_text<>''"), 6286, False),
  ("domain=system",                q(full,"SELECT COUNT(*) FROM episodes WHERE domain='system'"), 11409, True),
  ("domain=information",           q(full,"SELECT COUNT(*) FROM episodes WHERE domain='information'"), 7130, True),
  ("domain=git",                   q(full,"SELECT COUNT(*) FROM episodes WHERE domain='git'"), 717, True),
  ("første episode",               q(full,"SELECT MIN(timestamp) FROM episodes"), "2026-06-04T06:57:18.154Z", True),
  ("siste episode",                q(full,"SELECT MAX(timestamp) FROM episodes"), "2026-07-02T15:47:57.448Z", True),
  ("world_model_priors",           q(full,"SELECT COUNT(*) FROM world_model_priors"), 198, True),
  ("oracle_bandit_state",          q(full,"SELECT COUNT(*) FROM oracle_bandit_state"), 3, True),
  ("intelligence_scores (≥)",      q(full,"SELECT COUNT(*) FROM intelligence_scores"), 37694, False),
  ("research.db episodes = full",  q(res,"SELECT COUNT(*) FROM episodes"), q(full,"SELECT COUNT(*) FROM episodes"), True),
]
bad = 0
for name, got, exp, exact in checks:
    ok = (got == exp) if exact else (got >= exp)
    bad += not ok
    print(f"   {'OK  ' if ok else 'AVVIK'} {name:32} {got!s:28} (forventet {'' if exact else '≥ '}{exp})")
if bad:
    print(f"   {bad} avvik — eksporten er IKKE verifisert. Ingenting slettes.")
    sys.exit(4)
print("   Alle kontroller OK.")
PY

COPYFILE_DISABLE=1 tar -czf "${OUT}.tar.gz" "$OUT"
echo "==> Privat eksport ferdig: ${OUT}.tar.gz ($EP_KEPT episoder verifisert)"
echo "    INNEHOLDER RÅ TOOL-INPUT (meta.input_preview) — skal IKKE publiseres."

echo "==> 3b Lager sanert publiseringspakke: ${OUT}-public/"
python3 - "$OUT" "${OUT}-public" <<'PY'
import csv, hashlib, json, os, re, sqlite3, sys

src_dir, pub = sys.argv[1], sys.argv[2]
os.makedirs(pub, exist_ok=True)
db = sqlite3.connect(os.path.join(src_dir, "aromer-research.db"))
db.row_factory = sqlite3.Row

# Felter som kan bære rå bruker-/agentinnhold fjernes helt.
DROP_COLS = {"critique_text", "raw_json", "input", "tool_input", "notes"}
DROP_META = {"input_preview", "session_id", "tool_input", "cwd", "command",
             "file_path", "path", "prompt", "content", "transcript"}
SECRETISH = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|(?i:password|passwd|api[_-]?key|secret|token)\s*[=:]\s*\S+"
    r"|/Users/[^/\s\"]+|/home/[^/\s\"]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

def clean_meta(raw):
    if raw in (None, ""):
        return None
    try:
        m = json.loads(raw)
    except Exception:
        return None
    if not isinstance(m, dict):
        return None
    out = {}
    for k, v in m.items():
        if k.lower() in DROP_META:
            continue
        if isinstance(v, str) and (len(v) > 80 or SECRETISH.search(v)):
            continue           # fritekst/stier/hemmeligheter ut
        if isinstance(v, (dict, list)):
            s = json.dumps(v)
            if len(s) > 2000 or SECRETISH.search(s):
                continue
        out[k] = v
    return out or None

summary = {"dropped_columns": sorted(DROP_COLS), "dropped_meta_keys": sorted(DROP_META), "files": {}}

# episodes (sanert)
cols = [r["name"] for r in db.execute("PRAGMA table_info(episodes)")]
keep = [c for c in cols if c not in DROP_COLS]
with open(os.path.join(pub, "episodes_public.jsonl"), "w", encoding="utf-8") as f:
    n = 0
    for r in db.execute(f"SELECT {','.join(keep)} FROM episodes"):
        d = dict(r)
        if "meta" in d:
            d["meta"] = clean_meta(d["meta"])
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
        n += 1
summary["episodes_public"] = n

# små, strukturelle tabeller
for t, fn in (("world_model_priors", "world_model_priors.csv"),
              ("oracle_bandit_state", "oracle_bandit_state.csv"),
              ("intelligence_scores", "intelligence_scores_daily.csv")):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
        continue
    tcols = [r["name"] for r in db.execute(f"PRAGMA table_info({t})") if r["name"] not in DROP_COLS]
    cur = db.execute(f"SELECT {','.join(tcols)} FROM {t}")
    with open(os.path.join(pub, fn), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(tcols); w.writerows(cur)

# Sluttkontroll: ingen hemmelighets-/sti-/e-postmønstre får bli igjen
hits = {}
for fn in sorted(os.listdir(pub)):
    p = os.path.join(pub, fn)
    with open(p, encoding="utf-8") as f:
        c = sum(1 for line in f if SECRETISH.search(line))
    if c:
        hits[fn] = c
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    summary["files"][fn] = {"sha256": h, "bytes": os.path.getsize(p)}
summary["residual_pattern_hits"] = hits
with open(os.path.join(pub, "manifest_public.json"), "w") as f:
    json.dump(summary, f, indent=2)
if hits:
    print(f"   STOPP: mønstertreff igjen i offentlig pakke: {hits} — se over før publisering")
    sys.exit(3)
print(f"   {n} sanerte episoder, 0 mønstertreff. Klar for gjennomgang.")
PY
COPYFILE_DISABLE=1 tar -czf "${OUT}-public.tar.gz" "${OUT}-public"
echo "==> Offentlig kandidat: ${OUT}-public.tar.gz"

echo "==> 4/4 Opprydding: $MODE"
case "$MODE" in
  export)
    echo "   Ingenting slettet." ;;
  --prune-remote)
    echo "   Time Travel-bokmerke før sletting (kan gjenopprettes i 30 dager):"
    npx wrangler d1 time-travel info "$DB_NAME" | tee "$OUT/bookmark-before-prune.txt"
    read -r -p "   Slette dupliserte rader i intelligence_scores/adaptation_cycles i D1? Skriv JA: " ok
    [ "$ok" = "JA" ] || { echo "   Avbrutt."; exit 0; }
    npx wrangler d1 execute "$DB_NAME" --remote --file="$OUT/prune-remote.sql"
    echo "   Ferdig. Worker og episoder står urørt." ;;
  --teardown)
    echo "   ADVARSEL: REMORA-hooken (/episode, /scan-result) slutter å fungere."
    read -r -p "   Slette worker '$WORKER_NAME', D1 '$DB_NAME' og KV AROMER_STATE? Skriv SLETT: " ok
    [ "$ok" = "SLETT" ] || { echo "   Avbrutt."; exit 0; }
    npx wrangler delete --name "$WORKER_NAME"
    npx wrangler d1 delete "$DB_NAME"
    npx wrangler kv namespace delete --namespace-id "$KV_ID"
    echo "   aromer er fjernet. Data ligger i ${OUT}.tar.gz." ;;
esac
