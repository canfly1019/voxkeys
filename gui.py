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

# Phases that should drive a spinning indicator on the row dot.
SPINNING_PHASES = {"queued", "loading_model", "transcribing", "transcribed", "polishing"}
SPIN_FRAMES = "◐◓◑◒"
SPIN_PERIOD_MS = 180
PULSE_PERIOD_MS = 520

PREVIEW_MAX = 30  # visual cells (CJK counts as 2)
MAX_ROWS = 3
WINDOW_W = 340
WINDOW_MAIN_H = 250
WINDOW_SETTINGS_H = 540
TOOLTIP_DELAY_MS = 450

# Short codes for the lang-flow badge on the main page.
LANG_SHORT = {
    "auto":  "Auto",
    None:    "Auto",
    "":      "Auto",
    "zh":    "中",
    "zh-cn": "简",
    "en":    "EN",
    "ja":    "JP",
}

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
        self._tooltip = None  # active tooltip Toplevel, if any

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
        out_lang = self.cfg.get("output_language", "")
        voxkeys.CONFIG["output_language"] = "" if out_lang in ("", "same") else out_lang
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

        # AI toggle (bottom) — single clean row, separator above for hierarchy
        ai_frame = tk.Frame(self.root, bg=C["base"])
        ai_frame.pack(fill="x", padx=16, pady=(6, 14))

        tk.Frame(ai_frame, bg=C["surface0"], height=1).pack(fill="x", pady=(0, 10))

        toggle_row = tk.Frame(ai_frame, bg=C["base"])
        toggle_row.pack(fill="x")

        self.ai_var = tk.BooleanVar(value=self.use_ai)
        self.ai_check = tk.Checkbutton(
            toggle_row, text="AI Polish", variable=self.ai_var,
            font=("sans-serif", 10), bg=C["base"], fg=C["text"],
            selectcolor=C["surface0"], activebackground=C["base"],
            activeforeground=C["text"], cursor="hand2",
            command=self._toggle_ai,
        )
        self.ai_check.pack(side="left")

        provider_text = self.cfg["provider"] if self.use_ai else "off"
        self.provider_label = tk.Label(
            toggle_row, text=provider_text,
            font=("sans-serif", 9), bg=C["surface0"], fg=C["subtext"],
            padx=8, pady=2,
        )
        self.provider_label.pack(side="left", padx=(8, 0))

        # Lang-flow chip on the right — shows input→output mode at a glance.
        self.lang_chip = tk.Label(
            toggle_row, text=self._lang_chip_text(),
            font=("sans-serif", 9, "bold"),
            bg=C["surface0"], fg=C["lavender"],
            padx=8, pady=2,
        )
        self.lang_chip.pack(side="right")

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
        self.provider_label.config(text=provider_text)
        if hasattr(self, "lang_chip") and self.lang_chip.winfo_exists():
            self.lang_chip.config(text=self._lang_chip_text())

    def _lang_chip_text(self):
        """Compact 'IN → OUT' label. Shows only IN when output is same as input."""
        in_code = self.cfg.get("language", "auto")
        out_code = self.cfg.get("output_language", "") or ""
        in_short = LANG_SHORT.get(in_code, in_code)
        if not out_code or out_code == in_code or not self.use_ai:
            return in_short
        out_short = LANG_SHORT.get(out_code, out_code)
        return f"{in_short} → {out_short}"

    # ─── Job list rendering (in-place updates) ───────────────────────────────

    def _ensure_empty_state(self):
        """Show the placeholder when no jobs are present."""
        if hasattr(self, "empty_frame") and self.empty_frame.winfo_exists():
            return
        self.empty_frame = tk.Frame(self.list_frame, bg=C["base"])
        self.empty_frame.pack(pady=(20, 0))
        tk.Label(self.empty_frame,
                 text="Hold  F9  to speak",
                 font=("sans-serif", 13),
                 bg=C["base"], fg=C["text"]).pack()
        tk.Label(self.empty_frame,
                 text="click any completed row to recopy",
                 font=("sans-serif", 9),
                 bg=C["base"], fg=C["overlay0"]).pack(pady=(4, 0))

    def _hide_empty_state(self):
        if hasattr(self, "empty_frame") and self.empty_frame.winfo_exists():
            self.empty_frame.destroy()

    def _create_row(self, jid):
        """Create the widgets for a job row once. Returns the widgets dict."""
        row = tk.Frame(self.list_frame, bg=C["base"], padx=10, pady=5)
        row.pack(fill="x", pady=2)

        dot = tk.Label(row, text="·", font=("sans-serif", 12, "bold"),
                       bg=C["base"], fg=C["overlay0"], width=2)
        dot.pack(side="left")

        lbl = tk.Label(row, text="", font=("sans-serif", 10),
                       bg=C["base"], fg=C["subtext"],
                       anchor="w", justify="left")
        lbl.pack(side="left", fill="x", expand=True, padx=(2, 0))

        id_lbl = tk.Label(row, text=f"#{jid}", font=("sans-serif", 8),
                          bg=C["base"], fg=C["overlay0"])
        id_lbl.pack(side="right")

        widgets = {
            "row": row, "dot": dot, "lbl": lbl, "id_lbl": id_lbl,
            "click_text": None, "label_color": C["subtext"],
            "anim_id": None, "anim_kind": None,
            "tooltip_after": None, "full_text": "",
        }

        # Hover effect — bound once. Idempotent; safe even if click_text is None.
        for w in (row, dot, lbl, id_lbl):
            w.bind("<Enter>", lambda _e, ws=widgets: self._row_enter(ws))
            w.bind("<Leave>", lambda _e, ws=widgets: self._row_leave(ws))
            w.bind("<Motion>", lambda e, ws=widgets: self._row_motion(e, ws))
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
            full_text = click_text or ""
        elif phase == "error":
            label_text = f"Error: {job.get('error') or 'unknown'}"
            label_color = C["red"]
            click_text = None
            full_text = ""
        else:
            label_text = default_label or phase
            label_color = C["subtext"]
            click_text = None
            full_text = ""

        widgets["dot"].config(text=icon, fg=C[color_key])
        widgets["lbl"].config(text=label_text, fg=label_color)
        widgets["label_color"] = label_color
        widgets["click_text"] = click_text
        widgets["full_text"] = full_text

        cursor = "hand2" if click_text else ""
        for w in (widgets["row"], widgets["dot"], widgets["lbl"], widgets["id_lbl"]):
            w.config(cursor=cursor)

        # Drive animations based on phase.
        self._stop_animation(widgets)
        if phase == "recording":
            self._start_pulse(widgets, C["green"])
        elif phase in SPINNING_PHASES:
            self._start_spin(widgets, C[color_key])

    def _row_clicked(self, widgets):
        text = widgets.get("click_text")
        if not text:
            return
        self._copy_to_clipboard(text, widgets["lbl"], widgets["label_color"])

    # ─── Row animations ──────────────────────────────────────────────────────

    def _stop_animation(self, widgets):
        aid = widgets.get("anim_id")
        if aid is not None:
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        widgets["anim_id"] = None
        widgets["anim_kind"] = None

    def _start_pulse(self, widgets, base_color):
        widgets["anim_kind"] = "pulse"
        state = {"on": True}

        def tick():
            if widgets.get("anim_kind") != "pulse":
                return
            dot = widgets["dot"]
            if not dot.winfo_exists():
                return
            try:
                state["on"] = not state["on"]
                dot.config(fg=base_color if state["on"] else C["surface1"])
            except tk.TclError:
                return
            widgets["anim_id"] = self.root.after(PULSE_PERIOD_MS, tick)

        tick()

    def _start_spin(self, widgets, color):
        widgets["anim_kind"] = "spin"
        idx = [0]

        def tick():
            if widgets.get("anim_kind") != "spin":
                return
            dot = widgets["dot"]
            if not dot.winfo_exists():
                return
            try:
                dot.config(text=SPIN_FRAMES[idx[0] % len(SPIN_FRAMES)], fg=color)
            except tk.TclError:
                return
            idx[0] += 1
            widgets["anim_id"] = self.root.after(SPIN_PERIOD_MS, tick)

        tick()

    # ─── Hover tooltip ───────────────────────────────────────────────────────

    def _row_enter(self, widgets):
        self._row_hover(widgets, True)
        # Schedule tooltip if the row has expandable content.
        full = widgets.get("full_text") or ""
        if not full or len(full) <= PREVIEW_MAX:
            return
        self._cancel_tooltip(widgets)
        widgets["tooltip_after"] = self.root.after(
            TOOLTIP_DELAY_MS,
            lambda: self._show_tooltip(widgets),
        )

    def _row_leave(self, widgets):
        self._row_hover(widgets, False)
        self._cancel_tooltip(widgets)
        self._hide_tooltip()

    def _row_motion(self, event, widgets):
        # Reposition the tooltip if it's already visible.
        if self._tooltip is not None:
            self._position_tooltip(event)

    def _cancel_tooltip(self, widgets):
        aid = widgets.get("tooltip_after")
        if aid is not None:
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
            widgets["tooltip_after"] = None

    def _show_tooltip(self, widgets):
        widgets["tooltip_after"] = None
        text = widgets.get("full_text") or ""
        if not text:
            return
        if not widgets["row"].winfo_exists():
            return

        self._hide_tooltip()
        tip = tk.Toplevel(self.root)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        try:
            tip.attributes("-type", "tooltip")
        except Exception:
            pass

        frame = tk.Frame(tip, bg=C["surface1"],
                         highlightthickness=1,
                         highlightbackground=C["overlay0"])
        frame.pack()
        tk.Label(frame, text=text,
                 font=("sans-serif", 9),
                 bg=C["surface1"], fg=C["text"],
                 padx=10, pady=6,
                 wraplength=300, justify="left").pack()

        self._tooltip = tip

        # Position below the row by default.
        row = widgets["row"]
        x = row.winfo_rootx() + 8
        y = row.winfo_rooty() + row.winfo_height() + 4
        tip.wm_geometry(f"+{x}+{y}")

    def _hide_tooltip(self):
        if self._tooltip is not None:
            try:
                self._tooltip.destroy()
            except Exception:
                pass
            self._tooltip = None

    def _position_tooltip(self, event):
        if self._tooltip is None:
            return
        try:
            x = event.x_root + 12
            y = event.y_root + 18
            self._tooltip.wm_geometry(f"+{x}+{y}")
        except Exception:
            pass

    @staticmethod
    def _truncate(text, n):
        """Truncate to n visual cells (CJK chars count as 2)."""
        text = text.strip().replace("\n", " ")
        out = []
        width = 0
        for ch in text:
            w = 2 if ord(ch) > 0x2E7F else 1
            if width + w > n:
                return "".join(out) + "…"
            out.append(ch)
            width += w
        return "".join(out)

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
            if old_widgets:
                self._stop_animation(old_widgets)
                self._cancel_tooltip(old_widgets)
                if old_widgets["row"].winfo_exists():
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

    OUTPUT_LANG_LABELS = {
        "":      "Same as input",
        "zh":    "中文（繁體）",
        "zh-cn": "中文（简体）",
        "en":    "English",
        "ja":    "日本語",
    }
    OUTPUT_LANG_FROM_LABEL = {v: k for k, v in OUTPUT_LANG_LABELS.items()}

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

        # ─── AI section ─────────────────────────────────────────────────────
        self._section_header(form, "AI Polish / Translate")

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

        # ─── Speech section ─────────────────────────────────────────────────
        self._section_header(form, "Speech Recognition", top_pad=4)

        # Whisper Model
        self._form_label(form, "Whisper Model (local)")
        self.model_var = tk.StringVar(value=self.cfg["whisper_model"])
        ttk.Combobox(form, textvariable=self.model_var,
                     values=["tiny", "base", "small", "medium", "large-v3"],
                     state="readonly", width=28).pack(fill="x", pady=(0, 12))

        # ─── Language section ───────────────────────────────────────────────
        self._section_header(form, "Languages", top_pad=4)

        # Input language (what Whisper expects)
        self._form_label(form, "Input Language")
        lang_display = self.LANG_LABELS.get(self.cfg["language"], self.cfg["language"])
        self.lang_var = tk.StringVar(value=lang_display)
        ttk.Combobox(form, textvariable=self.lang_var,
                     values=list(self.LANG_LABELS.values()),
                     state="readonly", width=28).pack(fill="x", pady=(0, 12))

        # Output language (translate target; "Same as input" = polish only)
        self._form_label(form, "Output Language")
        out_lang_key = self.cfg.get("output_language", "") or ""
        out_lang_display = self.OUTPUT_LANG_LABELS.get(out_lang_key, "Same as input")
        self.output_lang_var = tk.StringVar(value=out_lang_display)
        ttk.Combobox(form, textvariable=self.output_lang_var,
                     values=list(self.OUTPUT_LANG_LABELS.values()),
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

    def _section_header(self, parent, text, top_pad=0):
        """Subtle uppercase group header — gives the settings page rhythm."""
        wrap = tk.Frame(parent, bg=C["base"])
        wrap.pack(fill="x", pady=(top_pad, 6))
        tk.Label(wrap, text=text.upper(),
                 font=("sans-serif", 8, "bold"),
                 bg=C["base"], fg=C["mauve"], anchor="w").pack(side="left")
        tk.Frame(wrap, bg=C["surface0"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=(8, 0))

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

        out_lang = self.OUTPUT_LANG_FROM_LABEL.get(
            self.output_lang_var.get(), ""
        )

        updates = {
            "provider": provider,
            "whisper_model": self.model_var.get(),
            "language": lang,
            "output_language": out_lang,
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
