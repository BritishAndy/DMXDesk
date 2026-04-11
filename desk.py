#!/usr/bin/env python3
"""
DMX Desk Emulator
Reads a fixture patch from patch.json and outputs Art-Net DMX.

Fixture definitions live in a fixtures/ folder next to desk.py.
Each file is named <type>.json and defines the channels for that fixture type.
Built-in types (dimmer, rgb, rgbw) are auto-generated if no definition file exists.

patch.json format:
  [
    {"name": "Spot 1",   "type": "moving_head", "address": 1},
    {"name": "Wash 1",   "type": "rgbw",        "address": 9},
    {"name": "Wash Sub", "type": "submaster",   "targets": ["Wash 1"]}
  ]

Fixture definition format (fixtures/moving_head.json):
  {
    "channels": [
      {"label": "Intensity", "master": true,  "default": 0,   "range": [0, 100], "unit": "%",     "show": true},
      {"label": "Red",       "master": false, "default": 0,   "range": [0, 255], "unit": "raw",   "show": true},
      {"label": "Mode",      "master": false, "default": 0,
       "range": {"0-63": "Sound", "64-127": "Auto", "128-255": "Manual"},
       "unit": "named", "show": true}
    ]
  }

Channel state is stored as a flat list of raw values (one per visible channel),
with None for channels not included in a partial (solo) scene.
"""

import json
import argparse
import threading
import struct

VERSION = "1.0"
BUILD   = 78
import socket as _socket
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# ── Window preferences ─────────────────────────────────────────────────────────
# When running as a py2app bundle, resources are in Contents/Resources
# When running directly, they're alongside desk.py
def _app_dir() -> Path:
    """Return the directory where show files and fixtures live."""
    import sys
    if getattr(sys, 'frozen', False):
        # py2app bundle — Resources folder
        return Path(sys.executable).parent.parent / "Resources"
    return Path(__file__).parent

APP_DIR      = _app_dir()
PREFS_FILE   = APP_DIR / "desk_prefs.json"

def load_prefs() -> dict:
    try:
        if PREFS_FILE.exists():
            return json.load(open(PREFS_FILE))
    except Exception:
        pass
    return {}

