#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Merge a small JSON patch into config.json (for config keys git can't carry
to the Pi, config.json being gitignored). Backs config.json up first
(config.json.bak-YYYYmmdd-HHMMSS), merges dicts key by key (everything not
in the patch stays as it is, lists/values in the patch replace the old
ones), writes via a tmp file, and prints every changed key with old -> new
(values of keys containing PASSWORD/SECRET/KEY/TOKEN hidden).

--dry-run: only print what would change.

python3 dev/config_patch.py config.json patch.json [--dry-run]
"""

import datetime
import json
import os
import shutil
import sys

HIDDEN = ("PASSWORD", "SECRET", "KEY", "TOKEN")


def merge(base, patch, path=""):
    """Merges patch into base in place; returns [(key path, old, new)] of changes."""
    changes = []
    for key, value in patch.items():
        where = f"{path}.{key}" if path else key
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            changes += merge(base[key], value, where)
        elif base.get(key, "<missing>") != value:
            changes.append((where, base.get(key, "<missing>"), value))
            base[key] = value
    return changes


def show(key_path, value):
    if value == "<missing>":
        return value
    if any(word in key_path.upper() for word in HIDDEN):
        return "***"
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 70 else text[:67] + "..."


def main(config_path, patch_path, dry_run=False):
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    with open(patch_path, encoding="utf-8") as f:
        patch = json.load(f)
    changes = merge(config, patch)
    for key_path, old, new in changes:
        print(f"{key_path}: {show(key_path, old)} -> {show(key_path, new)}", flush=True)
    if not changes:
        print("nothing to change", flush=True)
        return changes
    if dry_run:
        print(f"dry run: {len(changes)} change(s), nothing written", flush=True)
        return changes
    backup = f"{config_path}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(config_path, backup)
    tmp = f"{config_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    os.replace(tmp, config_path)
    with open(config_path, encoding="utf-8") as f:
        json.load(f)  # still valid JSON
    print(f"{len(changes)} change(s) written, backup: {backup}", flush=True)
    return changes


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    main(args[0], args[1], dry_run="--dry-run" in sys.argv)
