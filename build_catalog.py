#!/usr/bin/env python3
"""Build Aetherlist's replaceable, image-free SQLite catalog on GitHub Actions."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import ijson
import requests

API = "https://api.scryfall.com/bulk-data"
UA = "Aetherlist catalog builder/1.0 (GitHub Actions)"
SCRIPT_DIR = Path(__file__).resolve().parent
# Keep CI output inside the checked-out repository. Previously, parents[1]
# pointed one directory above GITHUB_WORKSPACE when this script was stored at
# the repository root, so the build succeeded but the publishing step failed.
ROOT = Path(
    os.environ.get("AETHERLIST_OUTPUT_ROOT")
    or os.environ.get("GITHUB_WORKSPACE")
    or SCRIPT_DIR
).resolve()
DIST = ROOT / "dist"
DB = DIST / "aetherlist-library-build.sqlite"
MANIFEST = DIST / "aetherlist-library-manifest.json"
BATCH = 5000
# Increment only when the on-device meaning/schema of a split asset changes.
# Normal daily rebuilds use Scryfall's per-dataset updated_at for freshness.
DATASET_REVISION = 1

CARD_COLUMNS = (
    "id", "oracleId", "name", "manaCost", "manaValue", "typeLine", "oracleText", "colors",
    "colorIdentity", "rarity", "setCode", "setName", "collectorNumber", "releasedAt",
    "legalitiesJson", "keywordsJson", "imageNormal", "imageSmall", "lang", "cardmarketId",
    "cardmarketEur", "cardmarketEurFoil", "illustrationIdsJson", "localImagePath", "updatedAtEpochMs",
    "oracleLowestCardmarketCents", "oracleLowestCardmarketCardId", "oracleLowestCtZeroCents",
    "oracleLowestCtZeroCardId", "oraclePriceCurrency", "power", "toughness", "loyalty", "defense",
    "artist", "flavorText", "layout", "frame", "borderColor", "frameEffectsJson", "gamesJson",
    "finishesJson", "setType", "promoTypesJson", "producedManaJson", "fullArt", "textless",
    "oversized", "reserved", "reprint", "variation", "digital", "promo", "booster", "storySpotlight"
)


def get_json(url: str) -> dict:
    response = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=90)
    response.raise_for_status()
    return response.json()


def download(url: str, target: Path) -> None:
    with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=(30, 900)) as response:
        response.raise_for_status()
        with target.open("wb") as out:
            for block in response.iter_content(1024 * 1024):
                if block:
                    out.write(block)


def compact(value, default):
    return json.dumps(value if value is not None else default, ensure_ascii=False, separators=(",", ":"))


def image_urls(card: dict) -> tuple[str | None, str | None]:
    images = card.get("image_uris") or {}
    normal, small = images.get("normal"), images.get("small")
    if not (normal and small):
        for face in card.get("card_faces") or []:
            face_images = face.get("image_uris") or {}
            normal = normal or face_images.get("normal")
            small = small or face_images.get("small")
    return normal, small


def oracle_text(card: dict) -> str:
    direct = card.get("oracle_text") or ""
    if direct:
        return direct
    parts = []
    for face in card.get("card_faces") or []:
        text = face.get("oracle_text") or ""
        if text:
            parts.append(f"{face.get('name', '')}\n{text}".strip())
    return "\n\n—\n\n".join(parts)


def card_row(card: dict, stamp: int) -> tuple:
    normal, small = image_urls(card)
    prices = card.get("prices") or {}
    illustrations = {x for x in [card.get("illustration_id")] if x}
    illustrations.update(f.get("illustration_id") for f in card.get("card_faces") or [] if f.get("illustration_id"))
    mana = card.get("mana_cost")
    if mana is None and card.get("card_faces"):
        mana = card["card_faces"][0].get("mana_cost")
    def price(key):
        try: return float(prices[key]) if prices.get(key) is not None else None
        except (TypeError, ValueError): return None
    return (
        card.get("id", ""), card.get("oracle_id"), card.get("name", ""), mana,
        float(card.get("cmc") or 0), card.get("type_line", ""), oracle_text(card), "".join(card.get("colors") or []),
        "".join(card.get("color_identity") or []), card.get("rarity", ""), card.get("set", ""), card.get("set_name", ""),
        card.get("collector_number", ""), card.get("released_at", ""), compact(card.get("legalities"), {}),
        compact(card.get("keywords"), []), normal, small, card.get("lang") or "en", card.get("cardmarket_id"),
        price("eur"), price("eur_foil"), compact(sorted(illustrations), []), None, stamp,
        None, None, None, None, "EUR", card.get("power"), card.get("toughness"), card.get("loyalty"),
        card.get("defense"), card.get("artist") or "", card.get("flavor_text") or "", card.get("layout") or "",
        card.get("frame") or "", card.get("border_color") or "", compact(card.get("frame_effects"), []),
        compact(card.get("games"), []), compact(card.get("finishes"), []), card.get("set_type") or "",
        compact(card.get("promo_types"), []), compact(card.get("produced_mana"), []),
        int(bool(card.get("full_art"))), int(bool(card.get("textless"))), int(bool(card.get("oversized"))),
        int(bool(card.get("reserved"))), int(bool(card.get("reprint"))), int(bool(card.get("variation"))),
        int(bool(card.get("digital"))), int(bool(card.get("promo"))), int(bool(card.get("booster"))),
        int(bool(card.get("story_spotlight")))
    )


def schema(connection: sqlite3.Connection) -> None:
    columns = [
        "id TEXT PRIMARY KEY", "oracleId TEXT", "name TEXT NOT NULL", "manaCost TEXT", "manaValue REAL NOT NULL",
        "typeLine TEXT NOT NULL", "oracleText TEXT NOT NULL", "colors TEXT NOT NULL", "colorIdentity TEXT NOT NULL",
        "rarity TEXT NOT NULL", "setCode TEXT NOT NULL", "setName TEXT NOT NULL", "collectorNumber TEXT NOT NULL",
        "releasedAt TEXT NOT NULL", "legalitiesJson TEXT NOT NULL", "keywordsJson TEXT NOT NULL", "imageNormal TEXT",
        "imageSmall TEXT", "lang TEXT NOT NULL", "cardmarketId INTEGER", "cardmarketEur REAL", "cardmarketEurFoil REAL",
        "illustrationIdsJson TEXT NOT NULL", "localImagePath TEXT", "updatedAtEpochMs INTEGER NOT NULL",
        "oracleLowestCardmarketCents INTEGER", "oracleLowestCardmarketCardId TEXT", "oracleLowestCtZeroCents INTEGER",
        "oracleLowestCtZeroCardId TEXT", "oraclePriceCurrency TEXT NOT NULL", "power TEXT", "toughness TEXT", "loyalty TEXT",
        "defense TEXT", "artist TEXT NOT NULL", "flavorText TEXT NOT NULL", "layout TEXT NOT NULL", "frame TEXT NOT NULL",
        "borderColor TEXT NOT NULL", "frameEffectsJson TEXT NOT NULL", "gamesJson TEXT NOT NULL", "finishesJson TEXT NOT NULL",
        "setType TEXT NOT NULL", "promoTypesJson TEXT NOT NULL", "producedManaJson TEXT NOT NULL", "fullArt INTEGER NOT NULL",
        "textless INTEGER NOT NULL", "oversized INTEGER NOT NULL", "reserved INTEGER NOT NULL", "reprint INTEGER NOT NULL",
        "variation INTEGER NOT NULL", "digital INTEGER NOT NULL", "promo INTEGER NOT NULL", "booster INTEGER NOT NULL",
        "storySpotlight INTEGER NOT NULL"
    ]
    connection.executescript(f"""
        CREATE TABLE cards ({','.join(columns)});
        CREATE TABLE oracle_tags(slug TEXT PRIMARY KEY, label TEXT NOT NULL);
        CREATE TABLE card_oracle_tags(oracleId TEXT NOT NULL, tagSlug TEXT NOT NULL, weight REAL NOT NULL, PRIMARY KEY(oracleId,tagSlug));
        CREATE TABLE art_tags(slug TEXT PRIMARY KEY, label TEXT NOT NULL);
        CREATE TABLE illustration_art_tags(illustrationId TEXT NOT NULL, tagSlug TEXT NOT NULL, weight REAL NOT NULL, PRIMARY KEY(illustrationId,tagSlug));
        CREATE TABLE rulings(oracleId TEXT NOT NULL, publishedAt TEXT NOT NULL, comment TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(oracleId,publishedAt,comment));
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)


