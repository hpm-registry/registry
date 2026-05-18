#!/usr/bin/env python3
"""
update_part.py — HPM Registry contributor CLI for updating existing parts.

Finds an existing registry entry by fuzzy search, lets you choose what to
update, then bumps the revision and adds a history entry automatically.

Usage:
    python user_scripts/update_part.py
"""

import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
INCOMING_DIR = REPO_ROOT / "incoming"
INDEX_BY_ID = REPO_ROOT / "index" / "by-id.json"
COMPONENTS_DIR = REPO_ROOT / "components"

load_dotenv(REPO_ROOT / ".env")

PROHIBITED_GENERATORS = {
    "ultra librarian": "UltraLibrarian",
    "ultralibrarian": "UltraLibrarian",
    "snapeda": "SnapMagic/SnapEDA",
    "snapmagic": "SnapMagic/SnapEDA",
    "samacsys": "SamacSys",
    "mouser part wizard": "Mouser Part Wizard",
}

ORIGIN_MANUFACTURER = "downloaded from manufacturer website"
ORIGIN_DATASHEET = "drawn from manufacturer datasheet"
ORIGIN_KICAD = "KiCad official library"


# ---------------------------------------------------------------------------
# Search corpus
# ---------------------------------------------------------------------------

def build_corpus():
    """Load all component entries. Uses index when available, falls back to scan."""
    entries = []

    if INDEX_BY_ID.is_file():
        with open(INDEX_BY_ID) as f:
            by_id = json.load(f)
        if by_id:
            for rel_path in by_id.values():
                full_path = REPO_ROOT / rel_path
                try:
                    with open(full_path) as f:
                        entries.append((json.load(f), full_path))
                except (OSError, json.JSONDecodeError):
                    continue
            return entries

    # Index empty or missing — scan components/ directly
    for json_file in sorted(COMPONENTS_DIR.rglob("*.json")):
        if "_examples" in json_file.parts:
            continue
        try:
            with open(json_file) as f:
                entries.append((json.load(f), json_file))
        except (OSError, json.JSONDecodeError):
            continue

    return entries


def score_entry(query, entry):
    q = query.lower()
    checks = [
        (entry.get("id", "").lower(), 1.0),
        (entry.get("mpn", "").lower(), 1.0),
        (entry.get("manufacturer", "").lower(), 0.7),
        (entry.get("description", "").lower(), 0.6),
    ]
    best = 0.0
    for text, weight in checks:
        if not text:
            continue
        if q in text:
            score = weight * (0.5 + 0.5 * len(q) / max(len(text), 1))
            best = max(best, score)
        ratio = difflib.SequenceMatcher(None, q, text).ratio()
        best = max(best, ratio * weight)
    return best


def fuzzy_search(query, corpus, top_n=5, threshold=0.35):
    scored = [
        (score_entry(query, entry), entry, path)
        for entry, path in corpus
    ]
    scored = [(s, e, p) for s, e, p in scored if s >= threshold]
    scored.sort(key=lambda x: -x[0])
    return scored[:top_n]


def lookup_by_id(cid, corpus):
    for entry, path in corpus:
        if entry.get("id") == cid:
            return entry, path
    return None, None


# ---------------------------------------------------------------------------
# Auto-detect from incoming/
# ---------------------------------------------------------------------------

