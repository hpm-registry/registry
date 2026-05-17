# HPM Component Registry

A community-driven, open-source registry of common PCB components — symbols,
footprints, datasheets, and structured electrical specs — designed to be read
both by **humans** browsing for parts and by **AI agents** resolving and
filtering them.

> **Status: v1 — schema & tooling.** The structure, schema, and tooling are
> locked. Coverage is built incrementally by contributors. Accuracy is the
> priority; an unverified entry is worse than a missing one.

## Repository layout

```
hpm-registry/
├── components/              # the registry — one JSON file per part
│   └── <category>/<subcategory>/<ID>.json
├── footprints/              # hosted KiCad footprints, mirrors components/
│   └── <category>/<subcategory>/<ID>.kicad_mod
├── symbols/                 # hosted KiCad symbols, mirrors components/
│   └── <category>/<subcategory>/<ID>.kicad_sym
├── 3d_models/               # hosted STEP/WRL models, mirrors components/
│   └── <category>/<subcategory>/<ID>.step
├── schema/
│   └── component.schema.json   # the locked schema; every part validates here
├── index/                   # AUTO-GENERATED — do not edit by hand
│   ├── manifest.json        # registry table of contents + counts
│   ├── by-id.json           # {id: path} for O(1) lookup
│   ├── by-category.json     # category → subcategory → [ids] tree
│   ├── aliases.json         # {alias: canonical_id}
│   ├── variants.json        # {variant_base: [ids]} package-variant groups
│   └── by-spec/             # numeric spec index for agent filtering
├── scripts/
│   ├── validate.py          # schema + filesystem-convention checker (CI)
│   └── build_index.py       # regenerates index/ from components/
├── MANUFACTURERS.md         # canonical manufacturer name list
```

## How the file system works

Every part lives at a **predictable path**:
`components/<category>/<subcategory>/<ID>.json`. The path is the index — a human
finds a part by clicking folders, an AI finds it by convention. The validator
enforces that the path, filename, and the file's `category`/`subcategory`/`id`
fields all agree, so the tree can never drift out of sync.

## For AI agents

Consume the registry in this order:

1. **Load `index/manifest.json`** — small; gives you total counts and the
   category tree shape.
2. **Lookup by part number:** check `index/aliases.json` to resolve a query to a
   canonical `id`, then `index/by-id.json` to get the file path. Fetch that one
   file.
3. **Discover by spec:** use `index/by-category.json` to get candidate `id`s in
   the relevant subcategory, then fetch and filter those files. Specs are stored
   as `{value|min|typ|max, unit}` objects — filter numerically, never parse
   strings.

The `index/` files are derived from `components/`; treat `components/` as the
source of truth if they ever disagree.

## For human contributors

See **[CONTRIBUTING.md](CONTRIBUTING.md)**. In short: find the right folder in
the category table, fill in real datasheet-sourced values, run
`python scripts/validate.py`, open a PR.

## License

Component data (specs, metadata) is contributed under CC0. Tooling and schema
under MIT. See `LICENSE`.

Footprints and symbols are **hosted** in this repo (`footprints/`, `symbols/`),
not referenced from external libraries. Each hosted file carries its own
`license` and `origin` in the component entry — a hosted file keeps the license
of wherever it came from. Files with an `unknown` license are accepted but
flagged for audit; files known to be non-redistributable must not be hosted.