@contextmanager
def open_decoded(path: Path):
    """Open a plain or gzip payload, detecting gzip from its magic bytes.

    Scryfall's jsonl_download_uri currently returns gzip-compressed JSONL with
    no HTTP Content-Encoding that requests can transparently decode. Magic-byte
    detection also keeps this compatible with plain JSON/JSONL tag exports.
    """
    raw = path.open("rb")
    try:
        magic = raw.read(2)
        raw.seek(0)
        stream = gzip.GzipFile(fileobj=raw, mode="rb") if magic == b"\x1f\x8b" else raw
        try:
            yield stream
        finally:
            if stream is not raw:
                stream.close()
    finally:
        raw.close()


def first_non_whitespace(stream) -> bytes:
    while True:
        byte = stream.read(1)
        if not byte or not byte.isspace():
            return byte


def iter_json(path: Path):
    """Stream records from plain/gzipped JSON arrays or JSONL files."""
    with open_decoded(path) as stream:
        first = first_non_whitespace(stream)
        stream.seek(0)
        if first == b"[":
            yield from ijson.items(stream, "item")
        else:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError(f"Invalid JSONL record at {path.name}:{line_number}: {error}") from error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publish_dataset(source: sqlite3.Connection, name: str, tables: tuple[str, ...],
                    updated_at: str, count: int, base: str) -> dict:
    """Create one minimal, independently replaceable SQLite release asset."""
    plain = DIST / f"aetherlist-{name}.sqlite"
    archive = DIST / f"aetherlist-{name}.sqlite.gz"
    plain.unlink(missing_ok=True)
    archive.unlink(missing_ok=True)
    output = sqlite3.connect(plain)
    try:
        output.execute("PRAGMA journal_mode=OFF")
        output.execute("PRAGMA synchronous=OFF")
        for table in tables:
            create_sql = source.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            output.execute(create_sql)
            columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
            placeholders = ",".join("?" for _ in columns)
            insert = f"INSERT INTO {table} VALUES ({placeholders})"
            cursor = source.execute(f"SELECT * FROM {table}")
            while True:
                rows = cursor.fetchmany(BATCH)
                if not rows:
                    break
                output.executemany(insert, rows)
        output.commit()
        if output.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"{name} SQLite integrity check failed")
        output.execute("VACUUM")
    finally:
        output.close()
    with plain.open("rb") as src, archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
    result = {
        "revision": DATASET_REVISION,
        "updatedAt": updated_at or "",
        "count": count,
        "compressedBytes": archive.stat().st_size,
        "uncompressedBytes": plain.stat().st_size,
        "sha256": sha256_file(archive),
        "url": f"{base}/{archive.name}" if base else archive.name,
    }
    plain.unlink()
    return result


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def tag_weight(value) -> float:
    """Match Arcana's Android importer for numeric and qualitative weights."""
    if value is None:
        return 1.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return {
            "very_weak": 0.25,
            "weak": 0.5,
            "median": 1.0,
            "medium": 1.0,
            "normal": 1.0,
            "strong": 1.5,
            "very_strong": 2.0,
        }.get(str(value).strip().lower().replace("-", "_").replace(" ", "_"), 1.0)


