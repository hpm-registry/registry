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

The script will prompt you for your GitHub username and the URL you downloaded
the datasheet from. URLs are never generated automatically — they must come
from you to avoid hallucination.

**Do not put files from DigiKey, SnapMagic, UltraLibrarian, or SamacSys here.**
Those services prohibit redistribution. The script will reject them automatically.
Accepted sources: KiCad official library (CC-BY-SA-4.0) or files you drew
yourself from the manufacturer datasheet (CC0-1.0).

The script auto-detects the files in this folder. Once it completes, this
folder is cleared and the files live in the registry under `components/`,
`footprints/`, `symbols/`, and `3d_models/`.

If you have multiple unrelated parts to add, process them one at a time —
clear this folder between runs.
