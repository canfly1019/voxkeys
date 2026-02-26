#!/usr/bin/env python3
"""
Voxkeys — Core engine + CLI entry point
Hold hotkey to record → Whisper transcription → LLM polish → paste to cursor
"""

import os
import sys
import time
import wave
import tempfile
import subprocess
import threading
import shutil
import argparse
import pyaudio
from pynput import keyboard
from faster_whisper import WhisperModel

from config import load_config

# ─── Dependency Check ────────────────────────────────────────────────────────

def check_dependencies():
    """Check for required system tools. Returns list of missing ones."""
    missing = []
    for cmd in ("xclip", "xdotool"):
        if shutil.which(cmd) is None:
            missing.append(cmd)
    return missing

# ─── Config ──────────────────────────────────────────────────────────────────

CONFIG = load_config()
CONFIG.update({
    "output_mode": "clipboard",
    "hotkey": keyboard.Key.f9,
    "sample_rate": 16000,
    "channels": 1,
})

LANGUAGE_RULES = {
    "zh": "Output in Traditional Chinese (Taiwan usage). "
          "If the input mixes Chinese and English, keep the English parts as-is. "
          "Remove Chinese filler words (嗯、啊、那個、就是、然後...).",
    "zh-cn": "Output in Simplified Chinese (Mainland China usage). "
             "If the input mixes Chinese and English, keep the English parts as-is. "
             "Remove Chinese filler words (嗯、啊、那个、就是、然后...).",
    "en": "Output in English. "
          "Remove filler words (um, uh, like, you know, so, then...).",
    "ja": "Output in Japanese (日本語). "
          "If the input mixes Japanese and English, keep the English parts as-is. "
          "Remove filler words (えーと、あの、まあ、なんか...).",
}

LANGUAGE_RULES_DEFAULT = (
    "Output in the same language as the input. "
    "If the input mixes multiple languages, preserve each language as-is. "
    "Remove filler words appropriate to the detected language."
)


def build_system_prompt(lang=None):
    """Build a system prompt tailored to the configured language."""
    lang_rule = LANGUAGE_RULES.get(lang, LANGUAGE_RULES_DEFAULT)
    return f"""You are a speech-to-text post-processing assistant.
The user's speech has already been transcribed by a speech recognition system. Your job is to:
1. {lang_rule}
2. Fix obvious typos or recognition errors
3. Add proper punctuation and sentence breaks
4. Preserve the original meaning — do not alter or add content
5. Output the cleaned text directly, without any explanation
6. Even if the input is a question, only clean up the text — never answer or respond to the content itself

Keep technical terms and code-related content unchanged."""

# ─── Global State ────────────────────────────────────────────────────────────

recording = False
audio_frames = []
whisper_model = None
status_callback = None


def set_status_callback(fn):
    """Register a status callback (used by GUI)."""
    global status_callback
    status_callback = fn


def _notify(msg):
    """Notify GUI or print to CLI."""
    if status_callback:
        status_callback(msg)
    else:
        print(msg)

# ─── Recording ───────────────────────────────────────────────────────────────

def record_audio():
    """Record in background until recording = False."""
    global audio_frames
    audio_frames = []

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=CONFIG["channels"],
        rate=CONFIG["sample_rate"],
        input=True,
        frames_per_buffer=1024,
    )

    _notify("recording")
    while recording:
        data = stream.read(1024, exception_on_overflow=False)
        audio_frames.append(data)

    stream.stop_stream()
    stream.close()
    p.terminate()
    _notify("recording_done")


