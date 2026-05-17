#!/usr/bin/env python3
"""
check_revision_bump.py -- Enforce that modified component entries bump meta.revision.

For every component JSON file changed in a PR (compared to the base branch SHA),
verifies that:
  1. meta.revision increased by exactly 1
  2. meta.history has one new entry whose .revision matches the new meta.revision
  3. The new history entry has a non-empty .change description

New files (no base version) are exempt — their revision starts at 1, which
validate.py already checks.

Usage (called by CI):
    python scripts/check_revision_bump.py <base-sha>

Exit code 0 = all good, 1 = one or more violations.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = REPO_ROOT / "components"


def git_show(sha, rel_path):
    """Return parsed JSON of a file at a given commit, or None if it didn't exist."""
    result = subprocess.run(
        ["git", "show", f"{sha}:{rel_path}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def changed_component_files(base_sha):
    """Return repo-relative paths of component JSON files changed since base_sha."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base_sha, "HEAD", "--", "components/"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    paths = []
    for line in result.stdout.splitlines():
        p = Path(line.strip())
        if p.suffix == ".json" and p.parts[0] == "components" and "_examples" not in p.parts:
            paths.append(p)
    return paths


def check_file(rel_path, base_sha):
    errors = []

    base_data = git_show(base_sha, str(rel_path))
    if base_data is None:
        # New file — validate.py handles revision: 1 check, nothing to compare against.
        return errors

    with open(REPO_ROOT / rel_path) as f:
        try:
            new_data = json.load(f)
        except json.JSONDecodeError:
            # validate.py will catch this
            return errors

    base_meta = base_data.get("meta", {})
    new_meta = new_data.get("meta", {})

    base_rev = base_meta.get("revision", 0)
    new_rev = new_meta.get("revision", 0)
    new_history = new_meta.get("history", [])

    # Check the content actually changed (ignore meta.revision and meta.history
    # since those are what we're asking contributors to update).
    base_content = {k: v for k, v in base_data.items() if k != "meta"}
    new_content = {k: v for k, v in new_data.items() if k != "meta"}
    base_meta_trimmed = {k: v for k, v in base_meta.items() if k not in ("revision", "history")}
    new_meta_trimmed = {k: v for k, v in new_meta.items() if k not in ("revision", "history")}

    content_changed = (base_content != new_content) or (base_meta_trimmed != new_meta_trimmed)

    if not content_changed:
        return errors  # no substantive change — revision bump not required

    if new_rev != base_rev + 1:
        errors.append(
            f"meta.revision must increase by 1 (was {base_rev}, got {new_rev}). "
            f"Increment meta.revision and add a history entry describing your change."
        )

    if len(new_history) != base_rev + 1:
        errors.append(
            f"meta.history must have exactly {base_rev + 1} entries after this change "
            f"(has {len(new_history)}). Add one entry for revision {base_rev + 1}."
        )
    else:
        last = new_history[-1]
        if last.get("revision") != base_rev + 1:
            errors.append(
                f"meta.history last entry revision is {last.get('revision')}, "
                f"expected {base_rev + 1}."
            )
        change = last.get("change", "").strip()
        if len(change) < 8:
            errors.append(
                f"meta.history entry for revision {base_rev + 1} has a too-short "
                f"'change' description. Summarise what you actually changed."
            )

    return errors


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: check_revision_bump.py <base-sha>")

    base_sha = sys.argv[1]
    changed = changed_component_files(base_sha)

    if not changed:
        print("No component files changed. Nothing to check.")
        return 0

    total_errors = 0
    for rel in changed:
        errors = check_file(rel, base_sha)
        if errors:
            total_errors += len(errors)
            print(f"FAIL {rel}")
            for e in errors:
                print(f"      {e}")
        else:
            print(f"OK   {rel}")

    print(f"\n{len(changed)} file(s) checked, {total_errors} error(s).")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