def save_prefs(data: dict):
    try:
        with open(PREFS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

# ── Art-Net ────────────────────────────────────────────────────────────────────

dmx_values = [0] * 512
_artnet_sock     = None
_artnet_last_send = 0.0  # timestamp of last successful send
_artnet_error     = False
_artnet_ip       = None
_artnet_port     = 6454
_artnet_universe = 0
_artnet_sequence = 0
_dmx_interval_ms = 25   # DMX update rate (ms)
_fade_steps_sec  = 40   # Fade interpolation steps per second
_osc_enabled     = True
_osc_port        = 8000
_scene_layout    = "paired"  # "sequential" = 1-12/13-24, "paired" = odd/even
_current_show_file = None   # path of currently loaded scenes file
_reload_last_show  = False  # auto-reload last show on startup
_osc_sock        = None

_ARTNET_HEADER = bytearray([
    0x41, 0x72, 0x74, 0x2d, 0x4e, 0x65, 0x74, 0x00,
    0x00, 0x50, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00,
])

def start_artnet(ip: str, port: int = 6454, universe: int = 0):
    global _artnet_sock, _artnet_ip, _artnet_port, _artnet_universe
    _artnet_sock     = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    _artnet_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    _artnet_ip       = ip
    _artnet_port     = port
    _artnet_universe = universe
    print(f"Art-Net UDP socket ready, targeting {ip}:{port} universe {universe}")

def send_defaults(patch: list):
    """Send a final DMX frame with each fixture channel at its default value.
    Called on exit so fixtures hold their default state rather than snapping to zero."""
    if _artnet_sock is None or dry_run:
        return
    # Reset all channels to 0 first
    defaults = bytearray(512)
    for fix in patch:
        ftype = fix.get("type", "").lower()
        if ftype in ("submaster", "divider", "clock"):
            continue
        address = fix.get("address")
        if not address:
            continue
        try:
            defn = load_fixture_def(ftype)
            for i, ch in enumerate(defn.get("channels", [])):
                val = int(ch.get("default", 0))
                idx = address + i - 1
                if 0 <= idx < 512:
                    defaults[idx] = max(0, min(255, val))
        except Exception:
            pass
    # Build and send Art-Net packet with defaults
    header = bytearray(_ARTNET_HEADER)
    header[14] = _artnet_universe & 0xFF
    header[15] = (_artnet_universe >> 8) & 0xFF
    try:
        _artnet_sock.sendto(bytes(header) + bytes(defaults), (_artnet_ip, _artnet_port))
        print("Sent fixture defaults on exit.")
    except Exception:
        pass

def send_dmx():
    global _artnet_sequence, _artnet_last_send, _artnet_error
    if _artnet_sock is None:
        return
    _artnet_sequence = (_artnet_sequence + 1) % 256
    header = bytearray(_ARTNET_HEADER)
    header[12] = _artnet_sequence
    header[14] = _artnet_universe & 0xFF
    header[15] = (_artnet_universe >> 8) & 0xFF
    try:
        _artnet_sock.sendto(bytes(header) + bytes(dmx_values), (_artnet_ip, _artnet_port))
        _artnet_last_send = __import__('time').time()
        _artnet_error = False
    except Exception as e:
        _artnet_error = True

def set_channel(address: int, value: int):
    dmx_values[address - 1] = max(0, min(255, int(value)))

def apply_grand_master(fixture_widgets):
    gm = gm_var.get() / 100.0
    for fw in fixture_widgets:
        fw.apply_gm(gm)
    if not dry_run:
        send_dmx()

# ── Submaster registry ─────────────────────────────────────────────────────────

submaster_registry = {}

def get_submaster_scale(fixture_name: str) -> float:
    scale = 1.0
    for sm in submaster_registry.get(fixture_name, []):
        scale *= sm.level
    return scale

# ── Copy/paste clipboard ───────────────────────────────────────────────────────
_clipboard = {
    "state":    None,   # copied channel state dict
    "type_key": None,   # fixture type fingerprint for compatibility check
}

# ── Fixture definition loader ──────────────────────────────────────────────────

FIXTURES_DIR = APP_DIR / "fixtures"
MANUAL_FILE  = APP_DIR / "DMX_Desk_Manual.pdf"

# Built-in definitions — used when no .json file exists
_BUILTIN_DEFS = {
    "dimmer": {"channels": [
        {"label": "Dimmer", "master": True, "default": 0,
         "range": [0, 100], "unit": "%", "show": True},
    ]},
    "rgb": {"channels": [
        {"label": "Intensity", "master": True,  "default": 0,   "range": [0, 100], "unit": "%",   "show": True},
        {"label": "R",         "master": False, "default": 0,   "range": [0, 255], "unit": "raw", "show": True},
        {"label": "G",         "master": False, "default": 0,   "range": [0, 255], "unit": "raw", "show": True},
        {"label": "B",         "master": False, "default": 0,   "range": [0, 255], "unit": "raw", "show": True},
    ]},
    "rgbw": {"channels": [
        {"label": "Intensity", "master": True,  "default": 0,   "range": [0, 100], "unit": "%",   "show": True},
        {"label": "R",         "master": False, "default": 0,   "range": [0, 255], "unit": "raw", "show": True},
        {"label": "G",         "master": False, "default": 0,   "range": [0, 255], "unit": "raw", "show": True},
        {"label": "B",         "master": False, "default": 0,   "range": [0, 255], "unit": "raw", "show": True},
        {"label": "W",         "master": False, "default": 255, "range": [0, 255], "unit": "raw", "show": True},
    ]},
}

_def_cache = {}

def load_fixture_def(ftype: str) -> dict:
    """Load a fixture definition from fixtures/<ftype>.json, or use built-in."""
    if ftype in _def_cache:
        return _def_cache[ftype]
    path = FIXTURES_DIR / f"{ftype}.json"
    if path.exists():
        with open(path) as f:
            defn = json.load(f)
    elif ftype in _BUILTIN_DEFS:
        defn = _BUILTIN_DEFS[ftype]
    else:
        raise ValueError(f"Unknown fixture type '{ftype}' — no definition file at {path}")
    _def_cache[ftype] = defn
    return defn

def channel_range(ch: dict) -> tuple[int, int]:
    """Return (lo, hi) raw DMX range for a channel."""
    r = ch.get("range", [0, 255])
    if isinstance(r, list):
        return (int(r[0]), int(r[1]))
    elif isinstance(r, dict):
        # Named range — extract min/max from keys like "0-63"
        vals = []
        for k in r:
            parts = k.split("-")
            vals += [int(p) for p in parts]
        return (min(vals), max(vals))
    return (0, 255)

def named_label(ch: dict, raw_value: int) -> str:
    """Return the named label for a raw value, or empty string if not a named channel."""
    r = ch.get("range")
    if not isinstance(r, dict):
        return ""
    for k, name in r.items():
        parts = k.split("-")
        lo, hi = int(parts[0]), int(parts[-1])
        if lo <= raw_value <= hi:
            return name
    return ""

def raw_to_dmx(ch: dict, raw: int) -> int:
    """Convert a raw fader value to a DMX value (0-255)."""
    lo, hi = channel_range(ch)
    if hi == lo:
        return lo
    # Scale raw (lo..hi) → 0..255
    return int((raw - lo) / (hi - lo) * 255)

# ── MacButton ──────────────────────────────────────────────────────────────────

def _darken(hex_col: str, factor: float = 0.72) -> str:
    hex_col = hex_col.lstrip("#")
    r, g, b = (int(hex_col[i:i+2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(int(r*factor), int(g*factor), int(b*factor))

class MacButton(tk.Label):
    def __init__(self, parent, text, bg, fg, command=None,
                 activebackground=None, activeforeground=None, **kwargs):
        self._bg = bg; self._fg = fg
        self._active_bg = activebackground or _darken(bg)
        self._active_fg = activeforeground or fg
        self._command = command
        super().__init__(parent, text=text, bg=bg, fg=fg, cursor="hand2", **kwargs)
        self.bind("<ButtonPress-1>",  self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, e=None):
        if e and (e.state & 0x4):  return  # Ctrl held — skip highlight
        self.config(bg=self._active_bg, fg=self._active_fg)
    def _on_release(self, _=None):
        self.config(bg=self._bg, fg=self._fg)
        if self._command: self._command()

    def config(self, **kw):
        if "bg" in kw: self._bg = kw["bg"]
        if "fg" in kw: self._fg = kw["fg"]
        if "activebackground" in kw: self._active_bg = kw.pop("activebackground")
        if "activeforeground" in kw: self._active_fg = kw.pop("activeforeground")
        super().config(**kw)
    def configure(self, **kw): self.config(**kw)

def btn(parent, text, bg, fg, command=None, **kw):
    kw.setdefault("padx", 8); kw.setdefault("pady", 4)
    return MacButton(parent, text=text, bg=bg, fg=fg, command=command,
                     activebackground=_darken(bg), activeforeground=fg, **kw)

# ── SoloButton ─────────────────────────────────────────────────────────────────

SOLO_OFF_BG = "#333333"; SOLO_OFF_FG = "#666666"
SOLO_ON_BG  = "#ddaa00"; SOLO_ON_FG  = "#000000"

class SoloButton(tk.Label):
    def __init__(self, parent, **kw):
        self._soloed = False
        self._command = None
        super().__init__(parent, text="S", bg=SOLO_OFF_BG, fg=SOLO_OFF_FG,
                         font=("Helvetica", 6, "bold"), cursor="hand2",
                         padx=1, pady=1, **kw)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_release(self, _=None):
        self._soloed = not self._soloed
        self.config(bg=SOLO_ON_BG if self._soloed else SOLO_OFF_BG,
                    fg=SOLO_ON_FG if self._soloed else SOLO_OFF_FG)
        if self._command: self._command()

    @property
    def soloed(self): return self._soloed

    def reset(self):
        self._soloed = False
        self.config(bg=SOLO_OFF_BG, fg=SOLO_OFF_FG)

    def set_on(self):
        self._soloed = True
        self.config(bg=SOLO_ON_BG, fg=SOLO_ON_FG)

# ── Size system ────────────────────────────────────────────────────────────────

def make_sizes(z: float) -> dict:
    return {
        "master_h":  int(160 * z),  "master_w":  int(28 * z),
        "ch_h":      int(80  * z),  "ch_w":      int(16 * z),
        "name_font": max(6, int(9 * z)),
        "val_font":  max(6, int(9 * z)),
        "btn_font":  max(5, int(8 * z)),
        "ch_font":   max(5, int(7 * z)),
        "btn_w":     max(3, int(6 * z)),
        "btn_pad":   max(1, int(3 * z)),
        "wrap":      int(80 * z),
    }

DEFAULT_SIZES = make_sizes(1.0)

# ── CustomFixture ──────────────────────────────────────────────────────────────

class CustomFixture(tk.Frame):
    """
    Universal fixture widget. Driven entirely by a channel definition list.
    Each visible channel gets a fader + solo button.
    The master channel (if any) is shown prominently at the top.
    Hidden channels send their default value to DMX and are never shown.
    """

    def __init__(self, parent, name: str, address: int,
                 channel_defs: list, sz: dict = None, colour: str = "#2b2b2b", **kwargs):
        super().__init__(parent, **kwargs)
        self.name = name
        self.address = address
        self.channel_defs = channel_defs   # full list including hidden
        sz  = sz or DEFAULT_SIZES
        bg  = colour
        self._bg = bg

        self.configure(relief=tk.RIDGE, bd=2, padx=4, pady=4, bg=bg,
                       highlightthickness=2, highlightbackground=bg)

        # Separate channels
        self._master_idx  = None   # index into channel_defs
        self._visible     = []     # (orig_idx, ch_def) for shown non-master channels
        self._hidden      = []     # (orig_idx, ch_def) for hidden channels

        for i, ch in enumerate(channel_defs):
            if ch.get("master") and self._master_idx is None:
                self._master_idx = i
            elif not ch.get("show", True):
                self._hidden.append((i, ch))
            elif not ch.get("master"):
                self._visible.append((i, ch))

        # Raw values for every channel (fader position in channel's own range)
        lo_hi = [channel_range(ch) for ch in channel_defs]
        self._raw = [ch.get("default", lo_hi[i][0]) for i, ch in enumerate(channel_defs)]
        self._pre_bump = 0  # stores master value before a bump

        # ── Header: name + (if not compact) fixture-level solo ──
        header = tk.Frame(self, bg=bg)
        header.pack(fill=tk.X)
        tk.Label(header, text=name, bg=bg, fg="#ffffff",
                 font=("Helvetica", sz["name_font"], "bold"),
                 wraplength=sz["wrap"]).pack(side=tk.LEFT)
        self.fixture_solo = SoloButton(header)
        self.fixture_solo.config(text="Solo fix", font=("Helvetica", 7, "bold"),
                                  padx=3, pady=2)
        _total_shown = (1 if self._master_idx is not None else 0) + len(self._visible)
        if _total_shown > 1:
            self.fixture_solo.pack(side=tk.RIGHT)

        # Override Solo fix toggle to sync all channel solos
        def _fixture_solo_release(e=None):
            currently = self.fixture_solo.soloed
            if currently:
                # Turning off — reset all channel solos
                self.fixture_solo.reset()
                for sb in self._ch_solos.values():
                    sb.reset()
            else:
                # Turning on — set all channel solos
                self.fixture_solo.set_on()
                for sb in self._ch_solos.values():
                    sb.set_on()
        self.fixture_solo.unbind("<ButtonRelease-1>")
        self.fixture_solo.bind("<ButtonRelease-1>", _fixture_solo_release)

        # Pre-scan for colour channels so swatch can be placed beside master fader
        self._swatch_indices = {}
        for i, ch in enumerate(channel_defs):
            if ch.get("show", True) and not ch.get("master") and ch["label"] in ("R","G","B","W","A","UV"):
                self._swatch_indices[ch["label"]] = i
        _has_swatch = {"R", "G", "B"} <= set(self._swatch_indices)

        # ── Master channel — with optional colour swatch beside it ──
        self._master_fader = None
        self._master_val   = None
        self._ch_solos     = {}  # initialise here so master solo can be added
        self._swatch       = None
        if self._master_idx is not None:
            mch = channel_defs[self._master_idx]
            lo, hi = channel_range(mch)
            # Swatch + master column + non-colour channels all in a horizontal frame
            master_row = tk.Frame(self, bg=bg)
            master_row.pack()
            self._master_row_frame = master_row
            # Master column: S button, label, value, fader — all centered
            master_col = tk.Frame(master_row, bg=bg)
            master_col.pack(side=tk.LEFT)
            master_solo = SoloButton(master_col)
            master_solo.pack()
            self._ch_solos[self._master_idx] = master_solo
            tk.Label(master_col, text=mch["label"], bg=bg, fg="#aaaaaa",
                     font=("Helvetica", sz["btn_font"])).pack()
            # Fixed-size container for value label/entry
            _mval_font = ("Courier", sz["val_font"])
            _mval_w = sz["master_w"] + 8
            _mval_h = 16
            mval_container = tk.Frame(master_col, bg=bg,
                                      width=_mval_w, height=_mval_h)
            mval_container.pack()
            mval_container.pack_propagate(False)
            self._master_val = tk.Label(mval_container,
                                        text=self._fmt(self._master_idx),
                                        bg=bg, fg="#aaffaa", font=_mval_font,
                                        cursor="hand2")
            self._master_val.place(relx=0.5, rely=0.5, anchor="center")

            _midx = self._master_idx
            def _master_start_edit(e, i=_midx, c=mch, container=mval_container):
                for child in container.winfo_children():
                    if isinstance(child, tk.Entry): return
                lo2, hi2 = channel_range(c)
                lbl2 = [w for w in container.winfo_children()
                        if isinstance(w, tk.Label)][0]
                lbl2.place_forget()
                var = tk.StringVar(value=str(self._raw[i]))
                ent = tk.Entry(container, textvariable=var, width=5,
                               bg="#333333", fg="#aaffaa",
                               insertbackground="#aaffaa",
                               font=_mval_font, relief=tk.FLAT,
                               justify=tk.CENTER)
                ent.place(relx=0.5, rely=0.5, anchor="center")
                ent.focus_set(); ent.select_range(0, tk.END)
                def _commit(ev=None):
                    try:
                        v = max(lo2, min(hi2, int(var.get())))
                    except ValueError:
                        v = self._raw[i]
                    ent.place_forget(); ent.destroy()
                    lbl2.place(relx=0.5, rely=0.5, anchor="center")
                    self._master_fader.set(v)
                    self._on_fader(i, v)
                ent.bind("<Return>", _commit)
                ent.bind("<FocusOut>", _commit)
                ent.bind("<Escape>", lambda ev: _commit())
            self._master_val.bind("<Double-Button-1>", _master_start_edit)

            self._master_fader = tk.Scale(
                master_col, from_=hi, to=lo, orient=tk.VERTICAL,
                length=sz["master_h"], width=sz["master_w"], showvalue=False,
                bg="#3c3c3c", fg="#ffffff",
                troughcolor="#000000" if _has_swatch else "#555555",
                highlightthickness=0,
                command=lambda v, i=self._master_idx: self._on_fader(i, v))
            self._master_fader.set(self._raw[self._master_idx])
            self._master_fader.pack()
            if _has_swatch:
                self._swatch = self._master_fader  # swatch updates troughcolor directly

        # ── Visible sub-channels ──
        # Split into non-colour (top row, beside master) and colour (bottom row)
        _CH_COLOURS = {
            "R": "#ff4444", "G": "#44ff44", "B": "#4488ff",
            "W": "#ffffcc", "UV": "#aa44ff", "A": "#ffaa00",
        }
        _COLOUR_LABELS = {"R", "G", "B", "W", "A", "UV"}
        _non_colour = [(i, ch) for i, ch in self._visible if ch["label"] not in _COLOUR_LABELS]
        _colour     = [(i, ch) for i, ch in self._visible if ch["label"] in _COLOUR_LABELS]

        self._ch_faders = {}
        self._ch_namelabels = {}
        self._ch_vallabels = {}  # orig_idx → value Label (colour channels)

        def _build_ch_col(parent, orig_idx, ch, small=False):
            lo, hi = channel_range(ch)
            is_colour = ch["label"] in _COLOUR_LABELS
            col = tk.Frame(parent, bg=bg)
            col.pack(side=tk.LEFT, padx=2)
            sb = SoloButton(col)
            sb.pack()
            self._ch_solos[orig_idx] = sb
            ch_col = _CH_COLOURS.get(ch["label"], "#aaaaaa")
            h = sz["ch_h"] if not small else max(20, int(sz["master_h"] * 0.75))
            w = sz["ch_w"] if not small else max(10, int(sz["ch_w"] * 0.85))
            if ch.get("unit") == "named":
                _nl_font = ("Helvetica", max(5, sz["ch_font"]-1))
                _fader_px = w * 6
                nl = tk.Label(col, text=named_label(ch, self._raw[orig_idx]),
                              bg=bg, fg="#ffcc88", font=_nl_font,
                              wraplength=_fader_px, anchor="center")
                nl.pack()
                self._ch_namelabels[orig_idx] = nl
            if not is_colour:
                # Constrain label width to fader width so column stays compact
                fader_w = w if small else sz["ch_w"]
                tk.Label(col, text=ch["label"], bg=bg, fg=ch_col,
                         font=("Helvetica", sz["ch_font"]),
                         width=0, wraplength=fader_w * 6).pack()
            if is_colour:
                # Fixed-size container so swap between label/entry never resizes
                val_font = ("Courier", sz["ch_font"])
                val_container = tk.Frame(col, bg=bg,
                                         width=sz["ch_w"] + 4, height=14)
                val_container.pack()
                val_container.pack_propagate(False)
                val_lbl = tk.Label(val_container, text=self._fmt(orig_idx),
                                   bg=bg, fg=ch_col, font=val_font,
                                   cursor="hand2")
                val_lbl.place(relx=0.5, rely=0.5, anchor="center")
                self._ch_vallabels[orig_idx] = val_lbl

                def _start_edit(e, i=orig_idx, c=ch, container=val_container):
                    # Only one edit at a time — if entry already present, ignore
                    for child in container.winfo_children():
                        if isinstance(child, tk.Entry):
                            return
                    lo2, hi2 = channel_range(c)
                    lbl2 = [w for w in container.winfo_children()
                             if isinstance(w, tk.Label)][0]
                    lbl2.place_forget()
                    var = tk.StringVar(value=str(self._raw[i]))
                    ent = tk.Entry(container, textvariable=var, width=4,
                                   bg="#333333",
                                   fg=_CH_COLOURS.get(c["label"], "#ffffff"),
                                   insertbackground="#ffffff",
                                   font=val_font, relief=tk.FLAT,
                                   justify=tk.CENTER)
                    ent.place(relx=0.5, rely=0.5, anchor="center")
                    ent.focus_set(); ent.select_range(0, tk.END)
                    def _commit(ev=None):
                        try:
                            v = max(lo2, min(hi2, int(var.get())))
                        except ValueError:
                            v = self._raw[i]
                        ent.place_forget()
                        ent.destroy()
                        lbl2.place(relx=0.5, rely=0.5, anchor="center")
                        self._ch_faders[i].set(v)
                        self._on_fader(i, v)
                    ent.bind("<Return>", _commit)
                    ent.bind("<FocusOut>", _commit)
                    ent.bind("<Escape>", lambda ev: _commit())
                val_lbl.bind("<Double-Button-1>", _start_edit)

            s = tk.Scale(col, from_=hi, to=lo, orient=tk.VERTICAL,
                         length=h, width=w, showvalue=False,
                         bg="#3c3c3c", fg=ch_col,
                         troughcolor=_darken(ch_col, 0.35), highlightthickness=0,
                         command=lambda v, i=orig_idx: self._on_fader(i, v))
            s.set(self._raw[orig_idx])
            s.pack()
            self._ch_faders[orig_idx] = s

        # Non-colour channels beside master fader (if master exists), else own row
        if _non_colour:
            if self._master_idx is not None and hasattr(self, '_master_row_frame'):
                # Pack beside master in the existing master_row frame
                for orig_idx, ch in _non_colour:
                    _build_ch_col(self._master_row_frame, orig_idx, ch, small=True)
                # Bottom-align all columns in master row so faders line up
                for child in self._master_row_frame.winfo_children():
                    child.pack_configure(anchor="s")
            else:
                nc_frame = tk.Frame(self, bg=bg)
                nc_frame.pack(pady=(4, 0))
                for orig_idx, ch in _non_colour:
                    _build_ch_col(nc_frame, orig_idx, ch, small=False)

        # Colour channels on their own row below
        if _colour:
            col_frame = tk.Frame(self, bg=bg)
            col_frame.pack(pady=(4, 0))
            for orig_idx, ch in _colour:
                _build_ch_col(col_frame, orig_idx, ch, small=False)

        # No master but has RGB — place a horizontal swatch below the sub-channels
        if _has_swatch and self._master_idx is None:
            swatch_h = max(10, int(14 * (sz["ch_w"] / 16)))
            # Width = sum of visible channel fader widths + padding between them
            n_vis = len(self._visible)
            swatch_w = n_vis * (sz["ch_w"] + 4)
            self._swatch = tk.Canvas(self, width=swatch_w, height=swatch_h,
                                     bg="#000000", highlightthickness=1,
                                     highlightbackground="#444444")
            self._swatch.pack(pady=(4, 0))

        # Initialise swatch colour now all faders are set
        if self._swatch:
            self._update_swatch()

        # ── BUMP button ──
        bump_btn = MacButton(self, text="BUMP", bg="#cc4400", fg="#ffffff",
                             font=("Helvetica", sz["btn_font"], "bold"),
                             width=sz["btn_w"], padx=4, pady=sz["btn_pad"])
        bump_btn.bind("<ButtonPress-1>",  self._bump_on)
        bump_btn.bind("<ButtonRelease-1>", self._bump_off)
        # bump_btn hidden for now — functionality preserved but not displayed

        # ── Channel address label ──
        n_ch = len(channel_defs)
        addr_text = f"ch {address}" if n_ch == 1 else f"ch {address}–{address + n_ch - 1}"
        tk.Label(self, text=addr_text, bg=bg, fg="#888888",
                 font=("Helvetica", sz["ch_font"])).pack(pady=(2, 0))

        # Push hidden channel defaults to DMX immediately
        for i, ch in self._hidden:
            set_channel(self.address + i, raw_to_dmx(ch, ch.get("default", 0)))

    # ── Internal fader callback ────────────────────────────────────────────────

    def _update_swatch(self):
        """Recolour the swatch canvas to reflect current R/G/B/W/A/UV mix."""
        if not self._swatch: return
        si = self._swatch_indices

        def _norm(label):
            idx = si.get(label)
            if idx is None: return 0.0
            ch = self.channel_defs[idx]
            lo, hi = channel_range(ch)
            return (self._raw[idx] - lo) / (hi - lo) if hi != lo else 0.0

        r, g, b = _norm("R"), _norm("G"), _norm("B")
        w  = _norm("W")    # white — brightens all
        a  = _norm("A")    # amber — full red, ~50% green, no blue
        uv = _norm("UV")   # UV — deep violet (strong blue, some red)

        # Additive mix: start with RGB, add contributions from W, A, UV
        fr = r + w * (1-r) + a * 1.0  + uv * 0.4
        fg = g + w * (1-g) + a * 0.5
        fb = b + w * (1-b)             + uv * 0.8

        ri = min(255, int(fr * 255))
        gi = min(255, int(fg * 255))
        bi = min(255, int(fb * 255))
        colour = f"#{ri:02x}{gi:02x}{bi:02x}"
        if isinstance(self._swatch, tk.Scale):
            self._swatch.configure(troughcolor=colour)
        else:
            self._swatch.configure(bg=colour)

    # Set this to a callable(fixture, value) to receive master fader moves
    on_master_moved = None

    def _on_fader(self, ch_idx: int, val):
        self._raw[ch_idx] = int(float(val))
        if ch_idx == self._master_idx and self._master_val:
            ch = self.channel_defs[ch_idx]
            unit = ch.get("unit", "raw")
            self._master_val.config(text=self._fmt(ch_idx))
            if self.on_master_moved:
                self.on_master_moved(self, int(float(val)))
        if ch_idx in self._ch_namelabels:
            ch = self.channel_defs[ch_idx]
            self._ch_namelabels[ch_idx].config(
                text=named_label(ch, self._raw[ch_idx]))
        if ch_idx in self._ch_vallabels:
            self._ch_vallabels[ch_idx].config(text=self._fmt(ch_idx))
        if self._swatch and ch_idx in self._swatch_indices.values():
            self._update_swatch()
        self._push()

    def set_master_value(self, val: int):
        """Directly set the master fader value without triggering on_master_moved."""
        if self._master_idx is None: return
        self._raw[self._master_idx] = val
        if self._master_fader: self._master_fader.set(val)
        if self._master_val:   self._master_val.config(text=self._fmt(self._master_idx))
        self._update_swatch()
        self._push()

    def _fmt(self, ch_idx: int) -> str:
        ch  = self.channel_defs[ch_idx]
        raw = self._raw[ch_idx]
        unit = ch.get("unit", "raw")
        if unit == "%":     return f"{raw}%"
        if unit == "named": return named_label(ch, raw) or str(raw)
        return str(raw_to_dmx(ch, raw))

    # ── DMX push ──────────────────────────────────────────────────────────────

    def _push(self):
        gm = gm_var.get() / 100.0
        self.apply_gm(gm)

    def _set_submaster_tint(self, sm: float):
        """Show amber border when a submaster is scaling this fixture below 100%."""
        tinted = getattr(self, '_sm_tinted', False)
        if sm >= 1.0:
            if tinted:
                self._sm_tinted = False
                self.configure(highlightbackground=self._bg)
        else:
            if not tinted:
                self._sm_tinted = True
                self.configure(highlightbackground="#ddaa00")

    def apply_gm(self, gm: float):
        """Push all channel values to DMX. Every channel is independent —
        the master channel is just displayed prominently but does not scale others.
        The Grand Master and submaster scale all visible channels equally."""
        sm = get_submaster_scale(self.name)
        scale = gm * sm
        self._set_submaster_tint(sm)

        for i, ch in enumerate(self.channel_defs):
            if not ch.get("show", True):
                continue  # hidden channels already set at init
            lo, hi = channel_range(ch)
            frac = (self._raw[i] - lo) / (hi - lo) if hi != lo else 0
            set_channel(self.address + i, int(frac * scale * 255))

    # ── Bump ──────────────────────────────────────────────────────────────────

    def _bump_on(self, _=None):
        if self._master_idx is not None:
            mch = self.channel_defs[self._master_idx]
            _, hi = channel_range(mch)
            self._pre_bump = self._raw[self._master_idx]  # store before moving
            self._raw[self._master_idx] = hi
            if self._master_fader: self._master_fader.set(hi)
        self._push()

    def _bump_off(self, _=None):
        if self._master_idx is not None:
            self._raw[self._master_idx] = self._pre_bump
            if self._master_fader: self._master_fader.set(self._pre_bump)
        self._push()

    # ── Solo queries ──────────────────────────────────────────────────────────

    def is_soloed(self) -> bool:
        if self.fixture_solo.soloed: return True
        return any(sb.soloed for sb in self._ch_solos.values())

    def _soloed_channel_indices(self) -> set:
        """Return set of orig channel indices that are soloed.
        Fixture solo = all channels. Individual ch_solos (incl. master) are explicit."""
        if self.fixture_solo.soloed:
            s = set()
            if self._master_idx is not None: s.add(self._master_idx)
            for i, _ in self._visible: s.add(i)
            return s
        return {i for i, sb in self._ch_solos.items() if sb.soloed}

    # ── State get/set ─────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Full state — raw values for all visible+master channels."""
        vals = {}
        if self._master_idx is not None:
            vals[self._master_idx] = self._raw[self._master_idx]
        for i, _ in self._visible:
            vals[i] = self._raw[i]
        return vals

    def get_soloed_state(self):
        """Partial state for soloed channels only, or {} if nothing soloed."""
        soloed = self._soloed_channel_indices()
        if not soloed:
            return {}
        return {i: self._raw[i] for i in soloed}

    def set_state(self, state: dict):
        for idx_str, val in state.items():
            i = int(idx_str)
            if val is None: continue
            self._raw[i] = int(val)
            if i == self._master_idx and self._master_fader:
                self._master_fader.set(int(val))
                if self._master_val:
                    self._master_val.config(text=self._fmt(i))
            elif i in self._ch_faders:
                self._ch_faders[i].set(int(val))
                if i in self._ch_namelabels:
                    self._ch_namelabels[i].config(
                        text=named_label(self.channel_defs[i], int(val)))
        self._update_swatch()
        self._push()

    def illuminate_solos_from_state(self, state):
        """Light solo buttons to reflect which channels are stored in the scene."""
        self.fixture_solo.reset()
        for sb in self._ch_solos.values(): sb.reset()
        if state is None:
            return
        stored = {int(k) for k in state}
        for i in stored:
            if i in self._ch_solos:
                self._ch_solos[i].set_on()
        # Light fixture solo if all visible+master channels are stored
        all_ch = set()
        if self._master_idx is not None: all_ch.add(self._master_idx)
        for i, _ in self._visible: all_ch.add(i)
        if all_ch and all_ch <= stored:
            self.fixture_solo.set_on()

    def fixture_type_key(self) -> tuple:
        """A hashable key identifying this fixture type — used to match copy/paste targets."""
        return tuple((ch.get("label"), ch.get("unit")) for ch in self.channel_defs)

    def set_group_highlight(self, active: bool):
        """Highlight this fixture as part of a linked group (blue tint)."""
        bg = "#1a1a3a" if active else self._bg
        # Keep highlightthickness=2 always so size never changes
        self.configure(bg=bg, highlightbackground="#4466ff" if active else self._bg)
        for child in self.winfo_children():
            try: child.configure(bg=bg)
            except Exception: pass

    def set_paste_highlight(self, active: bool):
        """Highlight this fixture as a paste target."""
        bg = "#1a3a1a" if active else self._bg
        # Keep highlightthickness=2 always so size never changes
        self.configure(bg=bg, highlightbackground="#44ff44" if active else self._bg)
        for child in self.winfo_children():
            try: child.configure(bg=bg)
            except Exception: pass



# ── DigitalFixture ─────────────────────────────────────────────────────────────

def is_digital_fixture(channel_defs: list) -> bool:
    """Return True if all visible channels are binary named (Off/On only)."""
    visible = [ch for ch in channel_defs if ch.get("show", True) and not ch.get("master")]
    if not visible:
        return False
    for ch in visible:
        if ch.get("unit") != "named":
            return False
        ranges = ch.get("range", {})
        if not isinstance(ranges, dict) or len(ranges) != 2:
            return False
        vals = [v.strip().lower() for v in ranges.values()]
        if set(vals) != {"on", "off"} and set(vals) != {"off", "on"}:
            return False
    return True

def _digital_on_value(ch: dict) -> int:
    """Return the DMX value that means On for a binary channel."""
    for k, v in ch.get("range", {}).items():
        if v.strip().lower() == "on":
            lo = int(k.split("-")[0])
            hi = int(k.split("-")[1])
            return (lo + hi) // 2
    return 255

def _digital_off_value(ch: dict) -> int:
    """Return the DMX value that means Off for a binary channel."""
    for k, v in ch.get("range", {}).items():
        if v.strip().lower() == "off":
            lo = int(k.split("-")[0])
            hi = int(k.split("-")[1])
            return (lo + hi) // 2
    return 0


class DigitalFixture(tk.Frame):
    """
    Faceplate for relay/digital fixtures — all channels are binary On/Off.
    Shows toggle buttons instead of faders.
    Fully compatible with scene record/recall interface.
    """

    def __init__(self, parent, name: str, address: int,
                 channel_defs: list, sz: dict = None, colour: str = "#1a2b8a", **kwargs):
        layout = kwargs.pop("layout", "auto")
        super().__init__(parent, **kwargs)
        self.name         = name
        self.address      = address
        self.channel_defs = channel_defs
        sz  = sz or DEFAULT_SIZES
        bg  = colour
        self._bg = bg

        self.configure(relief=tk.RIDGE, bd=2, padx=4, pady=4, bg=bg,
                       highlightthickness=2, highlightbackground=bg)

        self._visible = [(i, ch) for i, ch in enumerate(channel_defs)
                         if ch.get("show", True)]
        self._state   = {}   # {orig_idx: bool}  True = On
        self._raw     = [int(ch.get("default", 0)) for ch in channel_defs]
        self._solos   = {}   # {orig_idx: bool}
        self._sm_tinted = False

        for i, ch in self._visible:
            self._state[i] = False
            self._solos[i] = False

        zoom = sz.get("zoom", 1.0)
        fnt_hdr = ("Helvetica", max(8, int(10 * zoom)), "bold")
        fnt_btn = ("Helvetica", max(8, int(9 * zoom)), "bold")
        btn_w   = max(6, int(8 * zoom))
        btn_h   = max(28, int(36 * zoom))

        # Header
        header = tk.Frame(self, bg=bg)
        header.pack(fill=tk.X)
        tk.Label(header, text=name, bg=bg, fg="#ffffff",
                 font=fnt_hdr, anchor="w").pack(side=tk.LEFT)

        # Solo fix button
        self.fixture_solo = SoloButton(header)
        self.fixture_solo.config(text="Solo fix", font=("Helvetica", 7, "bold"),
                                  padx=3, pady=2)
        if len(self._visible) > 0:
            self.fixture_solo.pack(side=tk.RIGHT)

        def _fixture_solo_release(e=None):
            if self.fixture_solo.soloed:
                self.fixture_solo.reset()
                for i in self._solos:
                    self._solos[i] = False
                for sb in self._solo_btns.values():
                    sb.reset()
            else:
                self.fixture_solo.set_on()
                for i in self._solos:
                    self._solos[i] = True
                for sb in self._solo_btns.values():
                    sb.set_on()
        self.fixture_solo.unbind("<ButtonRelease-1>")
        self.fixture_solo.bind("<ButtonRelease-1>", _fixture_solo_release)

        # Channel buttons
        btn_frame = tk.Frame(self, bg=bg)
        btn_frame.pack(pady=(6, 2))

        self._buttons = {}
        self._solo_btns = {}

        # Layout: "vertical" stacks buttons, "horizontal" places side by side
        # Reads from fixture def; falls back to auto (vertical if >3 channels)
        if layout == "vertical":
            vertical = True
        elif layout == "horizontal":
            vertical = False
        else:
            vertical = len(self._visible) > 3
        pack_side = tk.TOP if vertical else tk.LEFT

        for orig_idx, ch in self._visible:
            label = ch.get("label", str(orig_idx + 1))

            if vertical:
                # Row: [button (fills)] [solo (right)]
                row = tk.Frame(btn_frame, bg=bg)
                row.pack(side=tk.TOP, pady=(0, 3), fill=tk.X)
                b_width = max(10, int(14 * zoom))
                b = MacButton(row, text=label,
                              bg="#333333", fg="#888888",
                              font=fnt_btn, width=b_width, pady=4,
                              anchor="center")
                b.pack(side=tk.LEFT, fill=tk.X, expand=True)
                sb = SoloButton(row)
                sb.pack(side=tk.LEFT, padx=(3, 0))
            else:
                # Column: [solo (top)] [button (below)]
                col = tk.Frame(btn_frame, bg=bg)
                col.pack(side=tk.LEFT, padx=4)
                sb = SoloButton(col)
                sb.pack()
                b = MacButton(col, text=label,
                              bg="#333333", fg="#888888",
                              font=fnt_btn, width=btn_w, pady=4,
                              anchor="center")
                b.pack()

            self._solo_btns[orig_idx] = sb
            self._buttons[orig_idx]   = b

            def _toggle(e=None, i=orig_idx):
                self._state[i] = not self._state[i]
                self._update_button(i)
                self._push_dmx()
            b.bind("<ButtonRelease-1>", _toggle)

        # Channel address
        n = len(channel_defs)
        addr_text = f"ch {address}" if n == 1 else f"ch {address}–{address + n - 1}"
        tk.Label(self, text=addr_text, bg=bg, fg="#555555",
                 font=("Helvetica", max(6, int(7 * zoom)))).pack(pady=(4, 0))

        self._push_dmx()

    def _update_button(self, i):
        b   = self._buttons[i]
        ch  = self.channel_defs[i]
        lbl = ch.get("label", str(i + 1))
        if self._state[i]:
            b.config(text=lbl, bg="#224422", fg="#44ff44")
        else:
            b.config(text=lbl, bg="#333333", fg="#888888")

    def _push_dmx(self):
        gm = gm_var.get() / 100.0
        sm = get_submaster_scale(self.name)
        scale = gm * sm
        for i, ch in self._visible:
            if self._state[i]:
                val = _digital_on_value(ch) if scale > 0.5 else _digital_off_value(ch)
            else:
                val = _digital_off_value(ch)
            self._raw[i] = val
            set_channel(self.address + i, val)

    def _set_submaster_tint(self, sm: float):
        tinted = getattr(self, '_sm_tinted', False)
        if sm >= 1.0:
            if tinted:
                self._sm_tinted = False
                self.configure(highlightbackground=self._bg)
        else:
            if not tinted:
                self._sm_tinted = True
                self.configure(highlightbackground="#ddaa00")

    # ── Scene interface ───────────────────────────────────────────────────────
    def get_state(self) -> dict:
        return {"digital": {str(i): v for i, v in self._state.items()}}

    def set_state(self, state: dict):
        if not state: return
        digital = state.get("digital", {})
        for k, v in digital.items():
            i = int(k)
            if i in self._state:
                self._state[i] = bool(v)
                self._update_button(i)
        self._push_dmx()

    def is_soloed(self) -> bool:
        if self.fixture_solo.soloed: return True
        return any(self._solos.values())

    def get_soloed_state(self) -> dict:
        if self.fixture_solo.soloed:
            return self.get_state()
        result = {}
        for i, on in self._state.items():
            if self._solos.get(i):
                result[str(i)] = on
        return {"digital": result} if result else {}

    def illuminate_solos_from_state(self, state: dict):
        if not state: return
        digital = state.get("digital", {})
        for k in digital:
            i = int(k)
            if i in self._solo_btns:
                self._solo_btns[i].set_on()
        if len(digital) == len(self._state):
            self.fixture_solo.set_on()

    def apply_gm(self, gm: float):
        sm = get_submaster_scale(self.name)
        self._set_submaster_tint(sm)
        self._push_dmx()

    def fixture_type_key(self):
        return "digital"

    def set_master_value(self, val): pass  # not applicable

# ── SubmasterWidget ────────────────────────────────────────────────────────────

class SubmasterWidget(tk.Frame):
    def __init__(self, parent, name: str, targets: list,
                 all_fixture_widgets: list, sz: dict = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.name = name
        self.target_names = targets
        self.all_fixture_widgets = all_fixture_widgets
        self.level = 1.0
        sz = sz or DEFAULT_SIZES

        self.configure(relief=tk.RIDGE, bd=2, padx=6, pady=6, bg="#1a2b2b")

        header = tk.Frame(self, bg="#1a2b2b")
        header.pack(fill=tk.X)
        tk.Label(header, text=name, bg="#1a2b2b", fg="#44ffdd",
                 font=("Helvetica", sz["name_font"], "bold"),
                 wraplength=sz["wrap"]).pack(side=tk.LEFT)
        self.solo_btn = SoloButton(header)
        self.solo_btn.pack(side=tk.RIGHT)

        tk.Label(self, text="\n".join(targets), bg="#1a2b2b", fg="#558888",
                 font=("Helvetica", sz["ch_font"]),
                 wraplength=sz["wrap"]).pack(pady=(2, 0))

        self.val_label = tk.Label(self, text="100%", bg="#1a2b2b", fg="#44ffdd",
                                  font=("Courier", sz["val_font"]))
        self.val_label.pack()

        self.fader = tk.Scale(self, from_=100, to=0, orient=tk.VERTICAL,
                              length=sz["master_h"], width=sz["master_w"],
                              showvalue=False, bg="#2a3c3c", fg="#44ffdd",
                              troughcolor="#336655", highlightthickness=0,
                              command=self._on_fader)
        self.fader.set(100)
        self.fader.pack()

        tk.Label(self, text="SUB", bg="#1a2b2b", fg="#44ffdd",
                 font=("Helvetica", sz["btn_font"], "bold")).pack(pady=(4, 0))

    def _on_fader(self, val):
        self.level = int(val) / 100.0
        self.val_label.config(text=f"{int(val)}%")
        gm = gm_var.get() / 100.0
        for fw in self.all_fixture_widgets:
            if fw.name in self.target_names:
                fw.apply_gm(gm)
        if not dry_run: send_dmx()

    def is_soloed(self): return self.solo_btn.soloed

    def get_state(self):   return {"level": int(self.fader.get())}
    def get_soloed_state(self):
        if self.solo_btn.soloed: return {"level": int(self.fader.get())}
        return {}

    def set_state(self, state: dict):
        level = state.get("level", 100)
        self.fader.set(level)
        self.level = level / 100.0
        self.val_label.config(text=f"{level}%")
        gm = gm_var.get() / 100.0
        for fw in self.all_fixture_widgets:
            if fw.name in self.target_names:
                fw.apply_gm(gm)
        if not dry_run: send_dmx()

    def illuminate_solos_from_state(self, state):
        if state is not None: self.solo_btn.set_on()
        else:                 self.solo_btn.reset()

    def apply_gm(self, gm: float):
        gm2 = gm_var.get() / 100.0
        for fw in self.all_fixture_widgets:
            if fw.name in self.target_names:
                fw.apply_gm(gm2)


# ── ClockWidget ────────────────────────────────────────────────────────────────

class ClockWidget(tk.Frame):
    """
    A panel widget showing current time, a stopwatch with laps,
    and a countdown timer. Placed in the fixture area via patch.json:
        {"type": "clock", "name": "Clock", "row": 1}
    Does not affect DMX or scenes.
    """

    BG       = "#1a1a2b"
    FG_TIME  = "#aaddff"
    FG_SW    = "#aaffaa"
    FG_CD    = "#ffdd88"
    FG_DIM   = "#556677"
    FG_ALERT = "#ff4444"

    def __init__(self, parent, name: str = "Clock", sz: dict = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.name  = name
        sz = sz or DEFAULT_SIZES
        self.configure(relief=tk.RIDGE, bd=2, padx=6, pady=6, bg=self.BG)

        class _NoSolo:
            soloed = False
            def reset(self): pass
        self.fixture_solo = _NoSolo()
        self._ch_solos    = {}

        fnt_big  = ("Courier", max(14, int(18 * (sz["master_h"] / 160))), "bold")
        fnt_med  = ("Courier", max(9,  int(11 * (sz["master_h"] / 160))), "bold")
        fnt_sml  = ("Courier", max(7,  int(9  * (sz["master_h"] / 160))))
        fnt_lbl  = ("Helvetica", sz["btn_font"])

        # Current time
        tk.Label(self, text="CLOCK", bg=self.BG, fg=self.FG_DIM,
                 font=fnt_lbl).pack(pady=(2, 0))
        self._clock_lbl = tk.Label(self, text="00:00:00",
                                   bg=self.BG, fg=self.FG_TIME, font=fnt_big)
        self._clock_lbl.pack()

        tk.Frame(self, bg="#333355", height=1).pack(fill=tk.X, pady=(6, 2))

        # Stopwatch
        tk.Label(self, text="STOPWATCH", bg=self.BG, fg=self.FG_DIM,
                 font=fnt_lbl).pack()
        self._sw_lbl = tk.Label(self, text="00:00.0",
                                bg=self.BG, fg=self.FG_SW, font=fnt_med)
        self._sw_lbl.pack()
        sw_btns = tk.Frame(self, bg=self.BG)
        sw_btns.pack(pady=(2, 0))
        self._sw_start_btn = MacButton(sw_btns, text="START", bg="#224422",
                                       fg=self.FG_SW, font=fnt_lbl,
                                       width=5, padx=6, pady=2, command=self._sw_startstop)
        self._sw_start_btn.pack(side=tk.LEFT, padx=2)
        MacButton(sw_btns, text="LAP", bg="#222244", fg=self.FG_TIME,
                  font=fnt_lbl, padx=6, pady=2,
                  command=self._sw_lap).pack(side=tk.LEFT, padx=2)
        MacButton(sw_btns, text="RST", bg="#332222", fg="#ff8888",
                  font=fnt_lbl, padx=6, pady=2,
                  command=self._sw_reset).pack(side=tk.LEFT, padx=2)
        self._lap_text = tk.Text(self, height=4, width=12,
                                 bg="#111122", fg=self.FG_DIM,
                                 font=fnt_sml, relief=tk.FLAT,
                                 state=tk.DISABLED, cursor="arrow")
        self._lap_text.pack(fill=tk.X, pady=(2, 0))

        tk.Frame(self, bg="#333355", height=1).pack(fill=tk.X, pady=(6, 2))

        # Countdown
        tk.Label(self, text="COUNTDOWN", bg=self.BG, fg=self.FG_DIM,
                 font=fnt_lbl).pack()
        self._cd_lbl = tk.Label(self, text="00:00",
                                bg=self.BG, fg=self.FG_CD, font=fnt_med)
        self._cd_lbl.pack()
        cd_set = tk.Frame(self, bg=self.BG)
        cd_set.pack(pady=(2, 0))
        tk.Label(cd_set, text="mm:ss", bg=self.BG, fg=self.FG_DIM,
                 font=fnt_sml).pack(side=tk.LEFT)
        self._cd_entry = tk.Entry(cd_set, width=6, bg="#111122", fg=self.FG_CD,
                                  insertbackground=self.FG_CD,
                                  font=fnt_med, relief=tk.FLAT, justify=tk.CENTER)
        self._cd_entry.insert(0, "05:00")
        self._cd_entry.pack(side=tk.LEFT, padx=4)
        cd_btns = tk.Frame(self, bg=self.BG)
        cd_btns.pack(pady=(2, 0))
        self._cd_start_btn = MacButton(cd_btns, text="START", bg="#443322",
                                       fg=self.FG_CD, font=fnt_lbl,
                                       width=5, padx=6, pady=2, command=self._cd_startstop)
        self._cd_start_btn.pack(side=tk.LEFT, padx=2)
        MacButton(cd_btns, text="RST", bg="#332222", fg="#ff8888",
                  font=fnt_lbl, padx=6, pady=2,
                  command=self._cd_reset).pack(side=tk.LEFT, padx=2)

        # State
        self._sw_running  = False
        self._sw_elapsed  = 0.0
        self._sw_start_t  = None
        self._sw_laps     = []
        self._cd_running   = False
        self._cd_remaining = 0.0
        self._cd_start_t  = None
        self._cd_alert     = False
        self._cd_expired   = False
        self._cd_flash_tick = 0

        self._tick()

    def _set_panel_bg(self, colour):
        """Recolour widget and all children to the given background."""
        self.configure(bg=colour)
        for child in self.winfo_children():
            try: child.configure(bg=colour)
            except Exception: pass
            for grandchild in child.winfo_children():
                try: grandchild.configure(bg=colour)
                except Exception: pass

    def _tick(self):
        import time as _t
        self._clock_lbl.config(text=_t.strftime("%H:%M:%S", _t.localtime()))
        elapsed = self._sw_elapsed + (_t.time() - self._sw_start_t if self._sw_running else 0)
        m, s = divmod(elapsed, 60)
        self._sw_lbl.config(text=f"{int(m):02d}:{s:04.1f}")
        remaining = max(0.0, self._cd_remaining - (_t.time() - self._cd_start_t if self._cd_running else 0))
        cm, cs = divmod(remaining, 60)
        self._cd_lbl.config(text=f"{int(cm):02d}:{int(cs):02d}")

        if self._cd_running and remaining <= 0:
            # Countdown just expired
            self._cd_running   = False
            self._cd_remaining = 0.0
            self._cd_expired   = True
            self._cd_start_btn.config(text="START", bg="#443322")

        if self._cd_expired:
            # Flash whole panel until reset — alternate every 500ms (5 ticks)
            self._cd_flash_tick = (self._cd_flash_tick + 1) % 10
            flash_on = self._cd_flash_tick < 5
            panel_bg = "#3a0000" if flash_on else self.BG
            lbl_fg   = self.FG_ALERT if flash_on else "#ff8888"
            self._set_panel_bg(panel_bg)
            self._cd_lbl.config(fg=lbl_fg)
        elif self._cd_running and remaining <= 10:
            # Last 10 seconds — flash label only
            self._cd_alert = not self._cd_alert
            self._cd_lbl.config(fg=self.FG_ALERT if self._cd_alert else self.FG_CD)
        self.after(100, self._tick)

    def _sw_startstop(self):
        import time as _t
        if self._sw_running:
            self._sw_elapsed += _t.time() - self._sw_start_t
            self._sw_running  = False
            self._sw_start_btn.config(text="START", bg="#224422")
        else:
            self._sw_start_t = _t.time()
            self._sw_running = True
            self._sw_start_btn.config(text="STOP", bg="#442222")

    def _sw_lap(self):
        import time as _t
        if not self._sw_running and self._sw_elapsed == 0: return
        elapsed = self._sw_elapsed + (_t.time() - self._sw_start_t if self._sw_running else 0)
        m, s = divmod(elapsed, 60)
        n = len(self._sw_laps) + 1
        entry = f"L{n:02d} {int(m):02d}:{s:04.1f}\n"
        self._sw_laps.append(entry)
        self._lap_text.config(state=tk.NORMAL)
        self._lap_text.insert("1.0", entry)
        self._lap_text.config(state=tk.DISABLED)

    def _sw_reset(self):
        self._sw_running = False; self._sw_elapsed = 0.0; self._sw_start_t = None
        self._sw_laps = []
        self._sw_start_btn.config(text="START", bg="#224422")
        self._lap_text.config(state=tk.NORMAL)
        self._lap_text.delete("1.0", tk.END)
        self._lap_text.config(state=tk.DISABLED)

    def _parse_cd(self) -> float:
        txt = self._cd_entry.get().strip()
        try:
            if ":" in txt:
                p = txt.split(":")
                return int(p[0]) * 60 + float(p[1])
            return float(txt)
        except Exception:
            return 300.0

    def _cd_startstop(self):
        import time as _t
        if self._cd_running:
            self._cd_remaining = max(0.0, self._cd_remaining - (_t.time() - self._cd_start_t))
            self._cd_running   = False
            self._cd_start_btn.config(text="START", bg="#443322")
        else:
            if self._cd_remaining <= 0:
                self._cd_remaining = self._parse_cd()
            self._cd_start_t = _t.time()
            self._cd_running = True
            self._cd_alert   = False
            self._cd_lbl.config(fg=self.FG_CD)
            self._cd_start_btn.config(text="STOP", bg="#664422")

    def _cd_reset(self):
        self._cd_running    = False
        self._cd_remaining  = self._parse_cd()
        self._cd_alert      = False
        self._cd_expired    = False
        self._cd_flash_tick = 0
        self._set_panel_bg(self.BG)
        self._cd_lbl.config(fg=self.FG_CD)
        self._cd_start_btn.config(text="START", bg="#443322")

    def get_clock_state(self) -> dict:
        """Capture timer state for preservation across rebuilds."""
        import time as _t
        sw_elapsed = self._sw_elapsed + (_t.time() - self._sw_start_t if self._sw_running else 0)
        cd_remaining = max(0.0, self._cd_remaining - (_t.time() - self._cd_start_t if self._cd_running else 0))
        return {
            "sw_elapsed":   sw_elapsed,
            "sw_running":   self._sw_running,
            "sw_laps":      list(self._sw_laps),
            "cd_remaining": cd_remaining,
            "cd_running":   self._cd_running,
            "cd_expired":   self._cd_expired,
            "cd_entry":     self._cd_entry.get(),
        }

    def restore_clock_state(self, state: dict):
        """Restore timer state after a rebuild."""
        import time as _t
        self._sw_elapsed  = state.get("sw_elapsed", 0.0)
        self._sw_running  = state.get("sw_running", False)
        self._sw_start_t  = _t.time() if self._sw_running else None
        laps = state.get("sw_laps", [])
        self._sw_laps = laps
        self._lap_text.config(state=tk.NORMAL)
        self._lap_text.delete("1.0", tk.END)
        for lap in laps:
            self._lap_text.insert(tk.END, lap)
        self._lap_text.config(state=tk.DISABLED)
        if self._sw_running:
            self._sw_start_btn.config(text="STOP", bg="#442222")

        self._cd_remaining  = state.get("cd_remaining", 0.0)
        self._cd_running    = state.get("cd_running", False)
        self._cd_start_t    = _t.time() if self._cd_running else None
        self._cd_expired    = state.get("cd_expired", False)
        entry_val = state.get("cd_entry", "05:00")
        self._cd_entry.delete(0, tk.END)
        self._cd_entry.insert(0, entry_val)
        if self._cd_running:
            self._cd_start_btn.config(text="STOP", bg="#664422")
        if self._cd_expired:
            self._cd_flash_tick = 0

    def is_soloed(self):                          return False
    def get_state(self):                          return {}
    def get_soloed_state(self):                   return {}
    def set_state(self, state):                   pass
    def illuminate_solos_from_state(self, state): pass
    def apply_gm(self, gm):                       pass


# ── Scene memory ───────────────────────────────────────────────────────────────

scenes = {}
scenes_path = None

def scenes_file(): return Path(scenes_path)

def save_scenes_to_disk():
    try:
        # Save to current show file if one is loaded, otherwise default scenes file
        target = Path(_current_show_file) if _current_show_file else scenes_file()
        with open(target, "w") as f:
            json.dump({str(k): v for k, v in scenes.items()}, f, indent=2)
        # Always keep default scenes file in sync too
        if _current_show_file and str(target) != str(scenes_file()):
            with open(scenes_file(), "w") as f:
                json.dump({str(k): v for k, v in scenes.items()}, f, indent=2)
    except Exception as e:
        print(f"Error saving scenes: {e}")

def load_scenes_from_disk(all_widget_names: list = None):
    """Load scenes from disk. Migrates old list-format scenes to name-keyed dicts
    using all_widget_names to map positions to fixture names."""
    if not scenes_file().exists():
        print("No saved scenes found."); return
    try:
        with open(scenes_file()) as f:
            data = json.load(f)
        for k, v in data.items():
            slot = int(k)
            if not isinstance(v, dict):
                scenes[slot] = {"fade": 0.0, "fixtures": {}}
            else:
                # Migrate list-format fixtures to name-keyed dict
                fx = v.get("fixtures", {})
                if isinstance(fx, list):
                    if all_widget_names:
                        fx = {all_widget_names[i]: s
                              for i, s in enumerate(fx)
                              if i < len(all_widget_names)}
                    else:
                        fx = {}
                    v = dict(v)
                    v["fixtures"] = fx
                scenes[slot] = v
        print(f"Loaded scenes from {scenes_file()}: slots {sorted(scenes.keys())}")
    except Exception as e:
        print(f"Error loading scenes: {e}")

def any_soloed(all_widgets): return any(fw.is_soloed() for fw in all_widgets)

def store_scene(slot: int, all_widgets: list, fade_time: float = 0.0):
    """Store scene keyed by fixture name so patch reordering doesn't break recall."""
    existing_name = scenes.get(slot, {}).get("name")
    if any_soloed(all_widgets):
        new_fixtures = {}
        for fw in all_widgets:
            s = fw.get_soloed_state()
            if s:
                new_fixtures[fw.name] = s
            # Non-soloed fixtures simply absent from the dict
        print(f"Scene {slot} stored (partial, fade: {fade_time}s).")
    else:
        new_fixtures = {fw.name: fw.get_state() for fw in all_widgets}
        print(f"Scene {slot} stored (full, fade: {fade_time}s).")
    scenes[slot] = {"fade": fade_time, "fixtures": new_fixtures}
    if existing_name: scenes[slot]["name"] = existing_name
    save_scenes_to_disk()

def clear_scene(slot: int):
    if slot in scenes:
        del scenes[slot]; save_scenes_to_disk()
        print(f"Scene {slot} cleared.")

def recall_scene(slot: int, all_widgets: list, root, on_complete=None, stop_flag=None):
    if slot not in scenes: return
    scene = scenes[slot]
    fixture_states = scene.get("fixtures", {})  # name → state dict
    fade_time = scene.get("fade", 0.0)

    # Build a name→widget lookup
    by_name = {fw.name: fw for fw in all_widgets}

    # Determine if partial (some fixtures absent from scene)
    all_names = {fw.name for fw in all_widgets}
    is_partial = not all_names <= set(fixture_states.keys())

    # Illuminate solos
    for fw in all_widgets:
        state = fixture_states.get(fw.name)
        if is_partial:
            fw.illuminate_solos_from_state(state)
        else:
            fw.illuminate_solos_from_state(None)

    # Only apply to widgets present in this scene
    active_pairs = [(by_name[name], state)
                    for name, state in fixture_states.items()
                    if name in by_name and state]

    if fade_time <= 0:
        for fw, state in active_pairs:
            fw.set_state(state)
        if not dry_run: send_dmx()
        print(f"Scene {slot} recalled (instant).")
        if on_complete: on_complete()
        return

    start_states = [(fw, fw.get_state(), state) for fw, state in active_pairs]
    steps = max(1, int(fade_time * _fade_steps_sec))
    interval = int(fade_time * 1000 / steps)
    step_ref = [0]

    def _fade_step():
        t = min(1.0, step_ref[0] / steps)
        for fw, start, target in start_states:
            if isinstance(fw, SubmasterWidget):
                if "level" in target:
                    sl = start.get("level", 100)
                    fw.fader.set(int(sl + (target["level"] - sl) * t))
                    fw.level = fw.fader.get() / 100.0
                    fw.val_label.config(text=f"{fw.fader.get()}%")
                    gm = gm_var.get() / 100.0
                    for w in fw.all_fixture_widgets:
                        if w.name in fw.target_names: w.apply_gm(gm)
            elif isinstance(fw, CustomFixture):
                interp = {}
                for idx_str, tval in target.items():
                    if tval is None: continue
                    i = int(idx_str)
                    sval = start.get(idx_str, start.get(i, fw._raw[i]))
                    interp[idx_str] = int(sval + (tval - sval) * t)
                fw.set_state(interp)
        if not dry_run: send_dmx()
        step_ref[0] += 1
        if step_ref[0] <= steps and not (stop_flag and stop_flag[0]):
            root.after(interval, _fade_step)
        else:
            if not (stop_flag and stop_flag[0]):
                print(f"Scene {slot} recalled (fade: {fade_time}s).")
            else:
                print(f"Scene {slot} fade interrupted.")
            if on_complete: on_complete()

    _fade_step()


# ── Open Fixture Library integration ──────────────────────────────────────────

# OFL fixtures live directly on GitHub — much more reliable than the OFL web API
OFL_RAW   = "https://raw.githubusercontent.com/OpenLightingProject/open-fixture-library/master/fixtures"
OFL_API   = "https://api.github.com/repos/OpenLightingProject/open-fixture-library"
OFL_INDEX = "https://raw.githubusercontent.com/OpenLightingProject/open-fixture-library/master/fixtures/manufacturers.json"

def _http_get(url: str) -> bytes:
    """GET a URL, return raw bytes or raise RuntimeError."""
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DMXDesk/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e}")

def _json_get(url: str):
    return json.loads(_http_get(url).decode("utf-8"))

def _ofl_fixture(mfr_key: str, fix_key: str) -> dict:
    """Fetch and return a raw OFL fixture JSON."""
    url = f"{OFL_RAW}/{mfr_key}/{fix_key}.json"
    return _json_get(url)

OFL_CACHE_FILE = APP_DIR / "ofl_fixtures.json"

# In-memory cache
_ofl_index_cache = None

def _ofl_load_cache() -> list:
    """Load index from disk cache if available."""
    if OFL_CACHE_FILE.exists():
        try:
            with open(OFL_CACHE_FILE) as f:
                data = json.load(f)
            print(f"OFL disk cache loaded: {len(data.get('fixtures',[]))} fixtures, updated {data.get('updated','?')}")
            return data.get("fixtures", [])
        except Exception as e:
            print(f"OFL cache read error: {e}")
    return []

def _ofl_fetch_index() -> list:
    """Fetch full fixture index from GitHub and save to disk. Returns fixture list."""
    import datetime
    print("Fetching OFL index from GitHub...")

    tree_url = f"{OFL_API}/git/trees/master?recursive=1"
    data = _json_get(tree_url)

    try:
        mfr_names = {k: v.get("name", k)
                     for k, v in _json_get(OFL_INDEX).items()
                     if k != "$schema"}
    except Exception:
        mfr_names = {}

    results = []
    for item in data.get("tree", []):
        path = item.get("path", "")
        if (path.startswith("fixtures/") and path.endswith(".json")
                and path.count("/") == 2):
            parts = path[len("fixtures/"):].replace(".json","").split("/")
            if len(parts) == 2:
                mfr_key, fix_key = parts
                if fix_key == "manufacturers": continue
                mfr_name = mfr_names.get(mfr_key, mfr_key.replace("-"," ").title())
                name = fix_key.replace("-", " ").title()
                results.append({"mfr_key": mfr_key, "fix_key": fix_key,
                                 "name": name, "mfr_name": mfr_name})

    updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        with open(OFL_CACHE_FILE, "w") as f:
            json.dump({"updated": updated, "fixtures": results}, f)
        print(f"OFL index saved to disk: {len(results)} fixtures")
    except Exception as e:
        print(f"OFL cache write error: {e}")

    return results

def _ofl_get_index() -> list:
    """Return cached index, loading from disk or fetching if needed."""
    global _ofl_index_cache
    if _ofl_index_cache is not None:
        return _ofl_index_cache
    cached = _ofl_load_cache()
    if cached:
        _ofl_index_cache = cached
        return _ofl_index_cache
    # No disk cache — fetch from GitHub
    _ofl_index_cache = _ofl_fetch_index()
    return _ofl_index_cache

def _ofl_refresh_index() -> list:
    """Force re-fetch from GitHub regardless of cache."""
    global _ofl_index_cache
    _ofl_index_cache = _ofl_fetch_index()
    return _ofl_index_cache

def _ofl_cache_date() -> str:
    """Return the date string from the disk cache, or empty string."""
    if OFL_CACHE_FILE.exists():
        try:
            with open(OFL_CACHE_FILE) as f:
                return json.load(f).get("updated", "")
        except Exception:
            pass
    return ""

def _ofl_find_fixtures(mfr_query: str, fix_query: str) -> list:
    """Filter the cached index by manufacturer and/or fixture name."""
    index = _ofl_get_index()
    mq = mfr_query.lower().strip()
    fq = fix_query.lower().strip()
    results = []
    for f in index:
        if mq and mq not in f["mfr_key"].lower() and mq not in f["mfr_name"].lower():
            continue
        if fq and fq not in f["fix_key"].lower() and fq not in f["name"].lower():
            continue
        results.append(f)
    return results[:100]

def _ofl_convert(fixture_json: dict) -> dict:
    """
    Convert an OFL fixture definition to our channel format.
    Returns {"colour": ..., "channels": [...]} or raises ValueError.
    """
    # OFL stores modes; use the first mode
    modes = fixture_json.get("modes", [])
    if not modes:
        raise ValueError("No modes found in fixture definition")
    mode = modes[0]
    all_channels = fixture_json.get("availableChannels", {})

    # Flatten channel list — some modes contain dicts (matrix insertions) not strings
    def _flatten_channels(ch_list):
        result = []
        for item in ch_list:
            if item is None:
                result.append(None)
            elif isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                # Matrix channel insertion — skip (too complex for simple mapping)
                pass
        return result

    channel_keys = _flatten_channels(mode.get("channels", []))

    # Colour hint from physical data
    colours = fixture_json.get("physical", {}).get("bulb", {}).get("colorTemperature")
    faceplate = "#2b2b2b"

    LABEL_MAP = {
        "red": "R", "green": "G", "blue": "B", "white": "W",
        "amber": "A", "uv": "UV", "ultraviolet": "UV",
        "intensity": "Intensity", "dimmer": "Dimmer",
        "strobe": "Strobe", "zoom": "Zoom", "focus": "Focus",
        "pan": "Pan", "tilt": "Tilt", "speed": "Speed",
        "color temperature": "Colour Temp", "colour temperature": "Colour Temp",
        "color wheel": "Colour", "colour wheel": "Colour",
        "gobo wheel": "Gobo", "prism": "Prism", "iris": "Iris",
        "shutter": "Shutter", "frost": "Frost",
    }
    COLOUR_LABELS = {"R", "G", "B", "W", "A", "UV"}
    FACEPLATE_HINTS = {
        frozenset({"R","G","B"}):      "#2b2020",
        frozenset({"R","G","B","W"}):  "#2b2020",
        frozenset({"Dimmer"}):         "#2b2b2b",
    }

    channels_out = []
    found_labels = set()
    master_set = False

    for key in channel_keys:
        if key is None:
            continue  # OFL uses null for unused slots
        ch_def = all_channels.get(key, {})
        raw_name = (ch_def.get("name") or key or "").strip()
        label = LABEL_MAP.get(raw_name.lower(), raw_name)

        # Determine range & unit
        caps = ch_def.get("capabilities", [])
        unit = "raw"
        rng  = [0, 255]
        named_ranges = {}

        if caps:
            # Check if all capabilities have a name → named range
            if all(c.get("type") not in (None, "Generic") and c.get("comment") or
                   c.get("slotNumber") or c.get("colorTemperature")
                   for c in caps):
                for cap in caps:
                    dmx_r = cap.get("dmxRange", [0, 255])
                    name  = (cap.get("comment") or cap.get("type") or "").strip()
                    if name and dmx_r:
                        named_ranges[f"{dmx_r[0]}-{dmx_r[1]}"] = name
                if named_ranges:
                    rng  = named_ranges
                    unit = "named"

        # Detect intensity/dimmer channel
        cap_types = {c.get("type","") if isinstance(c.get("type"), str) else "" for c in caps}
        is_intensity = (
            "Intensity" in cap_types or
            raw_name.lower() in ("intensity", "dimmer", "master dimmer", "master") or
            label in ("Intensity", "Dimmer")
        )

        if is_intensity and not master_set:
            master = True
            master_set = True
            unit = "%"
            rng  = [0, 100]
        else:
            master = False

        show = label not in ("Speed", "Pan", "Tilt", "Prism", "Gobo", "Focus",
                              "Colour Temp", "Colour") or label in COLOUR_LABELS

        default = 0
        channels_out.append({
            "label":   label,
            "master":  master,
            "default": default,
            "range":   rng,
            "unit":    unit,
            "show":    show,
        })
        found_labels.add(label)

    if not channels_out:
        raise ValueError("No usable channels found")

    # Pick faceplate colour
    for key_set, col in FACEPLATE_HINTS.items():
        if key_set <= found_labels:
            faceplate = col
            break

    return {"colour": faceplate, "channels": channels_out}


def open_fixture_library_dialog(parent, fixtures_dir: Path):
    """Open a dialog to search OFL and import a fixture definition."""
    import threading

    win = tk.Toplevel(parent)
    win.title("Open Fixture Library — Import Fixture")
    win.configure(bg="#1a1a1a")
    win.resizable(True, True)
    win.geometry("640x520")
    win.grab_set()

    BG   = "#1a1a1a"
    BG2  = "#222222"
    FG   = "#ffffff"
    FGA  = "#aaaaaa"
    GOLD = "#ffcc00"
    fnt  = ("Helvetica", 11)
    fnt_s = ("Helvetica", 9)

    def lbl(p, t, **kw): return tk.Label(p, text=t, bg=kw.pop("bg", BG), fg=kw.pop("fg", FGA), font=kw.pop("font", fnt_s), **kw)
    def entry(p, **kw):  return tk.Entry(p, bg=BG2, fg=FG, insertbackground=FG, font=fnt, relief=tk.FLAT, bd=4, **kw)

    # ── Search row ──
    search_frame = tk.Frame(win, bg=BG)
    search_frame.pack(fill=tk.X, padx=12, pady=(12, 4))
    lbl(search_frame, "Manufacturer:").grid(row=0, column=0, sticky="w", padx=(0,4))
    mfr_var = tk.StringVar()
    mfr_entry = entry(search_frame, textvariable=mfr_var, width=20)
    mfr_entry.grid(row=0, column=1, padx=(0,8))
    lbl(search_frame, "Fixture name:").grid(row=0, column=2, sticky="w", padx=(0,4))
    fix_var = tk.StringVar()
    fix_entry = entry(search_frame, textvariable=fix_var, width=22)
    fix_entry.grid(row=0, column=3, padx=(0,8))
    search_btn = btn(search_frame, "Search", bg="#224422", fg=GOLD,
                     font=("Helvetica", 10, "bold"), pady=4)
    search_btn.grid(row=0, column=4)

    # ── Results list ──
    results_frame = tk.Frame(win, bg=BG)
    results_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
    lbl(results_frame, "Results:").pack(anchor="w")
    list_frame = tk.Frame(results_frame, bg=BG2)
    list_frame.pack(fill=tk.BOTH, expand=True)
    scrollbar = ttk.Scrollbar(list_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    results_list = tk.Listbox(list_frame, bg=BG2, fg=FG, font=fnt_s,
                               selectbackground="#334433", selectforeground=GOLD,
                               relief=tk.FLAT, yscrollcommand=scrollbar.set,
                               activestyle="none")
    results_list.pack(fill=tk.BOTH, expand=True)
    scrollbar.config(command=results_list.yview)

    # ── Channel preview ──
    preview_frame = tk.Frame(win, bg=BG)
    preview_frame.pack(fill=tk.X, padx=12, pady=4)
    lbl(preview_frame, "Channel preview:").pack(anchor="w")
    preview_text = tk.Text(preview_frame, height=6, bg=BG2, fg=FGA,
                           font=("Courier", 9), relief=tk.FLAT, state=tk.DISABLED)
    preview_text.pack(fill=tk.X)

    # ── Status + buttons ──
    bottom = tk.Frame(win, bg=BG)
    bottom.pack(fill=tk.X, padx=12, pady=(4, 12))
    cache_date = _ofl_cache_date()
    hint = f"DB cached {cache_date}. " if cache_date else "No local DB — search will fetch from GitHub. "
    status_lbl = lbl(bottom, hint + "Enter manufacturer and/or fixture name.", fg=FGA)
    status_lbl.pack(side=tk.LEFT, expand=True, anchor="w")
    import_btn = btn(bottom, "Import", bg="#225522", fg=GOLD,
                     font=("Helvetica", 10, "bold"), pady=4)
    import_btn.pack(side=tk.RIGHT, padx=(8, 0))
    btn(bottom, "Cancel", bg="#333333", fg="#aaaaaa",
        font=("Helvetica", 10), pady=4,
        command=win.destroy).pack(side=tk.RIGHT)
    refresh_btn = btn(bottom, "↻ Refresh DB", bg="#332233", fg="#bb88ff",
                      font=("Helvetica", 9), pady=4)
    refresh_btn.pack(side=tk.RIGHT, padx=(0, 6))

    # ── State ──
    _results = []     # list of (manufacturer_key, fixture_key, display_name)
    _converted = [None]  # converted fixture dict when selected
    _fixture_key = [None]

    def _set_status(msg, colour=FGA):
        status_lbl.config(text=msg, fg=colour)
        win.update_idletasks()

    def _do_search():
        mfr = mfr_var.get().strip()
        fix = fix_var.get().strip()
        if not mfr and not fix:
            _set_status("Please enter a manufacturer and/or fixture name.", "#ff8888")
            return
        search_btn.config(bg="#443300")
        _set_status("Searching…")
        results_list.delete(0, tk.END)
        _results.clear()
        _converted[0] = None

        def _fetch():
            try:
                if not mfr.strip() and not fix.strip():
                    win.after(0, lambda: _set_status("Enter a manufacturer and/or fixture name.", "#ff8888"))
                    return
                print(f"Browsing OFL — manufacturer: '{mfr}', fixture: '{fix}'")
                results = _ofl_find_fixtures(mfr, fix)
                print(f"Found {len(results)} results")
                win.after(0, lambda: _show_results(results))
            except Exception as e:
                err = str(e)
                print(f"Browse error: {err}")
                win.after(0, lambda: _set_status(f"Error: {err}", "#ff8888"))

        threading.Thread(target=_fetch, daemon=True).start()

    def _show_results(fixtures):
        results_list.delete(0, tk.END)
        _results.clear()
        if not fixtures:
            _set_status("No results found. Try a different search term.", "#ff8888"); return
        for f in fixtures[:50]:
            mkey  = f.get("mfr_key", "")
            fkey  = f.get("fix_key", "")
            name  = f.get("name", fkey)
            mname = f.get("mfr_name", mkey)
            display = f"{mname}  —  {name}"
            _results.append((mkey, fkey, name))
            results_list.insert(tk.END, display)
        _set_status(f"{len(_results)} result(s). Select one to preview.")

    def _on_select(event=None):
        sel = results_list.curselection()
        if not sel: return
        idx = sel[0]
        mkey, fkey, name = _results[idx]
        _fixture_key[0] = fkey
        _set_status(f"Loading {name}…")
        _converted[0] = None

        def _fetch():
            try:
                print(f"Fetching: {OFL_RAW}/{mkey}/{fkey}.json")
                data = _ofl_fixture(mkey, fkey)
                converted = _ofl_convert(data)
                win.after(0, lambda: _show_preview(name, converted))
            except Exception as e:
                err = str(e)
                print(f"Fetch error: {err}")
                win.after(0, lambda: _set_status(f"Error: {err}", "#ff8888"))

        threading.Thread(target=_fetch, daemon=True).start()

    def _show_preview(name, converted):
        _converted[0] = converted
        lines = [f"Fixture: {name}", f"Faceplate: {converted['colour']}", ""]
        for ch in converted["channels"]:
            flags = []
            if ch.get("master"):  flags.append("MASTER")
            if not ch.get("show"): flags.append("hidden")
            rng = ch["range"]
            if isinstance(rng, dict):
                rng_str = f"named ({len(rng)} values)"
            else:
                rng_str = f"{rng[0]}–{rng[1]} {ch['unit']}"
            lines.append(f"  {ch['label']:12s}  {rng_str:25s}  {'  '.join(flags)}")
        preview_text.config(state=tk.NORMAL)
        preview_text.delete("1.0", tk.END)
        preview_text.insert("1.0", "\n".join(lines))
        preview_text.config(state=tk.DISABLED)
        _set_status(f"Ready to import '{name}'.", GOLD)

    def _do_import():
        converted = _converted[0]
        if not converted:
            _set_status("Select a fixture first.", "#ff8888"); return
        fkey = _fixture_key[0] or "imported_fixture"
        # Sanitise filename
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in fkey)
        out_path = fixtures_dir / f"{safe}.json"
        if out_path.exists():
            if not messagebox.askyesno("Overwrite?",
                    f"'{safe}.json' already exists.\nOverwrite it?",
                    parent=win):
                return
        with open(out_path, "w") as f:
            json.dump(converted, f, indent=2)
        _set_status(f"Saved to fixtures/{safe}.json ✓", "#44ff44")
        win.after(1500, win.destroy)

    def _do_refresh():
        global _ofl_index_cache
        _ofl_index_cache = None   # clear memory cache so disk re-fetch is forced
        _set_status("Refreshing fixture database from GitHub…", "#bb88ff")
        results_list.delete(0, tk.END)
        _results.clear()
        _converted[0] = None
        import threading
        def _fetch():
            try:
                data = _ofl_refresh_index()
                cache_date = _ofl_cache_date()
                win.after(0, lambda: _set_status(
                    f"DB updated {cache_date}. {len(data)} fixtures. Search to continue.", "#44ff44"))
            except Exception as e:
                err = str(e)
                win.after(0, lambda: _set_status(f"Refresh error: {err}", "#ff8888"))
        threading.Thread(target=_fetch, daemon=True).start()

    search_btn._command = _do_search
    import_btn._command = _do_import
    refresh_btn._command = _do_refresh
    results_list.bind("<<ListboxSelect>>", _on_select)
    mfr_entry.bind("<Return>", lambda e: _do_search())
    fix_entry.bind("<Return>", lambda e: _do_search())
    mfr_entry.focus_set()


# ── Patch Editor ───────────────────────────────────────────────────────────────

def open_patch_editor(parent, patch_path: Path, fixtures_dir: Path, on_save_callback):
    """
    GUI editor for patch.json.
    on_save_callback() is called after a successful save so the desk reloads.
    """
    # Load current patch
    try:
        with open(patch_path) as f:
            patch_data = json.load(f)
        print(f"Patch loaded: {len(patch_data)} entries from {patch_path}")
    except Exception as e:
        messagebox.showerror("Patch Editor", f"Could not load patch: {e}", parent=parent)
        return

    # Available fixture types from fixtures/ folder + builtins
    def _get_fixture_types():
        types = set()
        for p in fixtures_dir.glob("*.json"):
            types.add(p.stem)
        types.update(["dimmer", "rgb", "rgbw"])
        return sorted(types)

    win = tk.Toplevel(parent)
    win.title("Patch Editor")
    win.configure(bg="#1a1a1a")
    win.geometry("900x560")
    win.resizable(True, True)
    win.grab_set()

    BG   = "#1a1a1a"
    BG2  = "#222222"
    BG3  = "#2a2a2a"
    FG   = "#ffffff"
    FGA  = "#aaaaaa"
    GOLD = "#ffcc00"
    SEL  = "#1a3a1a"
    ERR  = "#3a1a1a"
    fnt  = ("Helvetica", 10)
    fnt_s = ("Helvetica", 9)
    fnt_hdr = ("Helvetica", 9, "bold")

    # ── Working copy of patch ──
    rows = [dict(r) for r in patch_data]

    # ── Column definitions ──
    COLS = [
        ("Row",     "row",     4),
        ("Name",    "name",    18),
        ("Type",    "type",    14),
        ("Address", "address", 7),
        ("Colour",  "colour",  8),
    ]
    COL_WIDTHS = [c[2] for c in COLS]

    # ── Layout: right column for all buttons, left for table ──
    win.geometry("780x520")

    # Right column — all buttons
    side = tk.Frame(win, bg=BG2, padx=8, pady=8)
    side.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 0), pady=0)

    def sbtn(text, bg, fg, cmd, sep_after=False):
        b = btn(side, text, bg=bg, fg=fg, font=fnt_s, pady=4, width=14, command=cmd)
        b.pack(fill=tk.X, pady=1)
        if sep_after:
            tk.Frame(side, bg="#444444", height=1).pack(fill=tk.X, pady=4)
        return b

    sbtn("＋ Add Fixture",   "#224422", "#88ff88",  lambda: _add_row("dimmer"))
    sbtn("＋ Add Sub",       "#223333", "#44ffdd",  lambda: _add_row("submaster"))
    sbtn("＋ Add Divider",   "#222244", "#8888ff",  lambda: _add_row("divider"))
    sbtn("＋ Add Clock",     "#332233", "#cc88ff",  lambda: _add_row("clock"), sep_after=True)
    sbtn("▲ Up",             "#2a2a2a", FGA,        lambda: _move_up())
    sbtn("▼ Down",           "#2a2a2a", FGA,        lambda: _move_down(), sep_after=True)
    sbtn("✕ Delete",         "#442222", "#ff8888",  lambda: _delete_row())
    sbtn("✎ Edit Fixture Def", "#222233", "#aaaaff",  lambda: _edit_fixture_def())
    sbtn("✚ Create Fixture",  "#223322", "#88ffaa",  lambda: _create_fixture_def())
    sbtn("🔍 Find Fixture",    "#223344", "#88bbff",  lambda: open_fixture_library_dialog(win, fixtures_dir), sep_after=True)
    sbtn("Load…",            "#223344", "#88bbff",  lambda: _load_patch())
    sbtn("Save As…",         "#224433", "#88ffcc",  lambda: _save_as(), sep_after=True)
    sbtn("Save & Reload",    "#225522", GOLD,       lambda: _save())

    # Status label at bottom of side panel
    status_lbl = tk.Label(side, text="", bg=BG2, fg=FGA, font=fnt_s,
                          wraplength=110, justify=tk.LEFT, anchor="nw")
    status_lbl.pack(fill=tk.X, pady=(6, 0))

    # Left — table
    top = tk.Frame(win, bg=BG)
    top.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 4), pady=8)

    # Header
    hdr = tk.Frame(top, bg=BG2)
    hdr.pack(fill=tk.X)
    for i, (label, _, w) in enumerate(COLS):
        tk.Label(hdr, text=label, bg=BG2, fg=GOLD, font=fnt_hdr,
                 width=w, anchor="w").grid(row=0, column=i, padx=4, pady=3, sticky="w")
    tk.Label(hdr, text="DMX range", bg=BG2, fg=GOLD, font=fnt_hdr,
             width=10, anchor="w").grid(row=0, column=len(COLS), padx=4, pady=3, sticky="w")

    # Scrollable body
    body_outer = tk.Frame(top, bg=BG)
    body_outer.pack(fill=tk.BOTH, expand=True)
    body_canvas = tk.Canvas(body_outer, bg=BG, highlightthickness=0)
    body_scroll = ttk.Scrollbar(body_outer, orient=tk.VERTICAL, command=body_canvas.yview)
    body_canvas.configure(yscrollcommand=body_scroll.set)
    body_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    body_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    body_frame = tk.Frame(body_canvas, bg=BG)
    body_canvas.create_window((0, 0), window=body_frame, anchor="nw")
    body_frame.bind("<Configure>",
                    lambda e: body_canvas.configure(scrollregion=body_canvas.bbox("all")))

    selected = set()   # indices of selected rows (multi-select)
    row_frames = []

    def _dmx_range(r):
        ftype = r.get("type","").lower()
        addr  = r.get("address")
        if ftype in ("divider","clock","submaster") or not addr:
            return ""
        try:
            defn = load_fixture_def(ftype)
            n = len(defn["channels"])
            return f"{addr}" if n == 1 else f"{addr}–{addr+n-1}"
        except Exception:
            return f"{addr}"

    def _row_bg(idx, r):
        if idx in selected:
            return SEL
        # Highlight address conflicts
        ftype = r.get("type","").lower()
        if ftype not in ("divider","clock") and r.get("address"):
            for j, other in enumerate(rows):
                if j == idx: continue
                if other.get("type","").lower() in ("divider","clock"): continue
                if other.get("address") == r.get("address"):
                    return ERR
        return BG3 if idx % 2 == 0 else BG2

    def _refresh_table():
        for f in row_frames:
            f.destroy()
        row_frames.clear()
        for idx, r in enumerate(rows):
            bg = _row_bg(idx, r)
            rf = tk.Frame(body_frame, bg=bg, cursor="hand2")
            rf.pack(fill=tk.X, pady=1)
            row_frames.append(rf)
            vals = [
                str(r.get("row", 1)),
                r.get("name", ""),
                r.get("type", ""),
                str(r.get("address", "")) if r.get("address") else "",
                r.get("colour", ""),
            ]
            for ci, (v, w) in enumerate(zip(vals, COL_WIDTHS)):
                fg_col = FG
                if ci == 4 and v:  # colour swatch
                    try:
                        swatch = tk.Frame(rf, bg=v, width=14, height=14)
                        swatch.grid(row=0, column=ci, padx=(4,0), pady=3, sticky="w")
                        tk.Label(rf, text=f" {v}", bg=bg, fg=FGA, font=fnt_s,
                                 width=w-2, anchor="w").grid(row=0, column=ci, padx=(20,0), sticky="w")
                        rf.grid_columnconfigure(ci, minsize=w*7)
                        continue
                    except Exception:
                        pass
                if ci == 2 and v.lower() == "divider":
                    fg_col = "#4466ff"
                elif ci == 2 and v.lower() == "clock":
                    fg_col = "#cc88ff"
                tk.Label(rf, text=v, bg=bg, fg=fg_col, font=fnt_s,
                         width=w, anchor="w").grid(row=0, column=ci, padx=4, pady=3, sticky="w")
            # DMX range column
            tk.Label(rf, text=_dmx_range(r), bg=bg, fg=FGA, font=fnt_s,
                     width=10, anchor="w").grid(row=0, column=len(COLS), padx=4, pady=3, sticky="w")

            # Use click counting for reliable double-click on macOS
            for w in [rf] + rf.winfo_children():
                w.bind("<Button-1>",       lambda e, i=idx: _on_click(i))
                w.bind("<Shift-Button-1>", lambda e, i=idx: _on_click(i, extend=True))

    _click_state = {"count": 0, "after_id": None, "last_idx": None, "extend": False}

    def _on_click(idx, extend=False):
        _click_state["count"] += 1
        _click_state["last_idx"] = idx
        _click_state["extend"]   = extend
        if _click_state["after_id"]:
            win.after_cancel(_click_state["after_id"])
        def _decide():
            n   = _click_state["count"]
            i   = _click_state["last_idx"]
            ext = _click_state.get("extend", False)
            _click_state["count"] = 0
            if n >= 2:
                _edit(i)
            else:
                _select(i, extend=ext)
        _click_state["after_id"] = win.after(400, _decide)

    def _select(idx, extend=False):
        if extend:
            if idx in selected:
                selected.discard(idx)
            else:
                selected.add(idx)
        else:
            selected.clear()
            selected.add(idx)
        _refresh_table()

    def _add_row(ftype):
        # Auto-increment address
        max_addr = 1
        for r in rows:
            if r.get("type","").lower() not in ("divider","clock","submaster") and r.get("address"):
                try:
                    defn = load_fixture_def(r["type"])
                    max_addr = max(max_addr, r["address"] + len(defn["channels"]))
                except Exception:
                    max_addr = max(max_addr, r.get("address", 1) + 1)
        new_row = {"type": ftype, "row": 1}
        if ftype == "submaster":
            new_row["name"] = "New Sub"
            new_row["targets"] = []
        elif ftype not in ("divider", "clock"):
            new_row["name"] = "New Fixture"
            new_row["address"] = max_addr
        ins = (max(selected) + 1) if selected else len(rows)
        rows.insert(ins, new_row)
        selected.clear()
        selected.add(ins)
        _refresh_table()
        _edit(ins)

    def _delete_row():
        if not selected: return
        n = len(selected)
        msg = f"Delete {n} rows?" if n > 1 else "Delete this row?"
        if not messagebox.askyesno("Delete", msg, parent=win): return
        for i in sorted(selected, reverse=True):
            rows.pop(i)
        selected.clear()
        _refresh_table()

    def _move_up():
        idxs = sorted(selected)
        if not idxs or idxs[0] == 0: return
        for i in idxs:
            rows[i], rows[i-1] = rows[i-1], rows[i]
        selected.clear()
        selected.update(i - 1 for i in idxs)
        _refresh_table()

    def _move_down():
        idxs = sorted(selected, reverse=True)
        if not idxs or idxs[0] >= len(rows)-1: return
        for i in idxs:
            rows[i], rows[i+1] = rows[i+1], rows[i]
        selected.clear()
        selected.update(i + 1 for i in idxs)
        _refresh_table()

    def _edit(idx):
        r = rows[idx]
        ftype = r.get("type", "dimmer").lower()

        d = tk.Toplevel(win)
        d.title("Edit Entry")
        d.configure(bg=BG)
        d.resizable(False, False)
        d.grab_set()
        d.geometry("420x380")
        d.columnconfigure(1, weight=1)

        def lrow(label, widget_fn, row_n):
            tk.Label(d, text=label, bg=BG, fg=FGA, font=fnt_s,
                     width=14, anchor="e").grid(row=row_n, column=0, padx=(10,4), pady=5, sticky="e")
            w = widget_fn(d)
            w.grid(row=row_n, column=1, padx=(0,10), pady=5, sticky="ew")
            return w

        # Type
        type_var = tk.StringVar(value=ftype)
        tk.Label(d, text="Type:", bg=BG, fg=FGA, font=fnt_s,
                 width=14, anchor="e").grid(row=0, column=0, padx=(10,4), pady=5, sticky="e")
        type_cb = ttk.Combobox(d, textvariable=type_var, font=fnt_s,
                               values=["submaster","divider","clock"] + _get_fixture_types(),
                               state="readonly")
        type_cb.grid(row=0, column=1, padx=(0,10), pady=5, sticky="ew")

        # Name
        name_var = tk.StringVar(value=r.get("name",""))
        name_e = lrow("Name:", lambda p: tk.Entry(p, textvariable=name_var,
                       bg=BG2, fg=FG, insertbackground=FG, font=fnt_s,
                       relief=tk.FLAT, bd=3), 1)

        # Address (fixtures only)
        addr_var = tk.StringVar(value=str(r.get("address","")) if r.get("address") else "")
        addr_lbl = tk.Label(d, text="DMX Address:", bg=BG, fg=FGA, font=fnt_s,
                            width=14, anchor="e")
        addr_lbl.grid(row=2, column=0, padx=(10,4), pady=5, sticky="e")
        addr_e = tk.Entry(d, textvariable=addr_var,
                          bg=BG2, fg=FG, insertbackground=FG,
                          font=fnt_s, relief=tk.FLAT, bd=3)
        addr_e.grid(row=2, column=1, padx=(0,10), pady=5, sticky="ew")

        # Targets (submaster only) — comma-separated
        targets_var = tk.StringVar(value=", ".join(r.get("targets", [])))
        targets_lbl = tk.Label(d, text="Targets:", bg=BG, fg=FGA, font=fnt_s,
                               width=14, anchor="e")
        targets_lbl.grid(row=3, column=0, padx=(10,4), pady=5, sticky="e")
        targets_e = tk.Entry(d, textvariable=targets_var,
                             bg=BG2, fg=FG, insertbackground=FG,
                             font=fnt_s, relief=tk.FLAT, bd=3)
        targets_e.grid(row=3, column=1, padx=(0,10), pady=5, sticky="ew")

        # Row
        row_var = tk.StringVar(value=str(r.get("row", 1)))
        lrow("Row (1 or 2):", lambda p: ttk.Combobox(p, textvariable=row_var,
              values=["1","2"], state="readonly", font=fnt_s), 4)

        # Colour
        colour_var = tk.StringVar(value=r.get("colour",""))
        colour_lbl = tk.Label(d, text="Colour:", bg=BG, fg=FGA, font=fnt_s,
                               width=14, anchor="e")
        colour_lbl.grid(row=5, column=0, padx=(10,4), pady=5, sticky="e")
        colour_frame = tk.Frame(d, bg=BG)
        colour_frame.grid(row=5, column=1, padx=(0,10), pady=5, sticky="ew")
        colour_e = tk.Entry(colour_frame, textvariable=colour_var,
                            bg=BG2, fg=FG, insertbackground=FG,
                            font=fnt_s, relief=tk.FLAT, bd=3, width=10)
        colour_e.pack(side=tk.LEFT, fill=tk.X, expand=True)
        colour_swatch = tk.Frame(colour_frame, width=20, height=20, bg=BG2)
        colour_swatch.pack(side=tk.LEFT, padx=(4,0))
        def _update_swatch(*_):
            try: colour_swatch.configure(bg=colour_var.get())
            except Exception: colour_swatch.configure(bg=BG2)
        colour_var.trace_add("write", _update_swatch)
        _update_swatch()
        def _pick_colour():
            from tkinter import colorchooser
            c = colorchooser.askcolor(color=colour_var.get() or "#2b2b2b", parent=d)
            if c and c[1]: colour_var.set(c[1])
        btn(colour_frame, "…", bg="#333333", fg=FGA, font=fnt_s, padx=4, pady=1,
            command=_pick_colour).pack(side=tk.LEFT, padx=(2,0))

        def _on_type_change(*_):
            t = type_var.get().lower()
            is_fixture   = t not in ("divider", "clock", "submaster")
            is_submaster = t == "submaster"
            is_named     = t not in ("divider", "clock")
            name_e.configure(state="normal" if is_named else "disabled")
            if is_named:
                colour_lbl.grid()
                colour_frame.grid()
            else:
                colour_lbl.grid_remove()
                colour_frame.grid_remove()
            # Show/hide address row
            if is_fixture:
                addr_lbl.grid()
                addr_e.grid()
            else:
                addr_lbl.grid_remove()
                addr_e.grid_remove()
            # Show/hide targets row
            if is_submaster:
                targets_lbl.grid()
                targets_e.grid()
            else:
                targets_lbl.grid_remove()
                targets_e.grid_remove()
        type_var.trace_add("write", _on_type_change)
        _on_type_change()

        def _apply():
            t = type_var.get().lower()
            r["type"] = t
            r["row"]  = int(row_var.get())
            if t in ("divider", "clock"):
                for k in ("name","address","colour","targets"): r.pop(k, None)
            elif t == "submaster":
                r["name"] = name_var.get().strip() or r.get("name","Sub")
                targets_raw = targets_var.get()
                r["targets"] = [x.strip() for x in targets_raw.split(",") if x.strip()]
                r.pop("address", None)
                col = colour_var.get().strip()
                if col: r["colour"] = col
                elif "colour" in r: del r["colour"]
            else:
                r["name"] = name_var.get().strip() or r.get("name","Fixture")
                try:
                    r["address"] = int(addr_var.get())
                except ValueError:
                    messagebox.showerror("Error", "Address must be a number.", parent=d)
                    return
                r.pop("targets", None)
                col = colour_var.get().strip()
                if col: r["colour"] = col
                elif "colour" in r: del r["colour"]
            rows[idx] = r
            _refresh_table()
            d.destroy()

        btm = tk.Frame(d, bg=BG)
        btm.grid(row=7, column=0, columnspan=2, pady=(10,10))
        btn(btm, "Apply", bg="#225522", fg=GOLD, font=fnt, pady=5,
            command=_apply).pack(side=tk.LEFT, padx=6)
        btn(btm, "Cancel", bg="#333333", fg=FGA, font=fnt, pady=5,
            command=d.destroy).pack(side=tk.LEFT, padx=6)
        d.bind("<Return>", lambda e: _apply())

    def _save():
        # Validate
        errors = []
        addr_map = {}
        for i, r in enumerate(rows):
            ftype = r.get("type","").lower()
            if ftype in ("divider","clock"): continue
            if not r.get("name"):
                errors.append(f"Row {i+1}: missing name")
            if ftype == "submaster":
                continue  # no address needed
            if not r.get("address"):
                errors.append(f"Row {i+1}: missing address")
                continue
            try:
                defn = load_fixture_def(ftype)
                n = len(defn["channels"])
            except Exception:
                errors.append(f"Row {i+1}: unknown type '{ftype}'")
                continue
            for ch in range(r["address"], r["address"] + n):
                if ch in addr_map:
                    errors.append(f"Row {i+1} ({r['name']}): address {ch} conflicts with {addr_map[ch]}")
                addr_map[ch] = r.get("name","?")

        if errors:
            messagebox.showerror("Validation Errors",
                                 "\\n".join(errors[:8]), parent=win)
            return

        try:
            with open(patch_path, "w") as f:
                json.dump(rows, f, indent=2)
            status_lbl.config(text=f"Saved {len(rows)} entries to {patch_path.name}", fg="#44ff44")
            def _do_reload():
                win.destroy()
                on_save_callback()
            win.after(800, _do_reload)
        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=win)

    def _edit_fixture_def():
        if not selected:
            status_lbl.config(text="Select a fixture row first.", fg="#ff8888")
            return
        r = rows[min(selected)]
        ftype = r.get("type","").lower()
        if ftype in ("divider", "clock", "submaster"):
            status_lbl.config(text="No fixture def for this type.", fg="#ff8888")
            return

        # Find the fixture def file
        fix_path = fixtures_dir / f"{ftype}.json"
        is_builtin = not fix_path.exists()

        if is_builtin:
            # Create from builtin def so user can customise it
            try:
                defn = load_fixture_def(ftype)
                fix_path.write_text(json.dumps(defn, indent=2))
                status_lbl.config(text=f"Created {ftype}.json from built-in.", fg="#88ffcc")
            except Exception as e:
                status_lbl.config(text=f"Error: {e}", fg="#ff8888")
                return

        # ── Built-in editor dialog ──
        ed = tk.Toplevel(win)
        ed.title(f"Fixture Def — {ftype}.json")
        ed.configure(bg="#1a1a1a")
        ed.geometry("640x520")
        ed.resizable(True, True)
        ed.grab_set()

        # Toolbar
        toolbar = tk.Frame(ed, bg="#111111")
        toolbar.pack(fill=tk.X, padx=8, pady=(8,0))
        tk.Label(toolbar, text=str(fix_path), bg="#111111", fg="#888888",
                 font=("Helvetica", 9)).pack(side=tk.LEFT)

        def _open_external():
            import subprocess
            subprocess.Popen(["open", str(fix_path)])

        btn(toolbar, "Open in System Editor", bg="#222244", fg="#aaaaff",
            font=("Helvetica", 9), pady=3,
            command=_open_external).pack(side=tk.RIGHT, padx=(4,0))

        # Text area
        txt_frame = tk.Frame(ed, bg="#1a1a1a")
        txt_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4,0))
        txt_scroll = ttk.Scrollbar(txt_frame)
        txt_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        txt = tk.Text(txt_frame, bg="#111122", fg="#ccccff",
                      insertbackground="#ffffff", font=("Courier", 11),
                      relief=tk.FLAT, yscrollcommand=txt_scroll.set,
                      undo=True, tabs="    ")
        txt.pack(fill=tk.BOTH, expand=True)
        txt_scroll.config(command=txt.yview)

        # Load current content
        try:
            txt.insert("1.0", fix_path.read_text())
        except Exception as e:
            txt.insert("1.0", f"Error reading file: {e}")

        # Status
        ed_status = tk.Label(ed, text="", bg="#1a1a1a", fg="#aaaaaa",
                             font=("Helvetica", 9), anchor="w")
        ed_status.pack(fill=tk.X, padx=8, pady=(2,0))

        def _ed_save():
            raw = txt.get("1.0", tk.END).strip()
            try:
                parsed = json.loads(raw)  # validate JSON
                fix_path.write_text(json.dumps(parsed, indent=2))
                # Reload with pretty-printed version
                txt.delete("1.0", tk.END)
                txt.insert("1.0", json.dumps(parsed, indent=2))
                ed_status.config(text=f"Saved {fix_path.name} ✓", fg="#44ff44")
                _def_cache.clear()
            except json.JSONDecodeError as e:
                ed_status.config(text=f"JSON error: {e}", fg="#ff4444")

        def _ed_save_close():
            _ed_save()
            if "JSON error" not in ed_status.cget("text"):
                ed.destroy()

        # Bottom buttons
        ed_btns = tk.Frame(ed, bg="#1a1a1a")
        ed_btns.pack(fill=tk.X, padx=8, pady=(4,8))
        btn(ed_btns, "Save & Close", bg="#225522", fg=GOLD,
            font=("Helvetica", 10, "bold"), pady=5,
            command=_ed_save_close).pack(side=tk.RIGHT, padx=(4,0))
        btn(ed_btns, "Save", bg="#224422", fg="#88ff88",
            font=("Helvetica", 10), pady=5,
            command=_ed_save).pack(side=tk.RIGHT, padx=(4,0))
        btn(ed_btns, "Cancel", bg="#333333", fg="#aaaaaa",
            font=("Helvetica", 10), pady=5,
            command=ed.destroy).pack(side=tk.RIGHT)
        ed.bind("<Command-s>", lambda e: _ed_save())

    def _create_fixture_def():
        """Prompt for a new fixture type name, create a template JSON and open the editor."""
        # Ask for fixture type name
        name_win = tk.Toplevel(win)
        name_win.title("Create Fixture Definition")
        name_win.configure(bg="#1a1a1a")
        name_win.geometry("380x200")
        name_win.resizable(False, False)
        name_win.grab_set()

        tk.Label(name_win, text="New Fixture Definition",
                 bg="#1a1a1a", fg=GOLD,
                 font=("Helvetica", 12, "bold")).pack(pady=(16, 4))
        tk.Label(name_win, text="Enter a type name (used as the filename, no spaces):",
                 bg="#1a1a1a", fg=FGA,
                 font=("Helvetica", 9)).pack(pady=(0, 6))

        name_var = tk.StringVar(value="my_fixture")
        name_entry = tk.Entry(name_win, textvariable=name_var,
                              bg="#222233", fg="#ffffff",
                              insertbackground="#ffffff",
                              font=("Helvetica", 11), relief=tk.FLAT, bd=4,
                              width=24, justify=tk.CENTER)
        name_entry.pack(pady=(0, 8))
        name_entry.select_range(0, tk.END)
        name_entry.focus_set()

        err_lbl = tk.Label(name_win, text="", bg="#1a1a1a", fg="#ff8888",
                           font=("Helvetica", 9))
        err_lbl.pack()

        def _do_create():
            raw = name_var.get().strip().lower().replace(" ", "_")
            if not raw:
                err_lbl.config(text="Please enter a name.")
                return
            fix_path = fixtures_dir / f"{raw}.json"
            if fix_path.exists():
                err_lbl.config(text=f"{raw}.json already exists.")
                return

            template = {
                "colour": "#2b2b2b",
                "channels": [
                    {
                        "label": "Master",
                        "master": True,
                        "default": 0,
                        "range": [0, 255],
                        "unit": "%",
                        "show": True
                    },
                    {
                        "label": "Ch2",
                        "master": False,
                        "default": 0,
                        "range": [0, 255],
                        "unit": "%",
                        "show": True
                    }
                ]
            }
            try:
                fix_path.write_text(json.dumps(template, indent=2))
            except Exception as e:
                err_lbl.config(text=f"Error: {e}")
                return

            name_win.destroy()

            # Open in built-in editor (reuse _edit_fixture_def logic)
            ed = tk.Toplevel(win)
            ed.title(f"Fixture Def — {raw}.json")
            ed.configure(bg="#1a1a1a")
            ed.geometry("640x560")
            ed.resizable(True, True)
            ed.grab_set()

            toolbar = tk.Frame(ed, bg="#111111")
            toolbar.pack(fill=tk.X, padx=8, pady=(8,0))
            tk.Label(toolbar, text=str(fix_path), bg="#111111", fg="#888888",
                     font=("Helvetica", 9)).pack(side=tk.LEFT)

            def _open_external():
                import subprocess
                subprocess.Popen(["open", str(fix_path)])
            btn(toolbar, "Open in System Editor", bg="#222244", fg="#aaaaff",
                font=("Helvetica", 9), pady=3,
                command=_open_external).pack(side=tk.RIGHT, padx=(4,0))

            # Help text
            help_text = (
                "Channel fields:\n"
                "  label   — channel name (use R/G/B/W/A/UV for colour channels)\n"
                "  master  — true for the main intensity/dimmer channel\n"
                "  default — DMX value on startup (0–255)\n"
                "  range   — [0,255] for numeric, or {\"0-127\": \"Off\", \"128-255\": \"On\"} for named\n"
                "  unit    — \"%\" (percentage), \"raw\" (DMX value), \"named\" (mode names)\n"
                "  show    — false to hide channel (sends default value silently)\n"
                "  layout  — (top level) \"vertical\" or \"horizontal\" for digital fixtures"
            )
            help_lbl = tk.Label(ed, text=help_text, bg="#111122", fg="#557755",
                                font=("Courier", 8), justify=tk.LEFT, anchor="w",
                                padx=8, pady=4)
            help_lbl.pack(fill=tk.X, padx=8, pady=(4,0))

            txt_frame = tk.Frame(ed, bg="#1a1a1a")
            txt_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4,0))
            txt_scroll = ttk.Scrollbar(txt_frame)
            txt_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            txt = tk.Text(txt_frame, bg="#111122", fg="#ccccff",
                          insertbackground="#ffffff", font=("Courier", 11),
                          relief=tk.FLAT, yscrollcommand=txt_scroll.set,
                          undo=True, tabs="    ")
            txt.pack(fill=tk.BOTH, expand=True)
            txt_scroll.config(command=txt.yview)
            txt.insert("1.0", fix_path.read_text())

            ed_status = tk.Label(ed, text="", bg="#1a1a1a", fg="#aaaaaa",
                                 font=("Helvetica", 9), anchor="w")
            ed_status.pack(fill=tk.X, padx=8, pady=(2,0))

            def _ed_save():
                raw_json = txt.get("1.0", tk.END).strip()
                try:
                    parsed = json.loads(raw_json)
                    fix_path.write_text(json.dumps(parsed, indent=2))
                    txt.delete("1.0", tk.END)
                    txt.insert("1.0", json.dumps(parsed, indent=2))
                    ed_status.config(text=f"Saved {fix_path.name} ✓", fg="#44ff44")
                    _def_cache.clear()
                    status_lbl.config(text=f"Created {fix_path.name}", fg="#88ffcc")
                except json.JSONDecodeError as e:
                    ed_status.config(text=f"JSON error: {e}", fg="#ff4444")

            def _ed_save_close():
                _ed_save()
                if "JSON error" not in ed_status.cget("text"):
                    ed.destroy()

            ed_btns = tk.Frame(ed, bg="#1a1a1a")
            ed_btns.pack(fill=tk.X, padx=8, pady=(4,8))
            btn(ed_btns, "Save & Close", bg="#225522", fg=GOLD,
                font=("Helvetica", 10, "bold"), pady=5,
                command=_ed_save_close).pack(side=tk.RIGHT, padx=(4,0))
            btn(ed_btns, "Save", bg="#224422", fg="#88ff88",
                font=("Helvetica", 10), pady=5,
                command=_ed_save).pack(side=tk.RIGHT, padx=(4,0))
            btn(ed_btns, "Cancel", bg="#333333", fg="#aaaaaa",
                font=("Helvetica", 10), pady=5,
                command=ed.destroy).pack(side=tk.RIGHT)
            ed.bind("<Command-s>", lambda e: _ed_save())

        btn_frame = tk.Frame(name_win, bg="#1a1a1a")
        btn_frame.pack(pady=(4, 12))
        btn(btn_frame, "Create", bg="#225522", fg=GOLD,
            font=("Helvetica", 10, "bold"), pady=4, padx=12,
            command=_do_create).pack(side=tk.LEFT, padx=4)
        btn(btn_frame, "Cancel", bg="#333333", fg="#aaaaaa",
            font=("Helvetica", 10), pady=4, padx=12,
            command=name_win.destroy).pack(side=tk.LEFT, padx=4)
        name_win.bind("<Return>", lambda e: _do_create())

    def _save_as():
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="Save Patch As",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(patch_path.parent),
            parent=win)
        if not path: return
        try:
            with open(path, "w") as f:
                json.dump(rows, f, indent=2)
            status_lbl.config(text=f"Saved to {Path(path).name}", fg="#44ff44")
        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=win)

    def _load_patch():
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Load Patch",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(patch_path.parent),
            parent=win)
        if not path: return
        if not messagebox.askyesno("Load Patch",
                "Replace current patch?\nUnsaved changes will be lost.",
                parent=win): return
        try:
            with open(path) as f:
                data = json.load(f)
            rows.clear()
            rows.extend(data)
            _refresh_table()
            status_lbl.config(text=f"Loaded {Path(path).name} — {len(rows)} entries", fg="#88bbff")
        except Exception as e:
            messagebox.showerror("Load Error", str(e), parent=win)



    btn(side, "Cancel", bg="#333333", fg=FGA, font=fnt_s,
        pady=4, width=14, command=win.destroy).pack(fill=tk.X, pady=(2,0))

    _refresh_table()



