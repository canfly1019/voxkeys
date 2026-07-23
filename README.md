# Voxkeys

Linux voice dictation tool. Hold a hotkey to speak, auto-transcribe, AI polish, paste to cursor.

## Features

- **Hold to speak**: Hold F9 to record, release to process
- **Edit selected text**: If text is selected, the record key uses your speech as an edit instruction
- **Whisper transcription**: Offline speech recognition (faster-whisper)
- **AI text polish**: Auto-fix typos, add punctuation, remove filler words
- **Multi-provider support**: GitHub Models (free) / OpenAI / Claude
- **Auto-paste**: Result pasted directly to the current cursor position
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

A floating window shows the current status. Use the settings page to configure provider, API key, model, etc.

### CLI Mode

```bash
# Default (reads ~/.config/voxkeys/config.json)
python3 voxkeys.py

# With arguments
python3 voxkeys.py --provider github --model small --lang zh

# No AI polish
python3 voxkeys.py --provider none
```

### Arguments

| Argument | Options | Description |
|----------|---------|-------------|
| `--model` | tiny / base / small / medium / large-v3 | Whisper model size |
| `--lang` | zh / zh-cn / en / ja / auto | Recognition language |
| `--provider` | github / openai / claude / none | LLM provider |
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
  "provider": "github",
  "github_token": "<your-token>",
  "whisper_model": "small",
  "record_hotkey": "f9",
  "language": "zh"
}
```

API key priority: config.json → environment variables (`GITHUB_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)

Using environment variables for API keys is recommended to avoid storing them in plaintext.

## Security

- Config file permissions are automatically set to `600` (owner read/write only)
- `config.json` is included in `.gitignore` to prevent accidental commits
- To use environment variables instead of config file, add keys to `~/.bashrc` or `~/.zshrc`:
  ```bash
  export GITHUB_TOKEN="your-token-here"
  ```

## Notes

- Linux only (X11). Global hotkeys may not work under Wayland
- Selected-text edit mode is disabled in terminal/code windows so Voxkeys never sends Ctrl+C to Codex or shells
- Whisper model is downloaded automatically on first run
- GitHub Models is a free tier with sufficient daily quota for normal use

## License

MIT
