# Contributing to HPM

The registry's value is **accuracy**. An unverified or wrong entry is worse than
a missing one. Everything below is designed to keep data correct at community scale.

---

## Quick start (recommended)

The fastest way to add a part is with `scripts/add_part.py`. It uses Claude to
extract structured data from the manufacturer datasheet, walks you through a
review step, then places all files into the correct locations and validates.

**What you need to gather first:**

| File | Required | Notes |
|---|---|---|
| Datasheet PDF | Yes | Manufacturer-hosted preferred |
| `.kicad_mod` footprint | Yes | One per IPC density variant (L/M/nominal) |
| `.kicad_sym` symbol | Yes | KiCad 6+ format |
| `.step` or `.wrl` 3D model | No | Adds 3D view in KiCad |

**Setup (once):**

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # get one at https://console.anthropic.com
```

**Run:**

Drop your files into the `incoming/` folder (see `incoming/README.md`), then:

```bash
python scripts/add_part.py
```

The script will prompt you for your GitHub username and the URL you downloaded
the datasheet from.

The script auto-detects the datasheet, footprint(s), symbol, and 3D model from
`incoming/`. If you have multiple `.kicad_mod` files in there (IPC density
variants), all of them are picked up and registered as linked variants.

The script will show you the proposed JSON before writing anything — review it,
correct any extraction errors, then confirm. It validates and rebuilds the index
automatically, leaving you with a clean `git add` / `git commit` / PR.

**After the script runs, review the entry** and set `meta.verified: true` +
`meta.verified_by: "your-handle"` only after you've cross-checked every spec
against the datasheet yourself.

---

## Manual process

If you prefer to fill the JSON by hand, follow Steps 1–7 below.

---

## What a part is

Every part is three files in parallel locations, all sharing the same stem:

```
components/<category>/<subcategory>/<ID>.json
footprints/<category>/<subcategory>/<ID>.kicad_mod
symbols/<category>/<subcategory>/<ID>.kicad_sym
```

The JSON entry's `footprint.path` and `symbol.path` point at the other two files.
The validator confirms they exist — a component entry with a missing asset file
will not pass CI.

---

## Step 1 — Find where your part goes

Use the table below. Choose by **primary function**, not packaging. A voltage
reference goes in `analog-ics`, not `regulators`, even though it regulates voltage.

| Category | Subcategories |
|---|---|
| `resistors` | `smd-chip`, `through-hole`, `potentiometer`, `current-sense`, `resistor-array` |
| `capacitors` | `mlcc`, `electrolytic`, `tantalum`, `film`, `supercapacitor` |
| `inductors` | `power-inductor`, `ferrite-bead`, `common-mode-choke`, `rf-inductor` |
| `diodes` | `rectifier`, `schottky`, `zener`, `tvs`, `led-indicator` |
| `transistors` | `n-channel-mosfet`, `p-channel-mosfet`, `npn-bjt`, `pnp-bjt`, `igbt` |
| `regulators` | `ldo`, `switching-buck`, `switching-boost`, `buck-boost`, `charge-pump` |
| `microcontrollers` | `8-bit`, `16-bit`, `32-bit-arm`, `risc-v`, `wireless-soc` |
| `logic-ics` | `gate`, `flip-flop`, `shift-register`, `buffer`, `level-shifter`, `multiplexer` |
| `analog-ics` | `op-amp`, `comparator`, `voltage-reference`, `adc`, `dac`, `analog-switch` |
| `interface-ics` | `usb`, `can`, `rs485`, `i2c-io-expander`, `ethernet-phy`, `uart-bridge` |
| `memory` | `eeprom`, `flash`, `sram`, `fram`, `sd-emmc` |
| `sensors` | `temperature`, `imu`, `pressure`, `hall-effect`, `optical`, `current` |
| `connectors` | `header`, `usb`, `terminal-block`, `ffc-fpc`, `board-to-board`, `rf` |
| `electromechanical` | `relay`, `switch`, `pushbutton`, `rotary-encoder`, `buzzer` |
| `power-modules` | `dc-dc-module`, `ac-dc-module`, `pol-module` |
| `crystals-oscillators` | `crystal`, `oscillator`, `resonator`, `rtc-crystal` |
| `optoelectronics` | `led`, `optocoupler`, `photodiode`, `display`, `laser` |
| `protection` | `fuse`, `ptc-resettable`, `tvs-array`, `esd-suppressor` |

If your part fits two categories, pick the one a contributor would search first
and add the other as a tag in `meta.tags`.

If your part fits no subcategory, **open an issue** rather than inventing a
folder. Adding a subcategory requires a schema change reviewed by maintainers.

---

## Step 2 — Name your files

The canonical ID is the primary MPN, uppercased, with slashes replaced by hyphens:
`AMS1117/3.3` → `AMS1117-3.3`. All three files share this stem.

- `components/regulators/ldo/AMS1117-3.3.json`
- `footprints/regulators/ldo/AMS1117-3.3.kicad_mod`
- `symbols/regulators/ldo/AMS1117-3.3.kicad_sym`

The `id` field inside the JSON must match the filename exactly. The validator
rejects mismatches.

---

## Step 3 — Fill in the JSON entry

All required fields are defined in `schema/component.schema.json`. The key ones:

**`manufacturer`** — use the canonical spelling from `MANUFACTURERS.md`.
Add the manufacturer there if they are not listed.

**`specs`** — every value is a structured object, never a string:

```json
"output_voltage": { "typ": 3.3, "unit": "V" },
"dropout_voltage": { "min": 0.8, "typ": 1.1, "max": 1.3, "unit": "V" },
"operating_temp": { "min": -40, "max": 125, "unit": "degC" }
```

Use `min`/`typ`/`max` for whichever values the datasheet gives. This is what
lets agents filter parts numerically — a string like `"1.1V typ"` is useless
to a machine.

Use `snake_case` for spec key names. Reuse existing key names from other entries
in the same subcategory for consistency. Common keys by category:

| Category | Common spec keys |
|---|---|
| `resistors` | `resistance`, `tolerance`, `power_rating`, `temp_coefficient`, `max_voltage` |
| `capacitors` | `capacitance`, `voltage_rating`, `tolerance`, `esr`, `ripple_current` |
| `inductors` | `inductance`, `current_rating`, `dc_resistance`, `saturation_current`, `self_resonant_frequency` |
| `diodes` | `forward_voltage`, `reverse_voltage`, `forward_current`, `reverse_recovery_time`, `power_dissipation` |
| `transistors` | `vds_max`, `vgs_th`, `rds_on`, `id_continuous`, `gate_charge`, `power_dissipation` |
| `regulators` | `output_voltage`, `output_current_max`, `input_voltage_max`, `dropout_voltage`, `quiescent_current`, `switching_frequency` |
| `microcontrollers` | `cpu_frequency_max`, `flash`, `ram`, `gpio_count`, `supply_voltage`, `adc_channels` |
| `logic-ics` | `supply_voltage`, `propagation_delay`, `output_current`, `input_threshold_high`, `input_threshold_low` |
| `analog-ics` | `supply_voltage`, `gain_bandwidth_product`, `input_offset_voltage`, `slew_rate`, `quiescent_current` |
| `interface-ics` | `supply_voltage`, `data_rate`, `bus_voltage`, `esd_rating` |
| `memory` | `capacity`, `supply_voltage`, `interface`, `access_time`, `data_retention` |
| `sensors` | `measurement_range`, `accuracy`, `resolution`, `sample_rate`, `supply_voltage`, `interface` |
| `connectors` | `contact_count`, `pitch`, `current_rating`, `voltage_rating`, `mating_cycles` |
| `electromechanical` | `supply_voltage`, `contact_rating`, `coil_resistance`, `operating_force` |
| `power-modules` | `input_voltage`, `output_voltage`, `output_current_max`, `efficiency`, `switching_frequency` |
| `crystals-oscillators` | `frequency`, `frequency_tolerance`, `load_capacitance`, `esr`, `stability` |
| `optoelectronics` | `forward_voltage`, `wavelength`, `luminous_intensity`, `forward_current`, `viewing_angle` |
| `protection` | `voltage_rating`, `current_rating`, `response_time`, `capacitance` |

For frequency-dependent specs (ferrite bead impedance, capacitor ESR at
frequency), use `at_frequency`:

```json
"impedance": { "value": 600, "unit": "Ohm", "at_frequency": { "value": 100, "unit": "MHz" } }
```

**`pins`** — optional but strongly recommended for ICs. Keys are pin numbers as
strings; each pin has a `name`, `type`, and optional `description`:

```json
"pins": {
  "1": { "name": "IN", "type": "power-in" },
  "2": { "name": "GND", "type": "ground" },
  "3": { "name": "OUT", "type": "power-out", "description": "Adjustable via external resistor divider" }
}
```

Pin types: `power-in`, `power-out`, `ground`, `signal-in`, `signal-out`,
`signal-bidir`, `passive`, `open-drain`, `open-collector`, `no-connect`.

**`datasheet`** — `url` must point to the manufacturer's PDF. Record the exact
revision string in `datasheet.revision`. Add `archived_url` if the manufacturer's
site is uncertain. Add `sha256` if you want to lock the document.

**`meta.verified`** — set to `false` unless you have personally cross-checked
every spec against the cited datasheet revision. If `true`, put your GitHub
handle in `meta.verified_by`.

---

## Step 4 — Package variants

The same silicon in two packages = two entries, not one. Each package gets its
own `id` and its own correct footprint. Link them with `variant_of`:

```
components/analog-ics/op-amp/LM358-SOIC8.json   "variant_of": "LM358"
components/analog-ics/op-amp/LM358-TSSOP8.json  "variant_of": "LM358"
```

Rules:
- All variants share the same `variant_of` base string.
- The base string must **not** be a real entry `id` — the validator rejects this.
- A `variant_of` group must have 2 or more members. A lone variant is a validator error.
- Parts with no package variants set `variant_of` to `null`.

Reel/tape-and-reel suffixes of the same package (e.g. `LM358DR` vs `LM358DT`)
are **not** separate entries — add the alternate MPN to `aliases`.

---

## Step 5 — Footprint and symbol files

KiCad formats only: `.kicad_mod` for footprints, `.kicad_sym` for symbols.

For each file, fill in the component entry's `footprint` / `symbol` block:
- `path` — repo-relative path to the file (validator checks it exists)
- `format_version` — the minimum KiCad major.minor that can open it. Author to
  the oldest version you can. Symbols have been stable since `"6.0"`.
- `origin` — where the file came from (e.g. `"KiCad official library"`,
  `"drawn from manufacturer land pattern"`). This is required for attribution.

**License policy:** all hosted footprints and symbols must be **CC-BY-SA-4.0**
(KiCad official library) or **CC0-1.0** (original contributor work).

**Do not use files from DigiKey, SnapMagic, or UltraLibrarian.**
DigiKey's component pages link to downloads provided by SnapMagic (formerly
SnapEDA) and UltraLibrarian. Both services grant a license to use files in your
own designs only — they explicitly prohibit redistribution. "Free to download"
is not the same as "free to redistribute." Contributing these files to HPM
violates their terms of service regardless of where you downloaded them from.

**Accepted sources:**
- **KiCad official library** — CC-BY-SA-4.0, fully redistributable
- **Drawn yourself from the manufacturer datasheet** — your original work, use CC0-1.0
- **Manufacturer-provided** — check their specific terms before hosting; some (e.g. Texas Instruments) grant redistribution rights, most do not

---

## Step 6 — Versioning

**New entry** — set `meta.revision` to `1` with one matching `meta.history` entry:

```json
"revision": 1,
"history": [{ "revision": 1, "date": "2026-05-17", "by": "your-handle", "change": "Initial entry" }]
```

**Editing an existing entry** — increment `meta.revision` by 1 and append a
history line describing what changed. The validator enforces
`revision == len(history)`. Be specific: `"Corrected dropout_voltage typ from
1.3V to 1.1V per datasheet Rev C"`, not `"Fixed spec"`.

Bump `meta.revision` when the data record changes (wrong spec corrected, footprint
added, verified status updated). Create a **new entry** when it is a different
part (different silicon, different package, meaningfully different electrical
behaviour).

---

## Before opening a PR

Run the validator locally:

```bash
pip install jsonschema
python scripts/validate.py
```

Exit code 0 means clean. CI runs the same check and will block your PR on any
error. Fix all errors before opening; warnings (unverified entry) are allowed to merge.

---

## What not to do

- **Don't edit `index/`** — auto-generated by `scripts/build_index.py`. Hand
  edits are overwritten on the next build.
- **Don't invent a new category folder** — open an issue. New categories require
  a schema PR reviewed by maintainers.
- **Don't bulk-import unverified data** — small and correct beats large and wrong.
- **Don't host non-redistributable files** — only CC-BY-SA-4.0 and CC0-1.0
  assets are accepted. SnapEDA and Ultra Librarian files are typically not
  freely redistributable and must not be hosted.
