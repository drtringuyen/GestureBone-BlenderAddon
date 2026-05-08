# GestureBone

Rig and animate bendy characters by aligning them to curve bones

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
│   ├── __init__.py              # Addon metadata & registration
│   ├── properties.py            # Global properties
│   ├── panels.py                # UI panels
│   ├── infos.py                 # Info panel & debugging
│   ├── module_*_operators.py    # Module operators
│   ├── module_*_ui.py           # Module UI
│   └── module_*_utils.py        # Module utilities
├── manifest.toml                # Extension format metadata
├── zip_addon.py                 # Build traditional ZIP
├── build_extension.py           # Build Blender Extension
├── install.py                   # Installation script
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Modules

This addon is organized into modules. Each module is self-contained:
- `module_example_operators.py` - Operators
- `module_example_ui.py` - UI elements
- `module_example_utils.py` - Utility functions

Enable/disable modules in `addons/GestureBone/__init__.py`:
```python
MODULES = {
    "example": True,  # Set to False to disable
}
```

## Global Properties

All global properties are defined in `properties.py`. Access them:
```python
context.scene.gesturebone_props.debug_mode
```

## Debug Mode

- Enable debug mode in the Info panel (N-Panel → GestureBone → Debug button)
- Shows extra labels marked with `text_ctxt="extra-info-label"`
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
- All UI elements subscribe to the main panel in `panels.py`
- Use `extra-info-label` markup for debug-only text
- Run `install.py` after editing to auto-reload in Blender

## License

[Add your license here]

## Author

Nguyen Duc Tri

---

Generated with [Blender Addon Init](https://github.com/yourusername/blender-addon-init)
