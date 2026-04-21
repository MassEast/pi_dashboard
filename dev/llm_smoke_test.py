#!/usr/bin/env python3
"""
Smoke test for LLM emotion classification with Claude Sonnet 4.6
Standalone test without full PiDashboard imports
"""

import json
import sys
import requests
import re
from pathlib import Path

def load_config():
    """Load configuration from config.json"""
    config_path = Path(__file__).parent / "config.json"
    with open(config_path) as f:
        return json.load(f)

def extract_json_from_text(text):
    """Extract JSON from LLM response text"""
    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None

def classify_emotion(emotion_name, config):
    """Classify a new emotion using Claude Sonnet 4.6 API"""
    emotion_cfg = config.get("EMOTION", {})
    llm_cfg = emotion_cfg.get("LLM", {})
    
    if not llm_cfg.get("ENABLED"):
        print("   ❌ LLM is disabled!")
        return None
    
    api_key = llm_cfg.get("API_KEY")
    model = llm_cfg.get("MODEL", "claude-sonnet-4-6")
    url = llm_cfg.get("URL", "https://api.anthropic.com/v1/messages")
    prompt_template = llm_cfg.get("PROMPT_TEMPLATE", "")
    
    if not api_key:
        print("   ❌ API key not configured!")
        return None
    
    # Get current catalog
    catalog = emotion_cfg.get("CATALOG", [])
    catalog_data = [
        {
            "name": e.get("name"),
            "emoji": e.get("emoji"),
            "color": e.get("color"),
        }
        for e in catalog
    ]
    
    # Build prompt
    prompt = (
        prompt_template
        .replace("{{catalog_json}}", json.dumps(catalog_data, ensure_ascii=False))
        .replace("{{new_emotion_json}}", json.dumps({"name": emotion_name}, ensure_ascii=False))
    )
    
    print(f"      📡 Calling API: {model}")
    
    # Call Claude API
    try:
        response = requests.post(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 200,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
            timeout=8,
        )
        
        if response.status_code != 200:
            print(f"      ❌ API error: {response.status_code}")
            print(f"         {response.text}")
            return None
        
        data = response.json()
        response_text = data.get("content", [{}])[0].get("text", "")
        
        print(f"      📝 Raw response: {response_text[:100]}...")
        
        # Extract JSON
        result = extract_json_from_text(response_text)
        if not result:
            print(f"      ❌ Could not parse JSON from response")
            return None
        
        return result
        
    except requests.exceptions.Timeout:
        print(f"      ❌ Request timeout after 8 seconds")
        return None
    except Exception as e:
        print(f"      ❌ Error: {type(e).__name__}: {str(e)}")
        return None

def run_smoke_test():
    """Run smoke test for emotion classification"""
    print("=" * 80)
    print("EMOTION CLASSIFICATION SMOKE TEST - Claude Sonnet 4.6")
    print("=" * 80)
    
    config = load_config()
    emotion_cfg = config.get("EMOTION", {})
    llm_cfg = emotion_cfg.get("LLM", {})
    
    # Check configuration
    print("\n1. CONFIGURATION CHECK")
    print(f"   LLM Enabled: {llm_cfg.get('ENABLED')}")
    print(f"   Model: {llm_cfg.get('MODEL')}")
    print(f"   API URL: {llm_cfg.get('URL')}")
    
    catalog = emotion_cfg.get("CATALOG", [])
    print(f"   Catalog size: {len(catalog)} emotions")
    
    fallback = emotion_cfg.get("FALLBACK_STYLE", {})
    print(f"   Fallback style: {fallback}")
    
    if not llm_cfg.get("ENABLED"):
        print("\n   ❌ LLM is disabled in config!")
        return False
    
    if not llm_cfg.get("API_KEY"):
        print("\n   ❌ API key not configured!")
        return False
    
    # Display current catalog
    print("\n2. CURRENT EMOTION CATALOG (Sentiment Spectrum Order)")
    for i, emotion in enumerate(catalog):
        print(f"   [{i:2d}] {emotion['name']:12} {emotion['emoji']} {emotion['color']}")
    
    # Test emotion classification
    print("\n3. TESTING EMOTION CLASSIFICATION")
    test_emotions = ["content", "chill"]
    success_count = 0
    
    for test_emotion in test_emotions:
        print(f"\n   Testing: '{test_emotion}'")
        result = classify_emotion(test_emotion, config)
        
        if result is None:
            print(f"   ❌ Classification failed")
            continue
        
        print(f"      ✓ Name: {result.get('name')}")
        print(f"      ✓ Emoji: {result.get('emoji')}")
        print(f"      ✓ Color: {result.get('color')}")
        print(f"      ✓ Insert After: {result.get('insert_after')}")
        
        # Validate response structure
        required_fields = ['name', 'emoji', 'color', 'insert_after']
        missing = [f for f in required_fields if f not in result]
        if missing:
            print(f"      ⚠️  Missing fields: {missing}")
        else:
            print(f"      ✓ All required fields present")
        
        # Validate insert_after
        insert_after = result.get('insert_after')
        if insert_after is not None:
            catalog_names = [e['name'] for e in catalog]
            if insert_after not in catalog_names:
                print(f"      ⚠️  insert_after '{insert_after}' not found in catalog!")
            else:
                idx = catalog_names.index(insert_after)
                print(f"      ✓ Position: Would insert after position {idx} ({insert_after})")
                success_count += 1
        else:
            print(f"      ✓ Position: Would insert at beginning (most positive)")
            success_count += 1
    
    print("\n" + "=" * 80)
    print(f"SMOKE TEST COMPLETE - {success_count}/{len(test_emotions)} classifications successful")
    print("=" * 80)
    return success_count > 0

if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
