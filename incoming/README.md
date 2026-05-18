# incoming/

Drop your contribution files here before running `user_scripts/add_part.py`.

```
incoming/
├── datasheet.pdf          ← manufacturer datasheet (one PDF)
├── PART.kicad_mod         ← KiCad footprint
├── PART-L.kicad_mod       ← optional: IPC least-density variant
├── PART-M.kicad_mod       ← optional: IPC most-density variant
├── PART.kicad_sym         ← KiCad schematic symbol
└── PART.step              ← optional: 3D model
```

Then run:

```bash
python user_scripts/add_part.py
```

The script will prompt you for:
- Your GitHub username
- The datasheet PDF URL (never generated automatically — must come from you)
- The origin of each file (where you got the footprint, symbol, and 3D model)

**Do not put files from DigiKey, SnapMagic, UltraLibrarian, or SamacSys here.**
Those services prohibit redistribution. The script detects and rejects them
automatically based on generator strings embedded in the file.

Accepted sources:
- KiCad official library (CC-BY-SA-4.0)
- Drawn yourself from the manufacturer datasheet (CC0-1.0)
- Manufacturer's own download page (check their specific terms)

The script auto-detects the files in this folder and copies them into the
registry under `components/`, `footprints/`, `symbols/`, and `3d_models/`.
Your original files stay in `incoming/` but are gitignored — they will never
be committed.

If you have multiple unrelated parts to add, process them one at a time and
manually clear this folder between runs.
