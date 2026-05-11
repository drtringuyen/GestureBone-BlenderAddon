import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "modules_config.json")
_LOADED = {}

# Add new modules here — panels.py iterates this list automatically
ALL_MODULES = [
    {"name": "gesture_draw", "op": "gesturebone.toggle_gesture_draw", "icon": "GREASEPENCIL"},
    {"name": "mesh_spritesheet", "op": "gesturebone.toggle_mesh_spritesheet", "icon": "POSE_HLT"},
]


def is_loaded(name):
    return _LOADED.get(name, False)


def _read_config():
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _write_config(config):
    try:
        with open(_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


def _get_module(name):
    import importlib
    try:
        return importlib.import_module(f".modules.{name}", package=__package__)
    except ImportError:
        return None


def load_all():
    config = _read_config()
    for m in ALL_MODULES:
        name = m["name"]
        mod = _get_module(name)
        if mod and config.get(name, True):
            mod.register()
            _LOADED[name] = True
        else:
            _LOADED[name] = False


def unload_all():
    for m in reversed(ALL_MODULES):
        name = m["name"]
        if _LOADED.get(name, False):
            mod = _get_module(name)
            if mod:
                try:
                    mod.unregister()
                except Exception:
                    pass
        _LOADED[name] = False


def toggle(name):
    mod = _get_module(name)
    if not mod:
        return
    if _LOADED.get(name, False):
        try:
            mod.unregister()
        except Exception:
            pass
        _LOADED[name] = False
    else:
        mod.register()
        _LOADED[name] = True
    config = _read_config()
    config[name] = _LOADED[name]
    _write_config(config)
