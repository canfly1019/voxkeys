"""Antialiased shapes and icons for the Tk UI, plus rounded window corners.

Tk's canvas draws ovals and arcs without antialiasing, so small rounded shapes
come out as jagged polygons. Everything here is drawn by Pillow at 4x and
scaled down, then composited onto the exact background colour it will sit on
(Tk photo images are opaque on X11, so there is no alpha to rely on).

Images are cached: the cache also keeps the PhotoImage objects alive, which
Tk needs, since it drops an image once Python loses its last reference.
"""

from functools import lru_cache

from PIL import Image, ImageDraw, ImageTk

SS = 4  # supersampling factor


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _new(w, h, bg):
    img = Image.new("RGB", (w * SS, h * SS), _rgb(bg))
    return img, ImageDraw.Draw(img)


def _finish(img, w, h):
    return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))


@lru_cache(maxsize=512)
def rounded_rect(w, h, r, fill, bg, outline=None, width=0):
    """Filled rounded rectangle, optionally outlined; `width` in px."""
    img, d = _new(w, h, bg)
    inset = 0.5 * SS if outline else 0  # keep the outline's soft edge inside
    d.rounded_rectangle(
        (inset, inset, w * SS - 1 - inset, h * SS - 1 - inset),
        radius=r * SS, fill=_rgb(fill),
        outline=_rgb(outline) if outline else None,
        width=round(width * SS) if outline else 0)
    return _finish(img, w, h)


@lru_cache(maxsize=8)
def switch(on, track_on, track_off, knob, bg, w=36, h=20):
    img, d = _new(w, h, bg)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=h * SS // 2,
                        fill=_rgb(track_on if on else track_off))
    pad = 3 * SS
    k = h * SS - 2 * pad
    x = w * SS - pad - k if on else pad
    d.ellipse((x, pad, x + k, pad + k), fill=_rgb(knob))
    return _finish(img, w, h)


@lru_cache(maxsize=64)
def slider(w, h, frac, fill, track, knob, bg):
    """Horizontal slider: a thin rounded track, filled up to `frac`, and a knob."""
    img, d = _new(w, h, bg)
    k = (h - 4) * SS                       # knob diameter
    cy = h * SS / 2
    t = 4 * SS                             # track thickness
    x0, x1 = k / 2, w * SS - k / 2
    kx = x0 + (x1 - x0) * frac
    d.rounded_rectangle((x0, cy - t / 2, x1, cy + t / 2), radius=t / 2, fill=_rgb(track))
    d.rounded_rectangle((x0, cy - t / 2, kx, cy + t / 2), radius=t / 2, fill=_rgb(fill))
    d.ellipse((kx - k / 2, cy - k / 2, kx + k / 2, cy + k / 2), fill=_rgb(knob))
    return _finish(img, w, h)


SPIN_STEPS = 8


@lru_cache(maxsize=256)
def status_icon(kind, color, bg, size=14, frame=0):
    """Job-state marks: dot, ring, spin (animated by `frame`), check, cross, dash."""
    img, d = _new(size, size, bg)
    s = size * SS
    c = _rgb(color)
    stroke = round(1.7 * SS)
    if kind == "dot":
        r = s * 0.28
        d.ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), fill=c)
    elif kind == "ring":
        r = s * 0.28
        d.ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), outline=c, width=stroke)
    elif kind == "spin":
        m = s * 0.16
        faint = tuple(round(a * 0.3 + b * 0.7) for a, b in zip(c, _rgb(bg)))
        d.ellipse((m, m, s - m, s - m), outline=faint, width=stroke)
        start = frame * 360 / SPIN_STEPS
        d.arc((m, m, s - m, s - m), start, start + 100, fill=c, width=stroke)
    elif kind == "check":
        pts = [(s * 0.2, s * 0.52), (s * 0.42, s * 0.72), (s * 0.8, s * 0.3)]
        d.line(pts, fill=c, width=stroke, joint="curve")
    elif kind == "cross":
        a, b = s * 0.27, s * 0.73
        d.line((a, a, b, b), fill=c, width=stroke)
        d.line((a, b, b, a), fill=c, width=stroke)
    elif kind == "dash":
        d.line((s * 0.3, s / 2, s * 0.7, s / 2), fill=c, width=stroke)
    return _finish(img, size, size)


