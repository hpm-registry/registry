# incoming/

Drop your contribution files here before running `scripts/add_part.py`.

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
python scripts/add_part.py --github your-github-handle
```

The script auto-detects the files in this folder. Once it completes, this
folder is cleared and the files live in the registry under `components/`,
`footprints/`, `symbols/`, and `3d_models/`.

If you have multiple unrelated parts to add, process them one at a time —
clear this folder between runs.