def save_audio_to_wav(frames):
    """Save recorded frames to a temporary WAV file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(CONFIG["channels"])
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(CONFIG["sample_rate"])
        wf.writeframes(b"".join(frames))
    return tmp.name

# ─── Transcription ───────────────────────────────────────────────────────────

def transcribe(wav_path):
    """Transcribe audio with faster-whisper."""
    global whisper_model

    if whisper_model is None:
        _notify("loading_model")
        whisper_model = WhisperModel(
            CONFIG["whisper_model"],
            device="cpu",
            compute_type="int8",
        )

    _notify("transcribing")
    # Whisper only understands "zh", not "zh-cn"
    whisper_lang = CONFIG["language"]
    if whisper_lang == "zh-cn":
        whisper_lang = "zh"
    segments, info = whisper_model.transcribe(
        wav_path,
        language=whisper_lang,
        beam_size=5,
        vad_filter=True,
    )

    text = " ".join(seg.text.strip() for seg in segments)
    _notify(f"transcribed:{text}")
    return text

# ─── LLM Polish ──────────────────────────────────────────────────────────────

def polish_with_claude(text, prompt):
    """Polish text using Claude API."""
    import anthropic
    client = anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"])
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=prompt,
        messages=[{"role": "user", "content": text}],
    )
    return message.content[0].text.strip()


def polish_with_github(text, prompt):
    """Polish text using GitHub Models API (free, OpenAI-compatible)."""
    import openai
    client = openai.OpenAI(
        api_key=CONFIG["github_token"],
        base_url="https://models.inference.ai.azure.com",
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
    )
    return response.choices[0].message.content.strip()


def polish_with_openai(text, prompt):
    """Polish text using OpenAI API."""
    import openai
    client = openai.OpenAI(api_key=CONFIG["openai_api_key"])
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
    )
    return response.choices[0].message.content.strip()


def polish(text):
    """Route to the configured LLM provider."""
    if not text.strip():
        return text

    provider = CONFIG.get("provider", CONFIG.get("llm_provider", "github"))

    if provider == "none":
        return text

    _notify("polishing")
    prompt = build_system_prompt(CONFIG.get("language"))
    try:
        if provider == "claude":
            return polish_with_claude(text, prompt)
        elif provider == "openai":
            return polish_with_openai(text, prompt)
        elif provider == "github":
            return polish_with_github(text, prompt)
        else:
            return text
    except Exception as e:
        # Only print exception type to avoid leaking API keys
        _notify(f"polish_failed:{type(e).__name__}")
        return text

# ─── Output to Cursor ────────────────────────────────────────────────────────

def output_text(text):
    """Paste text to the currently focused input field."""
    if not text:
        return

    _notify(f"output:{text}")

    if CONFIG["output_mode"] == "clipboard":
        process = subprocess.Popen(
            ["xclip", "-selection", "clipboard"],
            stdin=subprocess.PIPE
        )
        process.communicate(text.encode("utf-8"))
        time.sleep(0.3)

        # Detect if target is a terminal, use matching paste shortcut
        is_terminal = False
        try:
            wid = subprocess.run(["xdotool", "getactivewindow"],
                                 capture_output=True, text=True).stdout.strip()
            result = subprocess.run(["xprop", "-id", wid, "WM_CLASS"],
                                    capture_output=True, text=True)
            wm_class = result.stdout.lower()
            terminal_names = ("gnome-terminal", "xfce4-terminal", "konsole",
                              "xterm", "alacritty", "kitty", "terminator",
                              "tilix", "lxterminal", "mate-terminal")
            is_terminal = any(t in wm_class for t in terminal_names)
        except Exception:
            pass

        if is_terminal:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"])
        else:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])

    else:
        ctrl = keyboard.Controller()
        ctrl.type(text)

# ─── Hotkey Logic ────────────────────────────────────────────────────────────

def on_press(key):
    global recording
    if key == CONFIG["hotkey"] and not recording:
        recording = True
        t = threading.Thread(target=record_audio, daemon=True)
        t.start()


def on_release(key):
    global recording
    if key == CONFIG["hotkey"] and recording:
        recording = False
        time.sleep(0.1)

        frames = audio_frames.copy()
        if not frames:
            return

        def process():
            wav_path = save_audio_to_wav(frames)
            try:
                raw_text = transcribe(wav_path)
                if raw_text.strip():
                    polished = polish(raw_text)
                    output_text(polished)
                else:
                    _notify("no_speech")
            finally:
                os.unlink(wav_path)

        threading.Thread(target=process, daemon=True).start()

# ─── CLI Entry Point ─────────────────────────────────────────────────────────

def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Voxkeys — Linux voice dictation tool")
    parser.add_argument("--model", default=cfg["whisper_model"],
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Whisper model size")
    parser.add_argument("--lang", default=cfg["language"],
                        help="Language code (zh/en/ja...), leave empty for auto-detect")
    parser.add_argument("--provider", default=cfg["provider"],
                        choices=["claude", "openai", "github", "none"],
                        help="LLM provider")
    parser.add_argument("--output", default="clipboard",
                        choices=["clipboard", "type"],
                        help="Output mode")
    args = parser.parse_args()

    # CLI args override config
    CONFIG["whisper_model"] = args.model
    CONFIG["language"] = args.lang if args.lang != "auto" else None
    CONFIG["provider"] = args.provider
    CONFIG["output_mode"] = args.output

    # Check system dependencies
    missing = check_dependencies()
    if missing:
        print(f"Missing system tools: {', '.join(missing)}")
        print(f"Install with: sudo apt install {' '.join(missing)}")
        sys.exit(1)

    # Check API key
    if CONFIG["provider"] == "claude" and not CONFIG["anthropic_api_key"]:
        print("Please set ANTHROPIC_API_KEY (env var or ~/.config/voxkeys/config.json)")
        sys.exit(1)
    if CONFIG["provider"] == "openai" and not CONFIG["openai_api_key"]:
        print("Please set OPENAI_API_KEY (env var or ~/.config/voxkeys/config.json)")
        sys.exit(1)
    if CONFIG["provider"] == "github" and not CONFIG["github_token"]:
        print("Please set GITHUB_TOKEN (env var or ~/.config/voxkeys/config.json)")
        sys.exit(1)

    hotkey_name = str(CONFIG["hotkey"]).replace("Key.", "")
    lang_display = CONFIG["language"] or "auto-detect"
    print(f"""
╔══════════════════════════════════════╗
║  Voxkeys — Voice Dictation          ║
║  Hold {hotkey_name:<6} to speak, release to output ║
║  Ctrl+C to quit                      ║
╚══════════════════════════════════════╝
  Model:    {CONFIG['whisper_model']}
  Language: {lang_display}
  LLM:      {CONFIG['provider']}
  Output:   {CONFIG['output_mode']}
""")

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
