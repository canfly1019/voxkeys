#!/usr/bin/env python3
"""
Voxkeys GUI — Tkinter floating window
Imports voxkeys core engine directly, no subprocess.

The main view is a live job list (newest on top) so the user can keep recording
new segments while previous ones are still being transcribed and polished.
Completed rows are clickable to recopy the polished text to the clipboard.
"""

import fcntl
import os
import signal
import subprocess
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import draw
import voxkeys
from config import load_config, save_config

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, "assets", "voxkeys.png")
LOCK_PATH = os.path.expanduser("~/.config/voxkeys/gui.lock")

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
    "mauve":    "#9486c0",  # accent: switches, outlines, badges
    "lavender": "#c9bfe6",
    # The logo's own gradient: a muted lavender, not neon.
    "brand_a":  "#5b4b8a",
    "brand_b":  "#7a6a9e",
}

FONT_FAMILY = "Noto Sans"
MONO_FAMILY = "Noto Sans Mono"
FONT_TITLE = (FONT_FAMILY, 12, "bold")
FONT_SECTION = (FONT_FAMILY, 9, "bold")
FONT_BODY = (FONT_FAMILY, 10)
FONT_BODY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)
FONT_SMALL_BOLD = (FONT_FAMILY, 9, "bold")
FONT_TINY = (FONT_FAMILY, 8)
FONT_TINY_BOLD = (FONT_FAMILY, 8, "bold")
FONT_MONO = (MONO_FAMILY, 9)
FONT_MONO_ENTRY = (MONO_FAMILY, 10)

HOTKEY_LABELS = {
    "ctrl_r": "Right Ctrl",
    "alt_r": "Right Alt",
    "f8": "F8",
    "f9": "F9",
    "f10": "F10",
    "f12": "F12",
}
HOTKEY_FROM_LABEL = {v: k for k, v in HOTKEY_LABELS.items()}

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
                     # clam draws a light 1px bevel inside the border by default,
                     # which made comboboxes look taller than the flat tk Entry
                     # fields next to them. Flatten it to the border color.
                     lightcolor=C["surface1"],
                     darkcolor=C["surface1"],
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

# (icon kind, color_key, label_text). label_text=None means "show the text".
# Icon kinds are drawn by draw.status_icon.
PHASE_VISUALS = {
    "recording":     ("dot",   "green",    "錄音中…"),
    "queued":        ("spin",  "subtext",  "排隊中…"),
    "loading_model": ("spin",  "yellow",   "載入模型…"),
    "transcribing":  ("spin",  "yellow",   "轉文字中…"),
    "transcribed":   ("spin",  "yellow",   "處理中…"),  # transient: bridges to polishing or done
    "polishing":     ("spin",  "yellow",   "潤稿中…"),
    "done":          ("check", "green",    None),
    "polish_failed": ("check", "yellow",   None),
    "empty":         ("dash",  "overlay0", "沒有聽到聲音"),
    "error":         ("cross", "red",      None),
}

# Phases that should drive a spinning indicator on the row dot.
SPINNING_PHASES = {"queued", "loading_model", "transcribing", "transcribed", "polishing"}
SPIN_PERIOD_MS = 90
PULSE_PERIOD_MS = 520

MAX_ROWS = 3
ROW_H = 36
CAPSULE_DEFAULT_W = 260
CAPSULE_MIN_W = 160
CAPSULE_H = 34
CAPSULE_GRIP = 12  # right-end strip that resizes instead of moving
CAPSULE_FONT = FONT_BODY
WINDOW_W = 260
WINDOW_RADIUS = 14
HEADER_H = 56
MAIN_H = 380
WINDOW_ALPHA = 1.0
MIN_WINDOW_ALPHA = 0.70
MAX_WINDOW_ALPHA = 1.0
TOOLTIP_DELAY_MS = 450

LANG_NAMES = {"auto": "自動", "zh": "繁中", "zh-cn": "簡中", "en": "英文", "ja": "日文"}
INPUT_LANGS = ("auto", "zh", "zh-cn", "en", "ja")
OUTPUT_LANGS = ("zh", "zh-cn", "en", "ja")  # plus "" = same as input


def fit_px(font, text, avail):
    """Cut text with an ellipsis so it fits `avail` pixels in `font`."""
    text = text.strip().replace("\n", " ")
    if font.measure(text) <= avail:
        return text
    while text and font.measure(text + "…") > avail:
        text = text[:-1]
    return text + "…"


def pill_label(parent, text, *, fill, fg, font=FONT_SMALL_BOLD, bg=None):
    """Text on an antialiased rounded plate. Returns (label, (w, h))."""
    bg = bg or C["base"]
    f = tkfont.Font(font=font)
    w, h = f.measure(text) + 24, f.metrics("linespace") + 12
    lbl = tk.Label(parent, text=text, image=draw.rounded_rect(w, h, 8, fill, bg),
                   compound="center", font=font, fg=fg, bg=bg,
                   bd=0, padx=0, pady=0, highlightthickness=0)
    return lbl, (w, h)


def make_button(parent, text, command, *, variant="ghost", font=FONT_SMALL_BOLD, bg=None):
    """Rounded button; matches the switches and pills instead of Tk's bevel."""
    fill, fg, hover = {
        "ghost": (C["surface0"], C["subtext"], C["surface1"]),
        "primary": (C["mauve"], C["crust"], C["lavender"]),
    }[variant]
    bg = bg or C["base"]
    btn, (w, h) = pill_label(parent, text, fill=fill, fg=fg, font=font, bg=bg)
    rest, lit = btn.cget("image"), draw.rounded_rect(w, h, 8, hover, bg)
    btn.config(cursor="hand2", takefocus=True)
    btn.bind("<Enter>", lambda _e: btn.config(image=lit))
    btn.bind("<Leave>", lambda _e: btn.config(image=rest))
    for seq in ("<Button-1>", "<Return>", "<space>"):
        btn.bind(seq, lambda _e: btn.after_idle(command))
    return btn


class SettingSwitch(tk.Frame):
    """A setting row: title and a one-line explanation on the left, a pill
    switch on the right. Clicking anywhere on the row flips it."""

    def __init__(self, parent, title, desc, variable, command, *, bg=None):
        bg = bg or C["base"]
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var, self.command, self.bg = variable, command, bg
        self.sw = tk.Label(self, bg=bg, bd=0, highlightthickness=0,
                           cursor="hand2", takefocus=True)
        self.sw.pack(side="right")
        text = tk.Frame(self, bg=bg, cursor="hand2")
        text.pack(side="left", fill="x", expand=True)
        parts = [self, self.sw, text,
                 tk.Label(text, text=title, font=FONT_BODY, bg=bg, fg=C["text"],
                          anchor="w", cursor="hand2")]
        parts[-1].pack(fill="x")
        if desc:
            parts.append(tk.Label(text, text=desc, font=FONT_SMALL, bg=bg,
                                  fg=C["overlay0"], anchor="w", cursor="hand2"))
            parts[-1].pack(fill="x")
        for w in parts:
            w.bind("<Button-1>", self._flip)
        self.sw.bind("<space>", self._flip)
        # Redraw on any change, including ones made elsewhere (capsule menu).
        self._trace = variable.trace_add("write", lambda *_: self.draw())
        self.bind("<Destroy>", self._untrace)
        self.draw()

    def _untrace(self, event):
        if event.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except tk.TclError:
                pass

    def _flip(self, _event=None):
        self.var.set(not self.var.get())
        self.command()

    def draw(self):
        if self.sw.winfo_exists():
            self.sw.config(image=draw.switch(bool(self.var.get()), C["mauve"],
                                             C["surface1"], "#ffffff", self.bg))


