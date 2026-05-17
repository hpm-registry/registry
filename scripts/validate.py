#!/usr/bin/env python3
"""
validate.py -- Validate HPM Registry component files.

Checks every component JSON file against:
  1. The JSON Schema (schema/component.schema.json)
  2. Filesystem conventions the schema cannot express:
       - filename (without .json) must equal the `id` field
       - the file's parent directory must equal `subcategory`
       - the grandparent directory must equal `category`
       - `id` must be globally unique across the registry
       - if meta.verified is true, meta.verified_by must be present

Usage:
    python scripts/validate.py                # validate everything under components/
    python scripts/validate.py path/to/x.json # validate specific file(s)

Exit code 0 = all valid, 1 = one or more failures. Designed to run in CI.
"""
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("ERROR: pip install jsonschema  (see CONTRIBUTING.md)")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "component.schema.json"
COMPONENTS_DIR = REPO_ROOT / "components"
EXAMPLES_DIRNAME = "_examples"  # skipped from path-convention checks


def load_schema():
    with open(SCHEMA_PATH) as f:
        return Draft202012Validator(json.load(f))


def gather_files(args):
    if args:
        return [Path(a).resolve() for a in args]
    return sorted(COMPONENTS_DIR.rglob("*.json"))


def check_path_conventions(path, data, errors):
    """Conventions tying filesystem layout to file contents."""
    stem = path.stem
    if data.get("id") != stem:
        errors.append(f"filename '{stem}' does not match id '{data.get('id')}'")

    # _examples files are exempt from category/subcategory directory checks
    if EXAMPLES_DIRNAME in path.parts:
        return

    parent = path.parent.name
    grandparent = path.parent.parent.name
    if data.get("subcategory") != parent:
        errors.append(
            f"parent dir '{parent}' does not match subcategory '{data.get('subcategory')}'"
        )
    if data.get("category") != grandparent:
        errors.append(
            f"grandparent dir '{grandparent}' does not match category '{data.get('category')}'"
        )


def check_verified(data, errors):
    meta = data.get("meta", {})
    if meta.get("verified") is True and not meta.get("verified_by"):
        errors.append("meta.verified is true but meta.verified_by is missing")


def check_revision_history(data, errors):
    """meta.revision must equal len(history); history revisions must be 1..N ascending."""
    meta = data.get("meta", {})
    revision = meta.get("revision")
    history = meta.get("history")
    if revision is None or not isinstance(history, list):
        return  # schema validation already reported the missing/wrong-type field
    if revision != len(history):
        errors.append(
            f"meta.revision ({revision}) does not equal length of meta.history ({len(history)})"
        )
    for i, entry in enumerate(history, start=1):
        if not isinstance(entry, dict):
            continue
        if entry.get("revision") != i:
            errors.append(
                f"meta.history[{i-1}].revision is {entry.get('revision')}, expected {i} "
                f"(history must be ascending and start at 1)"
            )


def check_hosted_assets(data, errors, warnings):
    """footprint.path and symbol.path, when set, must point at files that exist.
    A null path is a warning (valid but incomplete), a dangling path is an error."""
    for field in ("footprint", "symbol"):
        block = data.get(field)
        if not isinstance(block, dict):
            continue
        path = block.get("path")
        if path is None:
            warnings.append(
                f"{field}.path is null; entry has no hosted {field} file yet"
            )
            continue
        asset = REPO_ROOT / path
        if not asset.is_file():
            errors.append(
                f"{field}.path '{path}' does not point to an existing file"
            )
        # 'unknown' license is allowed but flagged for audit
        if block.get("license") == "unknown":
            warnings.append(
                f"{field}.license is 'unknown' - flagged for later license audit"
            )

    # If a 3d_model is declared, warn if the footprint file has no (model ...) block.
    if data.get("3d_model") and isinstance(data.get("footprint"), dict):
        fp_path = data["footprint"].get("path")
        if fp_path:
            fp_file = REPO_ROOT / fp_path
            if fp_file.is_file() and "(model " not in fp_file.read_text():
                warnings.append(
                    "3d_model is declared but the footprint file has no (model ...) block; "
                    "KiCad won't display the 3D model until the footprint links to it"
                )


def main():
    validator = load_schema()
    files = gather_files(sys.argv[1:])
    if not files:
        print("No component files found. Nothing to validate.")
        return 0

    seen_ids = {}
    variant_groups = {}  # variant_of value -> list of (id, rel_path)
    per_file = []        # (rel, errors, warnings) accumulated for variant pass
    total_errors = 0
    total_warnings = 0

    for path in files:
        rel = path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path
        errors = []
        warnings = []
        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"FAIL {rel}\n      invalid JSON: {e}")
            total_errors += 1
            continue

        for err in sorted(validator.iter_errors(data), key=lambda e: e.path):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"[{loc}] {err.message}")

        check_path_conventions(path, data, errors)
        check_verified(data, errors)
        check_revision_history(data, errors)
        check_hosted_assets(data, errors, warnings)

        cid = data.get("id")
        if cid:
            if cid in seen_ids:
                errors.append(f"duplicate id '{cid}' (also in {seen_ids[cid]})")
            else:
                seen_ids[cid] = str(rel)

        vof = data.get("variant_of")
        if vof:
            variant_groups.setdefault(vof, []).append((cid, str(rel)))

        per_file.append((rel, errors, warnings))

    # Cross-file: a variant_of value must be shared by at least two entries,
    # and must not collide with a real component id.
    for base, members in variant_groups.items():
        if len(members) < 2:
            cid, rel = members[0]
            for r, errs, _w in per_file:
                if str(r) == rel:
                    errs.append(
                        f"variant_of '{base}' has only one entry; package variants "
                        f"must come in groups of 2+ sharing the same variant_of base"
                    )
        if base in seen_ids:
            for r, errs, _w in per_file:
                if str(r) == seen_ids[base]:
                    errs.append(
                        f"id '{base}' collides with a variant_of base; the shared "
                        f"base id must not also be a real entry id"
                    )

    for rel, errors, warnings in per_file:
        total_warnings += len(warnings)
        if errors:
            total_errors += len(errors)
            print(f"FAIL {rel}")
            for e in errors:
                print(f"      {e}")
        elif warnings:
            print(f"WARN {rel}")
        else:
            print(f"OK   {rel}")
        for w in warnings:
            print(f"      warning: {w}")

    print(f"\n{len(files)} file(s) checked, {total_errors} error(s), {total_warnings} warning(s).")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