# ── Settings dialog ────────────────────────────────────────────────────────────

def open_settings_dialog(parent, zoom_level: list, on_layout_change=None):
    """Settings dialog — Art-Net, Appearance, Behaviour. Applied live with Revert."""

    # Snapshot current values for revert
    _snap = {
        "artnet_ip":       _artnet_ip or "127.0.0.1",
        "artnet_port":     _artnet_port,
        "artnet_universe": _artnet_universe,
        "dmx_interval_ms": _dmx_interval_ms,
        "fade_steps_sec":  _fade_steps_sec,
        "startup_zoom":    load_prefs().get("startup_zoom", 1.0),
    }

    win = tk.Toplevel(parent)
    win.title("Settings")
    win.configure(bg="#1a1a1a")
    win.resizable(False, False)
    win.geometry("560x560")
    win.grab_set()

    BG   = "#1a1a1a"
    BG2  = "#222222"
    FG   = "#ffffff"
    FGA  = "#aaaaaa"
    GOLD = "#ffcc00"
    fnt  = ("Helvetica", 10)
    fnt_s = ("Helvetica", 9)
    fnt_hdr = ("Helvetica", 10, "bold")

    def section(text):
        f = tk.Frame(win, bg=BG2)
        f.pack(fill=tk.X, padx=10, pady=(10, 2))
        tk.Label(f, text=text, bg=BG2, fg=GOLD, font=fnt_hdr,
                 anchor="w").pack(fill=tk.X, padx=6, pady=3)

    def row(label, var, row_n, parent_f, tooltip=""):
        tk.Label(parent_f, text=label, bg=BG, fg=FGA, font=fnt_s,
                 width=20, anchor="e").grid(row=row_n, column=0, padx=(8,4), pady=4, sticky="e")
        e = tk.Entry(parent_f, textvariable=var, bg=BG2, fg=FG,
                     insertbackground=FG, font=fnt_s, relief=tk.FLAT, bd=3, width=14)
        e.grid(row=row_n, column=1, padx=(0,8), pady=4, sticky="w")
        if tooltip:
            tk.Label(parent_f, text=tooltip, bg=BG, fg="#666666",
                     font=("Helvetica", 8)).grid(row=row_n, column=2, padx=(0,8), sticky="w")
        return e

    # ── Art-Net ──
    section("🎛  Art-Net")
    an = tk.Frame(win, bg=BG); an.pack(fill=tk.X, padx=10)
    an.columnconfigure(2, weight=1)
    ip_var  = tk.StringVar(value=_artnet_ip or "2.0.0.1")
    prt_var = tk.StringVar(value=str(_artnet_port))
    uni_var = tk.StringVar(value=str(_artnet_universe))
    row("Target IP:",   ip_var,  0, an)
    row("Port:",        prt_var, 1, an, "default 6454")
    row("Universe:",    uni_var, 2, an, "0–15")

    # ── Appearance ──
    section("🎨  Appearance")
    ap = tk.Frame(win, bg=BG); ap.pack(fill=tk.X, padx=10)
    ap.columnconfigure(2, weight=1)
    zoom_var   = tk.StringVar(value=str(load_prefs().get("startup_zoom", zoom_level[0])))
    layout_var = tk.StringVar(value=_scene_layout)
    row("Startup zoom:", zoom_var, 0, ap, "0.5 – 1.5")
    tk.Label(ap, text="Scene layout:", bg=BG, fg=FGA, font=fnt_s,
             width=22, anchor="e").grid(row=1, column=0, padx=(8,4), pady=4, sticky="e")
    ttk.Combobox(ap, textvariable=layout_var,
                 values=["paired", "sequential"],
                 state="readonly", font=fnt_s,
                 width=12).grid(row=1, column=1, padx=(0,8), pady=4, sticky="w")
    tk.Label(ap, text="paired=odd/even  /  sequential=1-12/13-24",
             bg=BG, fg="#666666", font=("Helvetica", 8), wraplength=160
             ).grid(row=1, column=2, padx=(0,8), sticky="w")
    reload_var = tk.BooleanVar(value=_reload_last_show)
    tk.Label(ap, text="Reload last show:", bg=BG, fg=FGA, font=fnt_s,
             width=22, anchor="e").grid(row=2, column=0, padx=(8,4), pady=4, sticky="e")
    tk.Checkbutton(ap, variable=reload_var, bg=BG, fg=FG,
                   activebackground=BG, selectcolor=BG2
                   ).grid(row=2, column=1, sticky="w")
    tk.Label(ap, text="Auto-load last show file on startup",
             bg=BG, fg="#666666", font=("Helvetica", 8), wraplength=160
             ).grid(row=2, column=2, padx=(0,8), sticky="w")

    # ── Behaviour ──
    section("⚙  Behaviour")
    bh = tk.Frame(win, bg=BG); bh.pack(fill=tk.X, padx=10)
    bh.columnconfigure(2, weight=1)
    dmx_var  = tk.StringVar(value=str(_dmx_interval_ms))
    fade_var = tk.StringVar(value=str(_fade_steps_sec))
    row("DMX interval (ms):",    dmx_var,  0, bh, "25 = 40Hz")
    row("Fade steps/sec:",       fade_var, 1, bh, "40 = smooth")

    # ── OSC ──
    section("🎵  OSC Input (receive from QLab)")
    oc = tk.Frame(win, bg=BG); oc.pack(fill=tk.X, padx=10)
    oc.columnconfigure(2, weight=1)
    osc_en_var   = tk.BooleanVar(value=_osc_enabled)
    osc_port_var = tk.StringVar(value=str(_osc_port))
    tk.Label(oc, text="Enable OSC:", bg=BG, fg=FGA, font=fnt_s,
             width=22, anchor="e").grid(row=0, column=0, padx=(8,4), pady=4, sticky="e")
    tk.Checkbutton(oc, variable=osc_en_var, bg=BG, fg=FG,
                   activebackground=BG, selectcolor=BG2).grid(row=0, column=1, sticky="w")
    row("OSC Port:", osc_port_var, 1, oc, "default 8000")
    tk.Label(oc, text="QLab OSC path examples:", bg=BG, fg="#666666",
             font=("Helvetica", 8)).grid(row=2, column=0, columnspan=3,
             padx=(8,4), pady=(0,2), sticky="w")
    examples = ("/desk/scene/recall 3  or  /desk/scene/recall \"Scene Name\"\n"
                "/desk/scene/recall/Scene_Name  (underscores = spaces)\n"
                "/desk/scene/go  /  /desk/grandmaster 80\n"
                "/desk/fader/Wash1 75")
    tk.Label(oc, text=examples, bg=BG, fg="#557755",
             font=("Courier", 8), justify=tk.LEFT).grid(
             row=3, column=0, columnspan=3, padx=(8,4), pady=(0,4), sticky="w")

    def _apply():
        global _artnet_ip, _artnet_port, _artnet_universe, _dmx_interval_ms, _fade_steps_sec
        global _osc_enabled, _osc_port
        try:
            ip   = ip_var.get().strip()
            port = int(prt_var.get())
            uni  = int(uni_var.get())
            dmi  = int(dmx_var.get())
            fds  = int(fade_var.get())
            zm   = float(zoom_var.get())
            osc_p = int(osc_port_var.get())
            if not (0 <= uni <= 15):     raise ValueError("Universe must be 0–15")
            if not (1 <= port <= 65535): raise ValueError("Port out of range")
            if not (5 <= dmi <= 200):    raise ValueError("DMX interval must be 5–200ms")
            if not (10 <= fds <= 100):   raise ValueError("Fade steps must be 10–100")
            if not (0.5 <= zm <= 1.5):   raise ValueError("Zoom must be 0.5–1.5")
            if not (1 <= osc_p <= 65535): raise ValueError("OSC port out of range")
        except ValueError as e:
            status_lbl.config(text=f"Error: {e}", fg="#ff4444")
            return

        _artnet_ip       = ip
        _artnet_port     = port
        _artnet_universe = uni
        _dmx_interval_ms = dmi
        _fade_steps_sec  = fds

        if _artnet_sock:
            start_artnet(ip, port, uni)

        # Restart OSC listener if settings changed
        osc_changed = (osc_en_var.get() != _osc_enabled or osc_p != _osc_port)
        _osc_enabled = osc_en_var.get()
        _osc_port    = osc_p
        if osc_changed:
            stop_osc_listener()
            if _osc_enabled:
                import threading as _th
                _th.Timer(0.2, lambda: start_osc_listener(win.winfo_toplevel())).start()

        global _scene_layout, _reload_last_show
        _scene_layout     = layout_var.get()
        _reload_last_show = reload_var.get()

        prefs = load_prefs()
        prefs.update({
            "artnet_ip": ip, "artnet_port": port, "artnet_universe": uni,
            "dmx_interval_ms": dmi, "fade_steps_sec": fds, "startup_zoom": zm,
            "osc_enabled": _osc_enabled, "osc_port": _osc_port,
            "scene_layout":    _scene_layout,
            "reload_last_show": _reload_last_show,
        })
        save_prefs(prefs)
        # Rebuild scene buttons with new layout
        if on_layout_change: on_layout_change()
        status_lbl.config(text="Settings applied and saved ✓", fg="#44ff44")

    def _revert():
        global _artnet_ip, _artnet_port, _artnet_universe, _dmx_interval_ms, _fade_steps_sec
        _artnet_ip       = _snap["artnet_ip"]
        _artnet_port     = _snap["artnet_port"]
        _artnet_universe = _snap["artnet_universe"]
        _dmx_interval_ms = _snap["dmx_interval_ms"]
        _fade_steps_sec  = _snap["fade_steps_sec"]
        if _artnet_sock:
            start_artnet(_artnet_ip, _artnet_port, _artnet_universe)
        ip_var.set(_snap["artnet_ip"])
        prt_var.set(str(_snap["artnet_port"]))
        uni_var.set(str(_snap["artnet_universe"]))
        dmx_var.set(str(_snap["dmx_interval_ms"]))
        fade_var.set(str(_snap["fade_steps_sec"]))
        zoom_var.set(str(_snap["startup_zoom"]))
        status_lbl.config(text="Reverted to previous values.", fg="#ffaa44")

    status_lbl = tk.Label(win, text="", bg=BG, fg=FGA, font=fnt_s, anchor="w")
    status_lbl.pack(fill=tk.X, padx=12, pady=(4,0))

    btns = tk.Frame(win, bg=BG)
    btns.pack(fill=tk.X, padx=10, pady=(4,16))
    btn(btns, "Apply",  bg="#225522", fg=GOLD, font=fnt, pady=6,
        command=_apply).pack(side=tk.RIGHT, padx=(4,0))
    btn(btns, "Revert", bg="#332211", fg="#ffaa44", font=fnt, pady=6,
        command=_revert).pack(side=tk.RIGHT, padx=(4,0))
    btn(btns, "Close",  bg="#333333", fg=FGA, font=fnt, pady=6,
        command=win.destroy).pack(side=tk.RIGHT)