def _extract_kicad_tags(path):
    """Pull the (tags "...") string from a .kicad_mod or .kicad_sym file."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return []
    import re
    match = re.search(r'\(tags\s+"([^"]+)"', text)
    if match:
        return match.group(1).split()
    return []


def detect_from_incoming(corpus):
    """Scan incoming/ to derive search terms, run auto-match, return (entry, path) or None.

    Returns None if incoming/ is empty or no confident match is found — caller
    falls through to interactive search.
    """
    mods = sorted(INCOMING_DIR.glob("*.kicad_mod"))
    syms = sorted(INCOMING_DIR.glob("*.kicad_sym"))
    kicad_files = mods + syms

    if not kicad_files:
        return None

    # Collect search terms: filename stems + tags embedded in the files
    terms = set()
    for f in kicad_files:
        terms.add(f.stem)
        terms.update(_extract_kicad_tags(f))

    # Score each term against the corpus, keep the best overall hit
    best_score, best_entry, best_path = 0.0, None, None
    best_term = ""
    for term in terms:
        results = fuzzy_search(term, corpus, top_n=1, threshold=0.0)
        if results and results[0][0] > best_score:
            best_score, best_entry, best_path = results[0]
            best_term = term

    if best_entry is None or best_score < 0.5:
        return None

    print(f"  Auto-detected from incoming/: '{best_term}'")
    print(f"  Matched: {best_entry['id']} — {best_entry.get('description', '')}")
    print(f"           {best_entry.get('manufacturer', '')}")
    confirm = _prompt("  Is this the correct part? [y/n]: ").lower()
    if confirm == "y":
        return best_entry, best_path

    return None  # user rejected — fall through to interactive search


# ---------------------------------------------------------------------------
# Part selection
# ---------------------------------------------------------------------------

def _prompt(msg):
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)


def find_part(corpus):
    """Interactive search → confirm → manual ID fallback. Returns (entry, path)."""
    while True:
        print()
        query = _prompt("Search for a part (MPN, ID, description): ")
        if not query:
            continue

        results = fuzzy_search(query, corpus)

        if not results:
            print("  No matches found.")
            entry, path = _manual_id(corpus)
            if entry:
                return entry, path
            continue

        # Single clear winner
        if len(results) == 1 or results[0][0] >= 0.85:
            _, entry, path = results[0]
            print(f"\n  Found: {entry['id']}")
            print(f"         {entry.get('manufacturer', '')} — {entry.get('description', '')}")
            confirm = _prompt("  Is this the part? [y/n]: ").lower()
            if confirm == "y":
                return entry, path
            # User said no — show full list or go manual
            if len(results) == 1:
                entry, path = _manual_id(corpus)
                if entry:
                    return entry, path
                continue

        # Multiple candidates
        print(f"\n  Matches for '{query}':")
        for i, (_, entry, _p) in enumerate(results, 1):
            desc = entry.get("description", "")[:55]
            mfr = entry.get("manufacturer", "")
            print(f"    {i}. {entry['id']:35s}  {mfr:22s}  {desc}")
        print(f"    0. None of these")

        choice = _prompt(f"  Select [0–{len(results)}]: ")
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            _, entry, path = results[int(choice) - 1]
            return entry, path
        # 0 or invalid → manual ID
        entry, path = _manual_id(corpus)
        if entry:
            return entry, path


def _manual_id(corpus):
    """Ask for exact ID. Returns (entry, path) or (None, None) to retry search."""
    while True:
        print()
        cid = _prompt("  Type the exact part ID (or press Enter to search again): ")
        if not cid:
            return None, None

        entry, path = lookup_by_id(cid, corpus)
        if entry:
            return entry, path

        print(f"\n  '{cid}' not found in the registry.")
        print("    1. Retype the ID")
        print("    2. This is a new part — run user_scripts/add_part.py instead")
        choice = _prompt("  Choice [1/2]: ")
        if choice == "2":
            print("\nRun:  python user_scripts/add_part.py")
            sys.exit(0)
        # 1 or anything else → loop back


# ---------------------------------------------------------------------------
# Update type menu
# ---------------------------------------------------------------------------

def choose_update_type(entry):
    has_model = "3d_model" in entry
    variants = entry.get("variant_of")

    print(f"\nUpdating: {entry['id']}")
    print(f"  {entry.get('manufacturer', '')} — {entry.get('description', '')}")
    if variants:
        print(f"  (variant group: {variants})")
    print()
    print("  What would you like to update?")
    print("  1. Specs / metadata    — edit the JSON entry in your editor")
    print("  2. Footprint           — replace the .kicad_mod file (drop new file in incoming/)")
    print("  3. Symbol              — replace the .kicad_sym file (drop new file in incoming/)")
    if has_model:
        print("  4. 3D model            — replace the .step / .wrl file (drop new file in incoming/)")
        print("  5. Re-extract specs    — re-run LLM extraction from a new datasheet in incoming/")
        max_opt = 5
    else:
        print("  4. Re-extract specs    — re-run LLM extraction from a new datasheet in incoming/")
        max_opt = 4

    print()
    while True:
        choice = _prompt(f"  Choice [1–{max_opt}]: ")
        if choice.isdigit() and 1 <= int(choice) <= max_opt:
            n = int(choice)
            if not has_model and n == 4:
                return "reextract"
            return {1: "metadata", 2: "footprint", 3: "symbol", 4: "model", 5: "reextract"}[n]
        print(f"  Please enter a number between 1 and {max_opt}.")


# ---------------------------------------------------------------------------
# Prohibited file check
# ---------------------------------------------------------------------------

def check_prohibited(file_path):
    content = Path(file_path).read_text(errors="replace").lower()
    for signature, source_name in PROHIBITED_GENERATORS.items():
        if signature in content:
            print(f"\n✗ Prohibited file detected: {Path(file_path).name}")
            print(f"  Generated by: {source_name}")
            print(
                "\n  This file cannot be hosted in HPM — see incoming/README.md for\n"
                "  accepted alternatives (KiCad official library or drawn from datasheet)."
            )
            sys.exit(1)


# ---------------------------------------------------------------------------
# Origin prompt
# ---------------------------------------------------------------------------

def prompt_origin(label):
    print(f"\n  {label} origin:")
    print("    1. Downloaded from manufacturer website (preferred)")
    print("    2. Drawn from manufacturer datasheet")
    print("    3. KiCad official library")
    print("    4. Other")
    while True:
        choice = _prompt("  Choice [1/2/3/4]: ")
        if choice == "1":
            return ORIGIN_MANUFACTURER
        elif choice == "2":
            return ORIGIN_DATASHEET
        elif choice == "3":
            return ORIGIN_KICAD
        elif choice == "4":
            other = _prompt("  Describe the origin: ")
            if other:
                return other
            print("  Origin cannot be empty.")
        else:
            print("  Please enter 1, 2, 3, or 4.")


# ---------------------------------------------------------------------------
# Update actions
# ---------------------------------------------------------------------------

def update_metadata(entry):
    """Open the JSON in $EDITOR and return the edited result."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(entry, f, indent=2)
        f.write("\n")
        tmp = f.name

    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, tmp], check=False)

    try:
        with open(tmp) as f:
            updated = json.load(f)
    except json.JSONDecodeError as e:
        os.unlink(tmp)
        sys.exit(f"ERROR: Edited file is not valid JSON: {e}")
    os.unlink(tmp)
    return updated


