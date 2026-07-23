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

# ─── Colors ─────────────────────────────────────────────────────────────────

C = {
    "base":     "#17131f",
    "mantle":   "#110e18",
    "crust":    "#0b0910",
    "surface0": "#282134",
    "surface1": "#3a304b",
    "overlay0": "#a79ab8",
    "text":     "#f6f1ff",
    "subtext":  "#d8cdea",
    "green":    "#7ee7b8",
    "yellow":   "#ffd166",
    "red":      "#ff8fa3",
    "blue":     "#a996ff",
    "mauve":    "#a855f7",
    "lavender": "#c7a6ff",
}

FONT_FAMILY = "Noto Sans"
MONO_FAMILY = "Noto Sans Mono"
FONT_TITLE = (FONT_FAMILY, 14, "bold")
FONT_SECTION = (FONT_FAMILY, 9, "bold")
FONT_BODY = (FONT_FAMILY, 10)
FONT_BODY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)
FONT_SMALL_BOLD = (FONT_FAMILY, 9, "bold")
FONT_TINY = (FONT_FAMILY, 8)
FONT_TINY_BOLD = (FONT_FAMILY, 8, "bold")
FONT_MONO = (MONO_FAMILY, 9)
FONT_MONO_ENTRY = (MONO_FAMILY, 10)

# ─── ttk Theme ───────────────────────────────────────────────────────────────