# ── OSC Listener ───────────────────────────────────────────────────────────────
# Minimal OSC 1.0 parser — no dependencies, handles string/int/float args.

def _osc_pad(n):
    """Round up to next multiple of 4."""
    return (n + 3) & ~3

def _osc_parse(data: bytes):
    """
    Parse a minimal OSC message.
    Returns (address, args) or (None, None) on failure.
    """
    try:
        # Address string
        addr_end = data.index(b"\x00")
        address  = data[:addr_end].decode("ascii")
        pos      = _osc_pad(addr_end + 1)

        # Type tag string
        if pos >= len(data) or data[pos:pos+1] != b",":
            return address, []
        tag_end = data.index(b"\x00", pos)
        tags    = data[pos+1:tag_end].decode("ascii")
        pos     = _osc_pad(tag_end + 1)

        args = []
        for tag in tags:
            if tag == "i":
                args.append(struct.unpack_from(">i", data, pos)[0]); pos += 4
            elif tag == "f":
                args.append(struct.unpack_from(">f", data, pos)[0]); pos += 4
            elif tag == "s":
                s_end = data.index(b"\x00", pos)
                args.append(data[pos:s_end].decode("ascii"))
                pos = _osc_pad(s_end + 1)
        return address, args
    except Exception:
        return None, None