def replace_asset(entry, file_type):
    """Find the replacement file in incoming/, check it, copy to registry location."""
    glob_map = {
        "footprint": ["*.kicad_mod"],
        "symbol": ["*.kicad_sym"],
        "model": ["*.step", "*.wrl"],
    }
    field_map = {"footprint": "footprint", "symbol": "symbol", "model": "3d_model"}
    ext_label = {"footprint": ".kicad_mod", "symbol": ".kicad_sym", "model": ".step / .wrl"}

    candidates = []
    for pattern in glob_map[file_type]:
        candidates.extend(INCOMING_DIR.glob(pattern))

    if not candidates:
        print(f"\nERROR: No {ext_label[file_type]} file found in incoming/")
        print("  Drop the replacement file into incoming/ and re-run.")
        sys.exit(1)
    if len(candidates) > 1:
        print(f"\nERROR: Multiple {ext_label[file_type]} files found in incoming/:")
        for c in candidates:
            print(f"  {c.name}")
        print("  Keep only one and re-run.")
        sys.exit(1)

    new_file = candidates[0]

    if file_type in ("footprint", "symbol"):
        check_prohibited(new_file)

    field = field_map[file_type]
    dest = REPO_ROOT / entry[field]["path"]
    shutil.copy2(new_file, dest)
    print(f"  Replaced: {entry[field]['path']}")

    entry[field]["origin"] = prompt_origin(file_type.capitalize())
    return entry


