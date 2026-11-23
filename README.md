# Voxkeys

Linux voice dictation tool. Hold a hotkey to speak, auto-transcribe, paste to cursor. AI polish is optional and off by default.

## Features

- **Hold to speak**: Hold F9 to record, release to process
- **Edit selected text**: If text is selected, the record key uses your speech as an edit instruction
- **Flexible transcription**: Local faster-whisper, Groq, or GPUStack ASR
- **Optional AI text polish** (off by default): Auto-fix typos, add punctuation, remove filler words. Turn it on with the **AI Polish** toggle or `"provider"` in the config
- **Multi-provider support**: GPUStack (Qwen) / OpenAI / Claude
- **Auto-paste**: Result pasted into the window you were in when you pressed the hotkey (focus is restored if it drifted during processing); previous clipboard contents are restored after paste
+- **Submit after paste** (on by default): Presses Enter after pasting when you are still in the window where you started recording; if you switched away, the text is pasted but not sent. Never applies to edit-by-voice. Toggle it with **貼上後送出** in the panel or `"auto_submit"` in the config
- **GUI mode**: Tkinter floating window with real-time status
- **CLI mode**: Terminal-based, for advanced users

## Installation

### System Dependencies

```bash
# Ubuntu / Debian
sudo apt install -y xclip xdotool portaudio19-dev python3-dev python3-pip python3-tk

# Fedora
sudo dnf install xclip xdotool portaudio-devel python3-devel python3-tkinter
```

### Python Packages

```bash
pip install -r requirements.txt
```

## Usage

### GUI Mode (Recommended)

```bash
python3 gui.py
```

A small floating capsule stays on top of other windows and shows the current status (idle, recording with a timer, transcribing with a `+N` queue badge, then the pasted text for 2 seconds). Drag it anywhere and drag its right edge to make it wider or narrower; position and width are remembered. Only one copy runs at a time: launching again opens the running panel instead of adding a second F9 listener. Click it to open or close the full panel, right-click for a menu. The "Capsule" checkbox in the panel shows or hides it; while it is hidden the panel stays open, so Voxkeys never disappears entirely. Use the settings page to configure provider, API key, model, etc.

### CLI Mode

```bash
# Default (reads ~/.config/voxkeys/config.json)
python3 voxkeys.py

# With arguments
python3 voxkeys.py --provider gpustack --model small --lang zh

# No AI polish
python3 voxkeys.py --provider none
```

### Arguments

| Argument | Options | Description |
|----------|---------|-------------|
| `--model` | tiny / base / small / medium / large-v3 | Whisper model size |
| `--lang` | zh / zh-cn / en / ja / auto | Recognition language |
| `--provider` | gpustack / openai / claude / none | LLM provider |
| `--output` | clipboard / type | Output method |
| `--hotkey` | ctrl_r / alt_r / f8 / f9 / f10 / f12 | Hold-to-record key |

### Language Support

| Code | Language | Transcription | AI Polish Output |
|------|----------|---------------|------------------|
| `zh` | 中文（繁體） | Whisper `zh` | Traditional Chinese |
| `zh-cn` | 中文（简体） | Whisper `zh` | Simplified Chinese |
| `en` | English | Whisper `en` | English |
| `ja` | 日本語 | Whisper `ja` | Japanese |
| `auto` | Auto Detect | Whisper auto | Matches input language |

Transcription (Whisper) runs locally and does not distinguish between Traditional and Simplified Chinese — both use Whisper's `zh` model. The Traditional/Simplified distinction is handled by the AI polish step, which uses a language-specific prompt to produce the correct variant.

## Configuration

Config file location: `~/.config/voxkeys/config.json`

Can be modified via the GUI settings page, or edited manually:

```json
{
  "provider": "none",
  "gpustack_polish_model": "qwen3.8-27b-fp8",
  "whisper_model": "small",
  "record_hotkey": "f9",
  "language": "zh"
}
```

API key priority: config.json → environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `GPUSTACK_API_KEY`).

GPUStack supplies both OpenAI-compatible endpoints: `/audio/transcriptions` for
speech recognition and `/chat/completions` for polishing. The shared
`GPUSTACK_BASE_URL` includes the API prefix (typically `/v1`); `GPUSTACK_API_KEY`
authenticates both. Speech recognition and polishing can be selected independently.

Polishing is off by default (`"provider": "none"`). To use it, turn on **AI Polish**
(this selects GPUStack) or choose **GPUStack (Qwen)** under AI Polish. The Qwen model comes from
`gpustack_polish_model`, then `GPUSTACK_MODEL`, with `qwen3.8-27b-fp8` as the default.
Polishing disables Qwen thinking mode and keeps the existing timeout and retry
limit. The speech model remains independently configured as `breeze-asr-25`.

Keep keys in the environment rather than in `config.json`. A key that came from
the environment is never written back to `config.json`, so saving from the
settings dialog cannot copy it onto disk.

## Security

- Config file permissions are automatically set to `600` (owner read/write only)
- `config.json` is included in `.gitignore` to prevent accidental commits
- Keep API keys in a protected environment file loaded by the launcher, not in
  source code. Reuse an existing GPUStack credential source rather than copying
  its key into the application configuration.

## Notes

- Linux only (X11). Global hotkeys may not work under Wayland
- Selected-text edit mode is disabled in terminal/code windows so Voxkeys never sends Ctrl+C to Codex or shells
- Whisper model is downloaded automatically on first run
- GitHub Models has been retired and is no longer a supported polishing provider.
  Existing installations must select an available provider in Settings.

## License

MIT
