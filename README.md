# Aetherlist hosted card library

This repository builds the expensive part of Aetherlist's offline library on a GitHub runner. The Android app only has to download, verify, decompress, and bulk-copy the finished SQLite catalog. Card images are **not** included; only Scryfall image URLs are stored.

## Put this on GitHub

Put these files at the root of `Phonophor/Aetherlist`. In GitHub, open **Actions → Publish Aetherlist card library → Run workflow**. The workflow creates a release tagged `card-library` with:

- `aetherlist-library-manifest.json`
- `aetherlist-catalog.sqlite.gz` (ready-to-open database used by the app)
- `aetherlist-cards.sqlite.gz`
- `aetherlist-oracle-tags.sqlite.gz`
- `aetherlist-art-tags.sqlite.gz`
- `aetherlist-rulings.sqlite.gz`

The URLs remain stable. `aetherlist-catalog.sqlite.gz` already contains all catalog tables, Room-managed indexes, and FTS data. Runtime-only expression indexes are deliberately excluded until Room finishes schema validation. Aetherlist activates the file instead of copying cards or rebuilding search data on the phone. Split assets remain available for diagnostics and future modular readers.

## Oracle and art tags

The builder automatically discovers Scryfall's official `oracle_tags` and `art_tags` bulk exports and includes them. No secrets or manual URLs are required. `AETHERLIST_ORACLE_TAGS_URL` and `AETHERLIST_ART_TAGS_URL` remain available only as optional overrides for testing.

Accepted tag records use `label` or `name`, plus either an ID array (`oracle_ids` / `illustration_ids`) or `taggings` objects containing `oracle_id` / `illustration_id` and an optional `weight`.

## App connection

The accompanying Aetherlist Android source is already pointed at `Phonophor/Aetherlist` and installs this catalog through Initial setup, Cards, or Update all.

## Schedule

Scheduled builds start at **05:00 Europe/Zurich** every day. The workflow uses
two UTC triggers plus a Zurich-time guard so daylight-saving changes do not
move the local run time. Manual runs are always allowed.