# Callbacks set by build_ui so OSC thread can call into the UI safely
_osc_callbacks = {}

def _osc_dispatch(address: str, args: list, root):
    """Called from OSC thread via root.after — runs on UI thread."""
    cb = _osc_callbacks
    try:
        # /desk/scene/recall <int>  — recall a scene slot by number
        # /desk/scene/recall "Name" — recall by name (string arg)
        if address == "/desk/scene/recall" and args:
            if isinstance(args[0], str):
                if "recall_by_name" in cb:
                    cb["recall_by_name"](args[0])
                    print(f"OSC: recall scene '{args[0]}'")
            else:
                slot = int(args[0])
                if "recall_scene" in cb:
                    cb["recall_scene"](slot)
                    print(f"OSC: recall scene {slot}")

        # /desk/scene/go  — fire selected scene
        elif address == "/desk/scene/go":
            if "scene_go" in cb:
                cb["scene_go"]()
                print("OSC: scene go")

        # /desk/grandmaster <float 0-100>
        elif address == "/desk/grandmaster" and args:
            val = max(0, min(100, float(args[0])))
            if "set_gm" in cb:
                cb["set_gm"](val)
                print(f"OSC: GM → {val:.1f}%")

        # /desk/fader/<fixture_name> <float 0-100>
        elif address.startswith("/desk/fader/") and args:
            name = address[len("/desk/fader/"):]
            val  = max(0, min(100, float(args[0])))
            if "set_fader" in cb:
                cb["set_fader"](name, val)
                print(f"OSC: fader {name} → {val:.1f}%")

        # /desk/scene/select <int or string>  — select without recalling
        elif address == "/desk/scene/select" and args:
            if isinstance(args[0], str):
                if "select_by_name" in cb:
                    cb["select_by_name"](args[0])
                    print(f"OSC: select scene '{args[0]}'")
            else:
                slot = int(args[0])
                if "select_scene" in cb:
                    cb["select_scene"](slot)
                    print(f"OSC: select scene {slot}")

        # /desk/scene/recall/<name>  — recall by name (underscores = spaces)
        # /desk/scene/recall "Name"  — recall by name as string arg
        elif address.startswith("/desk/scene/recall/") or \
             (address == "/desk/scene/recall" and args and isinstance(args[0], str)):
            if address.startswith("/desk/scene/recall/"):
                name = address[len("/desk/scene/recall/"):].replace("_", " ")
            else:
                name = args[0]
            if "recall_by_name" in cb:
                cb["recall_by_name"](name)
                print(f"OSC: recall scene '{name}'")

        # /desk/scene/select/<name>  — select by name (underscores = spaces)
        # /desk/scene/select "Name"  — select by name as string arg
        elif address.startswith("/desk/scene/select/") or \
             (address == "/desk/scene/select" and args and isinstance(args[0], str)):
            if address.startswith("/desk/scene/select/"):
                name = address[len("/desk/scene/select/"):].replace("_", " ")
            else:
                name = args[0]
            if "select_by_name" in cb:
                cb["select_by_name"](name)
                print(f"OSC: select scene '{name}'")
    except Exception as e:
        print(f"OSC dispatch error: {e}")