def bulk_url(item: dict | None) -> str:
    if not item:
        return ""
    return item.get("jsonl_download_uri") or item.get("download_uri") or ""


def import_tags(connection: sqlite3.Connection, url: str, kind: str) -> int:
    if not url:
        return 0
    path = DIST / f"{kind}.json"
    download(url, path)
    tag_table, ref_table = (("oracle_tags", "card_oracle_tags") if kind == "oracle-tags" else ("art_tags", "illustration_art_tags"))
    id_key = "oracle_id" if kind == "oracle-tags" else "illustration_id"
    ids_key = "oracle_ids" if kind == "oracle-tags" else "illustration_ids"
    # First pass: retain only the small tag graph. Taggings themselves stay
    # streamed because the art export contains hundreds of thousands of them.
    graph = {}
    for record in iter_json(path):
        label = record.get("label") or record.get("name") or ""
        tag = record.get("slug") or slug(label)
        if not tag:
            continue
        aliases = [slug(value) for value in record.get("aliases", []) if slug(value)]
        graph[record.get("id") or tag] = {
            "slug": tag,
            "label": label,
            "aliases": aliases,
            "parents": record.get("parent_ids", []),
        }

    for node in graph.values():
        connection.execute(f"INSERT OR REPLACE INTO {tag_table} VALUES (?,?)", (node["slug"], node["label"]))
        connection.executemany(
            f"INSERT OR REPLACE INTO {tag_table} VALUES (?,?)",
            [(alias, alias) for alias in node["aliases"]],
        )

    ancestor_cache = {}
    def searchable_slugs(tag_id, visiting=None):
        if tag_id in ancestor_cache:
            return ancestor_cache[tag_id]
        node = graph.get(tag_id)
        if not node:
            return set()
        visiting = set() if visiting is None else visiting
        if tag_id in visiting:
            return {node["slug"], *node["aliases"]}
        visiting = visiting | {tag_id}
        result = {node["slug"], *node["aliases"]}
        for parent_id in node["parents"]:
            result.update(searchable_slugs(parent_id, visiting))
        ancestor_cache[tag_id] = result
        return result

    # Second pass: assign each card/illustration to its direct tag and every
    # ancestor (plus aliases). This is required for broad searches such as
    # otag:draw because Scryfall stores the actual cards on child tags.
    pending = []
    insert_sql = f"INSERT OR IGNORE INTO {ref_table} VALUES (?,?,?)"
    for record in iter_json(path):
        record_id = record.get("id") or record.get("slug") or slug(record.get("label") or record.get("name") or "")
        targets = searchable_slugs(record_id)
        pairs = [(value, 1.0) for value in record.get(ids_key, [])]
        pairs += [(entry.get(id_key), tag_weight(entry.get("weight"))) for entry in record.get("taggings", [])]
        for value, weight in pairs:
            if value:
                pending.extend((value, target, weight) for target in targets)
            if len(pending) >= 10_000:
                connection.executemany(insert_sql, pending)
                pending.clear()
    if pending:
        connection.executemany(insert_sql, pending)

    refs = connection.execute(f"SELECT COUNT(*) FROM {ref_table}").fetchone()[0]
    path.unlink(missing_ok=True)
    return refs


