# GestureBone

Rig and animate bendy characters by aligning them to curve bones.

> **Architecture:** see [ARCHITECTURE.md](ARCHITECTURE.md) for the current
> design (two-rig PLOTTING/GESTURE model, unified `ChainDefinition`, module
> layout, rig-generation pipeline, and build/deploy).

## Installation

### Manual (ZIP)
1. Download the latest `GestureBone.zip`
2. Open Blender → `Edit > Preferences > Add-ons > Install`
3. Select the ZIP file and enable the addon

### Blender Extension (Official)
1. Visit [Blender Extensions](https://extensions.blender.org/)
2. Search for "GestureBone"
3. Install and enable

## Getting Started

### Development Setup
```bash
# Install dependencies (if any)
pip install -r requirements.txt

# Build and reload in Blender
python install.py
```

### Project Structure
```
GestureBone/
├── addons/GestureBone/
│   ├── __init__.py         # Addon metadata & registration
│   ├── properties.py       # Scene-level global properties
│   ├── panels.py           # Infos panel + MainPanel (rig_type dispatch)
│   ├── infos.py            # Build / reload / debug / console operators
│   ├── module_manager.py   # Loads modules per modules_config.json
│   └── modules/
│       ├── shared/         # ChainDefinition, ArmatureProps, shared utils
│       ├── plotting/       # PLOTTING rig: rig generation
│       └── gesture/        # GESTURE rig: drawing & binding
├── ARCHITECTURE.md         # Design overview (start here)
├── manifest.toml           # Extension format metadata
├── zip_addon.py            # Build traditional ZIP
├── build_extension.py      # Build Blender Extension
├── install.py              # Deploy + hot-reload (5.1 & 5.2)
└── README.md               # This file
```

## Modules

The addon is split into three module packages under `modules/`:
- **`shared`** — always loaded; the unified `ChainDefinition` /
  `ArmatureProps` data model and common utilities.
- **`plotting`** — the PLOTTING rig (rig generation).
- **`gesture`** — the GESTURE rig (spline drawing & bone binding).

`plotting` and `gesture` are toggled in `modules_config.json`
(`{ "plotting": true, "gesture": true }`) and registered by
`module_manager.py`. Each module registers its operators; its UI is drawn
inline from `panels.py` based on the active armature's `rig_type`. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the full picture.

## Global Properties

All global properties are defined in `properties.py`. Access them:
```python
context.scene.gesturebone_props.debug_mode
```

## Debug Mode

- Enable debug mode in the Infos panel (N-Panel → GestureBone → Debug button)
- Reveals the step-by-step rig-generation pipeline, per-chain property
  readouts, the loaded-module list, and the armature override
- Displays build time and version information

## Publishing

### As Traditional ZIP
```bash
python zip_addon.py
# Creates: GestureBone.zip
```

### As Blender Extension
```bash
python build_extension.py
# Creates: GestureBone-extension.zip
# Submit to: https://extensions.blender.org/
```

## Development Notes

- Code files longer than 500 lines should be split into modules
- Module UI is drawn inline from `panels.py` via `draw_plotting_ui` /
  `draw_gesture_ui`, dispatched on the armature's `rig_type`
- Run `python install.py` after editing to deploy to Blender 5.1 & 5.2 and
  hot-reload the running instance (see [ARCHITECTURE.md](ARCHITECTURE.md) §7)

## License

[Add your license here]

## Author

Nguyen Duc Tri

---

Generated with [Blender Addon Init](https://github.com/yourusername/blender-addon-init)