def start_osc_listener(root):
    """Start OSC UDP listener in a background daemon thread."""
    global _osc_sock
    if not _osc_enabled:
        return
    try:
        _osc_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        _osc_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        _osc_sock.bind(("0.0.0.0", _osc_port))
        _osc_sock.settimeout(1.0)
        print(f"OSC listener ready on port {_osc_port}")
    except Exception as e:
        print(f"OSC listener failed to start: {e}")
        return

    def _listen():
        while _osc_enabled:
            try:
                data, _ = _osc_sock.recvfrom(1024)
                addr, args = _osc_parse(data)
                if addr:
                    root.after(0, lambda a=addr, g=args: _osc_dispatch(a, g, root))
            except _socket.timeout:
                continue
            except Exception:
                break

    t = threading.Thread(target=_listen, daemon=True)
    t.start()

def stop_osc_listener():
    global _osc_sock, _osc_enabled
    _osc_enabled = False
    if _osc_sock:
        try: _osc_sock.close()
        except Exception: pass
        _osc_sock = None

# ── Main UI ────────────────────────────────────────────────────────────────────

dry_run = False

def build_ui(patch: list, patch_path: Path = None):
    global gm_var

    root = tk.Tk()
    root.title("DMX Desk Emulator")
    root.configure(bg="#1a1a1a")
    root.resizable(True, True)

    # Restore saved window geometry
    _prefs = load_prefs()
    if "geometry" in _prefs:
        try: root.geometry(_prefs["geometry"])
        except Exception: pass

    # Apply saved settings
    global _artnet_ip, _artnet_port, _artnet_universe, _dmx_interval_ms, _fade_steps_sec
    if "artnet_ip"       in _prefs and _artnet_ip:
        _artnet_ip       = _prefs["artnet_ip"]
        if _artnet_sock: start_artnet(_artnet_ip, _prefs.get("artnet_port", 6454),
                                      _prefs.get("artnet_universe", 0))
    if "artnet_port"     in _prefs: _artnet_port     = int(_prefs["artnet_port"])
    if "artnet_universe" in _prefs: _artnet_universe = int(_prefs["artnet_universe"])
    if "dmx_interval_ms" in _prefs: _dmx_interval_ms = int(_prefs["dmx_interval_ms"])
    if "fade_steps_sec"  in _prefs: _fade_steps_sec  = int(_prefs["fade_steps_sec"])
    if "osc_enabled"     in _prefs: _osc_enabled     = bool(_prefs["osc_enabled"])
    if "osc_port"        in _prefs: _osc_port        = int(_prefs["osc_port"])
    if "scene_layout"      in _prefs: _scene_layout      = _prefs["scene_layout"]
    if "reload_last_show"  in _prefs: _reload_last_show  = bool(_prefs["reload_last_show"])

    def _on_geometry_change(event=None):
        if root.wm_state() == "normal":
            p = load_prefs()
            p["geometry"] = root.winfo_geometry()
            save_prefs(p)
    root.bind("<Configure>", _on_geometry_change)

    # ── Top bar ──
    topbar = tk.Frame(root, bg="#111111", pady=6)
    topbar.pack(fill=tk.X, padx=10, pady=(6, 0))
    tk.Label(topbar, text=f"DMX DESK EMULATOR  v{VERSION}.{BUILD}", bg="#111111", fg="#ffcc00",
             font=("Helvetica", 15, "bold")).pack(side=tk.LEFT, padx=10)

    # Show file label in header
    show_file_var = tk.StringVar(value="No show file loaded")
    tk.Label(topbar, textvariable=show_file_var, bg="#111111", fg="#44aa66",
             font=("Helvetica", 12, "bold"), anchor="w").pack(side=tk.LEFT, padx=(16, 0))

    def _update_show_label():
        if _current_show_file:
            show_file_var.set(f"Show: {Path(_current_show_file).name}")
        else:
            show_file_var.set("Show: patch_scenes.json")
    _update_show_label()  # set initial label

    # Art-Net indicator with background ping
    import time as _time, subprocess as _sp
    _an_indicator = tk.Label(topbar, text="● ArtNet", bg="#111111",
                             fg="#444444", font=("Helvetica", 12))
    _an_indicator.pack(side=tk.RIGHT, padx=(0, 8))

    _ping_state = {"reachable": None, "pinging": False}
    PING_INTERVAL = 5000  # ms between pings

    def _run_ping():
        """Run a single ping in a background thread, update state."""
        if dry_run or _artnet_sock is None:
            return
        ip = _artnet_ip
        def _do():
            try:
                r = _sp.run(["ping", "-c", "1", "-W", "1", "-t", "1", ip],
                             stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                _ping_state["reachable"] = (r.returncode == 0)
            except Exception:
                _ping_state["reachable"] = False
            finally:
                _ping_state["pinging"] = False
        if not _ping_state["pinging"]:
            _ping_state["pinging"] = True
            threading.Thread(target=_do, daemon=True).start()

    def _update_artnet_indicator():
        if dry_run:
            _an_indicator.config(text="● ArtNet", fg="#888888")
        elif _artnet_error or _artnet_sock is None:
            _an_indicator.config(text="● ArtNet", fg="#ff4444")
        elif _ping_state["reachable"] is None:
            # No ping result yet — just show send status
            if _time.time() - _artnet_last_send < 0.5:
                _an_indicator.config(text="● ArtNet", fg="#44ff44")
            else:
                _an_indicator.config(text="● ArtNet", fg="#888844")
        elif _ping_state["reachable"]:
            _an_indicator.config(text="● ArtNet", fg="#44ff44")
        else:
            _an_indicator.config(text="● ArtNet", fg="#ff4444")
        root.after(500, _update_artnet_indicator)

    def _ping_loop():
        _run_ping()
        root.after(PING_INTERVAL, _ping_loop)

    root.after(600,  _update_artnet_indicator)
    root.after(1000, _ping_loop)

    def _open_manual():
        import subprocess
        if MANUAL_FILE.exists():
            subprocess.Popen(["open", str(MANUAL_FILE)])
        else:
            messagebox.showinfo("Help", f"Manual not found.\n\nExpected at:\n{MANUAL_FILE}",
                                parent=root)
    btn(topbar, "? Help", bg="#222233", fg="#aaaaff",
        font=("Helvetica", 10, "bold"), pady=4,
        command=_open_manual).pack(side=tk.LEFT, padx=(4, 0))
    if dry_run:
        tk.Label(topbar, text="DRY RUN — no Art-Net output", bg="#111111",
                 fg="#ff6666", font=("Helvetica", 9)).pack(side=tk.LEFT, padx=10)

    btn(topbar, "⚙ Edit Patch", bg="#332211", fg="#ffaa44",
        font=("Helvetica", 10, "bold"), pady=4,
        command=lambda: open_patch_editor(
            root, patch_path, FIXTURES_DIR,
            _reload_patch)
        ).pack(side=tk.RIGHT, padx=(0, 4))

    btn(topbar, "⚙ Settings", bg="#222233", fg="#aaaaff",
        font=("Helvetica", 10, "bold"), pady=4,
        command=lambda: open_settings_dialog(root, zoom_level, _rebuild_scene_buttons)
        ).pack(side=tk.RIGHT, padx=(0, 4))

    gm_var = tk.IntVar(value=100)

    # ── Fixture canvas ──
    canvas_frame = tk.Frame(root, bg="#1a1a1a")
    canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    # Scrollbars must be packed before canvas so layout reserves space correctly
    # They are hidden initially and shown only when content overflows
    h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
    v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
    canvas = tk.Canvas(canvas_frame, bg="#1a1a1a", highlightthickness=0,
                       xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)
    h_scroll.config(command=canvas.xview)
    v_scroll.config(command=canvas.yview)

    def _h_scroll_set(lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            h_scroll.pack_forget()
        else:
            h_scroll.pack(side=tk.BOTTOM, fill=tk.X, before=canvas)
        h_scroll.set(lo, hi)

    def _v_scroll_set(lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            v_scroll.pack_forget()
        else:
            v_scroll.pack(side=tk.RIGHT, fill=tk.Y, before=canvas)
        v_scroll.set(lo, hi)

    canvas.configure(xscrollcommand=_h_scroll_set, yscrollcommand=_v_scroll_set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    fixture_frame = tk.Frame(canvas, bg="#1a1a1a")
    canvas.create_window((0, 0), window=fixture_frame, anchor="nw")

    zoom_level = [1.0]
    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.25, 1.75, 0.05

    # ── Copy/paste state — lives at build_ui scope so it persists across rebuilds ──
    paste_mode   = [False]
    last_clicked = [None]

    # ── Group selection state ──
    group_selected = []   # list of CustomFixture currently in the group

    def _clear_group():
        for fw in group_selected:
            fw.set_group_highlight(False)
            fw.on_master_moved = None
        group_selected.clear()

    def _on_group_master_moved(source_fw, val):
        """Called when any grouped fixture's master moves — sync all others."""
        for fw in group_selected:
            if fw is not source_fw and fw._master_idx is not None:
                fw.set_master_value(val)

    def _fade_fixture_to(fw, target_val, steps=40, interval_ms=25, on_done=None):
        """Smoothly fade a fixture's master to target_val without triggering group sync."""
        if fw._master_idx is None:
            if on_done: on_done()
            return
        start_val = fw._raw[fw._master_idx]
        step_ref  = [0]
        def _step():
            t      = min(1.0, step_ref[0] / steps)
            t_ease = t * t * (3 - 2 * t)
            fw.set_master_value(int(start_val + (target_val - start_val) * t_ease))
            step_ref[0] += 1
            if step_ref[0] <= steps:
                root.after(interval_ms, _step)
            else:
                if on_done: on_done()
        _step()

    def _on_shift_click(fw):
        """Shift+click: toggle fixture in/out of group. Only same-type allowed.
        When adding to a group, fade the new fixture to match the first fixture's level."""
        if fw in group_selected:
            fw.set_group_highlight(False)
            fw.on_master_moved = None
            group_selected.remove(fw)
        else:
            if group_selected and fw.fixture_type_key() != group_selected[0].fixture_type_key():
                return  # different type — ignore
            fw.set_group_highlight(True)
            if group_selected and group_selected[0]._master_idx is not None:
                # Fade to match — don't add to group until fade completes
                # so set_master_value during fade doesn't trigger group sync
                target = group_selected[0]._raw[group_selected[0]._master_idx]
                def _on_fade_done(fixture=fw):
                    group_selected.append(fixture)
                    fixture.on_master_moved = _on_group_master_moved
                _fade_fixture_to(fw, target, on_done=_on_fade_done)
            else:
                # First fixture or no master — just add immediately
                group_selected.append(fw)
                fw.on_master_moved = _on_group_master_moved

    def _cancel_paste(update_btn=True):
        if not paste_mode[0]: return
        paste_mode[0] = False
        for fw in all_widgets:
            if isinstance(fw, CustomFixture):
                fw.set_paste_highlight(False)

    def _do_copy(fw=None):
        if fw is None: fw = last_clicked[0]
        if fw is None: return
        _cancel_paste(update_btn=False)
        _clipboard["state"]    = fw.get_state()
        _clipboard["type_key"] = fw.fixture_type_key()
        paste_mode[0] = True
        for other in all_widgets:
            if isinstance(other, CustomFixture) and other is not fw:
                if other.fixture_type_key() == _clipboard["type_key"]:
                    other.set_paste_highlight(True)

    def _on_paste(fw):
        if not paste_mode[0]: return
        if fw.fixture_type_key() != _clipboard["type_key"]: return
        fw.set_state(_clipboard["state"])
        fw.set_paste_highlight(False)

    def _on_fixture_click(fw):
        last_clicked[0] = fw
        _clear_group()  # plain click clears any group selection
        if paste_mode[0]:
            _on_paste(fw)



    regular_defs   = [(f, load_fixture_def(f["type"])) for f in patch
                      if f.get("type", "").lower() not in ("submaster", "divider", "clock")]
    submaster_defs = [f for f in patch if f.get("type", "").lower() == "submaster"]
    # Dividers are rendered inline during rebuild — extract with row info
    divider_entries = [f for f in patch if f.get("type", "").lower() == "divider"]

    all_widgets   = []
    clock_widgets  = []  # ClockWidgets tracked separately

    def _reload_patch():
        """Re-read patch.json and rebuild the entire fixture panel."""
        nonlocal regular_defs, submaster_defs, divider_entries
        _def_cache.clear()  # force fixture defs to reload from disk
        try:
            with open(patch_path) as f:
                new_patch = json.load(f)
        except Exception as e:
            print(f"Error reloading patch: {e}")
            return
        _def_cache.clear()
        # Update patch in-place so rebuild_fixtures sees the new entries
        patch.clear()
        patch.extend(new_patch)
        new_regular = []
        skip_types = ("submaster", "divider", "clock")
        for fi in new_patch:
            ftype = fi.get("type", "").lower()
            if ftype in skip_types:
                continue
            try:
                defn = load_fixture_def(ftype)
                new_regular.append((fi, defn))
            except Exception as e:
                print(f"Skipping '{fi.get('name','?')}': {e}")
        regular_defs    = new_regular
        submaster_defs  = [fi for fi in new_patch if fi.get("type","").lower() == "submaster"]
        divider_entries = [fi for fi in new_patch if fi.get("type","").lower() == "divider"]
        print(f"Patch reloaded: {len(new_patch)} entries, {len(regular_defs)} fixtures")
        rebuild_fixtures(zoom_level[0])

    def rebuild_fixtures(zoom: float):
        states      = [fw.get_state() for fw in all_widgets]
        solo_states = []
        # Save clock states keyed by name
        clock_states = {cw.name: cw.get_clock_state() for cw in clock_widgets}
        for fw in all_widgets:
            if isinstance(fw, DigitalFixture):
                solo_states.append({
                    "fixture": fw.fixture_solo.soloed,
                    "channels": {i: fw._solos.get(i, False) for i in fw._solos}
                })
            elif isinstance(fw, CustomFixture):
                solo_states.append({
                    "fixture": fw.fixture_solo.soloed,
                    "channels": {i: sb.soloed for i, sb in fw._ch_solos.items()}
                })
            else:
                solo_states.append({"main": fw.solo_btn.soloed})

        for child in fixture_frame.winfo_children():
            child.destroy()
        all_widgets.clear()
        clock_widgets.clear()
        submaster_registry.clear()

        sz = make_sizes(zoom)

        left_frame = tk.Frame(fixture_frame, bg="#1a1a1a")
        left_frame.pack(side=tk.LEFT, anchor="n")
        row_top = tk.Frame(left_frame, bg="#1a1a1a")
        row_bot = tk.Frame(left_frame, bg="#1a1a1a")
        row_top.pack(side=tk.TOP, anchor="nw", pady=(2, 0))
        row_bot.pack(side=tk.TOP, anchor="nw", pady=(0, 2))

        # ── Build real widgets — row assigned from patch entry (default: 1) ──
        # Rebuild full patch order including dividers so placement is preserved
        fixture_widgets = []
        reg_iter = iter(regular_defs)
        for f in patch:
            ftype = f.get("type", "").lower()
            if ftype == "divider":
                parent = row_bot if f.get("row", 1) == 2 else row_top
                div_h = max(20, int(sz["master_h"] * 0.3))
                tk.Frame(parent, bg="#555555", width=2, height=div_h
                         ).pack(side=tk.LEFT, padx=max(2, int(6 * zoom_level[0])),
                                pady=2, anchor="n")
            elif ftype == "clock":
                parent = row_bot if f.get("row", 1) == 2 else row_top
                cname = f.get("name", "Clock")
                w = ClockWidget(parent, name=cname, sz=sz)
                w.pack(side=tk.LEFT, padx=2, pady=2, anchor="n")
                if cname in clock_states:
                    w.restore_clock_state(clock_states[cname])
                clock_widgets.append(w)
                # ClockWidget is not a DMX fixture — don't add to fixture_widgets
            elif ftype not in ("submaster",):
                try:
                    f2, defn = next(reg_iter)
                except StopIteration:
                    break
                parent = row_bot if f2.get("row", 1) == 2 else row_top
                colour = f2.get("colour", defn.get("colour", "#2b2b2b"))
                if is_digital_fixture(defn["channels"]):
                    w = DigitalFixture(parent, f2["name"], f2["address"],
                                       defn["channels"], sz=sz, colour=colour,
                                       layout=defn.get("layout", "auto"))
                else:
                    w = CustomFixture(parent, f2["name"], f2["address"],
                                      defn["channels"], sz=sz, colour=colour)
                w.pack(side=tk.LEFT, padx=2, pady=2, anchor="n")
                w.bind("<Button-1>",  lambda e, fw=w: _on_fixture_click(fw))
                w.bind("<Shift-Button-1>", lambda e, fw=w: _on_shift_click(fw))
                w.bind("<Button-2>",  lambda e, fw=w: _do_copy(fw))
                w.bind("<Button-3>",  lambda e, fw=w: _do_copy(fw))
                w.bind("<Control-1>", lambda e, fw=w: _do_copy(fw))
                fixture_widgets.append(w)

        # ── Submasters ──
        submaster_widgets = []
        if submaster_defs:
            tk.Frame(fixture_frame, bg="#444444", width=2).pack(
                side=tk.LEFT, fill=tk.Y, padx=(6, 6), pady=4)
            sub_frame = tk.Frame(fixture_frame, bg="#1a1a1a")
            sub_frame.pack(side=tk.LEFT, anchor="n")
            sub_row_top = tk.Frame(sub_frame, bg="#1a1a1a")
            sub_row_bot = tk.Frame(sub_frame, bg="#1a1a1a")
            sub_row_top.pack(side=tk.TOP, anchor="nw", pady=(2, 0))
            sub_row_bot.pack(side=tk.TOP, anchor="nw", pady=(0, 2))
            for f in submaster_defs:
                parent = sub_row_bot if f.get("row", 1) == 2 else sub_row_top
                w = SubmasterWidget(parent, f["name"],
                                    f.get("targets", []), fixture_widgets, sz=sz)
                w.pack(side=tk.LEFT, padx=2, pady=2, anchor="n")
                submaster_widgets.append(w)
                for t in f.get("targets", []):
                    submaster_registry.setdefault(t, []).append(w)

        all_widgets.extend(fixture_widgets + submaster_widgets)

        # ── Restore states ──
        for i, fw in enumerate(all_widgets):
            if i < len(states) and states[i]:
                fw.set_state(states[i])
            if i < len(solo_states):
                ss = solo_states[i]
                if isinstance(fw, DigitalFixture):
                    if ss.get("fixture"): fw.fixture_solo.set_on()
                    for ci, on in ss.get("channels", {}).items():
                        if on:
                            fw._solos[ci] = True
                            if ci in fw._solo_btns: fw._solo_btns[ci].set_on()
                elif isinstance(fw, CustomFixture):
                    if ss.get("fixture"): fw.fixture_solo.set_on()
                    for ci, was_soloed in ss.get("channels", {}).items():
                        if was_soloed and ci in fw._ch_solos:
                            fw._ch_solos[ci].set_on()
                else:
                    if ss.get("main"): fw.solo_btn.set_on()

        root.after(50, lambda: canvas.configure(scrollregion=canvas.bbox("all")))

    fixture_frame.bind("<Configure>",
                       lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    rebuild_fixtures(zoom_level[0])

    # ── Scene bar ──
    scene_names   = {slot: scene["name"]   for slot, scene in scenes.items() if "name"   in scene}
    scene_colours = {slot: scene["colour"] for slot, scene in scenes.items() if "colour" in scene}
    scene_bar = tk.Frame(root, bg="#111111", pady=2)
    scene_bar.pack(fill=tk.X, padx=10, pady=(0, 10))

    selected_slot = tk.IntVar(value=1)
    go_buttons = {}

    def _slot_bg(s):
        if s == selected_slot.get(): return "#cc8800"
        if s in scene_colours:
            # Blend scene colour toward dark background
            try:
                c = scene_colours[s].lstrip("#")
                r = int(int(c[0:2], 16) * 0.35)
                g = int(int(c[2:4], 16) * 0.35)
                b = int(int(c[4:6], 16) * 0.35)
                return f"#{r:02x}{g:02x}{b:02x}"
            except Exception:
                pass
        return "#1a4a1a" if s in scenes else "#333333"
    def _slot_fg(s):
        if s == selected_slot.get(): return "#000000"
        return "#ffffff" if s in scenes else "#aaaaaa"

    def _rebuild_scene_buttons():
        """Re-grid all scene buttons using current _scene_layout."""
        for slot, b in go_buttons.items():
            grid_row, grid_col = _slot_pos(slot)
            b.grid(row=grid_row, column=grid_col, sticky="ew", padx=2, pady=2)
        # Ensure all 15 columns are weighted
        for _c in range(SCENE_COLS):
            scene_grid.columnconfigure(_c, weight=1, uniform="scene")

    def _refresh_buttons():
        for s, b in go_buttons.items():
            b.config(bg=_slot_bg(s), fg=_slot_fg(s),
                     activebackground=_darken(_slot_bg(s)),
                     activeforeground=_slot_fg(s),
                     text=scene_names.get(s, f"Scene {s}"))

    def _select_slot(s): selected_slot.set(s); _refresh_buttons()

    def _rename_slot(slot):
        if _scene_fade_active[0]: return
        win = tk.Toplevel(root)
        win.title(f"Edit Scene {slot}")
        win.configure(bg="#1a1a1a"); win.resizable(False, False); win.grab_set()

        # Name
        tk.Label(win, text=f"Name for scene {slot}:", bg="#1a1a1a", fg="#aaaaaa",
                 font=("Helvetica", 10)).pack(padx=16, pady=(12, 4))
        name_var = tk.StringVar(value=scene_names.get(slot, f"Scene {slot}"))
        entry = tk.Entry(win, textvariable=name_var, width=24,
                         bg="#333333", fg="#ffcc00", insertbackground="#ffcc00",
                         font=("Helvetica", 11), relief=tk.FLAT, bd=4)
        entry.pack(padx=16, pady=4); entry.select_range(0, tk.END); entry.focus_set()

        # Colour picker
        colour_frame = tk.Frame(win, bg="#1a1a1a")
        colour_frame.pack(padx=16, pady=(4, 8))
        tk.Label(colour_frame, text="Button colour:", bg="#1a1a1a", fg="#aaaaaa",
                 font=("Helvetica", 10)).pack(side=tk.LEFT, padx=(0, 8))
        current_colour = scene_colours.get(slot, "")
        colour_var = tk.StringVar(value=current_colour)
        swatch = tk.Frame(colour_frame, width=32, height=22,
                          bg=current_colour if current_colour else "#333333",
                          relief=tk.RIDGE, bd=1)
        swatch.pack(side=tk.LEFT, padx=(0, 6))

        def _pick_colour():
            from tkinter import colorchooser
            c = colorchooser.askcolor(
                color=colour_var.get() or "#336633",
                title="Scene button colour", parent=win)
            if c and c[1]:
                colour_var.set(c[1])
                swatch.config(bg=c[1])

        def _clear_colour():
            colour_var.set("")
            swatch.config(bg="#333333")

        btn(colour_frame, "Choose…", bg="#333333", fg="#aaaaaa",
            font=("Helvetica", 9), pady=2,
            command=_pick_colour).pack(side=tk.LEFT, padx=(0, 4))
        btn(colour_frame, "Clear", bg="#333333", fg="#aaaaaa",
            font=("Helvetica", 9), pady=2,
            command=_clear_colour).pack(side=tk.LEFT)

        def _confirm(_=None):
            name = name_var.get().strip() or f"Scene {slot}"
            scene_names[slot] = name
            col = colour_var.get().strip()
            if col:
                scene_colours[slot] = col
            else:
                scene_colours.pop(slot, None)
            if slot in scenes:
                scenes[slot]["name"]   = name
                if col: scenes[slot]["colour"] = col
                else:   scenes[slot].pop("colour", None)
                save_scenes_to_disk()
            _refresh_buttons(); win.destroy()

        entry.bind("<Return>", _confirm)
        btn(win, "OK", bg="#225522", fg="#ffffff",
            font=("Helvetica", 10, "bold"), width=8,
            command=_confirm).pack(pady=(4, 12))

    fade_var = tk.StringVar(value="0.0")
    def get_fade_time():
        try: return max(0.0, float(fade_var.get()))
        except ValueError: return 0.0

    def _do_rec():
        slot = selected_slot.get()
        if any_soloed(all_widgets):
            from tkinter import messagebox as _mb
            answer = _mb.askyesnocancel(
                "Solos Active",
                "Some channels are soloed — only soloed channels will be recorded.\n\n"
                "• Yes  — clear solos and record all channels\n"
                "• No   — record with solos (partial scene)\n"
                "• Cancel — do not record",
                parent=root)
            if answer is None:   # Cancel
                return
            if answer:           # Yes — clear solos first
                _do_clear_solos()
        store_scene(slot, all_widgets, get_fade_time())
        if slot in scene_names: scenes[slot]["name"] = scene_names[slot]
        if slot in scene_colours: scenes[slot]["colour"] = scene_colours[slot]
        save_scenes_to_disk()
        _refresh_buttons()
        rec_btn.config(bg="#ddaa00", fg="#000000")
        root.after(180, lambda: rec_btn.config(bg="#aa3300", fg="#ffffff"))

    def _do_clr():
        slot = selected_slot.get()
        if slot not in scenes: return
        if messagebox.askyesno("Clear Scene",
                               f"Clear scene {slot} ({scene_names.get(slot, f'Scene {slot}')})?\n\nThis cannot be undone."):
            clear_scene(slot); scene_names.pop(slot, None); scene_colours.pop(slot, None); _refresh_buttons()

    def _do_save_show():
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="Save Show", defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="show.json")
        if not path: return
        try:
            data = {str(k): v for k, v in scenes.items()}
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"Show saved to {path}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def _do_load_show():
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Load Show",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path: return
        if not messagebox.askyesno("Load Show",
                                   "Replace all current scenes with the loaded show?\n\nThis cannot be undone."):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            scenes.clear()
            scene_names.clear()
            scene_colours.clear()
            all_names = [fw.name for fw in all_widgets]
            for k, v in data.items():
                slot = int(k)
                if not isinstance(v, dict):
                    continue
                # Migrate list-format if needed
                fx = v.get("fixtures", {})
                if isinstance(fx, list):
                    fx = {all_names[i]: s for i, s in enumerate(fx)
                          if i < len(all_names)}
                    v = dict(v); v["fixtures"] = fx
                scenes[slot] = v
                if "name" in v:
                    scene_names[slot] = v["name"]
                if "colour" in v:
                    scene_colours[slot] = v["colour"]
            global _current_show_file, scenes_path
            _current_show_file = path
            scenes_path        = path
            save_scenes_to_disk()
            _refresh_buttons()
            _update_show_label()
            prefs = load_prefs()
            prefs["last_show_file"] = path
            save_prefs(prefs)
            print(f"Show loaded from {path}")
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    _scene_fade_active = [False]
    _scene_fade_stop    = [False]

    def _set_scene_buttons_state(state):
        """Enable or disable all scene buttons."""
        _scene_fade_active[0] = (state == tk.DISABLED)
        _scene_fade_stop[0]   = False
        for slot, b in go_buttons.items():
            if state == tk.DISABLED:
                b.config(fg="#555555")
                b._active_fg = "#555555"
                b._active_bg = b.cget("bg")
            else:
                b.config(fg=_slot_fg(slot))
                b._active_fg = _slot_fg(slot)
                b._active_bg = _darken(_slot_bg(slot))
        # Light up stop button during fade, dim when idle
        if state == tk.DISABLED:
            stop_fade_btn.config(bg="#663300", fg="#ff8800")
            stop_fade_btn._active_bg = "#884400"
            stop_fade_btn._active_fg = "#ffaa00"
        else:
            stop_fade_btn.config(bg="#333333", fg="#555555")
            stop_fade_btn._active_bg = "#444444"
            stop_fade_btn._active_fg = "#555555"

    def _do_stop_fade():
        if not _scene_fade_active[0]: return
        _scene_fade_stop[0]   = True
        _scene_fade_active[0] = False
        # Re-enable buttons directly without resetting stop flag
        for slot, b in go_buttons.items():
            b.config(fg=_slot_fg(slot))
            b._active_fg = _slot_fg(slot)
            b._active_bg = _darken(_slot_bg(slot))
        stop_fade_btn.config(bg="#333333", fg="#555555")
        stop_fade_btn._active_bg = "#444444"
        stop_fade_btn._active_fg = "#555555"

    def _do_go(slot):
        if _scene_fade_active[0]: return
        _select_slot(slot)
        if slot in scenes:
            fade_var.set(str(scenes[slot].get("fade", 0.0)))
        _scene_fade_stop[0] = False
        _set_scene_buttons_state(tk.DISABLED)
        def _on_done():
            if not _scene_fade_stop[0]:  # only re-enable if not already stopped
                _set_scene_buttons_state(tk.NORMAL)
        recall_scene(slot, all_widgets, root, on_complete=_on_done, stop_flag=_scene_fade_stop)

    def _do_clear_solos():
        for fw in all_widgets:
            if isinstance(fw, DigitalFixture):
                fw.fixture_solo.reset()
                for i in fw._solos: fw._solos[i] = False
                for sb in fw._solo_btns.values(): sb.reset()
            elif isinstance(fw, CustomFixture):
                fw.fixture_solo.reset()
                for sb in fw._ch_solos.values(): sb.reset()
            else:
                fw.solo_btn.reset()

    def _do_zoom(delta):
        new_zoom = round(zoom_level[0] + delta, 2)
        if not (ZOOM_MIN <= new_zoom <= ZOOM_MAX): return
        zoom_level[0] = new_zoom
        zoom_label.config(text=f"{int(new_zoom * 100)}%")
        rebuild_fixtures(new_zoom)

    # ── Footer ──
    # Row 1+2: scene buttons full width (15 per row, 30 total)
    # Row 3: controls strip

    scene_grid = tk.Frame(scene_bar, bg="#111111")
    scene_grid.pack(fill=tk.X, padx=6, pady=(4, 2))
    for _c in range(15):
        scene_grid.columnconfigure(_c, weight=1, uniform="scene")

    ctrl_strip = tk.Frame(scene_bar, bg="#111111")
    ctrl_strip.pack(fill=tk.X, padx=6, pady=(2, 4))

    # Controls strip — left side
    rec_btn = btn(ctrl_strip, "⏺  REC", bg="#aa3300", fg="#ffffff",
                  font=("Helvetica", 11, "bold"), width=7, pady=6, command=_do_rec)
    rec_btn.pack(side=tk.LEFT, padx=(0, 3))
    btn(ctrl_strip, "✕  CLR", bg="#444444", fg="#ff8888",
        font=("Helvetica", 11, "bold"), width=7, pady=6,
        command=_do_clr).pack(side=tk.LEFT, padx=(0, 10))
    tk.Label(ctrl_strip, text="Fade (s)", bg="#111111", fg="#aaaaaa",
             font=("Helvetica", 9)).pack(side=tk.LEFT, padx=(0, 3))
    tk.Entry(ctrl_strip, textvariable=fade_var, width=4,
             bg="#333333", fg="#ffcc00", insertbackground="#ffcc00",
             font=("Courier", 11), justify=tk.CENTER,
             relief=tk.FLAT, bd=4).pack(side=tk.LEFT, padx=(0, 10))
    stop_fade_btn = btn(ctrl_strip, "◼ STOP FADE", bg="#333333", fg="#555555",
        font=("Helvetica", 9, "bold"), pady=6,
        command=lambda: _do_stop_fade())
    stop_fade_btn.pack(side=tk.LEFT, padx=(0, 10))

    btn(ctrl_strip, "CLEAR SOLOS", bg="#332200", fg="#ddaa00",
        font=("Helvetica", 9, "bold"), pady=6,
        command=_do_clear_solos).pack(side=tk.LEFT, padx=(0, 6))
    btn(ctrl_strip, "💾 SAVE", bg="#223344", fg="#88bbff",
        font=("Helvetica", 9, "bold"), pady=6,
        command=_do_save_show).pack(side=tk.LEFT, padx=(0, 3))
    btn(ctrl_strip, "📂 LOAD", bg="#223344", fg="#88bbff",
        font=("Helvetica", 9, "bold"), pady=6,
        command=_do_load_show).pack(side=tk.LEFT, padx=(0, 10))

    # Zoom — left side continuing
    btn(ctrl_strip, "−", bg="#333333", fg="#ffffff",
        font=("Helvetica", 12, "bold"), width=2, pady=3,
        command=lambda: _do_zoom(-ZOOM_STEP)).pack(side=tk.LEFT)
    zoom_label = tk.Label(ctrl_strip, text="100%", bg="#111111", fg="#aaaaaa",
                          font=("Helvetica", 9), width=5)
    zoom_label.pack(side=tk.LEFT, padx=2)
    btn(ctrl_strip, "+", bg="#333333", fg="#ffffff",
        font=("Helvetica", 12, "bold"), width=2, pady=3,
        command=lambda: _do_zoom(+ZOOM_STEP)).pack(side=tk.LEFT)

    # Grand Master — right side
    gm_frame = tk.Frame(ctrl_strip, bg="#111111")
    gm_frame.pack(side=tk.RIGHT, padx=(6, 0))
    tk.Label(gm_frame, text="GRAND MASTER", bg="#111111", fg="#ffcc00",
             font=("Helvetica", 8, "bold")).pack(side=tk.LEFT, padx=(0, 4))
    gm_fader = tk.Scale(gm_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                        length=160, width=24, variable=gm_var,
                        showvalue=True, bg="#3c3c3c", fg="#ffcc00",
                        troughcolor="#555555", highlightthickness=0,
                        command=lambda _v: apply_grand_master(all_widgets))
    gm_fader.set(100); gm_fader.pack(side=tk.LEFT)

    root.bind("<Escape>", lambda e: (_cancel_paste(), _clear_group()))

    # Scene buttons — 30 slots, 15 per row
    SCENE_COLS = 15
    NUM_SCENES = 30
    _drag_state = {"src": None, "orig_bg": None, "orig_fg": None}

    def _slot_pos(slot):
        layout = globals().get("_scene_layout", "sequential")
        if layout == "paired":
            row = 0 if slot % 2 == 1 else 1
            col = ((slot - 1) // 2)
        else:
            row = 0 if slot <= SCENE_COLS else 1
            col = (slot - 1) % SCENE_COLS
        return (row, col)

    def _slot_at_grid(row, col):
        """Return slot number for a given grid row/col, or None."""
        for s in range(1, NUM_SCENES + 1):
            r, c = _slot_pos(s)
            if r == row and c == col:
                return s
        return None

    def _drag_start(e, slot):
        _drag_state["src"] = slot
        b = go_buttons[slot]
        _drag_state["orig_bg"] = _slot_bg(slot)
        _drag_state["orig_fg"] = _slot_fg(slot)
        b.configure(bg="#664400", fg="#ffffff",
                    highlightbackground="#ffaa00", highlightthickness=2)

    def _drag_motion(e, slot):
        # Find which button is under the pointer
        wx = e.widget.winfo_rootx() + e.x
        wy = e.widget.winfo_rooty() + e.y
        for s, b in go_buttons.items():
            if s == _drag_state["src"]: continue
            bx, by = b.winfo_rootx(), b.winfo_rooty()
            bw, bh = b.winfo_width(), b.winfo_height()
            if bx <= wx <= bx + bw and by <= wy <= by + bh:
                # Highlight target
                for s2, b2 in go_buttons.items():
                    if s2 != _drag_state["src"]:
                        b2.configure(highlightthickness=0)
                b.configure(highlightbackground="#ffffff", highlightthickness=2)
                return
        # No target — clear highlights
        for s2, b2 in go_buttons.items():
            if s2 != _drag_state["src"]:
                b2.configure(highlightthickness=0)

    def _drag_end(e, slot):
        src = _drag_state["src"]
        if src is None: return

        # Find drop target
        wx = e.widget.winfo_rootx() + e.x
        wy = e.widget.winfo_rooty() + e.y
        tgt = None
        for s, b in go_buttons.items():
            if s == src: continue
            bx, by = b.winfo_rootx(), b.winfo_rooty()
            bw, bh = b.winfo_width(), b.winfo_height()
            if bx <= wx <= bx + bw and by <= wy <= by + bh:
                tgt = s; break

        # Restore src button appearance
        go_buttons[src].configure(
            bg=_drag_state["orig_bg"], fg=_drag_state["orig_fg"],
            highlightthickness=0)
        # Clear all highlights
        for b in go_buttons.values():
            b.configure(highlightthickness=0)

        _drag_state["src"] = None

        if tgt is None or tgt == src: return

        # Swap scene data and names between src and tgt
        src_scene = scenes.pop(src, None)
        tgt_scene = scenes.pop(tgt, None)
        src_name   = scene_names.pop(src, None)
        tgt_name   = scene_names.pop(tgt, None)
        src_colour = scene_colours.pop(src, None)
        tgt_colour = scene_colours.pop(tgt, None)
        # src_scene moves to tgt slot, carrying src_name
        if src_scene:
            scenes[tgt] = src_scene
            if src_name: scenes[tgt]["name"] = src_name
            else:        scenes[tgt].pop("name", None)
        # tgt_scene moves to src slot, carrying tgt_name
        if tgt_scene:
            scenes[src] = tgt_scene
            if tgt_name: scenes[src]["name"] = tgt_name
            else:        scenes[src].pop("name", None)
        # Update scene_names and colours to match
        if src_name:   scene_names[tgt]   = src_name
        if tgt_name:   scene_names[src]   = tgt_name
        if src_colour: scene_colours[tgt] = src_colour
        if tgt_colour: scene_colours[src] = tgt_colour

        save_scenes_to_disk()
        _refresh_buttons()

    for slot in range(1, NUM_SCENES + 1):
        grid_row, grid_col = _slot_pos(slot)
        label = scene_names.get(slot, f"Scene {slot}")
        b = MacButton(scene_grid, text=label,
                      bg=_slot_bg(slot), fg=_slot_fg(slot),
                      activebackground=_darken(_slot_bg(slot)),
                      activeforeground=_slot_fg(slot),
                      font=("Helvetica", 9, "bold"), pady=6, padx=2,
                      height=2, justify=tk.CENTER,
                      command=lambda s=slot: _do_go(s))
        b.bind("<Double-Button-1>", lambda e, s=slot: _rename_slot(s))
        b.bind("<Button-2>",               lambda e: "break")
        b.bind("<Button-3>",               lambda e: "break")
        b.bind("<Double-Button-3>",        lambda e, s=slot: _rename_slot(s))

        b.bind("<Configure>",       lambda e, btn=b: btn.config(wraplength=e.width - 4))
        b.bind("<Control-Button-1>",        lambda e, s=slot: _drag_start(e, s))
        b.bind("<Control-B1-Motion>",       lambda e, s=slot: _drag_motion(e, s))
        b.bind("<Control-ButtonRelease-1>", lambda e, s=slot: _drag_end(e, s))
        b.grid(row=grid_row, column=grid_col, sticky="ew", padx=2, pady=2)
        go_buttons[slot] = b

    # ── OSC callbacks ──
    def _osc_recall(slot):
        _do_go(slot)
    def _osc_go():
        _do_go(selected_slot.get())
    def _osc_set_gm(val):
        gm_var.set(int(val))
        apply_grand_master(all_widgets)
    def _osc_set_fader(name, val):
        for fw in all_widgets:
            if isinstance(fw, CustomFixture) and fw.name == name:
                if fw._master_idx is not None:
                    lo, hi = channel_range(fw.channel_defs[fw._master_idx])
                    raw = int(lo + (hi - lo) * val / 100)
                    fw.set_master_value(raw)
                break
    def _osc_select(slot):
        _select_slot(slot)

    def _osc_find_slot_by_name(name: str):
        """Find scene slot by name, case-insensitive."""
        nl = name.lower().strip()
        for slot, scene in scenes.items():
            sname = scene.get("name", f"Scene {slot}")
            if sname.lower().strip() == nl:
                return slot
        return None

    def _osc_recall_by_name(name: str):
        slot = _osc_find_slot_by_name(name)
        if slot:
            _do_go(slot)
        else:
            print(f"OSC: scene '{name}' not found")

    def _osc_select_by_name(name: str):
        slot = _osc_find_slot_by_name(name)
        if slot:
            _select_slot(slot)
        else:
            print(f"OSC: scene '{name}' not found")

    _osc_callbacks["recall_scene"]    = _osc_recall
    _osc_callbacks["scene_go"]        = _osc_go
    _osc_callbacks["set_gm"]          = _osc_set_gm
    _osc_callbacks["set_fader"]       = _osc_set_fader
    _osc_callbacks["select_scene"]    = _osc_select
    _osc_callbacks["recall_by_name"]  = _osc_recall_by_name
    _osc_callbacks["select_by_name"]  = _osc_select_by_name

    start_osc_listener(root)

    # ── DMX loop ──
    def dmx_loop():
        if not dry_run: send_dmx()
        root.after(_dmx_interval_ms, dmx_loop)
    root.after(500, dmx_loop)
    def _on_close():
        if not dry_run:
            send_defaults(patch)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    try:
        root.mainloop()
    finally:
        import platform as _platform
        if _platform.system() == "Darwin":
            try:
                if _caffeinate: _caffeinate.terminate()
            except Exception: pass
        elif _platform.system() == "Windows":
            import ctypes
            # Reset to normal (ES_CONTINUOUS only)
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    global dry_run, scenes_path
    _prefs = load_prefs()

    # Prevent the OS from sleeping while desk.py is running
    import platform as _platform, subprocess as _sp
    _caffeinate = None
    if _platform.system() == "Darwin":
        _caffeinate = _sp.Popen(["caffeinate", "-i", "-d", "-u"])
    elif _platform.system() == "Windows":
        import ctypes
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
    parser = argparse.ArgumentParser(description="DMX Desk Emulator")
    parser.add_argument("--patch",   default=str(APP_DIR / "patch.json"))
    parser.add_argument("--ip",      default="127.0.0.1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run
    patch_path = Path(args.patch)
    if not patch_path.exists():
        print(f"Patch file '{patch_path}' not found."); return

    FIXTURES_DIR.mkdir(exist_ok=True)

    with open(patch_path) as f:
        patch = json.load(f)
    print(f"Loaded {len(patch)} entries from {patch_path}")

    _all_names = [f["name"] for f in patch if f.get("type","").lower() not in ("divider", "clock") and "name" in f]

    # Apply relevant prefs before scenes loading
    global _reload_last_show, _current_show_file
    if "reload_last_show" in _prefs:
        _reload_last_show = bool(_prefs["reload_last_show"])

    last = _prefs.get("last_show_file")
    if _reload_last_show and last and Path(last).exists():
        scenes_path        = last
        _current_show_file = last
        print(f"Auto-loading last show: {Path(last).name}")
    else:
        scenes_path = str(patch_path).replace(".json", "_scenes.json")

    load_scenes_from_disk(all_widget_names=_all_names)

    if not dry_run:
        start_artnet(args.ip)
    else:
        print("Dry run mode — no Art-Net output.")

    build_ui(patch, patch_path)

if __name__ == "__main__":
    main()
