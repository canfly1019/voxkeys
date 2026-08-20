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


# API key field -> environment variable. Keys sourced from the environment are
# never written back to config.json (see save_config), so putting a token in
# the environment keeps it out of the file the settings dialog rewrites.
ENV_KEYS = {
    "github_token": "GITHUB_TOKEN",
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
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
    for field, env_name in ENV_KEYS.items():
        if not config.get(field):
            config[field] = os.environ.get(env_name, "")

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

    # The settings dialog round-trips whatever load_config() returned, so a key
    # that came from the environment would otherwise get persisted to disk on
    # the next save. Drop it back to empty and let the env supply it again.
    for field, env_name in ENV_KEYS.items():
        env_value = os.environ.get(env_name, "")
        if env_value and current.get(field) == env_value:
            current[field] = ""

    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 600: owner read/write only