@lru_cache(maxsize=32)
def action_icon(name, color, bg, plate=None, size=30):
    """Header icons drawn as strokes: settings, collapse, back.

    `plate` paints a rounded hover background behind the stroke.
    """
    img, d = _new(size, size, bg)
    s = size * SS
    if plate:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=8 * SS, fill=_rgb(plate))
    c = _rgb(color)
    w = round(1.6 * SS)
    if name == "settings":
        # Two slider lines with knobs: reads as "adjust", without a gear glyph.
        for y, kx in ((0.38, 0.62), (0.62, 0.38)):
            d.line((s * 0.28, s * y, s * 0.72, s * y), fill=c, width=w)
            r = s * 0.075
            d.ellipse((s * kx - r, s * y - r, s * kx + r, s * y + r),
                      fill=_rgb(plate or bg), outline=c, width=w)
    elif name == "collapse":
        d.line((s * 0.32, s / 2, s * 0.68, s / 2), fill=c, width=w)
    elif name == "close":
        d.line((s * 0.34, s * 0.34, s * 0.66, s * 0.66), fill=c, width=w)
        d.line((s * 0.34, s * 0.66, s * 0.66, s * 0.34), fill=c, width=w)
    elif name == "back":
        d.line([(s * 0.56, s * 0.32), (s * 0.4, s / 2), (s * 0.56, s * 0.68)],
               fill=c, width=w, joint="curve")
    return _finish(img, size, size)


@lru_cache(maxsize=8)
def logo(path, size, bg):
    src = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    out = Image.new("RGB", (size, size), _rgb(bg))
    out.paste(src, mask=src.split()[3])
    return ImageTk.PhotoImage(out)


# ─── Window shape (X11) ──────────────────────────────────────────────────────

_xdisplay = None


def _display():
    global _xdisplay
    if _xdisplay is None:
        from Xlib import display
        _xdisplay = display.Display()
    return _xdisplay


def _wrapper(widget):
    """Tk puts each toplevel inside a wrapper window; that is the one the
    window manager sees, so shape and hints go there."""
    d = _display()
    win = d.create_resource_object("window", widget.winfo_id())
    return d, win.query_tree().parent


def round_window(widget, w, h, r, *, own=False, inset=0):
    """Clip a window to a rounded rectangle via the X SHAPE extension.

    By default the toplevel's wrapper is shaped; `own` shapes the widget's
    own X window instead (used for the inner frame that leaves a 1px ring of
    the toplevel's background as a border).

    The mask is 1-bit, so the cut edge is not antialiased. When the window
    carries its own antialiased border, set `inset` to land the cut on the
    border's centerline: outside the cut is clipped away, and the border's
    inner half ends the pill in full color, so the staircase is invisible.
    Without it, the cut slices the border's outer edge and leaves a fuzzy
    hairline along the curve.
    """
    try:
        from Xlib.ext import shape
        if own:
            d = _display()
            win = d.create_resource_object("window", widget.winfo_id())
        else:
            d, win = _wrapper(widget)
        pm = win.create_pixmap(w, h, 1)
        gc = pm.create_gc(foreground=0, background=0)
        pm.fill_rectangle(gc, 0, 0, w, h)
        gc.change(foreground=1)
        s = inset
        r = min(r, (w - 2 * s) // 2, (h - 2 * s) // 2)
        pm.fill_rectangle(gc, r + s, s, w - 2 * (r + s), h - 2 * s)
        pm.fill_rectangle(gc, s, r + s, w - 2 * s, h - 2 * (r + s))
        # Right/bottom arcs start at w/h - s - 2r so the cut mirrors the
        # left/top; w - 2*(r+s) would clip `s` extra px on the right end.
        for x, y in ((s, s), (w - s - 2 * r, s),
                     (s, h - s - 2 * r), (w - s - 2 * r, h - s - 2 * r)):
            pm.fill_arc(gc, x, y, 2 * r, 2 * r, 0, 360 * 64)
        win.shape_mask(shape.SO.Set, shape.SK.Bounding, 0, 0, pm)
        gc.free()
        pm.free()
        d.flush()
    except Exception:
        pass  # square corners are an acceptable fallback


def undecorate(widget):
    """Ask the window manager to drop the title bar but keep managing the
    window (focus, stacking), unlike override-redirect."""
    try:
        d, win = _wrapper(widget)
        atom = d.intern_atom("_MOTIF_WM_HINTS")
        win.change_property(atom, atom, 32, [2, 0, 0, 0, 0])  # flags=decorations, none
        d.flush()
    except Exception:
        pass
