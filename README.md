# Aetherlist hosted card library

This repository builds the expensive part of Aetherlist's offline library on a GitHub runner. The Android app only has to download, verify, decompress, and bulk-copy the finished SQLite catalog. Card images are **not** included; only Scryfall image URLs are stored.

## Put this on GitHub

Put these files at the root of `Phonophor/Aetherlist`. In GitHub, open **Actions → Publish Aetherlist card library → Run workflow**. The workflow creates a release tagged `card-library` with:

- `aetherlist-library-manifest.json`
- `aetherlist-cards.sqlite.gz`
- `aetherlist-oracle-tags.sqlite.gz`
- `aetherlist-art-tags.sqlite.gz`
- `aetherlist-rulings.sqlite.gz`

The URLs remain stable. Every dataset has its own Scryfall update time, byte size, and SHA-256 in the manifest, so the app checks first and downloads only datasets that changed.

## Oracle and art tags

The builder automatically discovers Scryfall's official `oracle_tags` and `art_tags` bulk exports and includes them. No secrets or manual URLs are required. `AETHERLIST_ORACLE_TAGS_URL` and `AETHERLIST_ART_TAGS_URL` remain available only as optional overrides for testing.

Accepted tag records use `label` or `name`, plus either an ID array (`oracle_ids` / `illustration_ids`) or `taggings` objects containing `oracle_id` / `illustration_id` and an optional `weight`.

## App connection

The accompanying Aetherlist Android source is already pointed at `Phonophor/Aetherlist` and installs this catalog through Initial setup, Cards, or Update all.

## Schedule

Scheduled builds start at **05:00 Europe/Zurich** every day. The workflow uses
two UTC triggers plus a Zurich-time guard so daylight-saving changes do not
move the local run time. Manual runs are always allowed.
