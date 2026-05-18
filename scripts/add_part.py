#!/usr/bin/env python3
"""
add_part.py — HPM Registry contributor CLI.

Reads a datasheet PDF and KiCad files, uses Claude to extract structured
component data, shows a review prompt, then places all files into the correct
registry locations, validates, and rebuilds the index.

Usage:
    python scripts/add_part.py \\
        --datasheet path/to/ds.pdf \\
        --footprint path/to/PART.kicad_mod \\
        --symbol    path/to/PART.kicad_sym \\
        [--model    path/to/PART.step] \\
        --github    your-github-handle

    # Multiple footprints for IPC density variants:
    python scripts/add_part.py \\
        --datasheet path/to/ds.pdf \\
        --footprint path/to/PART.kicad_mod \\
        --footprint path/to/PART-L.kicad_mod \\
        --footprint path/to/PART-M.kicad_mod \\
        --symbol    path/to/PART.kicad_sym \\
        [--model    path/to/PART.step] \\
        --github    your-github-handle

Requires:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import argparse
import base64
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
MODEL = "claude-opus-4-7"

load_dotenv(REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# LLM system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a precision data-extraction assistant for the HPM Component Registry.
Given a manufacturer datasheet PDF, extract component metadata and return a
single JSON object that validates against the schema below. Return ONLY valid
JSON — no markdown fences, no explanation, no prose.

=== SCHEMA (schema_version 1.5.0) ===

Required fields (you must populate all of them):

  schema_version   string  Always "1.5.0"
  id               string  Uppercase MPN with slashes replaced by hyphens.
                           Pattern: ^[A-Z0-9]([A-Z0-9._-]*[A-Z0-9])?$
                           Example: "AMS1117-3.3", "MMBT3904", "GRM155R71C104KA88D"
  mpn              string  Manufacturer Part Number exactly as on the datasheet.
  manufacturer     string  Full canonical manufacturer name, e.g. "Texas Instruments",
                           "Murata", "ON Semiconductor". Never abbreviate.
  category         string  One of:
                             resistors | capacitors | inductors | diodes | transistors |
                             regulators | microcontrollers | logic-ics | analog-ics |
                             interface-ics | memory | sensors | connectors |
                             electromechanical | power-modules | crystals-oscillators |
                             optoelectronics | protection
  subcategory      string  Lowercase slug matching one of the subcategories for the chosen
                           category (see taxonomy below). Pattern: ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$
  description      string  8–160 chars. One-line, factual, no marketing language.
                           Example: "100mA 3.3V LDO linear regulator, SOT-23-5"
  package          object  {
                             "name": string   // JEDEC/IPC designation, e.g. "SOT-23-3", "SOIC-8", "0402"
                             "type": string   // "smd" | "through-hole" | "module" | "bare-die"
                             "pin_count": int // total pins/pads including NC and power (optional but recommended)
                           }
  lifecycle_status string  "active" | "not-recommended" | "obsolete" | "preliminary" | "unknown"
  specs            object  At least one spec. Each key is a snake_case parameter name.
                           Each value is one of:
                             {"value": <number|string|boolean>, "unit": "<unit>"}
                             {"min": <number>, "unit": "<unit>"}
                             {"typ": <number>, "unit": "<unit>"}
                             {"max": <number>, "unit": "<unit>"}
                             {"min": <number>, "typ": <number>, "max": <number>, "unit": "<unit>"}
                           Never embed the unit inside the value string.
                           Use "notes" key for test conditions: {"typ": 1.1, "unit": "V", "notes": "VIN=5V, IOUT=500mA"}
                           For frequency-dependent specs add: "at_frequency": {"value": 100, "unit": "MHz"}
  footprint        object  {"path": null, "format": "kicad_mod", "format_version": "6.0",
                             "origin": "contributor-provided"}
                           Leave path as null — the script fills it.
  symbol           object  {"path": null, "format": "kicad_sym", "format_version": "6.0",
                             "origin": "contributor-provided"}
                           Leave path as null — the script fills it.
  datasheet        object  {"url": null}
                           ALWAYS set url to null — do NOT generate, guess, or infer a URL.
                           The contributor will supply the correct URL separately.
                           Also include "revision" if visible on the cover page (e.g. "Rev. C").
                           Do NOT include sha256 — that requires downloading the file.
  meta             object  DO NOT include meta.added, meta.revision, or meta.history —
                           the script fills those. Set:
                             {"verified": false}

Optional fields (include when the datasheet has clear data):

  aliases          array   Alternate MPNs, reel/tape suffixes that are the same silicon.
                           Example: ["MMBT3904LT1G", "MMBT3904WT1G"]
  substitutes      array   Pin-compatible alternatives: [{"id": "OTHER-ID", "note": "caveat text"}]
  variant_of       null    Leave as null (script sets this for multi-footprint runs).
  pins             object  For ICs: keyed by pin number string "1", "2", etc.
                           Each value: {"name": "VCC", "type": "<pin_type>", "description": "optional"}
                           Pin types: power-in | power-out | ground | signal-in | signal-out |
                                      signal-bidir | passive | open-drain | open-collector | no-connect
                           Omit for passives (resistors, capacitors, inductors) where pins are symmetric.
  compliance       object  Include if datasheet mentions compliance:
                           {
                             "rohs": "compliant" | "exempt" | "non-compliant" | "unknown",
                             "reach": "compliant" | "svhc-declared" | "non-compliant" | "unknown",
                             "aec_q": "AEC-Q100" | "AEC-Q101" | "AEC-Q102" | "AEC-Q200" | "none" | "unknown",
                             "halogen_free": true | false
                           }
  meta.tags        array   Free-form discovery tags, e.g. ["jellybean", "low-noise"]

=== TAXONOMY ===

resistors:          smd-chip, through-hole, potentiometer, current-sense, resistor-array
capacitors:         mlcc, electrolytic, tantalum, film, supercapacitor
inductors:          power-inductor, ferrite-bead, common-mode-choke, rf-inductor
diodes:             rectifier, schottky, zener, tvs, led-indicator
transistors:        n-channel-mosfet, p-channel-mosfet, npn-bjt, pnp-bjt, igbt
regulators:         ldo, switching-buck, switching-boost, buck-boost, charge-pump
microcontrollers:   8-bit, 16-bit, 32-bit-arm, risc-v, wireless-soc
logic-ics:          gate, flip-flop, shift-register, buffer, level-shifter, multiplexer
analog-ics:         op-amp, comparator, voltage-reference, adc, dac, analog-switch
interface-ics:      usb, can, rs485, i2c-io-expander, ethernet-phy, uart-bridge
memory:             eeprom, flash, sram, fram, sd-emmc
sensors:            temperature, imu, pressure, hall-effect, optical, current
connectors:         header, usb, terminal-block, ffc-fpc, board-to-board, rf
electromechanical:  relay, switch, pushbutton, rotary-encoder, buzzer
power-modules:      dc-dc-module, ac-dc-module, pol-module
crystals-oscillators: crystal, oscillator, resonator, rtc-crystal
optoelectronics:    led, optocoupler, photodiode, display, laser
protection:         fuse, ptc-resettable, tvs-array, esd-suppressor

=== ALLOWED UNIT STRINGS ===

""  (dimensionless / boolean flags)
V mV uV Vpp Vrms
A mA uA nA Arms
Ohm mOhm kOhm MOhm
F uF nF pF
H mH uH nH
W mW
Hz kHz MHz GHz
degC K
K/W degC/W
ppm ppm/degC
uV/degC mV/degC
s ms us ns ps
% %/degC
dB dBm
bps kbps Mbps Gbps
mm um nm inch
g mg
deg/s mdeg/s
Pa kPa hPa mbar bar
T mT uT Gauss
lux lm mcd cd
A/W
rpm
C mC uC Ah mAh
KB MB GB TB
bit byte Kbit Mbit Gbit

=== COMMON SPEC KEY NAMES ===

LDO/regulators:     input_voltage, output_voltage, dropout_voltage, quiescent_current,
                    output_current, psrr, line_regulation, load_regulation
Transistors:        vds_max, vgs_max, id_max, rds_on, vgs_th, ciss, coss, pd_max
BJTs:               vceo_max, vces_max, ic_max, hfe, vbe_sat, vce_sat, ft, pd_max
Resistors:          resistance, tolerance, power_rating, tcr
Capacitors:         capacitance, voltage_rating, tolerance, esr, dielectric
Inductors:          inductance, current_rating, dcr, saturation_current, srf
General:            operating_temperature, storage_temperature, package_height

=== OUTPUT FORMAT ===

Return exactly one JSON object. Begin with '{' and end with '}'. No other text.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Add it to the .env file in the repo root:\n"
            "  ANTHROPIC_API_KEY=sk-ant-...\n"
            "Or set it in your shell:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-..."
        )
    return key


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


def prompt_origin(label):
    """Ask contributor where a file came from. Returns a canonical origin string."""
    print(f"\n  {label} origin:")
    print("    1. Downloaded from manufacturer website (preferred)")
    print("    2. Drawn from manufacturer datasheet")
    print("    3. KiCad official library")
    print("    4. Other")
    while True:
        try:
            choice = input("  Choice [1/2/3/4]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)
        if choice == "1":
            return ORIGIN_MANUFACTURER
        elif choice == "2":
            return ORIGIN_DATASHEET
        elif choice == "3":
            return ORIGIN_KICAD
        elif choice == "4":
            try:
                other = input("  Describe the origin: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                sys.exit(0)
            if not other:
                print("  Origin cannot be empty.")
                continue
            return other
        else:
            print("  Please enter 1, 2, 3, or 4.")


def validate_inputs(args):
    missing = []
    for f in [args.datasheet, args.symbol] + args.footprint:
        if not Path(f).is_file():
            missing.append(f)
    if args.model and not Path(args.model).is_file():
        missing.append(args.model)
    if missing:
        print("ERROR: File(s) not found:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)

    # Reject files from sources that prohibit redistribution before calling the API.
    prohibited = []
    for f in [args.symbol] + args.footprint:
        content = Path(f).read_text(errors="replace").lower()
        for signature, source_name in PROHIBITED_GENERATORS.items():
            if signature in content:
                prohibited.append((f, source_name))
                break
    if prohibited:
        print("ERROR: File(s) from sources that prohibit redistribution:")
        for f, source in prohibited:
            print(f"  {f}  →  generated by {source}")
        print(
            "\nThese files cannot be hosted in HPM. Use files from:"
            "\n  - KiCad official library (CC-BY-SA-4.0)"
            "\n  - Drawn yourself from the manufacturer datasheet (CC0-1.0)"
            "\n  - Manufacturer's own download page (check their terms)"
        )
        sys.exit(1)


def extract_with_llm(datasheet_path, api_key):
    try:
        import anthropic
    except ImportError:
        sys.exit("ERROR: anthropic package not installed. Run: pip install -r requirements.txt")

    client = anthropic.Anthropic(api_key=api_key)
    pdf_bytes = Path(datasheet_path).read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()

    print(f"Sending datasheet to {MODEL} for extraction...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Extract the component data from this datasheet and return "
                        "a JSON object matching the schema."
                    ),
                },
            ],
        }],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if the model wraps the output despite instructions
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:])
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3].rstrip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print("ERROR: LLM returned invalid JSON.")
        print(f"  Parse error: {e}")
        print("  Raw output (first 500 chars):", raw[:500])
        sys.exit(1)


def detect_variants(footprint_paths):
    """Return list of (path, suffix) pairs where suffix identifies the density variant.

    For a single footprint: suffix is "".
    For multiple footprints: finds the longest common stem prefix, extracts
    the remaining suffix from each (e.g. "", "-L", "-M").
    """
    if len(footprint_paths) == 1:
        return [(footprint_paths[0], "")]

    stems = [Path(p).stem for p in footprint_paths]

    # Find longest common prefix among all stems
    prefix = stems[0]
    for stem in stems[1:]:
        while prefix and not stem.startswith(prefix):
            prefix = prefix[:-1]

    result = []
    for path, stem in zip(footprint_paths, stems):
        suffix = stem[len(prefix):]
        result.append((path, suffix))

    return result


def build_entries(base_data, footprint_variants, symbol_path, model_path,
                  github_handle, today, footprint_origin, symbol_origin, model_origin):
    """Clone base_data into one entry per footprint variant, filling paths and meta."""
    base_id = base_data["id"]
    is_multi = len(footprint_variants) > 1

    entries = []
    for fp_path, suffix in footprint_variants:
        entry = json.loads(json.dumps(base_data))  # deep copy

        if is_multi:
            # Nominal footprint (no suffix) gets "-N" tag; others keep their suffix
            density_tag = suffix if suffix else "-N"
            entry["id"] = base_id + density_tag
            entry["variant_of"] = base_id  # base_id is not itself a file entry

        eid = entry["id"]
        cat = entry["category"]
        sub = entry["subcategory"]
        model_ext = Path(model_path).suffix.lstrip(".") if model_path else None

        # Fill paths and origins
        entry["footprint"]["path"] = f"footprints/{cat}/{sub}/{eid}.kicad_mod"
        entry["footprint"]["origin"] = footprint_origin
        entry["symbol"]["path"] = f"symbols/{cat}/{sub}/{eid}.kicad_sym"
        entry["symbol"]["origin"] = symbol_origin

        if model_path:
            entry["3d_model"] = {
                "path": f"3d_models/{cat}/{sub}/{eid}.{model_ext}",
                "format": model_ext,
                "origin": model_origin,
            }

        # Fill meta (script-managed fields)
        entry.setdefault("meta", {})
        entry["meta"]["added"] = today
        entry["meta"]["revision"] = 1
        entry["meta"]["history"] = [{
            "revision": 1,
            "date": today,
            "by": github_handle,
            "change": "Initial entry",
        }]

        entries.append((entry, fp_path))

    return entries


def review_entries(entries):
    """Pretty-print entries and ask contributor to confirm, abort, or edit."""
    print("\n" + "=" * 60)
    print("PROPOSED REGISTRY ENTRIES")
    print("=" * 60)

    for entry, _ in entries:
        print(f"\n--- {entry['id']} ---")
        print(json.dumps(entry, indent=2))

    while True:
        try:
            choice = input("\nProceed? [y = yes / n = abort / e = open in $EDITOR]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)

        if choice == "y":
            return entries

        elif choice == "n":
            print("Aborted. No files written.")
            sys.exit(0)

        elif choice == "e":
            combined = [e for e, _ in entries]
            payload = combined[0] if len(combined) == 1 else combined

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(payload, f, indent=2)
                f.write("\n")
                tmp = f.name

            editor = os.environ.get("EDITOR", "nano")
            subprocess.run([editor, tmp], check=False)

            try:
                with open(tmp) as f:
                    edited = json.load(f)
            except json.JSONDecodeError as e:
                print(f"ERROR: Edited file is not valid JSON: {e}. Try again.")
                os.unlink(tmp)
                continue
            os.unlink(tmp)

            if not isinstance(edited, list):
                edited = [edited]

            fp_paths = [fp for _, fp in entries]
            if len(edited) != len(fp_paths):
                print(
                    f"ERROR: Expected {len(fp_paths)} entries, got {len(edited)}. "
                    "Do not add or remove entries in the editor."
                )
                continue

            entries = list(zip(edited, fp_paths))
            print("\nUpdated entries:")
            for entry, _ in entries:
                print(f"\n--- {entry['id']} ---")
                print(json.dumps(entry, indent=2))

        else:
            print("Please enter y, n, or e.")


def place_files(entries, symbol_path, model_path):
    """Copy all files to their registry locations and patch footprints with model blocks."""
    written_json = []

    for entry, fp_path in entries:
        eid = entry["id"]
        cat = entry["category"]
        sub = entry["subcategory"]

        # Create directories
        for base_dir in ("components", "footprints", "symbols"):
            (REPO_ROOT / base_dir / cat / sub).mkdir(parents=True, exist_ok=True)

        # Copy footprint
        fp_dest = REPO_ROOT / entry["footprint"]["path"]
        shutil.copy2(fp_path, fp_dest)

        # Copy symbol (same file for all density variants)
        sym_dest = REPO_ROOT / entry["symbol"]["path"]
        shutil.copy2(symbol_path, sym_dest)

        # Copy 3D model and patch footprint
        if model_path and "3d_model" in entry:
            model_dest = REPO_ROOT / entry["3d_model"]["path"]
            model_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(model_path, model_dest)

            fp_text = fp_dest.read_text()
            if "(model " not in fp_text:
                model_rel = entry["3d_model"]["path"]
                model_block = (
                    f'\n  (model "{model_rel}"\n'
                    f"    (offset (xyz 0 0 0))\n"
                    f"    (scale (xyz 1 1 1))\n"
                    f"    (rotate (xyz 0 0 0))\n"
                    f"  )"
                )
                fp_text = fp_text.rstrip()
                if fp_text.endswith(")"):
                    fp_text = fp_text[:-1] + model_block + "\n)"
                fp_dest.write_text(fp_text)

        # Write JSON
        json_dest = REPO_ROOT / "components" / cat / sub / f"{eid}.json"
        with open(json_dest, "w") as f:
            json.dump(entry, f, indent=2)
            f.write("\n")

        written_json.append(json_dest)
        print(f"  Written: components/{cat}/{sub}/{eid}.json")

    return written_json


def run_validate(json_files):
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "validate.py")] + [str(f) for f in json_files]
    return subprocess.run(cmd).returncode


def run_build_index():
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "build_index.py")]
    return subprocess.run(cmd).returncode


# ---------------------------------------------------------------------------
# Auto-detection from incoming/
# ---------------------------------------------------------------------------

def scan_incoming():
    """Scan incoming/ and return (datasheet, footprints, symbol, model) or exit with guidance."""
    if not INCOMING_DIR.is_dir():
        return None

    pdfs = sorted(INCOMING_DIR.glob("*.pdf"))
    mods = sorted(INCOMING_DIR.glob("*.kicad_mod"))
    syms = sorted(INCOMING_DIR.glob("*.kicad_sym"))
    models = sorted(p for p in INCOMING_DIR.iterdir() if p.suffix in (".step", ".wrl"))

    # Filter out README
    problems = []
    if len(pdfs) == 0:
        problems.append("No PDF datasheet found in incoming/")
    elif len(pdfs) > 1:
        problems.append(f"Multiple PDFs found in incoming/ — keep only one: {[p.name for p in pdfs]}")
    if len(mods) == 0:
        problems.append("No .kicad_mod footprint found in incoming/")
    if len(syms) == 0:
        problems.append("No .kicad_sym symbol found in incoming/")
    elif len(syms) > 1:
        problems.append(f"Multiple .kicad_sym files found — keep only one: {[s.name for s in syms]}")

    if problems:
        print("ERROR: incoming/ is not ready:")
        for p in problems:
            print(f"  • {p}")
        print(f"\nSee incoming/README.md for what to put there.")
        sys.exit(1)

    model = models[0] if len(models) == 1 else None

    print("Auto-detected from incoming/:")
    print(f"  Datasheet : {pdfs[0].name}")
    for m in mods:
        print(f"  Footprint : {m.name}")
    print(f"  Symbol    : {syms[0].name}")
    if model:
        print(f"  3D model  : {model.name}")
    elif len(models) > 1:
        print(f"  3D model  : (skipped — multiple found: {[m.name for m in models]})")

    return str(pdfs[0]), [str(m) for m in mods], str(syms[0]), str(model) if model else None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add a part to the HPM registry using Claude to extract datasheet data.\n\n"
            "By default, files are auto-detected from the incoming/ folder.\n"
            "Drop your datasheet PDF, .kicad_mod, .kicad_sym, and optionally a .step\n"
            "file into incoming/, then run:\n\n"
            "  python scripts/add_part.py --github your-handle"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Auto-detect from incoming/ (recommended):\n"
            "  python scripts/add_part.py\n\n"
            "  # Explicit paths:\n"
            "  python scripts/add_part.py \\\n"
            "      --datasheet ds.pdf --footprint PART.kicad_mod --symbol PART.kicad_sym\n\n"
            "  # Multiple density variants (explicit):\n"
            "  python scripts/add_part.py \\\n"
            "      --datasheet ds.pdf \\\n"
            "      --footprint PART.kicad_mod --footprint PART-L.kicad_mod \\\n"
            "      --symbol PART.kicad_sym --model PART.step\n"
        ),
    )
    parser.add_argument("--datasheet", metavar="PDF",
                        help="Path to the manufacturer datasheet PDF (auto-detected from incoming/ if omitted)")
    parser.add_argument("--footprint", action="append", metavar="KICAD_MOD",
                        help="Path to a .kicad_mod file (repeat for density variants; auto-detected if omitted)")
    parser.add_argument("--symbol", metavar="KICAD_SYM",
                        help="Path to the .kicad_sym file (auto-detected from incoming/ if omitted)")
    parser.add_argument("--model", metavar="STEP",
                        help="Path to a .step or .wrl 3D model (auto-detected from incoming/ if omitted)")
    args = parser.parse_args()

    api_key = check_api_key()

    # Prompt for contributor info
    print()
    try:
        github_handle = input("GitHub username (no @ prefix): ").strip()
        if not github_handle:
            sys.exit("ERROR: GitHub username cannot be empty.")
        datasheet_url = input("Datasheet URL (where you downloaded the PDF from): ").strip()
        if not datasheet_url:
            sys.exit("ERROR: Datasheet URL cannot be empty.")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)

    # Resolve file paths: explicit args win; fall back to incoming/ scan
    # (must happen before origin prompts so we know whether a model is present)
    if not args.datasheet and not args.footprint and not args.symbol:
        detected = scan_incoming()
        if detected is None:
            parser.error("incoming/ directory not found. Provide --datasheet, --footprint, and --symbol explicitly.")
        args.datasheet, args.footprint, args.symbol, detected_model = detected
        if args.model is None:
            args.model = detected_model
    else:
        missing = []
        if not args.datasheet:
            missing.append("--datasheet")
        if not args.footprint:
            missing.append("--footprint")
        if not args.symbol:
            missing.append("--symbol")
        if missing:
            parser.error(f"Missing required arguments: {', '.join(missing)}")

    validate_inputs(args)

    # Prompt for file origins
    print("\nFile origins (for attribution):")
    footprint_origin = prompt_origin("Footprint")
    symbol_origin = prompt_origin("Symbol")
    model_origin = prompt_origin("3D model") if args.model else None
    print()

    today = date.today().isoformat()

    # Step 1: LLM extraction
    base_data = extract_with_llm(args.datasheet, api_key)
    print("Extraction complete.")

    # Inject the contributor-supplied datasheet URL (never trust the LLM for URLs)
    base_data.setdefault("datasheet", {})["url"] = datasheet_url

    # Step 2: Variant detection
    variants = detect_variants(args.footprint)
    if len(variants) > 1:
        print(f"Detected {len(variants)} footprint variants:")
        for fp, suffix in variants:
            tag = suffix if suffix else "-N (nominal)"
            print(f"  {Path(fp).name}  →  suffix '{tag}'")

    # Step 3: Build entry JSONs
    entries = build_entries(base_data, variants, args.symbol, args.model,
                            github_handle, today,
                            footprint_origin, symbol_origin, model_origin)

    # Step 4: Interactive review
    entries = review_entries(entries)

    # Step 5: Place files
    print("\nWriting files...")
    json_files = place_files(entries, args.symbol, args.model)

    # Step 6: Validate
    print("\nRunning validator...")
    validate_rc = run_validate(json_files)
    if validate_rc != 0:
        print(
            "\nWARNING: Validation found errors above. "
            "Fix them and re-run:\n  python scripts/validate.py"
        )

    # Step 7: Rebuild index
    print("\nRebuilding index...")
    run_build_index()

    # Step 8: Done
    ids = [e["id"] for e, _ in entries]
    desc = entries[0][0].get("description", "")
    print(f"\n✓ Added {len(ids)} part(s): {', '.join(ids)}")
    print("\nNext steps:")
    print("  git add components/ footprints/ symbols/ 3d_models/ index/")
    print(f'  git commit -m "add {ids[0]}: {desc}"')
    print("  git push && open a PR")


if __name__ == "__main__":
    main()
