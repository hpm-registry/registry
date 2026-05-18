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
├── incoming/                # contributor staging area — never merged
├── user_scripts/
│   ├── add_part.py          # contributor CLI — adds a part end-to-end
│   └── update_part.py       # contributor CLI — updates an existing part
├── system_scripts/
│   ├── validate.py          # local schema + filesystem checker
│   ├── ci_validate.py       # strict merge-gate validator (GitHub Actions)
│   ├── build_index.py       # regenerates index/ from components/
│   └── check_revision_bump.py  # CI: ensures modified entries bump revision
├── requirements.txt         # pip dependencies for scripts
└── MANUFACTURERS.md         # canonical manufacturer name list
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

The fastest path is `user_scripts/add_part.py`. Drop your datasheet PDF, KiCad
footprint(s), and symbol into the `incoming/` folder, then run:

```bash
pip install -r requirements.txt
python user_scripts/add_part.py
```

The script uses Claude to extract structured data from the datasheet, shows you
a review step, places all files into the correct registry locations, and
validates everything — leaving you with a clean `git commit` and PR.

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the full contributor guide.

## License

Component data (specs, metadata) is contributed under CC0. Tooling and schema
under MIT. See `LICENSE`.

Footprints and symbols are **hosted** in this repo (`footprints/`, `symbols/`),
not referenced from external libraries. All hosted assets must be
**CC-BY-SA-4.0** (KiCad official library) or **CC0-1.0** (original contributor
work). Files from DigiKey, SnapMagic, UltraLibrarian, or SamacSys are not
accepted — those services prohibit redistribution. The `origin` field in each
component entry records provenance for attribution compliance.
