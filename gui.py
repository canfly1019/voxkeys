#!/usr/bin/env python3
"""
Voxkeys GUI — Tkinter floating window
Imports voxkeys core engine directly, no subprocess.
"""

import os
import tkinter as tk
from tkinter import ttk
import threading

import voxkeys
from config import load_config, save_config

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, "assets", "voxkeys.png")

# ─── Colors (Catppuccin Mocha) ───────────────────────────────────────────────

C = {
    "base":     "#1e1e2e",
    "mantle":   "#181825",
    "crust":    "#11111b",
    "surface0": "#313244",
    "surface1": "#45475a",
    "overlay0": "#6c7086",
    "text":     "#cdd6f4",
    "subtext":  "#a6adc8",
    "green":    "#a6e3a1",
    "yellow":   "#f9e2af",
    "red":      "#f38ba8",
    "blue":     "#89b4fa",
    "mauve":    "#cba6f7",
    "lavender": "#b4befe",
}

# ─── ttk Theme ───────────────────────────────────────────────────────────────

def setup_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TCombobox",
                     fieldbackground=C["surface0"],
                     background=C["surface1"],
                     foreground=C["text"],
                     bordercolor=C["surface1"],
                     arrowcolor=C["subtext"],
                     selectbackground=C["surface1"],
                     selectforeground=C["text"])
    style.map("TCombobox",
              fieldbackground=[("readonly", C["surface0"])],
              foreground=[("readonly", C["text"])],
              selectbackground=[("readonly", C["surface0"])],
              selectforeground=[("readonly", C["text"])])

    root.option_add("*TCombobox*Listbox.background", C["surface0"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["surface1"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["text"])

# ─── Main Application ────────────────────────────────────────────────────────

class VoxkeysApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Voxkeys")
        self.root.geometry("300x200")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=C["base"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Window icon for sidebar / taskbar
        try:
            icon = tk.PhotoImage(file=ICON_PATH)
            self.root.iconphoto(True, icon)
        except Exception:
            pass

        # WM_CLASS to match .desktop StartupWMClass
        self.root.wm_attributes("-type", "normal")
        try:
            self.root.tk.call("tk", "appname", "voxkeys")
        except Exception:
            pass

        setup_theme(self.root)

        self.cfg = load_config()
        self.use_ai = self.cfg["provider"] != "none"
        self.showing_settings = False

        self._apply_config()
        voxkeys.set_status_callback(self._on_status)

        # Check system dependencies
        self.missing_deps = voxkeys.check_dependencies()

        self._build_main_page()
        if not self.missing_deps:
            self._start_listener()

    def _apply_config(self):
        """Apply config to voxkeys engine."""
        voxkeys.CONFIG["whisper_model"] = self.cfg["whisper_model"]
        lang = self.cfg["language"]
        voxkeys.CONFIG["language"] = None if lang == "auto" else lang
        voxkeys.CONFIG["provider"] = self.cfg["provider"] if self.use_ai else "none"
        voxkeys.CONFIG["github_token"] = self.cfg["github_token"]
        voxkeys.CONFIG["openai_api_key"] = self.cfg["openai_api_key"]
        voxkeys.CONFIG["anthropic_api_key"] = self.cfg["anthropic_api_key"]

    # ─── Main Page ───────────────────────────────────────────────────────────

    def _build_main_page(self):
        self._clear()

        # Title bar
        header = tk.Frame(self.root, bg=C["base"])
        header.pack(fill="x", padx=16, pady=(14, 0))

        tk.Label(header, text="Voxkeys", font=("sans-serif", 14, "bold"),
                 bg=C["base"], fg=C["text"]).pack(side="left")

        btn_frame = tk.Frame(header, bg=C["base"])
        btn_frame.pack(side="right")

        tk.Button(btn_frame, text="⚙", font=("sans-serif", 13),
                  bg=C["base"], fg=C["overlay0"], bd=0, cursor="hand2",
                  activebackground=C["base"], activeforeground=C["text"],
                  command=self._build_settings_page).pack(side="left", padx=(0, 6))

        tk.Button(btn_frame, text="✕", font=("sans-serif", 13),
                  bg=C["base"], fg=C["overlay0"], bd=0, cursor="hand2",
                  activebackground=C["base"], activeforeground=C["red"],
                  command=self._on_close).pack(side="left")

        # Separator
        tk.Frame(self.root, bg=C["surface0"], height=1).pack(fill="x", padx=16, pady=8)

        # Status area (centered)
        status_frame = tk.Frame(self.root, bg=C["base"])
        status_frame.pack(expand=True)

        self.dot = tk.Canvas(status_frame, width=18, height=18,
                             bg=C["base"], highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 10))

        if self.missing_deps:
            self._set_dot("red")
            self.status_label = tk.Label(
                status_frame,
                text=f"Missing: {', '.join(self.missing_deps)}",
                font=("sans-serif", 11),
                bg=C["base"], fg=C["red"])
            self.status_label.pack(side="left")
            # Install hint
            hint = tk.Label(self.root,
                            text=f"sudo apt install {' '.join(self.missing_deps)}",
                            font=("monospace", 9), bg=C["surface0"], fg=C["subtext"],
                            padx=8, pady=4)
            hint.pack(padx=16, pady=(0, 4))
        else:
            self._set_dot("gray")
            self.status_label = tk.Label(status_frame, text="Hold F9 to speak",
                                         font=("sans-serif", 13),
                                         bg=C["base"], fg=C["text"])
            self.status_label.pack(side="left")

        # AI toggle (bottom)
        ai_frame = tk.Frame(self.root, bg=C["base"])
        ai_frame.pack(fill="x", padx=16, pady=(0, 14))

        self.ai_var = tk.BooleanVar(value=self.use_ai)
        self.ai_check = tk.Checkbutton(
            ai_frame, text="AI Polish", variable=self.ai_var,
            font=("sans-serif", 10), bg=C["base"], fg=C["subtext"],
            selectcolor=C["surface0"], activebackground=C["base"],
            activeforeground=C["text"], cursor="hand2",
            command=self._toggle_ai,
        )
        self.ai_check.pack(side="left")

        provider_text = self.cfg["provider"] if self.use_ai else "off"
        self.provider_label = tk.Label(
            ai_frame, text=f"({provider_text})",
            font=("sans-serif", 9), bg=C["base"], fg=C["overlay0"],
        )
        self.provider_label.pack(side="left", padx=(4, 0))

    def _set_dot(self, color):
        self.dot.delete("all")
        fill = {"gray": C["overlay0"], "green": C["green"], "yellow": C["yellow"], "red": C["red"]}.get(color, C["overlay0"])
        self.dot.create_oval(1, 1, 17, 17, fill=fill, outline="")

    def _toggle_ai(self):
        self.use_ai = self.ai_var.get()
        voxkeys.CONFIG["provider"] = self.cfg["provider"] if self.use_ai else "none"
        provider_text = self.cfg["provider"] if self.use_ai else "off"
        self.provider_label.config(text=f"({provider_text})")

    # ─── Settings Page ───────────────────────────────────────────────────────

    # Display label lookup tables
    PROVIDER_LABELS = {
        "github": "GitHub Models (Free)",
        "openai": "OpenAI",
        "claude": "Claude",
        "none":   "Off (transcription only)",
    }
    PROVIDER_FROM_LABEL = {v: k for k, v in PROVIDER_LABELS.items()}

    LANG_LABELS = {
        "auto":  "Auto Detect",
        "zh":    "中文（繁體）",
        "zh-cn": "中文（简体）",
        "en":    "English",
        "ja":    "日本語",
    }
    LANG_FROM_LABEL = {v: k for k, v in LANG_LABELS.items()}

    def _build_settings_page(self):
        self._clear()
        self._resize(300, 390)
        self.showing_settings = True

        # Title bar
        header = tk.Frame(self.root, bg=C["base"])
        header.pack(fill="x", padx=16, pady=(14, 0))

        tk.Button(header, text="←", font=("sans-serif", 13),
                  bg=C["base"], fg=C["overlay0"], bd=0, cursor="hand2",
                  activebackground=C["base"], activeforeground=C["text"],
                  command=self._back_to_main).pack(side="left")

        tk.Label(header, text="Settings", font=("sans-serif", 14, "bold"),
                 bg=C["base"], fg=C["text"]).pack(side="left", padx=(8, 0))

        # Separator
        tk.Frame(self.root, bg=C["surface0"], height=1).pack(fill="x", padx=16, pady=8)

        # Form area
        form = tk.Frame(self.root, bg=C["base"])
        form.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Provider
        self._form_label(form, "Provider")
        provider_display = self.PROVIDER_LABELS.get(self.cfg["provider"], self.cfg["provider"])
        self.provider_var = tk.StringVar(value=provider_display)
        provider_cb = ttk.Combobox(form, textvariable=self.provider_var,
                                   values=list(self.PROVIDER_LABELS.values()),
                                   state="readonly", width=28)
        provider_cb.pack(fill="x", pady=(0, 12))
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_change)

        # API Key
        self.key_label = tk.Label(form, text=self._key_label_text(),
                                  font=("sans-serif", 9, "bold"), bg=C["base"], fg=C["subtext"],
                                  anchor="w")
        self.key_label.pack(fill="x")
        self.key_var = tk.StringVar(value=self._current_key())
        self.key_entry = tk.Entry(form, textvariable=self.key_var, show="•",
                                  font=("monospace", 10),
                                  bg=C["surface0"], fg=C["text"],
                                  insertbackground=C["text"],
                                  relief="flat", bd=0,
                                  highlightthickness=1,
                                  highlightcolor=C["blue"],
                                  highlightbackground=C["surface1"])
        self.key_entry.pack(fill="x", ipady=4, pady=(2, 12))

        # Whisper Model
        self._form_label(form, "Whisper Model (local)")
        self.model_var = tk.StringVar(value=self.cfg["whisper_model"])
        ttk.Combobox(form, textvariable=self.model_var,
                     values=["tiny", "base", "small", "medium", "large-v3"],
                     state="readonly", width=28).pack(fill="x", pady=(0, 12))

        # Language
        self._form_label(form, "Language")
        lang_display = self.LANG_LABELS.get(self.cfg["language"], self.cfg["language"])
        self.lang_var = tk.StringVar(value=lang_display)
        ttk.Combobox(form, textvariable=self.lang_var,
                     values=list(self.LANG_LABELS.values()),
                     state="readonly", width=28).pack(fill="x", pady=(0, 16))

        # Save button
        save_btn = tk.Button(form, text="Save", font=("sans-serif", 10, "bold"),
                             bg=C["mauve"], fg=C["crust"], bd=0, cursor="hand2",
                             activebackground=C["lavender"], activeforeground=C["crust"],
                             padx=24, pady=8,
                             command=self._save_settings)
        save_btn.pack(anchor="e")

    def _form_label(self, parent, text):
        tk.Label(parent, text=text, font=("sans-serif", 9, "bold"),
                 bg=C["base"], fg=C["subtext"], anchor="w").pack(fill="x", pady=(0, 2))

    def _selected_provider(self):
        """Convert display label back to internal code."""
        if hasattr(self, "provider_var"):
            return self.PROVIDER_FROM_LABEL.get(self.provider_var.get(), self.cfg["provider"])
        return self.cfg["provider"]

    def _key_label_text(self):
        p = self._selected_provider()
        names = {"github": "GitHub Token", "openai": "OpenAI API Key",
                 "claude": "Anthropic API Key", "none": "(not required)"}
        return names.get(p, "API Key")

    def _current_key(self):
        p = self._selected_provider()
        keys = {"github": "github_token", "openai": "openai_api_key",
                "claude": "anthropic_api_key"}
        return self.cfg.get(keys.get(p, ""), "")

    def _on_provider_change(self, event=None):
        self.key_label.config(text=self._key_label_text())
        self.key_var.set(self._current_key())

    def _save_settings(self):
        provider = self._selected_provider()
        lang = self.LANG_FROM_LABEL.get(self.lang_var.get(), self.lang_var.get())
        key_field = {"github": "github_token", "openai": "openai_api_key",
                     "claude": "anthropic_api_key"}.get(provider)

        updates = {
            "provider": provider,
            "whisper_model": self.model_var.get(),
            "language": lang,
        }
        if key_field:
            updates[key_field] = self.key_var.get()

        save_config(updates)
        self.cfg = load_config()
        self.use_ai = self.cfg["provider"] != "none"

        if updates["whisper_model"] != voxkeys.CONFIG.get("whisper_model"):
            voxkeys.whisper_model = None

        self._apply_config()
        self._back_to_main()

    def _back_to_main(self):
        self.showing_settings = False
        self._resize(300, 200)
        self._build_main_page()

    # ─── Status Callback ─────────────────────────────────────────────────────

    def _on_status(self, msg):
        """Handle status updates from the voxkeys engine."""
        def _update():
            if self.showing_settings:
                return
            if msg == "recording":
                self._set_dot("green")
                self.status_label.config(text="Recording...")
            elif msg == "recording_done":
                self._set_dot("yellow")
                self.status_label.config(text="Processing...")
            elif msg == "transcribing":
                self._set_dot("yellow")
                self.status_label.config(text="Transcribing...")
            elif msg == "polishing":
                self._set_dot("yellow")
                self.status_label.config(text="AI polishing...")
            elif msg == "loading_model":
                self._set_dot("yellow")
                self.status_label.config(text="Loading model...")
            elif msg.startswith("output:") or msg == "no_speech" or msg.startswith("polish_failed:"):
                self._set_dot("gray")
                self.status_label.config(text="Hold F9 to speak")
        self.root.after(0, _update)

    # ─── Keyboard Listener ───────────────────────────────────────────────────

    def _start_listener(self):
        from pynput import keyboard as kb
        self.listener = kb.Listener(
            on_press=voxkeys.on_press,
            on_release=voxkeys.on_release,
        )
        self.listener.daemon = True
        self.listener.start()

    # ─── Utilities ───────────────────────────────────────────────────────────

    def _resize(self, w, h):
        """Resize window while preserving position."""
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def _on_close(self):
        if hasattr(self, "listener"):
            self.listener.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = VoxkeysApp()
    app.run()