def reextract_with_llm(entry):
    """Re-run LLM extraction from a new datasheet, merge results into existing entry."""
    # Import extraction logic from add_part to avoid duplicating the large system prompt
    sys.path.insert(0, str(REPO_ROOT / "user_scripts"))
    try:
        from add_part import extract_with_llm
    except ImportError as e:
        sys.exit(f"ERROR: Could not import from add_part.py: {e}")

    pdfs = list(INCOMING_DIR.glob("*.pdf"))
    if not pdfs:
        print("\nERROR: No PDF datasheet found in incoming/")
        print("  Drop the new datasheet PDF into incoming/ and re-run.")
        sys.exit(1)
    if len(pdfs) > 1:
        print(f"\nERROR: Multiple PDFs in incoming/: {[p.name for p in pdfs]}")
        print("  Keep only one and re-run.")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Add it to .env or: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    datasheet_url = _prompt("\nDatasheet PDF URL: ")
    if not datasheet_url:
        sys.exit("ERROR: Datasheet URL cannot be empty.")

    new_data = extract_with_llm(pdfs[0], api_key)
    new_data["datasheet"]["url"] = datasheet_url

    # Preserve registry-managed fields; take everything else from the LLM
    preserve = {"id", "category", "subcategory", "footprint", "symbol", "3d_model",
                "meta", "variant_of"}
    for key, val in new_data.items():
        if key not in preserve:
            entry[key] = val

    print("\nRe-extracted fields merged into existing entry.")
    return entry


# ---------------------------------------------------------------------------
# Revision bump + write
# ---------------------------------------------------------------------------

def bump_revision(entry, github_handle, change_desc, today):
    meta = entry.setdefault("meta", {})
    rev = meta.get("revision", 0) + 1
    meta["revision"] = rev
    meta.setdefault("history", []).append({
        "revision": rev,
        "date": today,
        "by": github_handle,
        "change": change_desc,
    })
    return entry


def run_validate(json_path):
    cmd = [sys.executable, str(REPO_ROOT / "system_scripts" / "validate.py"), str(json_path)]
    return subprocess.run(cmd).returncode


def run_build_index():
    cmd = [sys.executable, str(REPO_ROOT / "system_scripts" / "build_index.py")]
    return subprocess.run(cmd).returncode


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("HPM Registry — Update a part")
    print()
    print("Loading registry...")
    corpus = build_corpus()
    if not corpus:
        sys.exit(
            "ERROR: No components found in the registry.\n"
            "Use user_scripts/add_part.py to add a new part."
        )
    print(f"  {len(corpus)} part(s) loaded.")

    # Step 1: Find the part — try incoming/ auto-detection first
    result = detect_from_incoming(corpus)
    if result:
        entry, entry_path = result
    else:
        entry, entry_path = find_part(corpus)

    # Step 2: Choose what to update
    update_type = choose_update_type(entry)

    # Warn if this is a variant and the change affects shared files
    if entry.get("variant_of") and update_type == "symbol":
        print(
            f"\n  Note: this entry is part of variant group '{entry['variant_of']}'.\n"
            "  Symbol files are shared across variants — copy the updated symbol\n"
            "  to each variant's symbol path manually if they differ."
        )

    # Step 3: Perform the update
    if update_type == "metadata":
        entry = update_metadata(entry)
    elif update_type in ("footprint", "symbol", "model"):
        entry = replace_asset(entry, update_type)
    elif update_type == "reextract":
        entry = reextract_with_llm(entry)

    # Step 4: Review
    print(f"\n{'=' * 60}")
    print("UPDATED ENTRY")
    print("=" * 60)
    print(json.dumps(entry, indent=2))

    confirm = _prompt("\nWrite this entry? [y/n]: ").lower()
    if confirm != "y":
        print("Aborted. No files written.")
        sys.exit(0)

    # Step 5: Contributor info + revision bump
    print()
    github_handle = _prompt("GitHub username (no @ prefix): ")
    if not github_handle:
        sys.exit("ERROR: GitHub username cannot be empty.")
    change_desc = _prompt("Describe this change (for the revision history): ")
    if not change_desc:
        sys.exit("ERROR: Change description cannot be empty.")

    today = date.today().isoformat()
    entry = bump_revision(entry, github_handle, change_desc, today)

    # Step 6: Write JSON
    with open(entry_path, "w") as f:
        json.dump(entry, f, indent=2)
        f.write("\n")
    print(f"  Written: {entry_path.relative_to(REPO_ROOT)}")

    # Step 7: Validate + rebuild index
    print("\nRunning validator...")
    run_validate(entry_path)

    print("\nRebuilding index...")
    run_build_index()

    # Step 8: Done
    rev = entry["meta"]["revision"]
    print(f"\n✓ Updated {entry['id']} to revision {rev}.")
    print("\nNext steps:")
    print("  git add components/ footprints/ symbols/ 3d_models/ index/")
    print(f'  git commit -m "update {entry["id"]}: {change_desc}"')
    print("  git push && open a PR")


if __name__ == "__main__":
    main()