def setup_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")

    root.option_add("*Font", FONT_BODY)
    root.option_add("*Menu.font", FONT_SMALL)

    style.configure("TCombobox",
                     fieldbackground=C["surface0"],
                     background=C["surface1"],
                     foreground=C["text"],
                     font=FONT_SMALL,
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

    style.configure("Voxkeys.Horizontal.TScale",
                    background=C["base"],
                    troughcolor=C["surface0"],
                    bordercolor=C["surface0"],
                    lightcolor=C["mauve"],
                    darkcolor=C["mauve"],
                    sliderlength=18,
                    sliderthickness=12,
                    relief="flat")
    style.map("Voxkeys.Horizontal.TScale",
              background=[("active", C["mauve"])],
              troughcolor=[("active", C["surface1"])])

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
WINDOW_H = 300
WINDOW_ALPHA = 0.92
MIN_WINDOW_ALPHA = 0.70
MAX_WINDOW_ALPHA = 1.0
TOOLTIP_DELAY_MS = 450

# Short codes for the lang-flow badge on the main page.
LANG_SHORT = {
    "auto":  "自",
    None:    "自",
    "":      "自",
    "zh":    "中",
    "zh-cn": "簡",
    "en":    "英",
    "ja":    "日",
}


def make_button(parent, text, command, *, variant="ghost", font=FONT_BODY_BOLD):
    """Consistent Tk button with a usable hit target and visible focus border."""
    palette = {
        "ghost": (C["surface0"], C["subtext"], C["surface1"], C["text"]),
        "primary": (C["mauve"], C["crust"], C["lavender"], C["crust"]),
        "danger": (C["surface0"], C["red"], C["surface1"], C["red"]),
    }
    bg, fg, active_bg, active_fg = palette.get(variant, palette["ghost"])
    return tk.Button(
        parent, text=text, font=font, bg=bg, fg=fg,
        activebackground=active_bg, activeforeground=active_fg,
        bd=0, padx=10, pady=7, cursor="hand2",
        highlightthickness=1, highlightbackground=C["surface0"],
        highlightcolor=C["blue"], takefocus=True,
        command=command,
    )


def chip(parent, text, *, fg=None, bg=None, font=FONT_SMALL_BOLD):
    return tk.Label(
        parent, text=text, font=font,
        bg=bg or C["surface0"], fg=fg or C["subtext"],
        padx=8, pady=3,
    )


def menu_chip(parent, text, *, fg=None, bg=None, font=FONT_SMALL_BOLD):
    return tk.Menubutton(
        parent, text=text, font=font,
        bg=bg or C["surface0"], fg=fg or C["subtext"],
        activebackground=C["surface1"], activeforeground=C["text"],
        padx=8, pady=3, bd=0, cursor="hand2",
        highlightthickness=1, highlightbackground=C["surface0"],
        highlightcolor=C["blue"], takefocus=True,
    )

# ─── Main Application ────────────────────────────────────────────────────────

class VoxkeysApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Voxkeys")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
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
        self._apply_window_alpha(self.cfg.get("window_alpha", WINDOW_ALPHA))
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
            self._preload_local_whisper()

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
        voxkeys.CONFIG["stt_provider"] = self.cfg.get("stt_provider", "local")
        voxkeys.CONFIG["groq_api_key"] = self.cfg.get("groq_api_key", "")
        voxkeys.CONFIG["per_app_prompts"] = bool(self.cfg.get("per_app_prompts", False))

    def _apply_window_alpha(self, value):
        alpha = max(MIN_WINDOW_ALPHA, min(MAX_WINDOW_ALPHA, float(value)))
        self.root.attributes("-alpha", alpha)

    def _preload_local_whisper(self):
        if self.cfg.get("stt_provider", "local") == "local":
            voxkeys.preload_whisper_model()

    # ─── Main Page ───────────────────────────────────────────────────────────

    def _build_main_page(self):
        self._clear()

        # Title bar
        header = tk.Frame(self.root, bg=C["base"])
        header.pack(fill="x", padx=16, pady=(14, 0))

        tk.Label(header, text="Voxkeys", font=FONT_TITLE,
                 bg=C["base"], fg=C["text"]).pack(side="left")

        btn_frame = tk.Frame(header, bg=C["base"])
        btn_frame.pack(side="right")

        make_button(btn_frame, "⚙", self._build_settings_page,
                    font=(FONT_FAMILY, 13)).pack(side="left", padx=(0, 8))

        # Separator
        tk.Frame(self.root, bg=C["surface0"], height=1).pack(fill="x", padx=16, pady=8)

        # Missing-deps banner takes over the body area entirely
        if self.missing_deps:
            body = tk.Frame(self.root, bg=C["base"])
            body.pack(expand=True, fill="both", padx=16)
            tk.Label(body, text="Setup needed",
                     font=(FONT_FAMILY, 12, "bold"),
                     bg=C["base"], fg=C["red"]).pack(pady=(18, 4))
            tk.Label(body, text=f"Missing: {', '.join(self.missing_deps)}",
                     font=FONT_SMALL,
                     bg=C["base"], fg=C["subtext"]).pack(pady=(0, 8))
            install_cmd = f"sudo apt install {' '.join(self.missing_deps)}"
            tk.Label(body, text=install_cmd,
                     font=FONT_MONO, bg=C["surface0"], fg=C["subtext"],
                     padx=8, pady=6).pack(pady=(0, 8))
            make_button(body, "Copy command",
                        lambda: self._copy_plain(install_cmd),
                        variant="primary").pack()
            return

        # Job list area
        self.list_frame = tk.Frame(self.root, bg=C["base"])
        self.list_frame.pack(fill="both", expand=True, padx=16, pady=(2, 0))

        # AI toggle (bottom) — single clean row, separator above for hierarchy
        ai_frame = tk.Frame(self.root, bg=C["base"])
        ai_frame.pack(fill="x", padx=16, pady=(6, 12))

        tk.Frame(ai_frame, bg=C["surface0"], height=1).pack(fill="x", pady=(0, 10))

        toggle_row = tk.Frame(ai_frame, bg=C["base"])
        toggle_row.pack(fill="x")

        self.ai_var = tk.BooleanVar(value=self.use_ai)
        self.ai_check = tk.Checkbutton(
            toggle_row, text="AI Polish", variable=self.ai_var,
            font=FONT_BODY, bg=C["base"], fg=C["text"],
            selectcolor=C["surface0"], activebackground=C["base"],
            activeforeground=C["text"], cursor="hand2",
            highlightthickness=1, highlightbackground=C["surface0"],
            highlightcolor=C["blue"], padx=4, pady=4, takefocus=True,
            command=self._toggle_ai,
        )
        self.ai_check.pack(side="left")

        self.per_app_main_var = tk.BooleanVar(
            value=bool(self.cfg.get("per_app_prompts", False))
        )
        self.per_app_main_check = tk.Checkbutton(
            toggle_row, text="App Tone", variable=self.per_app_main_var,
            font=FONT_SMALL, bg=C["base"], fg=C["text"],
            selectcolor=C["surface0"], activebackground=C["base"],
            activeforeground=C["text"], cursor="hand2",
            highlightthickness=1, highlightbackground=C["surface0"],
            highlightcolor=C["blue"], padx=4, pady=4, takefocus=True,
            command=self._toggle_per_app_prompts,
        )
        self.per_app_main_check.pack(side="left", padx=(8, 0))
        self._sync_app_tone_state()

        # Language flow controls: input menu -> output menu.
        lang_frame = tk.Frame(toggle_row, bg=C["base"])
        lang_frame.pack(side="right")
        self.output_lang_chip = menu_chip(lang_frame, self._output_lang_text(), fg=C["lavender"])
        self._build_output_lang_menu()
        self.output_lang_chip.pack(side="right")
        tk.Label(lang_frame, text="->", font=FONT_SMALL_BOLD,
                 bg=C["base"], fg=C["overlay0"]).pack(side="right", padx=4)
        self.input_lang_chip = menu_chip(lang_frame, self._input_lang_text(), fg=C["lavender"])
        self._build_input_lang_menu()
        self.input_lang_chip.pack(side="right")

        opacity_row = tk.Frame(ai_frame, bg=C["base"])
        opacity_row.pack(fill="x", pady=(8, 0))
        tk.Label(opacity_row, text="Opacity", font=FONT_TINY,
                 bg=C["base"], fg=C["overlay0"]).pack(side="left")
        alpha = self.cfg.get("window_alpha", WINDOW_ALPHA)
        alpha = max(MIN_WINDOW_ALPHA, min(MAX_WINDOW_ALPHA, float(alpha)))
        self.main_alpha_var = tk.IntVar(value=int(round(alpha * 100)))
        self.main_alpha_value = chip(opacity_row, f"{self.main_alpha_var.get()}%",
                                     fg=C["lavender"], font=FONT_TINY_BOLD)
        self.main_alpha_value.pack(side="right")
        ttk.Scale(
            opacity_row, from_=70, to=100, orient="horizontal",
            variable=self.main_alpha_var, command=self._on_main_alpha_change,
            style="Voxkeys.Horizontal.TScale",
        ).pack(side="left", fill="x", expand=True, padx=(8, 8))

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
        self._refresh_lang_chip()
        self._sync_app_tone_state()

    def _toggle_per_app_prompts(self):
        enabled = bool(self.per_app_main_var.get())
        self.cfg["per_app_prompts"] = enabled
        voxkeys.CONFIG["per_app_prompts"] = enabled
        save_config({"per_app_prompts": enabled})

    def _on_main_alpha_change(self, value):
        pct = int(float(value))
        if hasattr(self, "main_alpha_value") and self.main_alpha_value.winfo_exists():
            self.main_alpha_value.config(text=f"{pct}%")
        self.cfg["window_alpha"] = pct / 100
        self._apply_window_alpha(self.cfg["window_alpha"])
        save_config({"window_alpha": self.cfg["window_alpha"]})

    def _sync_app_tone_state(self):
        if not hasattr(self, "per_app_main_check"):
            return
        if self.use_ai:
            if not self.per_app_main_check.winfo_manager():
                self.per_app_main_check.pack(side="left", padx=(8, 0))
            self.per_app_main_check.config(state="normal", fg=C["text"], cursor="hand2")
        else:
            self.per_app_main_check.pack_forget()

    def _build_input_lang_menu(self):
        menu = tk.Menu(
            self.input_lang_chip, tearoff=False,
            bg=C["surface0"], fg=C["text"],
            activebackground=C["surface1"], activeforeground=C["text"],
            bd=0,
        )
        for code, label in (("auto", "自"), ("zh", "中"), ("zh-cn", "簡"),
                            ("en", "英"), ("ja", "日")):
            menu.add_command(label=label, command=lambda c=code: self._set_input_language(c))
        self.input_lang_chip.config(menu=menu)

    def _build_output_lang_menu(self):
        menu = tk.Menu(
            self.output_lang_chip, tearoff=False,
            bg=C["surface0"], fg=C["text"],
            activebackground=C["surface1"], activeforeground=C["text"],
            bd=0,
        )
        for code, label in (("", "同輸入"), ("zh", "中"), ("zh-cn", "簡"),
                            ("en", "英"), ("ja", "日")):
            menu.add_command(label=label, command=lambda c=code: self._set_output_language(c))
        self.output_lang_chip.config(menu=menu)

    def _set_input_language(self, code):
        self.cfg["language"] = code
        self.cfg["output_language"] = ""
        voxkeys.CONFIG["language"] = None if code == "auto" else code
        voxkeys.CONFIG["output_language"] = ""
        save_config({"language": code, "output_language": ""})
        self._refresh_lang_chip()

    def _set_output_language(self, code):
        self.cfg["output_language"] = code
        voxkeys.CONFIG["output_language"] = code
        save_config({"output_language": code})
        self._refresh_lang_chip()

    def _refresh_lang_chip(self):
        if hasattr(self, "input_lang_chip") and self.input_lang_chip.winfo_exists():
            self.input_lang_chip.config(text=self._input_lang_text())
        if hasattr(self, "output_lang_chip") and self.output_lang_chip.winfo_exists():
            self.output_lang_chip.config(text=self._output_lang_text())

    def _input_lang_text(self):
        return LANG_SHORT.get(self.cfg.get("language", "auto"), "自")

    def _output_lang_text(self):
        out_code = self.cfg.get("output_language", "") or ""
        if not out_code or out_code == "same" or not self.use_ai:
            return self._input_lang_text()
        return LANG_SHORT.get(out_code, out_code)

    # ─── Job list rendering (in-place updates) ───────────────────────────────

    def _ensure_empty_state(self):
        """Show the placeholder when no jobs are present."""
        if hasattr(self, "empty_frame") and self.empty_frame.winfo_exists():
            return
        self.empty_frame = tk.Frame(self.list_frame, bg=C["base"])
        self.empty_frame.pack(fill="both", expand=True)
        self.empty_frame.grid_rowconfigure(0, weight=1)
        self.empty_frame.grid_rowconfigure(2, weight=1)
        self.empty_frame.grid_columnconfigure(0, weight=1)

        center = tk.Frame(self.empty_frame, bg=C["base"])
        center.grid(row=1, column=0, sticky="n")

        action_row = tk.Frame(center, bg=C["base"])
        action_row.pack(pady=(6, 8))
        chip(action_row, "F9", fg=C["lavender"]).pack(side="left", padx=(0, 6))
        tk.Label(action_row, text="Dictate / Edit", font=(FONT_FAMILY, 12, "bold"),
                 bg=C["base"], fg=C["text"]).pack(side="left")

        tk.Label(center,
                 text="Inserts at cursor. Select text to edit it.",
                 font=FONT_SMALL,
                 bg=C["base"], fg=C["subtext"]).pack()

    def _hide_empty_state(self):
        if hasattr(self, "empty_frame") and self.empty_frame.winfo_exists():
            self.empty_frame.destroy()

    def _create_row(self, jid):
        """Create the widgets for a job row once. Returns the widgets dict."""
        row = tk.Frame(self.list_frame, bg=C["base"], padx=10, pady=5)
        row.pack(fill="x", pady=2)

        dot = tk.Label(row, text="·", font=(FONT_FAMILY, 12, "bold"),
                       bg=C["base"], fg=C["overlay0"], width=2)
        dot.pack(side="left")

        lbl = tk.Label(row, text="", font=FONT_BODY,
                       bg=C["base"], fg=C["subtext"],
                       anchor="w", justify="left")
        lbl.pack(side="left", fill="x", expand=True, padx=(2, 0))

        id_lbl = tk.Label(row, text=f"#{jid}", font=FONT_TINY,
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
                 font=FONT_SMALL,
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

    @staticmethod
    def _copy_plain(text):
        if not text:
            return
        try:
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
            )
            p.communicate(text.encode("utf-8"))
        except Exception:
            pass

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
    }
    PROVIDER_FROM_LABEL = {v: k for k, v in PROVIDER_LABELS.items()}

    LANG_LABELS = {
        "auto":  "Auto Detect",
        "zh":    "中文（繁體）",
        "zh-cn": "中文（簡體）",
        "en":    "English",
        "ja":    "日本語",
    }
    LANG_FROM_LABEL = {v: k for k, v in LANG_LABELS.items()}

    OUTPUT_LANG_LABELS = {
        "":      "Same as input",
        "zh":    "中文（繁體）",
        "zh-cn": "中文（簡體）",
        "en":    "English",
        "ja":    "日本語",
    }
    OUTPUT_LANG_FROM_LABEL = {v: k for k, v in OUTPUT_LANG_LABELS.items()}

    STT_PROVIDER_LABELS = {
        "local": "Local Whisper",
        "groq":  "Groq Cloud",
    }
    STT_PROVIDER_FROM_LABEL = {v: k for k, v in STT_PROVIDER_LABELS.items()}

    def _build_settings_page(self):
        self._clear()
        self.showing_settings = True

        header = tk.Frame(self.root, bg=C["base"])
        header.pack(fill="x", padx=16, pady=(14, 0))

        make_button(header, "←", self._back_to_main,
                    font=(FONT_FAMILY, 13)).pack(side="left")

        tk.Label(header, text="Settings", font=(FONT_FAMILY, 12, "bold"),
                 bg=C["base"], fg=C["text"]).pack(side="left", padx=(8, 0))

        self.settings_actions = tk.Frame(header, bg=C["base"])
        self.settings_actions.pack(side="right")
        make_button(self.settings_actions, "Save", self._save_settings,
                    variant="primary", font=FONT_TINY_BOLD).pack(side="right")
        make_button(self.settings_actions, "Cancel", self._cancel_settings_changes,
                    font=FONT_TINY_BOLD).pack(side="right", padx=(0, 8))

        tk.Frame(self.root, bg=C["surface0"], height=1).pack(fill="x", padx=16, pady=8)

        form = tk.Frame(self.root, bg=C["base"])
        form.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        self._settings_loading = True
        self._init_settings_vars()
        self._build_all_settings(form)
        self._settings_snapshot = self._settings_values()
        self._settings_dirty = False
        self._settings_loading = False
        self._sync_settings_actions()

    def _init_settings_vars(self):
        provider = self.cfg["provider"] if self.cfg["provider"] in self.PROVIDER_LABELS else "github"
        provider_display = self.PROVIDER_LABELS[provider]
        self.provider_var = tk.StringVar(value=provider_display)
        self.key_var = tk.StringVar(value=self._current_key())

        stt_display = self.STT_PROVIDER_LABELS.get(
            self.cfg.get("stt_provider", "local"), "Local Whisper (faster-whisper, CPU)"
        )
        self.stt_var = tk.StringVar(value=stt_display)
        self.model_var = tk.StringVar(value=self.cfg["whisper_model"])
        self.groq_var = tk.StringVar(value=self.cfg.get("groq_api_key", ""))

        lang_display = self.LANG_LABELS.get(self.cfg["language"], self.cfg["language"])
        self.lang_var = tk.StringVar(value=lang_display)
        out_lang_key = self.cfg.get("output_language", "") or ""
        out_lang_display = self.OUTPUT_LANG_LABELS.get(out_lang_key, "Same as input")
        self.output_lang_var = tk.StringVar(value=out_lang_display)
        self.per_app_var = tk.BooleanVar(value=bool(self.cfg.get("per_app_prompts", False)))
        alpha = self.cfg.get("window_alpha", WINDOW_ALPHA)
        alpha = max(MIN_WINDOW_ALPHA, min(MAX_WINDOW_ALPHA, float(alpha)))
        self.alpha_var = tk.IntVar(value=int(round(alpha * 100)))

        for var in (
            self.provider_var,
            self.key_var,
            self.stt_var,
            self.model_var,
            self.groq_var,
        ):
            var.trace_add("write", self._mark_settings_dirty)

    def _build_all_settings(self, parent):
        self._section_header(parent, "AI Polish")

        provider_cb = self._combo_row(
            parent, "Provider", self.provider_var,
            list(self.PROVIDER_LABELS.values())
        )
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_change)

        key_row = self._row(parent)
        self.key_label = self._row_label(key_row, self._key_label_text())
        self.key_entry = self._entry(key_row, self.key_var)

        self._section_header(parent, "Speech Recognition")

        stt_cb = self._combo_row(
            parent, "STT Backend", self.stt_var,
            list(self.STT_PROVIDER_LABELS.values())
        )
        stt_cb.bind("<<ComboboxSelected>>", self._on_stt_change)

        self._combo_row(parent, "Whisper Model", self.model_var,
                        ["tiny", "base", "small", "medium", "large-v3"])

        self.groq_key_frame = tk.Frame(parent, bg=C["base"])
        groq_row = self._row(self.groq_key_frame)
        self._row_label(groq_row, "Groq API Key")
        self._entry(groq_row, self.groq_var)
        self._sync_groq_key_visibility()

    def _on_stt_change(self, event=None):
        self._sync_groq_key_visibility()

    def _sync_groq_key_visibility(self):
        if not hasattr(self, "groq_key_frame"):
            return
        stt = self.STT_PROVIDER_FROM_LABEL.get(self.stt_var.get(), "local")
        if stt == "groq":
            if not self.groq_key_frame.winfo_manager():
                self.groq_key_frame.pack(fill="x")
        else:
            self.groq_key_frame.pack_forget()

    def _row(self, parent):
        row = tk.Frame(parent, bg=C["base"])
        row.pack(fill="x", pady=(0, 7))
        return row

    def _row_label(self, row, text):
        label = tk.Label(row, text=text, font=FONT_TINY_BOLD,
                         bg=C["base"], fg=C["subtext"], anchor="w", width=13)
        label.pack(side="left")
        return label

    def _combo_row(self, parent, label, variable, values):
        row = self._row(parent)
        self._row_label(row, label)
        combo = ttk.Combobox(row, textvariable=variable, values=values,
                             state="readonly", width=18)
        combo.pack(side="right", ipady=1, padx=(0, 8))
        return combo

    def _entry(self, row, variable):
        entry = tk.Entry(row, textvariable=variable, show="•",
                         font=FONT_MONO_ENTRY,
                         bg=C["surface0"], fg=C["text"],
                         insertbackground=C["text"],
                         relief="flat", bd=0,
                         highlightthickness=1,
                         highlightcolor=C["blue"],
                         highlightbackground=C["surface1"])
        entry.pack(side="right", ipady=2, padx=(0, 8))
        return entry

    def _section_header(self, parent, text, top_pad=0):
        """Subtle uppercase group header — gives the settings page rhythm."""
        wrap = tk.Frame(parent, bg=C["base"])
        wrap.pack(fill="x", pady=(top_pad, 6))
        tk.Label(wrap, text=text.upper(),
                 font=FONT_SECTION,
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
                 "claude": "Anthropic API Key"}
        return names.get(p, "API Key")

    def _current_key(self):
        p = self._selected_provider()
        keys = {"github": "github_token", "openai": "openai_api_key",
                "claude": "anthropic_api_key"}
        return self.cfg.get(keys.get(p, ""), "")

    def _on_provider_change(self, event=None):
        self.key_label.config(text=self._key_label_text())
        self.key_var.set(self._current_key())

    def _settings_values(self):
        return {
            "provider": self._selected_provider(),
            "api_key": self.key_var.get(),
            "stt_provider": self.STT_PROVIDER_FROM_LABEL.get(self.stt_var.get(), "local"),
            "whisper_model": self.model_var.get(),
            "groq_api_key": self.groq_var.get(),
        }

    def _mark_settings_dirty(self, *_args):
        if getattr(self, "_settings_loading", False):
            return
        dirty = self._settings_values() != getattr(self, "_settings_snapshot", {})
        self._settings_dirty = dirty
        self._sync_settings_actions()

    def _sync_settings_actions(self):
        if not hasattr(self, "settings_actions"):
            return
        if getattr(self, "_settings_dirty", False):
            if not self.settings_actions.winfo_manager():
                self.settings_actions.pack(side="right")
        else:
            self.settings_actions.pack_forget()

    def _cancel_settings_changes(self):
        self._settings_loading = True
        provider = self.cfg["provider"] if self.cfg["provider"] in self.PROVIDER_LABELS else "github"
        self.provider_var.set(self.PROVIDER_LABELS[provider])
        self.key_var.set(self._current_key())
        stt_display = self.STT_PROVIDER_LABELS.get(
            self.cfg.get("stt_provider", "local"), self.STT_PROVIDER_LABELS["local"]
        )
        self.stt_var.set(stt_display)
        self.model_var.set(self.cfg["whisper_model"])
        self.groq_var.set(self.cfg.get("groq_api_key", ""))
        if hasattr(self, "key_label") and self.key_label.winfo_exists():
            self.key_label.config(text=self._key_label_text())
        self._sync_groq_key_visibility()
        self._settings_snapshot = self._settings_values()
        self._settings_dirty = False
        self._settings_loading = False
        self._sync_settings_actions()

    def _save_settings(self):
        provider = self._selected_provider()
        lang = self.LANG_FROM_LABEL.get(self.lang_var.get(), self.lang_var.get())
        key_field = {"github": "github_token", "openai": "openai_api_key",
                     "claude": "anthropic_api_key"}.get(provider)

        out_lang = self.OUTPUT_LANG_FROM_LABEL.get(
            self.output_lang_var.get(), ""
        )
        stt = self.STT_PROVIDER_FROM_LABEL.get(self.stt_var.get(), "local")

        updates = {
            "provider": provider,
            "whisper_model": self.model_var.get(),
            "language": lang,
            "output_language": out_lang,
            "stt_provider": stt,
            "groq_api_key": self.groq_var.get(),
            "per_app_prompts": bool(self.per_app_var.get()),
        }
        if key_field:
            updates[key_field] = self.key_var.get()

        save_config(updates)
        self.cfg = load_config()
        self.use_ai = self.cfg["provider"] != "none"

        if updates["whisper_model"] != voxkeys.CONFIG.get("whisper_model"):
            voxkeys.whisper_model = None

        self._apply_config()
        self._preload_local_whisper()
        self._settings_snapshot = self._settings_values()
        self._settings_dirty = False
        self._sync_settings_actions()

    def _back_to_main(self):
        self.showing_settings = False
        self._build_main_page()

    # ─── Keyboard Listener ───────────────────────────────────────────────────

    def _start_listener(self):
        try:
            kb = voxkeys.get_keyboard()
            voxkeys.configure_default_hotkeys()
            self.listener = kb.Listener(
                on_press=voxkeys.on_press,
                on_release=voxkeys.on_release,
            )
            self.listener.daemon = True
            self.listener.start()
        except RuntimeError as e:
            self._show_listener_error(str(e))

    def _show_listener_error(self, message):
        self._hide_empty_state()
        self.jobs.clear()
        self.job_order.clear()
        for widgets in self.rows.values():
            self._stop_animation(widgets)
            if widgets["row"].winfo_exists():
                widgets["row"].destroy()
        self.rows.clear()

        body = tk.Frame(self.list_frame, bg=C["base"])
        body.pack(expand=True, fill="both", pady=(12, 0))
        tk.Label(body, text="Hotkeys unavailable",
                 font=(FONT_FAMILY, 11, "bold"),
                 bg=C["base"], fg=C["red"]).pack(pady=(0, 6))
        tk.Label(body, text=message,
                 font=FONT_SMALL, wraplength=300, justify="center",
                 bg=C["base"], fg=C["subtext"]).pack()
        make_button(body, "Open settings", self._build_settings_page,
                    variant="primary").pack(pady=(12, 0))

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
