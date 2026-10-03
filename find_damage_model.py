"""Locate and load the maplestory-gms skill's damage_model.py, wherever the skills are installed.

Claude Code keeps skills in ~/.claude/skills/<name>/; Claude Desktop / claude.ai mounts them side by side
(e.g. /mnt/skills/user/<name>/). Set MAPLE_DAMAGE_MODEL to override."""
import glob, importlib.util, os, sys


def damage_model_path():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("MAPLE_DAMAGE_MODEL", ""),
        os.path.join(here, "damage_model.py"),
        os.path.join(here, "..", "..", "maplestory-gms", "scripts", "damage_model.py"),
        os.path.expanduser("~/.claude/skills/maplestory-gms/scripts/damage_model.py"),
        *sorted(glob.glob("/mnt/skills/*/maplestory-gms/scripts/damage_model.py")),
        *sorted(glob.glob("/mnt/skills/maplestory-gms/scripts/damage_model.py")),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    sys.exit("damage_model.py not found: install the maplestory-gms skill next to maplestory-strength-map, "
             "or set MAPLE_DAMAGE_MODEL to its path")


def load_damage_model():
    spec = importlib.util.spec_from_file_location("dm", damage_model_path())
    dm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dm)
    return dm
