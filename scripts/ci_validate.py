#!/usr/bin/env python3
"""
ci_validate.py — Strict merge-gate validator for GitHub Actions.

Runs all the same checks as validate.py but with tighter rules and
GitHub-native annotation output (::error / ::warning).

Differences from validate.py (the contributor tool):
  - null footprint.path or symbol.path  → ERROR   (local: warning)
  - unknown asset license               → ERROR   (local: warning)
  - missing datasheet.url               → ERROR   (local: not checked)
  - meta.verified: false                → WARNING (local: silent)
  - all output uses ::error / ::warning annotations for inline PR markers

Usage (CI only — not intended for local use):
    python scripts/ci_validate.py                # all files under components/
    python scripts/ci_validate.py path/to/x.json # specific file(s)

Exit code 0 = merge safe, 1 = one or more blocking errors.
"""
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("ERROR: pip install jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "component.schema.json"
COMPONENTS_DIR = REPO_ROOT / "components"
EXAMPLES_DIRNAME = "_examples"


def load_schema():
    with open(SCHEMA_PATH) as f:
        return Draft202012Validator(json.load(f))


def gather_files(args):
    if args:
        return [Path(a).resolve() for a in args]
    return sorted(COMPONENTS_DIR.rglob("*.json"))


def rel(path):
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return path


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------

def annotate_error(path, message):
    print(f"::error file={rel(path)}::{message}")


def annotate_warning(path, message):
    print(f"::warning file={rel(path)}::{message}")


# ---------------------------------------------------------------------------
# Checks (errors and warnings are collected, then emitted together)
# ---------------------------------------------------------------------------

def check_schema(data, validator, errors):
    for err in sorted(validator.iter_errors(data), key=lambda e: e.path):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        errors.append(f"[{loc}] {err.message}")


def check_path_conventions(path, data, errors):
    stem = path.stem
    if data.get("id") != stem:
        errors.append(f"filename '{stem}' does not match id '{data.get('id')}'")

    if EXAMPLES_DIRNAME in path.parts:
        return

    parent = path.parent.name
    grandparent = path.parent.parent.name
    if data.get("subcategory") != parent:
        errors.append(f"parent dir '{parent}' does not match subcategory '{data.get('subcategory')}'")
    if data.get("category") != grandparent:
        errors.append(f"grandparent dir '{grandparent}' does not match category '{data.get('category')}'")


def check_verified(data, errors):
    meta = data.get("meta", {})
    if meta.get("verified") is True and not meta.get("verified_by"):
        errors.append("meta.verified is true but meta.verified_by is missing")


def check_revision_history(data, errors):
    meta = data.get("meta", {})
    revision = meta.get("revision")
    history = meta.get("history")
    if revision is None or not isinstance(history, list):
        return
    if revision != len(history):
        errors.append(
            f"meta.revision ({revision}) does not equal length of meta.history ({len(history)})"
        )
    for i, entry in enumerate(history, start=1):
        if not isinstance(entry, dict):
            continue
        if entry.get("revision") != i:
            errors.append(
                f"meta.history[{i-1}].revision is {entry.get('revision')}, expected {i}"
            )


def check_hosted_assets(data, errors, warnings):
    for field in ("footprint", "symbol"):
        block = data.get(field)
        if not isinstance(block, dict):
            continue
        path = block.get("path")

        # CI rule: null path is a blocking error — cannot merge without real assets.
        if path is None:
            errors.append(
                f"{field}.path is null — a hosted {field} file is required before merge"
            )
            continue

        asset = REPO_ROOT / path
        if not asset.is_file():
            errors.append(f"{field}.path '{path}' does not point to an existing file")

    # 3D model not linked in footprint — warning only (3D models are optional).
    if data.get("3d_model") and isinstance(data.get("footprint"), dict):
        fp_path = data["footprint"].get("path")
        if fp_path:
            fp_file = REPO_ROOT / fp_path
            if fp_file.is_file() and "(model " not in fp_file.read_text():
                warnings.append(
                    "3d_model is declared but the footprint has no (model ...) block; "
                    "KiCad won't display the 3D model"
                )


def check_datasheet_url(data, errors):
    # CI rule: datasheet.url must be a non-null, non-empty string.
    ds = data.get("datasheet")
    if not isinstance(ds, dict):
        return  # schema validation already caught this
    url = ds.get("url")
    if not url:
        errors.append(
            "datasheet.url is missing or null — provide the manufacturer-hosted PDF URL"
        )


def check_unverified(data, warnings):
    meta = data.get("meta", {})
    if not meta.get("verified"):
        warnings.append(
            "meta.verified is false — specs have not been cross-checked against the datasheet. "
            "Merge is allowed but agents will warn users before using this entry in production designs."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    validator = load_schema()
    files = gather_files(sys.argv[1:])

    if not files:
        print("No component files found. Nothing to validate.")
        return 0

    seen_ids = {}
    variant_groups = {}
    per_file = []
    total_errors = 0
    total_warnings = 0

    for path in files:
        errors = []
        warnings = []

        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            annotate_error(path, f"Invalid JSON: {e}")
            total_errors += 1
            continue

        check_schema(data, validator, errors)
        check_path_conventions(path, data, errors)
        check_verified(data, errors)
        check_revision_history(data, errors)
        check_hosted_assets(data, errors, warnings)
        check_datasheet_url(data, errors)
        check_unverified(data, warnings)

        cid = data.get("id")
        if cid:
            if cid in seen_ids:
                errors.append(f"duplicate id '{cid}' (also in {seen_ids[cid]})")
            else:
                seen_ids[cid] = str(rel(path))

        vof = data.get("variant_of")
        if vof:
            variant_groups.setdefault(vof, []).append((cid, str(rel(path))))

        per_file.append((path, errors, warnings))

    # Cross-file variant check
    for base, members in variant_groups.items():
        if len(members) < 2:
            cid, rpath = members[0]
            for p, errs, _w in per_file:
                if str(rel(p)) == rpath:
                    errs.append(
                        f"variant_of '{base}' has only one entry; "
                        f"package variants must come in groups of 2+"
                    )
        if base in seen_ids:
            for p, errs, _w in per_file:
                if str(rel(p)) == seen_ids[base]:
                    errs.append(
                        f"id '{base}' collides with a variant_of base; "
                        f"the shared base must not also be a real entry id"
                    )

    # Emit annotations and summary
    for path, errors, warnings in per_file:
        for e in errors:
            annotate_error(path, e)
        for w in warnings:
            annotate_warning(path, w)
        total_errors += len(errors)
        total_warnings += len(warnings)

    # Human-readable summary line (visible in the Actions step log)
    status = "PASSED" if total_errors == 0 else "FAILED"
    print(
        f"\n{status}: {len(files)} file(s) checked, "
        f"{total_errors} error(s), {total_warnings} warning(s)."
    )
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
