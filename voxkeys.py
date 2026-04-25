#!/usr/bin/env python3
"""
Voxkeys — Core engine + CLI entry point
Hold hotkey to record → Whisper transcription → LLM polish → paste to cursor

Pipeline architecture:
- Press F9 → Recorder thread starts capturing audio (per-press PyAudio instance).
- Release F9 → Job is enqueued; user can immediately press F9 again to record the
  next segment while the worker is still transcribing/polishing the previous one.
- A single worker thread drains the queue (FIFO) so paste-back order matches the
  order segments were spoken.
"""

import os
import sys
import time
import wave
import queue
import tempfile
import subprocess
import threading
import shutil
import argparse
import itertools
from dataclasses import dataclass, field
from typing import Optional, Callable, List

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

# ─── Job & Events ────────────────────────────────────────────────────────────

# Phases:
#   recording      — audio capture in progress
#   queued         — released, waiting for worker
#   loading_model  — first job triggers Whisper model load
#   transcribing   — Whisper running
#   transcribed    — raw text ready (transient)
#   polishing      — LLM polish in progress
#   done           — text pasted; row is clickable to recopy
#   empty          — recording was empty / no speech detected
#   polish_failed  — LLM call failed; raw text was pasted instead
#   error          — unrecoverable error in pipeline


@dataclass
class Job:
    id: int
    frames: List[bytes] = field(default_factory=list)
    language: Optional[str] = None
    provider: str = "github"
    raw_text: str = ""
    polished_text: str = ""
    phase: str = "recording"
    error: str = ""


_job_counter = itertools.count(1)
_event_callback: Optional[Callable] = None
_status_callback: Optional[Callable] = None


def set_event_callback(fn):
    """Register a structured-event callback. fn receives a dict per phase change."""
    global _event_callback
    _event_callback = fn


def set_status_callback(fn):
    """Legacy single-line callback. Prefer set_event_callback for richer events."""
    global _status_callback
    _status_callback = fn


def _emit(job: Optional[Job], phase: str, **extra):
    """Update a job's phase and notify subscribers."""
    if job is not None:
        job.phase = phase

    if _event_callback:
        payload = {"job_id": job.id if job else None, "phase": phase}
        if job is not None:
            payload.update({
                "raw_text": job.raw_text,
                "polished_text": job.polished_text,
                "error": job.error,
            })
        payload.update(extra)
        try:
            _event_callback(payload)
        except Exception:
            pass

    if _status_callback:
        legacy = _legacy_status_for(job, phase, extra)
        if legacy is not None:
            try:
                _status_callback(legacy)
            except Exception:
                pass

    if not _event_callback and not _status_callback:
        # CLI fallback — emit a compact line so users can see pipeline progress.
        prefix = f"[#{job.id}] " if job else ""
        if phase == "transcribed":
            print(f"{prefix}transcribed: {job.raw_text}")
        elif phase == "done":
            print(f"{prefix}done: {job.polished_text}")
        elif phase == "error":
            print(f"{prefix}error: {job.error}")
        else:
            print(f"{prefix}{phase}")


def _legacy_status_for(job, phase, extra):
    """Map a structured event to the legacy status_callback strings."""
    if phase == "recording":
        return "recording"
    if phase == "queued":
        return "recording_done"
    if phase == "loading_model":
        return "loading_model"
    if phase == "transcribing":
        return "transcribing"
    if phase == "transcribed" and job:
        return f"transcribed:{job.raw_text}"
    if phase == "polishing":
        return "polishing"
    if phase == "done" and job:
        return f"output:{job.polished_text}"
    if phase == "empty":
        return "no_speech"
    if phase == "polish_failed" and job:
        return f"polish_failed:{job.error}"
    if phase == "error" and job:
        return f"error:{job.error}"
    return None


# ─── Recorder ────────────────────────────────────────────────────────────────


class Recorder:
    """One Recorder per F9 press. Captures into its own job.frames buffer."""

    def __init__(self, job: Job):
        self.job = job
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self):
        p = pyaudio.PyAudio()
        stream = None
        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=CONFIG["channels"],
                rate=CONFIG["sample_rate"],
                input=True,
                frames_per_buffer=1024,
            )
        except Exception as e:
            self.job.error = type(e).__name__
            _emit(self.job, "error")
            p.terminate()
            return

        try:
            while not self._stop.is_set():
                try:
                    data = stream.read(1024, exception_on_overflow=False)
                except Exception:
                    break
                self.job.frames.append(data)
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            p.terminate()


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

# Known Whisper hallucination phrases (Chinese subtitle watermarks, etc.)
HALLUCINATION_PATTERNS = [
    "字幕by索兰娅",
    "字幕by索蘭婭",
    "索兰娅",
    "索蘭婭",
    "字幕提供",
    "字幕制作",
    "字幕製作",
    "请不吝点赞",
    "請不吝點贊",
    "订阅我的频道",
    "訂閱我的頻道",
    "感谢观看",
    "感謝觀看",
    "谢谢观看",
    "謝謝觀看",
    "欢迎订阅",
    "歡迎訂閱",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "like and subscribe",
]

NO_SPEECH_PROB_THRESHOLD = 0.6


def _is_hallucination(text):
    normalized = text.strip().lower().replace(" ", "")
    for pattern in HALLUCINATION_PATTERNS:
        if pattern.replace(" ", "").lower() in normalized:
            return True
    return False


