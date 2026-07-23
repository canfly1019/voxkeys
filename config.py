"""
config.py — Configuration management
Config path: ~/.config/voxkeys/config.json
"""

import os
import json
import stat

CONFIG_DIR = os.path.expanduser("~/.config/voxkeys")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "provider": "github",
    "github_token": "",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "whisper_model": "small",
    "language": "zh",
    "output_language": "",
    # STT backend: "local" (faster-whisper on CPU) or "groq" (cloud whisper-large-v3).
    "stt_provider": "local",
    "groq_api_key": "",
    # Per-app prompts: when on, voxkeys detects the active window and adapts tone
    # (terminal / chat / email / code / social).
    "per_app_prompts": False,
    "record_hotkey": "f9",
    "window_alpha": 0.92,
}


def load_config():
    """Load config file, merge with defaults. API keys: config first, env var fallback."""
    config = dict(DEFAULT_CONFIG)

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            config.update(stored)
            # Fix permissions: ensure only owner can read/write
            current_mode = os.stat(CONFIG_PATH).st_mode & 0o777
            if current_mode != 0o600:
                os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except (json.JSONDecodeError, OSError):
            pass

    # API key fallback to environment variables
    if not config["github_token"]:
        config["github_token"] = os.environ.get("GITHUB_TOKEN", "")
    if not config["openai_api_key"]:
        config["openai_api_key"] = os.environ.get("OPENAI_API_KEY", "")
    if not config["anthropic_api_key"]:
        config["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    if not config["groq_api_key"]:
        config["groq_api_key"] = os.environ.get("GROQ_API_KEY", "")

    return config


def save_config(updates):
    """Write to JSON (only update the given keys)."""
    current = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                current = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    current.update(updates)

    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 600: owner read/write only