class Slider(tk.Canvas):
    """Rounded track with a round knob; ttk's clam slider is a square block."""

    W, H = 110, 20

    def __init__(self, parent, variable, lo, hi, command, *, bg=None):
        self.bg = bg or C["base"]
        super().__init__(parent, width=self.W, height=self.H, bg=self.bg, bd=0,
                         highlightthickness=0, cursor="hand2")
        self.var, self.lo, self.hi, self.command = variable, lo, hi, command
        self._img = self.create_image(0, 0, anchor="nw")
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.draw()

    def _drag(self, event):
        knob = self.H - 4
        frac = max(0.0, min(1.0, (event.x - knob / 2) / (self.W - knob)))
        value = round(self.lo + frac * (self.hi - self.lo))
        if value != self.var.get():
            self.var.set(value)
            self.command(value)
            self.draw()

    def draw(self):
        frac = (self.var.get() - self.lo) / (self.hi - self.lo)
        self.itemconfig(self._img, image=draw.slider(
            self.W, self.H, round(frac, 3), C["mauve"], C["surface1"], "#ffffff", self.bg))


# ─── Main Application ────────────────────────────────────────────────────────

class VoxkeysApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Voxkeys")
        self.root.geometry(f"{WINDOW_W}x{MAIN_H}")
        self._win_h = MAIN_H
        self._win_drag = None
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=C["base"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # No system title bar: the header is the drag handle, and the window
        # is clipped to rounded corners. Both need the mapped X window.
        self.root.bind("<Map>", self._on_root_map, add="+")

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

        self._body_font = tkfont.Font(root=self.root, font=FONT_BODY)

        self._build_main_page()
        self._build_capsule()
        if not self.missing_deps:
            self._start_listener()
            self._preload_local_whisper()
        # With the capsule on, start collapsed: only the capsule shows, and
        # clicking it opens this panel.
        if self.cfg.get("capsule_visible", True) and not self.missing_deps:
            self.root.withdraw()

    def _apply_config(self):
        voxkeys.CONFIG["whisper_model"] = self.cfg["whisper_model"]
        lang = self.cfg["language"]
        voxkeys.CONFIG["language"] = None if lang == "auto" else lang
        out_lang = self.cfg.get("output_language", "")
        voxkeys.CONFIG["output_language"] = "" if out_lang in ("", "same") else out_lang
        voxkeys.CONFIG["provider"] = self.cfg["provider"] if self.use_ai else "none"
        voxkeys.CONFIG["openai_api_key"] = self.cfg["openai_api_key"]
        voxkeys.CONFIG["anthropic_api_key"] = self.cfg["anthropic_api_key"]
        voxkeys.CONFIG["stt_provider"] = self.cfg.get("stt_provider", "local")
        voxkeys.CONFIG["groq_api_key"] = self.cfg.get("groq_api_key", "")
        voxkeys.CONFIG["gpustack_api_key"] = self.cfg.get("gpustack_api_key", "")
        voxkeys.CONFIG["gpustack_base_url"] = self.cfg.get("gpustack_base_url", "")
        voxkeys.CONFIG["gpustack_stt_model"] = self.cfg.get(
            "gpustack_stt_model", voxkeys.GPUSTACK_STT_MODELS[0]
        )
        voxkeys.CONFIG["gpustack_polish_model"] = self.cfg["gpustack_polish_model"]
        voxkeys.CONFIG["per_app_prompts"] = bool(self.cfg.get("per_app_prompts", False))
        voxkeys.CONFIG["auto_submit"] = bool(self.cfg.get("auto_submit", True))
        voxkeys.CONFIG["record_hotkey"] = self.cfg.get("record_hotkey", "f9")
        voxkeys.CONFIG["hotkey"] = None
        voxkeys.CONFIG["hotkey_display"] = HOTKEY_LABELS.get(
            voxkeys.CONFIG["record_hotkey"], "F9"
        )

    def _apply_window_alpha(self, value):
        alpha = max(MIN_WINDOW_ALPHA, min(MAX_WINDOW_ALPHA, float(value)))
        self.root.attributes("-alpha", alpha)

    def _preload_local_whisper(self):
        if self.cfg.get("stt_provider", "local") == "local":
            voxkeys.preload_whisper_model()

    # ─── Main Page ───────────────────────────────────────────────────────────

    def _on_root_map(self, event):
        if event.widget is self.root:
            draw.undecorate(self.root)
            draw.round_window(self.root, WINDOW_W, self._win_h, WINDOW_RADIUS)

    def _set_window_height(self, h):
        self._win_h = h
        self.root.geometry(f"{WINDOW_W}x{h}")
        self.root.update_idletasks()
        draw.round_window(self.root, WINDOW_W, h, WINDOW_RADIUS)

    def _build_header(self, title, *, back=None, actions=()):
        """Top bar shared by both pages. With no system title bar, it is
        also what the window is dragged by."""
        hdr = tk.Canvas(self.root, width=WINDOW_W, height=HEADER_H, bd=0,
                        highlightthickness=0, bg=C["base"])
        hdr.pack(fill="x")
        mid = HEADER_H // 2
        if back:
            self._header_icon(hdr, "back", 28, mid, back)
            x = 46
        else:
            hdr.create_image(16, mid, anchor="w", image=draw.logo(ICON_PATH, 28, C["base"]))
            x = 54
        hdr.create_text(x, mid, text=title, anchor="w", fill=C["text"], font=FONT_TITLE)
        for i, (name, cmd) in enumerate(actions):
            self._header_icon(hdr, name, WINDOW_W - 27 - i * 34, mid, cmd)
        hdr.bind("<ButtonPress-1>", self._win_press)
        hdr.bind("<B1-Motion>", self._win_motion)
        return hdr

    def _header_icon(self, hdr, name, x, y, cmd):
        rest = draw.action_icon(name, C["subtext"], C["base"])
        lit = draw.action_icon(name, C["text"], C["base"], plate=C["surface0"])
        item = hdr.create_image(x, y, image=rest, tags=("icon",))
        hdr.tag_bind(item, "<Enter>", lambda _e: (hdr.itemconfig(item, image=lit),
                                                  hdr.config(cursor="hand2")))
        hdr.tag_bind(item, "<Leave>", lambda _e: (hdr.itemconfig(item, image=rest),
                                                  hdr.config(cursor="")))
        # after_idle: the command rebuilds the page, which destroys this canvas.
        hdr.tag_bind(item, "<Button-1>", lambda _e: self.root.after_idle(cmd))

    def _win_press(self, event):
        if "icon" in event.widget.gettags("current"):
            self._win_drag = None
            return
        self._win_drag = (event.x_root - self.root.winfo_rootx(),
                          event.y_root - self.root.winfo_rooty())

    def _win_motion(self, event):
        if self._win_drag:
            dx, dy = self._win_drag
            self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _build_main_page(self):
        self._clear()
        self._set_window_height(MAIN_H)
        self._build_header("Voxkeys", actions=(("close", self._on_close),
                                               ("collapse", self._collapse_panel),
                                               ("settings", self._build_settings_page)))

        # Missing-deps banner takes over the body area entirely
        if self.missing_deps:
            body = tk.Frame(self.root, bg=C["base"])
            body.pack(expand=True, fill="both", padx=16)
            tk.Label(body, text="需要先安裝套件", font=FONT_TITLE,
                     bg=C["base"], fg=C["red"]).pack(pady=(18, 4))
            tk.Label(body, text=f"缺少：{', '.join(self.missing_deps)}",
                     font=FONT_SMALL, wraplength=WINDOW_W - 32,
                     bg=C["base"], fg=C["subtext"]).pack(pady=(0, 8))
            install_cmd = f"sudo apt install {' '.join(self.missing_deps)}"
            tk.Label(body, text=install_cmd, font=FONT_MONO, wraplength=WINDOW_W - 48,
                     bg=C["surface0"], fg=C["subtext"], padx=8, pady=6).pack(pady=(0, 8))
            make_button(body, "複製指令", lambda: self._copy_plain(install_cmd),
                        variant="primary").pack()
            return

        # Settings are packed first, from the bottom, so they keep their space;
        # a long job list is clipped (oldest rows, at the bottom) instead of
        # squeezing them.
        bottom = tk.Frame(self.root, bg=C["base"])
        bottom.pack(side="bottom", fill="x", padx=16, pady=(0, 14))
        self.list_frame = tk.Frame(self.root, bg=C["base"])
        self.list_frame.pack(fill="both", expand=True, padx=12)
        tk.Frame(bottom, bg=C["surface0"], height=1).pack(fill="x", pady=(0, 12))

        self.submit_var = tk.BooleanVar(value=bool(self.cfg.get("auto_submit", True)))
        SettingSwitch(bottom, "貼上後送出", None,
                      self.submit_var, self._toggle_auto_submit).pack(fill="x")
        self.capsule_var = tk.BooleanVar(value=bool(self.cfg.get("capsule_visible", True)))
        SettingSwitch(bottom, "浮動膠囊", None, self.capsule_var,
                      lambda: self._set_capsule_visible(self.capsule_var.get()),
                      ).pack(fill="x", pady=(10, 0))
        self.ai_var = tk.BooleanVar(value=self.use_ai)
        SettingSwitch(bottom, "AI 潤稿", None,
                      self.ai_var, self._toggle_ai).pack(fill="x", pady=(10, 0))

        lang_row = tk.Frame(bottom, bg=C["base"])
        lang_row.pack(fill="x", pady=(12, 0))
        tk.Label(lang_row, text="語言", font=FONT_BODY, bg=C["base"],
                 fg=C["text"]).pack(side="left")
        self.lang_pill = tk.Menubutton(
            lang_row, compound="center", font=FONT_BODY, fg=C["lavender"],
            activeforeground=C["text"], bg=C["base"], activebackground=C["base"],
            bd=0, padx=0, pady=0, highlightthickness=0, cursor="hand2",
            direction="above")
        self.lang_menu = tk.Menu(
            self.lang_pill, tearoff=False, postcommand=self._fill_lang_menu,
            bg=C["surface0"], fg=C["text"], activebackground=C["surface1"],
            activeforeground=C["text"], disabledforeground=C["overlay0"],
            selectcolor=C["lavender"], font=FONT_BODY, bd=0, activeborderwidth=0)
        self.lang_pill.config(menu=self.lang_menu)
        self.lang_pill.pack(side="right")
        self.lang_pill.bind("<Enter>", lambda _e: self.lang_pill.config(image=self._lang_imgs[1]))
        self.lang_pill.bind("<Leave>", lambda _e: self.lang_pill.config(image=self._lang_imgs[0]))
        self._lang_in_var = tk.StringVar()
        self._lang_out_var = tk.StringVar()
        self._refresh_lang_chip()

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
                self.rows[jid]["row"].pack(fill="x", pady=(0, 6))
        else:
            self._ensure_empty_state()

    def _toggle_ai(self):
        self.use_ai = self.ai_var.get()
        if self.use_ai:
            # Turning polish on from the "none" default picks the GPUStack backend.
            provider = self.cfg["provider"] if self.cfg["provider"] != "none" else "gpustack"
        else:
            provider = "none"
        self.cfg["provider"] = provider
        voxkeys.CONFIG["provider"] = provider
        save_config({"provider": provider})
        self._refresh_lang_chip()

    def _toggle_per_app_prompts(self):
        enabled = bool(self.per_app_var.get())
        self.cfg["per_app_prompts"] = enabled
        voxkeys.CONFIG["per_app_prompts"] = enabled
        save_config({"per_app_prompts": enabled})

    def _toggle_auto_submit(self):
        enabled = bool(self.submit_var.get())
        self.cfg["auto_submit"] = enabled
        voxkeys.CONFIG["auto_submit"] = enabled
        save_config({"auto_submit": enabled})

    def _on_alpha_change(self, value):
        self.alpha_value.config(text=f"{value}%")
        self.cfg["window_alpha"] = value / 100
        self._apply_window_alpha(self.cfg["window_alpha"])
        save_config({"window_alpha": self.cfg["window_alpha"]})

    def _fill_lang_menu(self):
        """Rebuilt on every open. Translating needs AI polish, so with it off
        the output section is shown disabled with a hint instead of hidden."""
        m = self.lang_menu
        m.delete(0, "end")
        self._lang_in_var.set(self.cfg.get("language", "auto"))
        m.add_command(label="說的語言", state="disabled")
        for code in INPUT_LANGS:
            m.add_radiobutton(label=LANG_NAMES[code], value=code, variable=self._lang_in_var,
                              command=lambda c=code: self._set_input_language(c))
        out = self.cfg.get("output_language", "") or ""
        self._lang_out_var.set("" if out == "same" else out)
        state = "normal" if self.use_ai else "disabled"
        m.add_separator()
        m.add_command(label="輸出成" if self.use_ai else "輸出成（需開 AI 潤稿）",
                      state="disabled")
        m.add_radiobutton(label="跟說的一樣", value="", variable=self._lang_out_var,
                          state=state, command=lambda: self._set_output_language(""))
        for code in OUTPUT_LANGS:
            m.add_radiobutton(label=LANG_NAMES[code], value=code, variable=self._lang_out_var,
                              state=state, command=lambda c=code: self._set_output_language(c))

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
        pill = getattr(self, "lang_pill", None)
        if pill is None or not pill.winfo_exists():
            return
        text = self._lang_text()
        w, h = self._body_font.measure(text) + 28, 28
        self._lang_imgs = (draw.rounded_rect(w, h, 8, C["surface0"], C["base"]),
                           draw.rounded_rect(w, h, 8, C["surface1"], C["base"]))
        pill.config(text=text, image=self._lang_imgs[0])

    def _lang_text(self):
        src = LANG_NAMES.get(self.cfg.get("language", "auto"), "自動")
        out = self.cfg.get("output_language", "") or ""
        if not self.use_ai or out in ("", "same"):
            return src
        return f"{src} → {LANG_NAMES.get(out, out)}"

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
        action_row.pack(pady=(0, 8))
        pill_label(action_row, self._hotkey_text(), fill=C["surface0"],
                   fg=C["lavender"])[0].pack(side="left", padx=(0, 8))
        tk.Label(action_row, text="開始聽寫", font=FONT_TITLE,
                 bg=C["base"], fg=C["text"]).pack(side="left")

        tk.Label(center, text="文字會貼到游標處；先選取文字可以改寫",
                 font=FONT_SMALL, wraplength=WINDOW_W - 40,
                 bg=C["base"], fg=C["overlay0"]).pack()

    def _hotkey_text(self):
        return HOTKEY_LABELS.get(self.cfg.get("record_hotkey", "f9"), "F9")

    def _hide_empty_state(self):
        if hasattr(self, "empty_frame") and self.empty_frame.winfo_exists():
            self.empty_frame.destroy()

    def _create_row(self, jid):
        """Create the canvas for a job row once. Returns the widgets dict."""
        w = WINDOW_W - 24
        row = tk.Canvas(self.list_frame, width=w, height=ROW_H, bg=C["base"],
                        bd=0, highlightthickness=0)
        row.pack(fill="x", pady=(0, 6))
        widgets = {
            "row": row, "w": w,
            "bg": row.create_image(0, 0, anchor="nw"),
            "dot": row.create_image(20, ROW_H // 2),
            "lbl": row.create_text(36, ROW_H // 2, anchor="w", font=self._body_font,
                                   fill=C["subtext"], text=""),
            "kind": "dash", "color": C["overlay0"], "frame": 0, "hover": False,
            "click_text": None, "label_color": C["subtext"],
            "anim_id": None, "anim_kind": None,
            "tooltip_after": None, "full_text": "", "truncated": False,
        }
        self._paint_row(widgets)
        row.bind("<Enter>", lambda _e, ws=widgets: self._row_enter(ws))
        row.bind("<Leave>", lambda _e, ws=widgets: self._row_leave(ws))
        row.bind("<Motion>", lambda e, ws=widgets: self._row_motion(e, ws))
        row.bind("<Button-1>", lambda _e, ws=widgets: self._row_clicked(ws))
        return widgets

    def _paint_row(self, ws):
        """Card and status icon; both depend on the hover state."""
        row = ws["row"]
        if not row.winfo_exists():
            return
        card = C["surface1"] if ws["hover"] else C["surface0"]
        row.itemconfig(ws["bg"], image=draw.rounded_rect(ws["w"], ROW_H, 8, card, C["base"]))
        row.itemconfig(ws["dot"], image=draw.status_icon(
            ws["kind"], ws["color"], card, frame=ws["frame"]))

    def _update_row(self, jid, job):
        """Update an existing row's visuals to reflect the latest job state."""
        widgets = self.rows.get(jid)
        if widgets is None:
            return
        if not widgets["row"].winfo_exists():
            return

        phase = job["phase"]
        kind, color_key, default_label = PHASE_VISUALS.get(
            phase, ("dash", "overlay0", phase))

        if phase in ("done", "polish_failed"):
            text = job["polished_text"] or job["raw_text"] or "(empty)"
            label_color = C["text"]
            click_text = job["polished_text"] or job["raw_text"]
        elif phase == "error":
            text = f"錯誤：{job.get('error') or '未知'}"
            label_color = C["red"]
            click_text = None
        else:
            text = default_label or phase
            label_color = C["subtext"]
            click_text = None
        label_text = fit_px(self._body_font, text, widgets["w"] - 36 - 12)

        row = widgets["row"]
        row.itemconfig(widgets["lbl"], text=label_text, fill=label_color)
        widgets.update(kind=kind, color=C[color_key], frame=0,
                       label_color=label_color, click_text=click_text,
                       full_text=click_text or "", truncated=label_text != text)
        row.config(cursor="hand2" if click_text else "")
        if not click_text:
            widgets["hover"] = False
        self._paint_row(widgets)

        # Drive animations based on phase.
        self._stop_animation(widgets)
        if phase == "recording":
            self._start_pulse(widgets)
        elif phase in SPINNING_PHASES:
            self._start_spin(widgets)

    def _row_clicked(self, widgets):
        if widgets.get("click_text"):
            self._copy_to_clipboard(widgets)

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

    def _start_pulse(self, widgets):
        widgets["anim_kind"] = "pulse"

        def tick():
            if widgets.get("anim_kind") != "pulse" or not widgets["row"].winfo_exists():
                return
            widgets["kind"] = "ring" if widgets["kind"] == "dot" else "dot"
            self._paint_row(widgets)
            widgets["anim_id"] = self.root.after(PULSE_PERIOD_MS, tick)

        tick()

    def _start_spin(self, widgets):
        widgets["anim_kind"] = "spin"

        def tick():
            if widgets.get("anim_kind") != "spin" or not widgets["row"].winfo_exists():
                return
            widgets["frame"] = (widgets["frame"] + 1) % draw.SPIN_STEPS
            self._paint_row(widgets)
            widgets["anim_id"] = self.root.after(SPIN_PERIOD_MS, tick)

        tick()

    # ─── Hover tooltip ───────────────────────────────────────────────────────

    def _row_enter(self, widgets):
        self._row_hover(widgets, True)
        # Schedule tooltip if the row has expandable content.
        if not widgets.get("truncated"):
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
                 wraplength=WINDOW_W - 40, justify="left").pack()

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

    def _row_hover(self, widgets, hovering):
        # Only highlight rows that are clickable.
        if not widgets["row"].winfo_exists() or not widgets.get("click_text"):
            return
        widgets["hover"] = hovering
        self._paint_row(widgets)

    def _copy_to_clipboard(self, widgets):
        text = widgets["click_text"]
        try:
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
            )
            p.communicate(text.encode("utf-8"))
        except Exception:
            return

        row, item = widgets["row"], widgets["lbl"]
        original_text = row.itemcget(item, "text")
        row.itemconfig(item, text="已複製", fill=C["green"])

        def restore():
            if row.winfo_exists():
                row.itemconfig(item, text=original_text, fill=widgets["label_color"])

        self.root.after(900, restore)

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
        # Phase trail on stdout (the launcher appends it to gui.log). voxkeys.py
        # only prints phases when no event callback is set, i.e. CLI mode, so
        # without this a stalled queue leaves no trace of where it stopped.
        # flush=True because a stall means the process never exits to flush.
        extras = []
        if e.get("error"):
            extras.append(f"err={e['error']}")
        if e.get("edit_mode"):
            extras.append("edit")
        print(f"[{time.strftime('%H:%M:%S')}] #{e.get('job_id')} {e.get('phase')}"
              + ((" " + " ".join(extras)) if extras else ""), flush=True)

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
        # The capsule tracks every job even while the settings page is open.
        self._capsule_on_event(e)
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
        "gpustack": "GPUStack (Qwen)",
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
        "gpustack": "GPUStack",
    }
    STT_PROVIDER_FROM_LABEL = {v: k for k, v in STT_PROVIDER_LABELS.items()}

    def _build_settings_page(self):
        self._clear()
        self.showing_settings = True

        hdr = self._build_header("設定", back=self._back_to_main)
        self.settings_actions = tk.Frame(hdr, bg=C["base"])
        make_button(self.settings_actions, "儲存", self._save_settings,
                    variant="primary").pack(side="right")
        make_button(self.settings_actions, "取消",
                    self._cancel_settings_changes).pack(side="right", padx=(0, 6))
        self._settings_hdr = hdr
        self._settings_actions_item = hdr.create_window(
            WINDOW_W - 12, HEADER_H // 2, anchor="e", window=self.settings_actions,
            state="hidden")

        form = tk.Frame(self.root, bg=C["base"])
        form.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self._settings_form = form

        self._settings_loading = True
        self._init_settings_vars()
        self._build_all_settings(form)
        self._settings_snapshot = self._settings_values()
        self._settings_dirty = False
        self._settings_loading = False
        self._sync_settings_actions()

    def _init_settings_vars(self):
        provider = self.cfg["provider"] if self.cfg["provider"] in self.PROVIDER_LABELS else "gpustack"
        provider_display = self.PROVIDER_LABELS[provider]
        self.provider_var = tk.StringVar(value=provider_display)
        self.key_var = tk.StringVar(value=self._current_key())

        stt_display = self.STT_PROVIDER_LABELS.get(
            self.cfg.get("stt_provider", "local"), "Local Whisper (faster-whisper, CPU)"
        )
        self.stt_var = tk.StringVar(value=stt_display)
        self.model_var = tk.StringVar(value=self.cfg["whisper_model"])
        self.gpustack_model_var = tk.StringVar(value=self.cfg.get(
            "gpustack_stt_model", voxkeys.GPUSTACK_STT_MODELS[0]
        ))
        self.gpustack_url_var = tk.StringVar(value=self.cfg.get("gpustack_base_url", ""))
        self.gpustack_key_var = tk.StringVar(value=self.cfg.get("gpustack_api_key", ""))
        self.polish_model_var = tk.StringVar(value=self.cfg["gpustack_polish_model"])
        hotkey_display = HOTKEY_LABELS.get(
            self.cfg.get("record_hotkey", "f9"), "F9"
        )
        self.hotkey_var = tk.StringVar(value=hotkey_display)
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
            self.hotkey_var,
            self.groq_var,
            self.gpustack_model_var,
            self.gpustack_url_var,
            self.gpustack_key_var,
            self.polish_model_var,
        ):
            var.trace_add("write", self._mark_settings_dirty)

    def _build_all_settings(self, parent):
        self._section_header(parent, "AI 潤稿")

        provider_cb = self._combo_row(
            parent, "潤稿服務", self.provider_var,
            list(self.PROVIDER_LABELS.values())
        )
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_change)

        self.polish_key_row = self._row(parent)
        self.key_label = self._row_label(self.polish_key_row, self._key_label_text())
        self.key_entry = self._entry(self.polish_key_row, self.key_var)
        self.polish_model_frame = tk.Frame(parent, bg=C["base"])
        self.polish_model_frame.pack(fill="x")
        self.polish_model_row = self._row(self.polish_model_frame)
        self._row_label(self.polish_model_row, "Qwen 模型")
        self._entry(self.polish_model_row, self.polish_model_var, secret=False)
        SettingSwitch(parent, "依 App 調整語氣", None,
                      self.per_app_var, self._toggle_per_app_prompts,
                      ).pack(fill="x", pady=(0, 10))

        self._section_header(parent, "語音辨識")

        stt_cb = self._combo_row(
            parent, "辨識引擎", self.stt_var,
            list(self.STT_PROVIDER_LABELS.values())
        )
        stt_cb.bind("<<ComboboxSelected>>", self._on_stt_change)

        # Packed and unpacked by _sync_stt_fields_visibility; this holder keeps
        # them above the appearance section.
        self.stt_fields = tk.Frame(parent, bg=C["base"])
        self.stt_fields.pack(fill="x")
        self.local_model_frame = tk.Frame(self.stt_fields, bg=C["base"])
        self._combo_row(self.local_model_frame, "Whisper 模型", self.model_var,
                        ["tiny", "base", "small", "medium", "large-v3"])

        # Record Key is not exposed here — it stays whatever record_hotkey says in
        # ~/.config/voxkeys/config.json. The main page already shows the active key.

        self.groq_key_frame = tk.Frame(self.stt_fields, bg=C["base"])
        groq_row = self._row(self.groq_key_frame)
        self._row_label(groq_row, "Groq API 金鑰")
        self._entry(groq_row, self.groq_var)
        self.gpustack_frame = tk.Frame(self.stt_fields, bg=C["base"])
        gpustack_combo = self._combo_row(
            self.gpustack_frame,
            "GPUStack 模型",
            self.gpustack_model_var,
            list(voxkeys.GPUSTACK_STT_MODELS),
        )
        self.gpustack_stt_row = gpustack_combo.master
        self.gpustack_url_row = self._row(self.gpustack_frame)
        self._row_label(self.gpustack_url_row, "GPUStack 網址")
        self._entry(self.gpustack_url_row, self.gpustack_url_var, secret=False)
        gpustack_key_row = self._row(self.gpustack_frame)
        self._row_label(gpustack_key_row, "GPUStack 金鑰")
        self._entry(gpustack_key_row, self.gpustack_key_var)

        self._section_header(parent, "外觀", top_pad=4)
        alpha_row = tk.Frame(parent, bg=C["base"])
        alpha_row.pack(fill="x")
        tk.Label(alpha_row, text="不透明度", font=FONT_BODY, bg=C["base"],
                 fg=C["text"]).pack(side="left")
        self.alpha_value = tk.Label(alpha_row, text=f"{self.alpha_var.get()}%",
                                    font=FONT_SMALL, bg=C["base"], fg=C["subtext"],
                                    width=5, anchor="e")
        self.alpha_value.pack(side="right")
        Slider(alpha_row, self.alpha_var, 70, 100,
               self._on_alpha_change).pack(side="right", padx=(0, 4))

        self._sync_stt_fields_visibility()
        self._sync_polish_fields_visibility()

    def _fit_settings_height(self):
        """Size the window to the form; the provider choices show and hide
        fields, so a fixed height either clips or leaves a gap."""
        form = getattr(self, "_settings_form", None)
        if form is None or not form.winfo_exists():
            return
        self.root.update_idletasks()
        h = HEADER_H + form.winfo_reqheight() + 14
        self._set_window_height(min(h, self.root.winfo_screenheight() - 80))

    def _on_stt_change(self, event=None):
        self._sync_stt_fields_visibility()

    def _sync_stt_fields_visibility(self):
        if not hasattr(self, "groq_key_frame"):
            return
        stt = self.STT_PROVIDER_FROM_LABEL.get(self.stt_var.get(), "local")
        frames = {
            "local": self.local_model_frame,
            "groq": self.groq_key_frame,
        }
        for provider, frame in frames.items():
            if provider == stt:
                if not frame.winfo_manager():
                    frame.pack(fill="x")
            else:
                frame.pack_forget()
        uses_gpustack = stt == "gpustack" or self._selected_provider() == "gpustack"
        if uses_gpustack:
            self.gpustack_frame.pack(fill="x")
        else:
            self.gpustack_frame.pack_forget()
        if stt == "gpustack":
            self.gpustack_stt_row.pack(fill="x", pady=(0, 7), before=self.gpustack_url_row)
        else:
            self.gpustack_stt_row.pack_forget()
        self._fit_settings_height()

    # Settings fields stack the label above a full-width control: the panel
    # is too narrow for label and field side by side.

    def _row(self, parent):
        row = tk.Frame(parent, bg=C["base"])
        row.pack(fill="x", pady=(0, 8))
        return row

    def _row_label(self, row, text):
        label = tk.Label(row, text=text, font=FONT_SMALL,
                         bg=C["base"], fg=C["subtext"], anchor="w")
        label.pack(fill="x", pady=(0, 3))
        return label

    def _combo_row(self, parent, label, variable, values):
        row = self._row(parent)
        self._row_label(row, label)
        combo = ttk.Combobox(row, textvariable=variable, values=values,
                             state="readonly", width=1)
        combo.pack(fill="x", ipady=2)
        return combo

    def _entry(self, row, variable, *, secret=True):
        entry = tk.Entry(row, textvariable=variable, show="•" if secret else "",
                         font=FONT_MONO_ENTRY, width=1,
                         bg=C["surface0"], fg=C["text"],
                         insertbackground=C["text"],
                         relief="flat", bd=0,
                         highlightthickness=1,
                         highlightcolor=C["mauve"],
                         highlightbackground=C["surface1"])
        entry.pack(fill="x", ipady=4)
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
        names = {"openai": "OpenAI API 金鑰", "claude": "Anthropic API 金鑰"}
        return names.get(p, "API 金鑰")

    def _current_key(self):
        p = self._selected_provider()
        keys = {"openai": "openai_api_key", "claude": "anthropic_api_key"}
        return self.cfg.get(keys.get(p, ""), "")

    def _on_provider_change(self, event=None):
        self.key_label.config(text=self._key_label_text())
        self.key_var.set(self._current_key())
        self._sync_polish_fields_visibility()
        self._sync_stt_fields_visibility()

    def _sync_polish_fields_visibility(self):
        if self._selected_provider() == "gpustack":
            self.polish_key_row.pack_forget()
            self.polish_model_row.pack(fill="x", pady=(0, 7))
        else:
            self.polish_key_row.pack(fill="x", pady=(0, 7), before=self.polish_model_frame)
            self.polish_model_row.pack_forget()
        self._fit_settings_height()

    def _settings_values(self):
        return {
            "provider": self._selected_provider(),
            "api_key": self.key_var.get(),
            "stt_provider": self.STT_PROVIDER_FROM_LABEL.get(self.stt_var.get(), "local"),
            "whisper_model": self.model_var.get(),
            "record_hotkey": HOTKEY_FROM_LABEL.get(self.hotkey_var.get(), "f9"),
            "groq_api_key": self.groq_var.get(),
            "gpustack_stt_model": self.gpustack_model_var.get(),
            "gpustack_base_url": self.gpustack_url_var.get(),
            "gpustack_api_key": self.gpustack_key_var.get(),
            "gpustack_polish_model": self.polish_model_var.get(),
        }

    def _mark_settings_dirty(self, *_args):
        if getattr(self, "_settings_loading", False):
            return
        dirty = self._settings_values() != getattr(self, "_settings_snapshot", {})
        self._settings_dirty = dirty
        self._sync_settings_actions()

    def _sync_settings_actions(self):
        hdr = getattr(self, "_settings_hdr", None)
        if hdr is None or not hdr.winfo_exists():
            return
        dirty = getattr(self, "_settings_dirty", False)
        hdr.itemconfigure(self._settings_actions_item, state="normal" if dirty else "hidden")

    def _cancel_settings_changes(self):
        self._settings_loading = True
        provider = self.cfg["provider"] if self.cfg["provider"] in self.PROVIDER_LABELS else "gpustack"
        self.provider_var.set(self.PROVIDER_LABELS[provider])
        self.key_var.set(self._current_key())
        stt_display = self.STT_PROVIDER_LABELS.get(
            self.cfg.get("stt_provider", "local"), self.STT_PROVIDER_LABELS["local"]
        )
        self.stt_var.set(stt_display)
        self.model_var.set(self.cfg["whisper_model"])
        self.hotkey_var.set(
            HOTKEY_LABELS.get(self.cfg.get("record_hotkey", "f9"), "F9")
        )
        self.groq_var.set(self.cfg.get("groq_api_key", ""))
        self.gpustack_model_var.set(self.cfg.get(
            "gpustack_stt_model", voxkeys.GPUSTACK_STT_MODELS[0]
        ))
        self.gpustack_url_var.set(self.cfg.get("gpustack_base_url", ""))
        self.gpustack_key_var.set(self.cfg.get("gpustack_api_key", ""))
        self.polish_model_var.set(self.cfg["gpustack_polish_model"])
        if hasattr(self, "key_label") and self.key_label.winfo_exists():
            self.key_label.config(text=self._key_label_text())
        self._sync_stt_fields_visibility()
        self._sync_polish_fields_visibility()
        self._settings_snapshot = self._settings_values()
        self._settings_dirty = False
        self._settings_loading = False
        self._sync_settings_actions()

    def _save_settings(self):
        # The provider dropdown only lists polish backends; keep "none" while
        # the AI Polish toggle is off so saving other settings cannot re-enable it.
        provider = self._selected_provider() if self.use_ai else "none"
        key_field = {"openai": "openai_api_key",
                     "claude": "anthropic_api_key"}.get(self._selected_provider())
        stt = self.STT_PROVIDER_FROM_LABEL.get(self.stt_var.get(), "local")

        updates = {
            "provider": provider,
            "whisper_model": self.model_var.get(),
            "record_hotkey": HOTKEY_FROM_LABEL.get(self.hotkey_var.get(), "f9"),
            "language": self.cfg.get("language", "zh"),
            "output_language": self.cfg.get("output_language", ""),
            "stt_provider": stt,
            "groq_api_key": self.groq_var.get(),
            "gpustack_stt_model": self.gpustack_model_var.get(),
            "gpustack_base_url": self.gpustack_url_var.get().rstrip("/"),
            "gpustack_api_key": self.gpustack_key_var.get(),
            "gpustack_polish_model": self.polish_model_var.get().strip(),
            "per_app_prompts": bool(self.cfg.get("per_app_prompts", False)),
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
        tk.Label(body, text="無法監聽快捷鍵",
                 font=FONT_TITLE,
                 bg=C["base"], fg=C["red"]).pack(pady=(0, 6))
        tk.Label(body, text=message,
                 font=FONT_SMALL, wraplength=WINDOW_W - 40, justify="center",
                 bg=C["base"], fg=C["subtext"]).pack()
        make_button(body, "打開設定", self._build_settings_page,
                    variant="primary").pack(pady=(12, 0))

    # ─── Floating Capsule ────────────────────────────────────────────────────

    CAPSULE_TERMINAL = {"done", "polish_failed", "empty", "error"}
    CAPSULE_FLASH_MS = 2000

    def _build_capsule(self):
        """Always-on-top status pill. Drag to move, drag the right end to
        resize, click to open the panel. Drawn on one canvas so the outline
        and icons are antialiased; the window itself is clipped to the pill."""
        cap = tk.Toplevel(self.root)
        cap.wm_overrideredirect(True)
        cap.attributes("-topmost", True)
        try:
            cap.attributes("-type", "dock")  # keep it out of the taskbar / alt-tab
        except tk.TclError:
            pass
        cap.configure(bg=C["base"])
        self.capsule = cap
        self._cap_jobs = {}           # job_id -> phase, busy jobs only
        self._cap_rec_start = None
        self._cap_flash = None        # (icon kind, color_key, text) of last finished job
        self._cap_flash_after = None
        self._cap_tick_after = None
        self._cap_spin_i = 0
        self._cap_drag = None
        self._cap_resize = None
        self._cap_shaped_w = None     # width the window shape was last cut for
        self._cap_w = max(CAPSULE_MIN_W, int(self.cfg.get("capsule_w") or CAPSULE_DEFAULT_W))
        self._cap_h = CAPSULE_H
        self._cap_font = tkfont.Font(root=self.root, font=CAPSULE_FONT)
        self._cap_badge_font = tkfont.Font(root=self.root, font=FONT_TINY_BOLD)

        cv = tk.Canvas(cap, width=self._cap_w, height=CAPSULE_H, bg=C["base"],
                       bd=0, highlightthickness=0, cursor="fleur")
        cv.pack(fill="both", expand=True)
        self._cap_cv = cv
        mid = CAPSULE_H // 2
        self._cap_bg = cv.create_image(0, 0, anchor="nw")
        # Inset so the square logo's corners clear the pill's round end.
        cv.create_image(12, mid, anchor="w", image=draw.logo(ICON_PATH, CAPSULE_H - 16, C["base"]))
        self._cap_dot = cv.create_image(CAPSULE_H + 8, mid)
        self._cap_lbl = cv.create_text(CAPSULE_H + 20, mid, anchor="w", font=self._cap_font)
        self._cap_badge_bg = cv.create_image(0, mid, anchor="e", state="hidden")
        self._cap_badge = cv.create_text(0, mid, font=self._cap_badge_font,
                                         fill=C["crust"], state="hidden")
        cv.bind("<ButtonPress-1>", self._cap_press)
        cv.bind("<B1-Motion>", self._cap_motion)
        cv.bind("<ButtonRelease-1>", self._cap_release)
        cv.bind("<Motion>", self._cap_hover)
        cv.bind("<Button-3>", self._cap_menu)

        self._cap_popup = tk.Menu(cap, tearoff=0, bg=C["surface0"], fg=C["text"],
                                  activebackground=C["surface1"], activeforeground=C["text"],
                                  font=FONT_BODY, bd=0, activeborderwidth=0)
        self._cap_popup.add_command(label="打開面板", command=self._open_panel)
        self._cap_popup.add_command(label="隱藏膠囊",
                                    command=lambda: self._set_capsule_visible(False))
        self._cap_popup.add_separator()
        self._cap_popup.add_command(label="結束 Voxkeys", command=self._on_close)

        self._cap_render()
        x, y = self.cfg.get("capsule_x"), self.cfg.get("capsule_y")
        if x is None or y is None:
            x = (cap.winfo_screenwidth() - self._cap_w) // 2
            y = cap.winfo_screenheight() - self._cap_h - 72
        self._cap_pos = self._cap_clamp(int(x), int(y))
        self._cap_place()
        if self.cfg.get("capsule_visible", True):
            self._show_capsule()
        else:
            cap.withdraw()

    def _cap_on_event_phase(self, jid, phase, e):
        if phase == "recording":
            self._cap_rec_start = time.monotonic()
        if phase in self.CAPSULE_TERMINAL:
            self._cap_jobs.pop(jid, None)
            icon, color, label = PHASE_VISUALS[phase]
            text = label or e.get("error") or e.get("polished_text") or e.get("raw_text") or ""
            self._cap_flash = (icon, color, text.strip().replace("\n", " "))
            if self._cap_flash_after:
                self.root.after_cancel(self._cap_flash_after)
            self._cap_flash_after = self.root.after(self.CAPSULE_FLASH_MS, self._cap_end_flash)
        else:
            self._cap_jobs[jid] = phase

    def _capsule_on_event(self, e):
        jid = e.get("job_id")
        phase = e.get("phase")
        if jid is None or phase not in PHASE_VISUALS:
            return
        self._cap_on_event_phase(jid, phase, e)
        self._cap_render()

    def _cap_end_flash(self):
        self._cap_flash = None
        self._cap_flash_after = None
        self._cap_render()

    def _cap_render(self):
        """Draw the capsule from current state: recording > busy > flash > idle."""
        if self._cap_tick_after:
            self.root.after_cancel(self._cap_tick_after)
            self._cap_tick_after = None
        phases = list(self._cap_jobs.values())
        busy = [p for p in phases if p in SPINNING_PHASES]
        badge = ""
        if "recording" in phases:
            secs = int(time.monotonic() - (self._cap_rec_start or time.monotonic()))
            on = (int(time.monotonic() * 1000) // PULSE_PERIOD_MS) % 2 == 0
            kind, color = ("dot" if on else "ring"), "green"
            text = f"錄音中  {secs // 60}:{secs % 60:02d}"
            if busy:
                badge = f"+{len(busy)}"
            self._cap_tick_after = self.root.after(250, self._cap_render)
        elif busy:
            self._cap_spin_i = (self._cap_spin_i + 1) % draw.SPIN_STEPS
            kind, color = "spin", "yellow"
            # Name the job actually being worked on, not one still waiting.
            active = [p for p in busy if p != "queued"]
            text = PHASE_VISUALS[(active or busy)[0]][2]
            if len(busy) > 1:
                badge = f"+{len(busy) - 1}"
            self._cap_tick_after = self.root.after(SPIN_PERIOD_MS, self._cap_render)
        elif self._cap_flash:
            kind, color, text = self._cap_flash
        else:
            kind, color, text = "dot", "mauve", f"{self._hotkey_text()}  開始聽寫"

        cv, w, h = self._cap_cv, self._cap_w, CAPSULE_H
        cv.itemconfig(self._cap_bg, image=draw.rounded_rect(
            w, h, h // 2, C["base"], C["crust"], outline=C[color], width=1.5))
        cv.itemconfig(self._cap_dot, image=draw.status_icon(
            kind, C[color], C["base"], frame=self._cap_spin_i))
        right = w - 12
        if badge:
            bw = self._cap_badge_font.measure(badge) + 14
            cv.itemconfig(self._cap_badge_bg, state="normal",
                          image=draw.rounded_rect(bw, 18, 9, C["mauve"], C["base"]))
            cv.coords(self._cap_badge_bg, right, h // 2)
            cv.itemconfig(self._cap_badge, text=badge, state="normal")
            cv.coords(self._cap_badge, right - bw / 2, h // 2)
            right -= bw + 8
        else:
            cv.itemconfig(self._cap_badge_bg, state="hidden")
            cv.itemconfig(self._cap_badge, state="hidden")
        avail = right - (CAPSULE_H + 20)
        cv.itemconfig(self._cap_lbl, text=fit_px(self._cap_font, text, avail),
                      fill=C["subtext"] if color == "mauve" else C["text"])

    def _cap_clamp(self, x, y):
        """Keep the capsule inside the usable screen area.

        Cinnamon takes every mouse click over its panel, so a capsule dropped
        on the taskbar is still drawn there but can no longer be grabbed.
        """
        left, top = 0, 0
        right, bottom = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        try:
            out = subprocess.run(["xprop", "-root", "_NET_WORKAREA"],
                                 capture_output=True, text=True, timeout=1).stdout
            l, t, w, h = (int(v) for v in out.split("=", 1)[1].split(",")[:4])
            left, top, right, bottom = l, t, l + w, t + h
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass
        x = max(left, min(x, right - self._cap_w))
        y = max(top, min(y, bottom - self._cap_h))
        return (x, y)

    def _cap_place(self):
        w, h = self._cap_w, CAPSULE_H
        self._cap_cv.config(width=w)
        self.capsule.geometry(f"{w}x{h}+{self._cap_pos[0]}+{self._cap_pos[1]}")
        if self._cap_shaped_w != w and self.capsule.winfo_ismapped():
            draw.round_window(self.capsule, w, h, h // 2)
            self._cap_shaped_w = w

    def _cap_on_grip(self, event):
        return event.x >= self._cap_w - CAPSULE_GRIP

    def _cap_hover(self, event):
        self._cap_cv.config(cursor="sb_h_double_arrow" if self._cap_on_grip(event) else "fleur")

    def _cap_press(self, event):
        if self._cap_on_grip(event):
            self._cap_resize = (event.x_root, self._cap_w)
            return
        # winfo_x/y can lag behind geometry() on an override-redirect window,
        # so start from the position this code last placed it at.
        self._cap_drag = (event.x_root, event.y_root, *self._cap_pos, False)

    def _cap_motion(self, event):
        if self._cap_resize:
            x0, w0 = self._cap_resize
            right = self.root.winfo_screenwidth() - self._cap_pos[0]
            self._cap_w = max(CAPSULE_MIN_W, min(right, w0 + event.x_root - x0))
            self._cap_place()
            self._cap_render()
            return
        if not self._cap_drag:
            return
        x0, y0, wx, wy, moved = self._cap_drag
        dx, dy = event.x_root - x0, event.y_root - y0
        if not moved and abs(dx) + abs(dy) < 4:
            return  # small jitter still counts as a click
        self._cap_drag = (x0, y0, wx, wy, True)
        self._cap_pos = (wx + dx, wy + dy)
        self._cap_place()

    def _cap_release(self, _event):
        if self._cap_resize:
            self._cap_resize = None
            self.cfg["capsule_w"] = self._cap_w
            save_config({"capsule_w": self._cap_w})
            return
        drag, self._cap_drag = self._cap_drag, None
        if not drag:
            return
        if drag[4]:
            self._cap_pos = self._cap_clamp(*self._cap_pos)
            self._cap_place()
            self.cfg["capsule_x"], self.cfg["capsule_y"] = self._cap_pos
            save_config({"capsule_x": self._cap_pos[0], "capsule_y": self._cap_pos[1]})
        else:
            self._toggle_panel()

    def _cap_menu(self, event):
        try:
            self._cap_popup.tk_popup(event.x_root, event.y_root)
        finally:
            self._cap_popup.grab_release()

    # Invariant: the capsule or the panel is always on screen, so Voxkeys can
    # never vanish entirely. Withdraw is used instead of iconify because the
    # window manager here ignores iconify requests.

    def _toggle_panel(self):
        if self.root.state() == "normal":
            self._collapse_panel()
        else:
            self._open_panel()

    def _open_panel(self):
        self.root.deiconify()
        self.root.lift()

    def _collapse_panel(self):
        if not self.cfg.get("capsule_visible", True):
            self._set_capsule_visible(True)
        self.root.withdraw()

    def _show_capsule(self):
        self.capsule.deiconify()
        self.capsule.attributes("-topmost", True)
        self.capsule.lift()
        # Tk maps an override-redirect window at +0+0 and drops a geometry set
        # before the map finishes, so place it once the map has settled.
        self.capsule.after(60, self._cap_place)

    def _set_capsule_visible(self, visible):
        self.cfg["capsule_visible"] = bool(visible)
        save_config({"capsule_visible": self.cfg["capsule_visible"]})
        if hasattr(self, "capsule_var") and self.capsule_var.get() != visible:
            try:
                self.capsule_var.set(visible)
            except tk.TclError:
                pass
        if visible:
            self._show_capsule()
        else:
            self.capsule.withdraw()
            self._open_panel()

    # ─── Utilities ───────────────────────────────────────────────────────────

    def _clear(self):
        # The capsule is a Toplevel child of root; page switches must not destroy it.
        for w in self.root.winfo_children():
            if w is not getattr(self, "capsule", None):
                w.destroy()

    def _on_close(self):
        if hasattr(self, "listener"):
            self.listener.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def _claim_single_instance():
    """Return True if this is the only running GUI.

    Every instance owns its own F9 listener, so a second copy would record and
    paste each dictation twice. A second launch instead asks the running copy
    (SIGUSR1) to open its panel and then exits.
    """
    os.makedirs(os.path.dirname(LOCK_PATH), mode=0o700, exist_ok=True)
    fh = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.seek(0)
        try:
            os.kill(int(fh.read().strip()), signal.SIGUSR1)
        except (ValueError, OSError):
            pass
        return False
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    globals()["_lock_handle"] = fh  # keep the lock for the process lifetime
    return True


if __name__ == "__main__":
    if not _claim_single_instance():
        print("Voxkeys is already running; opened its panel instead.", flush=True)
        raise SystemExit(0)
    app = VoxkeysApp()
    signal.signal(signal.SIGUSR1, lambda *_: app.root.after(0, app._open_panel))
    app.run()
