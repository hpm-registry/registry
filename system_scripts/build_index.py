#!/usr/bin/env python3
"""
build_index.py -- Generate the AI-facing index layer from component files.

The index/ directory is DERIVED. Never edit it by hand; it is regenerated
from components/ by this script (run it in CI on every merge to main).

Outputs into index/:
  manifest.json                              -- registry-wide table of contents + counts
  by-id.json                                 -- {id: path} for O(1) lookup by ID
  by-category.json                           -- {category: {subcategory: [ids]}} tree
  aliases.json                               -- {alias: canonical_id}
  variants.json                              -- {base_id: [variant_ids]}
  by-spec/<category>/<subcategory>/<key>.json -- sorted [{id, min, typ, max, value}]
                                                for numeric spec filtering without
                                                fetching every component file

Agent consumption order:
  1. manifest.json  -- understand registry shape and counts
  2. aliases.json   -- resolve non-canonical query to canonical id
  3. by-id.json     -- get file path for a known id
  4. by-category.json + by-spec/ -- discover by category and filter by spec numerically
"""
import json
import shutil
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = REPO_ROOT / "components"
INDEX_DIR = REPO_ROOT / "index"
SPEC_INDEX_DIR = INDEX_DIR / "by-spec"
EXAMPLES_DIRNAME = "_examples"


def load_components():
    items = []
    for path in sorted(COMPONENTS_DIR.rglob("*.json")):
        if EXAMPLES_DIRNAME in path.parts:
            continue
        with open(path) as f:
            data = json.load(f)
        data["_path"] = str(path.relative_to(REPO_ROOT))
        items.append(data)
    return items


def canonical_sort_value(spec):
    """Single numeric value used to sort a spec entry. Prefer typ, then value, then midpoint of range."""
    if spec.get("typ") is not None:
        return spec["typ"]
    v = spec.get("value")
    if isinstance(v, (int, float)):
        return v
    lo = spec.get("min")
    hi = spec.get("max")
    if lo is not None and hi is not None:
        return (lo + hi) / 2
    if lo is not None:
        return lo
    if hi is not None:
        return hi
    return None


def build_spec_index(components):
    """
    Returns {(category, subcategory, spec_key): {"unit": str, "entries": [...]}}

    Each entry: {id, min, typ, max, value, _sort}
    Entries are sorted ascending by _sort (canonical numeric value).
    Only numeric specs are indexed (string/boolean values are skipped).
    """
    groups = defaultdict(lambda: {"unit": None, "entries": []})

    for c in components:
        cat = c.get("category")
        sub = c.get("subcategory")
        cid = c.get("id")
        specs = c.get("specs", {})

        for key, spec in specs.items():
            if not isinstance(spec, dict):
                continue

            # Skip non-numeric value specs (boolean flags, string identifiers)
            raw_value = spec.get("value")
            if isinstance(raw_value, (bool, str)):
                continue

            sort_val = canonical_sort_value(spec)
            if sort_val is None:
                continue  # no numeric data to index

            group_key = (cat, sub, key)
            unit = spec.get("unit", "")

            # Consistency check: warn if same spec key has conflicting units
            # (different entries in same subcategory using different units for same key)
            existing_unit = groups[group_key]["unit"]
            if existing_unit is None:
                groups[group_key]["unit"] = unit
            elif existing_unit != unit:
                print(
                    f"  WARNING: unit conflict for {cat}/{sub}/{key}: "
                    f"'{existing_unit}' vs '{unit}' (id={cid}) — "
                    f"entries with mismatched units are excluded from spec index"
                )
                continue

            entry = {
                "id": cid,
                "min": spec.get("min"),
                "typ": spec.get("typ"),
                "max": spec.get("max"),
                "value": raw_value if isinstance(raw_value, (int, float)) else None,
                "_sort": sort_val,
            }
            groups[group_key]["entries"].append(entry)

    # Sort each group ascending by canonical value, strip internal _sort key
    result = {}
    for group_key, data in groups.items():
        sorted_entries = sorted(data["entries"], key=lambda e: e["_sort"])
        for e in sorted_entries:
            del e["_sort"]
        result[group_key] = {"unit": data["unit"], "entries": sorted_entries}

    return result


def write_spec_index(spec_index):
    # Clear and rebuild the entire by-spec tree so deleted specs don't linger
    if SPEC_INDEX_DIR.exists():
        shutil.rmtree(SPEC_INDEX_DIR)

    files_written = 0
    for (cat, sub, key), data in sorted(spec_index.items()):
        out_dir = SPEC_INDEX_DIR / cat / sub
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{key}.json"
        payload = {
            "category": cat,
            "subcategory": sub,
            "spec_key": key,
            "unit": data["unit"],
            "note": "Sorted ascending by canonical value (typ > midpoint(min,max) > min > max). "
                    "Fetch the full component file for non-numeric specs and full context.",
            "entries": data["entries"],
        }
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        files_written += 1

    return files_written


def main():
    INDEX_DIR.mkdir(exist_ok=True)
    components = load_components()

    by_id = {}
    by_category = defaultdict(lambda: defaultdict(list))
    aliases = {}
    variants = defaultdict(list)
    verified_count = 0
    unknown_license_count = 0

    for c in components:
        cid = c["id"]
        by_id[cid] = c["_path"]
        by_category[c["category"]][c["subcategory"]].append(cid)
        for alias in c.get("aliases", []):
            aliases[alias] = cid
        if c.get("variant_of"):
            variants[c["variant_of"]].append(cid)
        if c.get("meta", {}).get("verified"):
            verified_count += 1
        for field in ("footprint", "symbol"):
            if c.get(field, {}).get("license") == "unknown":
                unknown_license_count += 1

    by_category = {k: dict(v) for k, v in sorted(by_category.items())}
    variants = {k: sorted(v) for k, v in sorted(variants.items())}

    print("Building spec index...")
    spec_index = build_spec_index(components)
    spec_files_written = write_spec_index(spec_index)

    manifest = {
        "schema_version": "1.3.0",
        "total_components": len(components),
        "verified_components": verified_count,
        "assets_with_unknown_license": unknown_license_count,
        "categories": {
            cat: sum(len(ids) for ids in subs.values())
            for cat, subs in by_category.items()
        },
        "index_files": {
            "by_id": "index/by-id.json",
            "by_category": "index/by-category.json",
            "aliases": "index/aliases.json",
            "variants": "index/variants.json",
            "by_spec": "index/by-spec/<category>/<subcategory>/<spec_key>.json"
        },
        "note": "Derived file. Regenerated by system_scripts/build_index.py. Do not edit."
    }

    writes = {
        "manifest.json": manifest,
        "by-id.json": dict(sorted(by_id.items())),
        "by-category.json": by_category,
        "aliases.json": dict(sorted(aliases.items())),
        "variants.json": variants,
    }
    for name, payload in writes.items():
        with open(INDEX_DIR / name, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print(f"wrote index/{name}")

    print(f"wrote {spec_files_written} spec index file(s) under index/by-spec/")
    print(
        f"\nIndexed {len(components)} component(s), {verified_count} verified, "
        f"{unknown_license_count} asset(s) with unknown license."
    )


if __name__ == "__main__":
    import sys
    if "--quiet" in sys.argv:
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            main()
    else:
        main()