# Single shared model instance — loaded lazily, used only by the worker thread
# (faster-whisper's WhisperModel is not safe under concurrent transcribe calls).
whisper_model = None


def _transcribe_job(job: Job, wav_path: str) -> str:
    global whisper_model

    if whisper_model is None:
        _emit(job, "loading_model")
        whisper_model = WhisperModel(
            CONFIG["whisper_model"],
            device="cpu",
            compute_type="int8",
        )

    _emit(job, "transcribing")
    whisper_lang = job.language
    if whisper_lang == "zh-cn":
        whisper_lang = "zh"
    segments, _info = whisper_model.transcribe(
        wav_path,
        language=whisper_lang,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )

    filtered = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if seg.no_speech_prob > NO_SPEECH_PROB_THRESHOLD:
            continue
        if _is_hallucination(text):
            continue
        filtered.append(text)

    return " ".join(filtered)


# ─── LLM Polish ──────────────────────────────────────────────────────────────

def polish_with_claude(text, prompt):
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


def _polish_job(job: Job, text: str) -> str:
    if not text.strip() or job.provider == "none":
        return text
    _emit(job, "polishing")
    prompt = build_system_prompt(job.language)
    try:
        if job.provider == "claude":
            return polish_with_claude(text, prompt)
        if job.provider == "openai":
            return polish_with_openai(text, prompt)
        if job.provider == "github":
            return polish_with_github(text, prompt)
    except Exception as e:
        job.error = type(e).__name__
        _emit(job, "polish_failed")
    return text


# ─── Output to Cursor ────────────────────────────────────────────────────────

def output_text(text):
    """Paste text to the currently focused input field."""
    if not text:
        return

    if CONFIG["output_mode"] == "clipboard":
        process = subprocess.Popen(
            ["xclip", "-selection", "clipboard"],
            stdin=subprocess.PIPE,
        )
        process.communicate(text.encode("utf-8"))
        time.sleep(0.3)

        is_terminal = False
        try:
            wid = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True, text=True,
            ).stdout.strip()
            result = subprocess.run(
                ["xprop", "-id", wid, "WM_CLASS"],
                capture_output=True, text=True,
            )
            wm_class = result.stdout.lower()
            title_result = subprocess.run(
                ["xdotool", "getwindowname", wid],
                capture_output=True, text=True,
            )
            window_title = title_result.stdout.lower()
            terminal_names = (
                "gnome-terminal", "xfce4-terminal", "konsole",
                "xterm", "alacritty", "kitty", "terminator",
                "tilix", "lxterminal", "mate-terminal",
                "agent-deck", "agent_deck",
            )
            is_terminal = (
                any(t in wm_class for t in terminal_names)
                or any(t in window_title for t in terminal_names)
            )
        except Exception:
            pass

        if is_terminal:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"])
        else:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
    else:
        ctrl = keyboard.Controller()
        ctrl.type(text)


# ─── Worker Thread ───────────────────────────────────────────────────────────

_job_queue: "queue.Queue[Job]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, daemon=True)
        t.start()
        _worker_started = True


def _worker_loop():
    while True:
        job = _job_queue.get()
        try:
            _process_job(job)
        except Exception as e:
            job.error = type(e).__name__
            _emit(job, "error")
        finally:
            _job_queue.task_done()


def _process_job(job: Job):
    if not job.frames:
        _emit(job, "empty")
        return
    wav_path = save_audio_to_wav(job.frames)
    try:
        text = _transcribe_job(job, wav_path)
        job.raw_text = text
        if not text.strip():
            _emit(job, "empty")
            return
        _emit(job, "transcribed")
        polished = _polish_job(job, text)
        job.polished_text = polished
        output_text(polished)
        # If polish raised, _polish_job already emitted "polish_failed" — keep
        # that phase so the GUI shows the row as a fallback (raw text pasted),
        # not a clean success.
        if job.phase != "polish_failed":
            _emit(job, "done")
    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass


# ─── Hotkey Logic ────────────────────────────────────────────────────────────

_active_recorder: Optional[Recorder] = None
_recorder_lock = threading.Lock()


def on_press(key):
    """F9 down — start a new recorder for this segment."""
    global _active_recorder
    if key != CONFIG["hotkey"]:
        return
    with _recorder_lock:
        if _active_recorder is not None:
            return
        job = Job(
            id=next(_job_counter),
            language=CONFIG.get("language"),
            provider=CONFIG.get("provider", CONFIG.get("llm_provider", "github")),
        )
        _active_recorder = Recorder(job)
        _ensure_worker()
        _emit(job, "recording")
        _active_recorder.start()


def on_release(key):
    """F9 up — close out this segment's recorder and enqueue the job."""
    global _active_recorder
    if key != CONFIG["hotkey"]:
        return
    with _recorder_lock:
        recorder = _active_recorder
        _active_recorder = None
    if recorder is None:
        return
    recorder.stop()
    job = recorder.job
    if not job.frames:
        _emit(job, "empty")
        return
    _emit(job, "queued")
    _job_queue.put(job)


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

    CONFIG["whisper_model"] = args.model
    CONFIG["language"] = args.lang if args.lang != "auto" else None
    CONFIG["provider"] = args.provider
    CONFIG["output_mode"] = args.output

    missing = check_dependencies()
    if missing:
        print(f"Missing system tools: {', '.join(missing)}")
        print(f"Install with: sudo apt install {' '.join(missing)}")
        sys.exit(1)

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
