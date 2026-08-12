#!/usr/bin/env python3
"""
Backfill emoji/color for custom emotions that got stuck on FALLBACK_STYLE ("?" / gray)
because the LLM classification call failed when they were first typed in (e.g. no
internet at that moment). Standalone script, same pattern as llm_smoke_test.py - does
not import PiDashboard.py (that needs pygame/a display).

Run manually and only while online:
    python3 dev/reclassify_fallback_emotions.py
"""

import json
import re
import shutil
import sys
import time
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
UNKNOWN_OPTION = "don't know"
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def extract_json_from_text(text):
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def classify_emotion(emotion_name, llm_cfg, catalog_snapshot):
    catalog_data = [
        {"name": e.get("name"), "emoji": e.get("emoji"), "color": e.get("color")}
        for e in catalog_snapshot
    ]
    prompt = (
        llm_cfg.get("PROMPT_TEMPLATE", "")
        .replace("{{catalog_json}}", json.dumps(catalog_data, ensure_ascii=False))
        .replace("{{new_emotion_json}}", json.dumps({"name": emotion_name}, ensure_ascii=False))
    )

    response = requests.post(
        llm_cfg.get("URL", "https://api.anthropic.com/v1/messages"),
        headers={
            "x-api-key": llm_cfg["API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": llm_cfg.get("MODEL", "claude-3-5-haiku-latest"),
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=8,
    )
    response.raise_for_status()
    response_text = response.json()["content"][0]["text"]
    result = extract_json_from_text(response_text)
    if not result:
        raise ValueError(f"could not parse JSON from LLM response: {response_text!r}")
    return result


def main():
    config = load_config()
    emotion_cfg = config.get("EMOTION", {})
    llm_cfg = emotion_cfg.get("LLM", {})
    catalog = emotion_cfg.get("CATALOG", [])
    fallback = emotion_cfg.get("FALLBACK_STYLE", {"emoji": "?", "color": "#9ca3af"})

    if not llm_cfg.get("ENABLED") or not llm_cfg.get("API_KEY"):
        print("LLM classification is disabled or missing an API key in config.json - nothing to do.")
        sys.exit(1)

    candidates = [
        entry
        for entry in catalog
        if entry.get("name") != UNKNOWN_OPTION
        and entry.get("emoji") == fallback.get("emoji")
        and entry.get("color") == fallback.get("color")
    ]

    if not candidates:
        print("No catalog entries are stuck on the fallback style - nothing to backfill.")
        return

    print(f"Found {len(candidates)} catalog entries stuck on the fallback style: "
          f"{[c['name'] for c in candidates]}")

    updated = 0
    unchanged = 0
    failed = []
    for i, entry in enumerate(candidates, start=1):
        name = entry["name"]
        print(f"[{i}/{len(candidates)}] Classifying '{name}'...", flush=True)
        try:
            result = classify_emotion(name, llm_cfg, catalog)
        except Exception as ex:
            print(f"  FAILED: {type(ex).__name__}: {ex}", flush=True)
            failed.append(name)
            continue

        new_emoji = result.get("emoji") or fallback["emoji"]
        new_color = result.get("color")
        if not (isinstance(new_color, str) and COLOR_RE.match(new_color)):
            new_color = fallback["color"]

        if new_emoji == fallback["emoji"] and new_color == fallback["color"]:
            print(f"  LLM also returned the fallback style for '{name}' - leaving as-is.", flush=True)
            unchanged += 1
            continue

        print(f"  '{name}': {entry['emoji']} {entry['color']} -> {new_emoji} {new_color}", flush=True)
        entry["emoji"] = new_emoji
        entry["color"] = new_color
        updated += 1
        time.sleep(0.5)  # be polite to the API between requests

    if updated:
        backup_path = CONFIG_PATH.with_suffix(f".json.bak-{int(time.time())}")
        shutil.copy2(CONFIG_PATH, backup_path)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        print(f"\nBacked up previous config to {backup_path.name} and wrote updated catalog.")

    print(
        f"\nDone: {updated} reclassified, {unchanged} left as fallback "
        f"(LLM confirmed fallback fits), {len(failed)} failed ({failed})."
    )


if __name__ == "__main__":
    main()
