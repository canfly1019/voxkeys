#!/usr/bin/env python3
"""
Voxkeys GUI — Tkinter floating window
Imports voxkeys core engine directly, no subprocess.

The main view is a live job list (newest on top) so the user can keep recording
new segments while previous ones are still being transcribed and polished.
Completed rows are clickable to recopy the polished text to the clipboard.
"""

import os
import subprocess
import tkinter as tk
from tkinter import ttk

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

# ─── Job row visuals ─────────────────────────────────────────────────────────

# (icon, color_key, label_text). label_text=None means "show preview of text".
PHASE_VISUALS = {
    "recording":     ("●", "green",    "Recording…"),
    "queued":        ("◐", "subtext",  "Queued…"),
    "loading_model": ("◐", "yellow",   "Loading model…"),
    "transcribing":  ("◐", "yellow",   "Transcribing…"),
    "transcribed":   ("◐", "yellow",   "Processing…"),  # transient: bridges to polishing or done
    "polishing":     ("◐", "yellow",   "Polishing…"),
    "done":          ("✓", "green",    None),
    "polish_failed": ("✓", "yellow",   None),
    "empty":         ("·", "overlay0", "(no speech)"),
    "error":         ("⚠", "red",      None),
}

PREVIEW_MAX = 34
MAX_ROWS = 5
WINDOW_W = 340
WINDOW_MAIN_H = 320
WINDOW_SETTINGS_H = 420

# ─── Main Application ────────────────────────────────────────────────────────

class VoxkeysApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Voxkeys")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_MAIN_H}")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=C["base"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            icon = tk.PhotoImage(file=ICON_PATH)
            self.root.iconphoto(True, icon)
        except Exception:
            pass

        self.root.wm_attributes("-type", "normal")
        try:
            self.root.tk.call("tk", "appname", "voxkeys")
        except Exception:
            pass

        setup_theme(self.root)

        self.cfg = load_config()
        self.use_ai = self.cfg["provider"] != "none"
        self.showing_settings = False

        # Live pipeline state — populated by voxkeys event callback.
        self.jobs = {}        # job_id -> dict(phase, raw_text, polished_text, error)
        self.job_order = []   # oldest first
        self.rows = {}        # job_id -> dict of widgets for in-place updates

        self._apply_config()
        voxkeys.set_event_callback(self._on_event)

        self.missing_deps = voxkeys.check_dependencies()

        self._build_main_page()
        if not self.missing_deps:
            self._start_listener()

    def _apply_config(self):
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

        # Missing-deps banner takes over the body area entirely
        if self.missing_deps:
            body = tk.Frame(self.root, bg=C["base"])
            body.pack(expand=True, fill="both", padx=16)
            tk.Label(body, text=f"Missing: {', '.join(self.missing_deps)}",
                     font=("sans-serif", 11),
                     bg=C["base"], fg=C["red"]).pack(pady=(20, 6))
            tk.Label(body, text=f"sudo apt install {' '.join(self.missing_deps)}",
                     font=("monospace", 9), bg=C["surface0"], fg=C["subtext"],
                     padx=8, pady=4).pack(pady=(0, 4))
            return

        # Job list area
        self.list_frame = tk.Frame(self.root, bg=C["base"])
        self.list_frame.pack(fill="both", expand=True, padx=16)

        # Empty-state placeholder
        self.empty_label = tk.Label(self.list_frame,
                                    text="Hold F9 to speak",
                                    font=("sans-serif", 12),
                                    bg=C["base"], fg=C["subtext"])
        self.empty_label.pack(pady=(28, 0))

        # AI toggle (bottom)
        ai_frame = tk.Frame(self.root, bg=C["base"])
        ai_frame.pack(fill="x", padx=16, pady=(4, 12))

        tk.Frame(ai_frame, bg=C["surface0"], height=1).pack(fill="x", pady=(0, 8))

        toggle_row = tk.Frame(ai_frame, bg=C["base"])
        toggle_row.pack(fill="x")

        self.ai_var = tk.BooleanVar(value=self.use_ai)
        self.ai_check = tk.Checkbutton(
            toggle_row, text="AI Polish", variable=self.ai_var,
            font=("sans-serif", 10), bg=C["base"], fg=C["subtext"],
            selectcolor=C["surface0"], activebackground=C["base"],
            activeforeground=C["text"], cursor="hand2",
            command=self._toggle_ai,
        )
        self.ai_check.pack(side="left")

        provider_text = self.cfg["provider"] if self.use_ai else "off"
        self.provider_label = tk.Label(
            toggle_row, text=f"({provider_text})",
            font=("sans-serif", 9), bg=C["base"], fg=C["overlay0"],
        )
        self.provider_label.pack(side="left", padx=(4, 0))

        self.hint_label = tk.Label(
            toggle_row, text="Hold F9 · click a row to recopy",
            font=("sans-serif", 8),
            bg=C["base"], fg=C["overlay0"],
        )
        self.hint_label.pack(side="right")

        # The list_frame was just rebuilt — re-create row widgets for any jobs
        # we already have in memory (e.g. after returning from settings).
        self.rows = {}
        if self.job_order:
            self._hide_empty_state()
            for jid in self.job_order:
                widgets = self._create_row(jid)
                self.rows[jid] = widgets
                self._update_row(jid, self.jobs[jid])
            # Re-pack so newest is on top.
            for jid in self.job_order:
                self.rows[jid]["row"].pack_forget()
            for jid in reversed(self.job_order):
                self.rows[jid]["row"].pack(fill="x", pady=1)
        else:
            self._ensure_empty_state()

    def _toggle_ai(self):
        self.use_ai = self.ai_var.get()
        voxkeys.CONFIG["provider"] = self.cfg["provider"] if self.use_ai else "none"
        provider_text = self.cfg["provider"] if self.use_ai else "off"
        self.provider_label.config(text=f"({provider_text})")

    # ─── Job list rendering (in-place updates) ───────────────────────────────

    def _ensure_empty_state(self):
        """Show the placeholder when no jobs are present."""
        if hasattr(self, "empty_label") and self.empty_label.winfo_exists():
            return
        self.empty_label = tk.Label(self.list_frame,
                                    text="Hold F9 to speak",
                                    font=("sans-serif", 12),
                                    bg=C["base"], fg=C["subtext"])
        self.empty_label.pack(pady=(28, 0))

    def _hide_empty_state(self):
        if hasattr(self, "empty_label") and self.empty_label.winfo_exists():
            self.empty_label.destroy()

    def _create_row(self, jid):
        """Create the widgets for a job row once. Returns the widgets dict."""
        row = tk.Frame(self.list_frame, bg=C["base"], padx=6, pady=3)
        row.pack(fill="x", pady=1)

        dot = tk.Label(row, text="·", font=("sans-serif", 11, "bold"),
                       bg=C["base"], fg=C["overlay0"], width=2)
        dot.pack(side="left")

        lbl = tk.Label(row, text="", font=("sans-serif", 10),
                       bg=C["base"], fg=C["subtext"],
                       anchor="w", justify="left")
        lbl.pack(side="left", fill="x", expand=True)

        id_lbl = tk.Label(row, text=f"#{jid}", font=("sans-serif", 8),
                          bg=C["base"], fg=C["overlay0"])
        id_lbl.pack(side="right")

        widgets = {"row": row, "dot": dot, "lbl": lbl, "id_lbl": id_lbl,
                   "click_text": None, "label_color": C["subtext"]}

        # Hover effect — bound once. Idempotent; safe even if click_text is None.
        for w in (row, dot, lbl, id_lbl):
            w.bind("<Enter>", lambda _e, ws=widgets: self._row_hover(ws, True))
            w.bind("<Leave>", lambda _e, ws=widgets: self._row_hover(ws, False))
            w.bind("<Button-1>", lambda _e, ws=widgets: self._row_clicked(ws))

        return widgets

    def _update_row(self, jid, job):
        """Update an existing row's visuals to reflect the latest job state."""
        widgets = self.rows.get(jid)
        if widgets is None:
            return
        if not widgets["row"].winfo_exists():
            return

        phase = job["phase"]
        icon, color_key, default_label = PHASE_VISUALS.get(
            phase, ("·", "overlay0", phase))

        if phase in ("done", "polish_failed"):
            text = job["polished_text"] or job["raw_text"] or "(empty)"
            label_text = self._truncate(text, PREVIEW_MAX)
            label_color = C["text"]
            click_text = job["polished_text"] or job["raw_text"]
        elif phase == "error":
            label_text = f"Error: {job.get('error') or 'unknown'}"
            label_color = C["red"]
            click_text = None
        else:
            label_text = default_label or phase
            label_color = C["subtext"]
            click_text = None

        widgets["dot"].config(text=icon, fg=C[color_key])
        widgets["lbl"].config(text=label_text, fg=label_color)
        widgets["label_color"] = label_color
        widgets["click_text"] = click_text

        cursor = "hand2" if click_text else ""
        for w in (widgets["row"], widgets["dot"], widgets["lbl"], widgets["id_lbl"]):
            w.config(cursor=cursor)

    def _row_clicked(self, widgets):
        text = widgets.get("click_text")
        if not text:
            return
        self._copy_to_clipboard(text, widgets["lbl"], widgets["label_color"])

    @staticmethod
    def _truncate(text, n):
        text = text.strip().replace("\n", " ")
        return text if len(text) <= n else text[: n - 1] + "…"

    @staticmethod
    def _row_hover(widgets, hovering):
        if not widgets["row"].winfo_exists():
            return
        # Only highlight rows that are clickable.
        if not widgets.get("click_text"):
            return
        bg = C["surface0"] if hovering else C["base"]
        for key in ("row", "dot", "lbl", "id_lbl"):
            try:
                widgets[key].config(bg=bg)
            except tk.TclError:
                pass

    def _copy_to_clipboard(self, text, label_widget, original_color):
        if not text:
            return
        try:
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
            )
            p.communicate(text.encode("utf-8"))
        except Exception:
            return

        original_text = label_widget.cget("text")
        label_widget.config(text="Copied ✓", fg=C["green"])
        self.root.after(
            900,
            lambda: label_widget.config(text=original_text, fg=original_color),
        )

    # ─── Event Callback ──────────────────────────────────────────────────────

    def _on_event(self, e):
        """Called from worker / recorder threads. Marshal onto the Tk thread."""
        def _apply():
            try:
                self._apply_event(e)
            except tk.TclError:
                # Widget was destroyed mid-update; safe to ignore.
                pass

        try:
            self.root.after(0, _apply)
        except Exception:
            pass

    def _apply_event(self, e):
        if self.showing_settings or not hasattr(self, "list_frame"):
            return
        if not self.list_frame.winfo_exists():
            return

        jid = e.get("job_id")
        phase = e.get("phase")
        if jid is None:
            return

        job = self.jobs.get(jid)
        is_new = job is None
        if is_new:
            job = {"phase": phase, "raw_text": "", "polished_text": "", "error": ""}
            self.jobs[jid] = job
            self.job_order.append(jid)

        job["phase"] = phase
        if "raw_text" in e:
            job["raw_text"] = e["raw_text"]
        if "polished_text" in e:
            job["polished_text"] = e["polished_text"]
        if "error" in e:
            job["error"] = e["error"]

        if is_new:
            self._hide_empty_state()
            widgets = self._create_row(jid)
            self.rows[jid] = widgets
            # Newest row goes to the top (other rows are pushed down).
            widgets["row"].pack_configure(before=self._first_visible_row(exclude=jid))

        self._update_row(jid, job)

        # Cap history to MAX_ROWS — drop the oldest row's widgets cleanly.
        while len(self.job_order) > MAX_ROWS:
            drop = self.job_order.pop(0)
            self.jobs.pop(drop, None)
            old_widgets = self.rows.pop(drop, None)
            if old_widgets and old_widgets["row"].winfo_exists():
                old_widgets["row"].destroy()

        if not self.job_order:
            self._ensure_empty_state()

    def _first_visible_row(self, exclude=None):
        """Find the topmost existing row widget, used to anchor new rows above it."""
        for jid in reversed(self.job_order):
            if jid == exclude:
                continue
            w = self.rows.get(jid)
            if w and w["row"].winfo_exists():
                return w["row"]
        return None

    # ─── Settings Page ───────────────────────────────────────────────────────

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
        self._resize(WINDOW_W, WINDOW_SETTINGS_H)
        self.showing_settings = True

        header = tk.Frame(self.root, bg=C["base"])
        header.pack(fill="x", padx=16, pady=(14, 0))

        tk.Button(header, text="←", font=("sans-serif", 13),
                  bg=C["base"], fg=C["overlay0"], bd=0, cursor="hand2",
                  activebackground=C["base"], activeforeground=C["text"],
                  command=self._back_to_main).pack(side="left")

        tk.Label(header, text="Settings", font=("sans-serif", 14, "bold"),
                 bg=C["base"], fg=C["text"]).pack(side="left", padx=(8, 0))

        tk.Frame(self.root, bg=C["surface0"], height=1).pack(fill="x", padx=16, pady=8)

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
        self._resize(WINDOW_W, WINDOW_MAIN_H)
        self._build_main_page()

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