def main() -> None:
    DIST.mkdir(exist_ok=True)
    DB.unlink(missing_ok=True)
    bulk = get_json(API)["data"]
    items = {item["type"]: item for item in bulk}
    cards_item = items.get("default_cards") or items["oracle_cards"]
    stamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    source = DIST / "cards.json"
    download(bulk_url(cards_item), source)

    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("PRAGMA temp_store=MEMORY")
    schema(db)
    placeholders = ",".join("?" for _ in CARD_COLUMNS)
    sql = f"INSERT INTO cards ({','.join(CARD_COLUMNS)}) VALUES ({placeholders})"
    batch, card_count = [], 0
    with db:
        for card in iter_json(source):
            row = card_row(card, stamp)
            if row[0] and row[2]:
                batch.append(row)
            if len(batch) >= BATCH:
                db.executemany(sql, batch); card_count += len(batch); batch.clear()
                print(f"cards: {card_count}", flush=True)
        if batch:
            db.executemany(sql, batch); card_count += len(batch)
    source.unlink(missing_ok=True)

    ruling_count = 0
    rulings_item = items.get("rulings")
    if rulings_item:
        source = DIST / "rulings.json"
        download(bulk_url(rulings_item), source)
        rows = []
        with db:
            for ruling in iter_json(source):
                oracle_id = ruling.get("oracle_id")
                if oracle_id and ruling.get("comment"):
                    rows.append((oracle_id, ruling.get("published_at", ""), ruling["comment"], ruling.get("source", "scryfall")))
                if len(rows) >= BATCH:
                    db.executemany("INSERT OR IGNORE INTO rulings VALUES (?,?,?,?)", rows); ruling_count += len(rows); rows.clear()
            if rows:
                db.executemany("INSERT OR IGNORE INTO rulings VALUES (?,?,?,?)", rows); ruling_count += len(rows)
        # INSERT OR IGNORE removes duplicate ruling records; report stored rows,
        # not attempted rows, so the manifest matches the finished database.
        ruling_count = db.execute("SELECT COUNT(*) FROM rulings").fetchone()[0]
        source.unlink(missing_ok=True)

    # Prefer an explicit override when provided, otherwise use the official
    # oracle_tags and art_tags exports advertised by Scryfall's bulk manifest.
    oracle_tags_item = items.get("oracle_tags")
    art_tags_item = items.get("art_tags")
    oracle_tags_url = os.getenv("AETHERLIST_ORACLE_TAGS_URL") or bulk_url(oracle_tags_item)
    art_tags_url = os.getenv("AETHERLIST_ART_TAGS_URL") or bulk_url(art_tags_item)

    with db:
        print("Importing Oracle tags", flush=True)
        oracle_refs = import_tags(db, oracle_tags_url, "oracle-tags")
        print(f"Oracle tag references: {oracle_refs}", flush=True)
        print("Importing art tags", flush=True)
        art_refs = import_tags(db, art_tags_url, "art-tags")
        print(f"Art tag references: {art_refs}", flush=True)
        db.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("schema_version", "1"), ("cards_updated_at", cards_item.get("updated_at", "")),
            ("oracle_tags_updated_at", (oracle_tags_item or {}).get("updated_at", "")),
            ("art_tags_updated_at", (art_tags_item or {}).get("updated_at", "")),
            ("built_at", datetime.now(timezone.utc).isoformat())
        ])
        db.executescript("""
            CREATE INDEX index_cards_oracleId ON cards(oracleId);
            CREATE INDEX index_cards_setCode ON cards(setCode);
            CREATE INDEX index_cards_releasedAt ON cards(releasedAt);
            CREATE INDEX index_cards_cardmarketId ON cards(cardmarketId);
            CREATE INDEX index_cards_lang ON cards(lang);
            CREATE INDEX index_cards_oracleKey_expr ON cards(COALESCE(oracleId,id));
            CREATE INDEX index_card_oracle_tags_tagSlug ON card_oracle_tags(tagSlug);
            CREATE INDEX index_illustration_art_tags_tagSlug ON illustration_art_tags(tagSlug);
            CREATE INDEX index_illustration_art_tags_illustrationId ON illustration_art_tags(illustrationId);
            CREATE INDEX index_rulings_oracleId ON rulings(oracleId);
            CREATE VIRTUAL TABLE card_name_fts USING fts4(cardId TEXT, name TEXT, tokenize=unicode61);
            INSERT INTO card_name_fts(cardId,name) SELECT id,name FROM cards;
            ANALYZE;
        """)
    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    db.execute("VACUUM")
    base = os.getenv("AETHERLIST_RELEASE_BASE", "").rstrip("/")
    datasets = {
        "cards": publish_dataset(db, "cards", ("cards",), cards_item.get("updated_at", ""), card_count, base),
        "oracle_tags": publish_dataset(db, "oracle-tags", ("oracle_tags", "card_oracle_tags"),
                                       (oracle_tags_item or {}).get("updated_at", ""), oracle_refs, base),
        "art_tags": publish_dataset(db, "art-tags", ("art_tags", "illustration_art_tags"),
                                    (art_tags_item or {}).get("updated_at", ""), art_refs, base),
        "rulings": publish_dataset(db, "rulings", ("rulings",),
                                  (rulings_item or {}).get("updated_at", ""), ruling_count, base),
    }
    db.close()
    manifest = {
        "schemaVersion": 2,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "datasets": datasets,
        "containsImages": False,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    DB.unlink()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"catalog build failed: {error}", file=sys.stderr)
        raise
