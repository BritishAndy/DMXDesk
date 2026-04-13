#!/usr/bin/env python3
"""
Art-Net DMX Monitor — GUI
A tkinter-based companion to DMX Desk Emulator.

Listens for Art-Net packets, performs HTP merge from multiple sources,
and displays DMX values in a channel grid and fixture view.

Usage:
    python3 monitor_gui.py
    python3 monitor_gui.py --port 6454 --universe 0
    python3 monitor_gui.py --patch patch.json
    python3 monitor_gui.py --no-merge
"""

import tkinter as tk
from tkinter import ttk
import socket
import json
import threading
import argparse
import time
from pathlib import Path

# ── Colours ───────────────────────────────────────────────────────────────────
BG          = "#1a1a1a"
BG2         = "#222222"
BG3         = "#2a2a2a"
FG          = "#cccccc"
GOLD        = "#ffcc00"
GREY_DIM    = "#444444"
GREY_TEXT   = "#666666"

# Direction colours
COL_ZERO    = "#2a2a2a"   # cell background for zero
COL_RISING  = "#1a5c1a"   # green
COL_FALLING = "#5c1a1a"   # red
COL_STEADY  = "#1a2a5c"   # blue
COL_RISING_TEXT  = "#44ff44"
COL_FALLING_TEXT = "#ff4444"
COL_STEADY_TEXT  = "#6699ff"
COL_ZERO_TEXT    = "#444444"

ARTNET_HEADER     = b"Art-Net\x00"
ARTNET_OPCODE_DMX = 0x5000

# ── Fixture def loading ────────────────────────────────────────────────────────

_BUILTIN_DEFS = {
    "dimmer": {"channels": [{"label": "Dimmer", "master": True}]},
    "rgb":    {"channels": [{"label": "R"}, {"label": "G"}, {"label": "B"}]},
    "rgbw":   {"channels": [{"label": "R"}, {"label": "G"}, {"label": "B"}, {"label": "W"}]},
}

def load_fixture_def(ftype, fixtures_dir):
    path = fixtures_dir / f"{ftype}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return _BUILTIN_DEFS.get(ftype, _BUILTIN_DEFS["dimmer"])

def load_patch(patch_path):
    """Returns (channel_names dict, fixture_list)."""
    p = Path(patch_path)
    if not p.exists():
        return {}, []
    fixtures_dir = p.parent / "fixtures"
    with open(p) as f:
        patch = json.load(f)

    channel_names = {}
    fixtures = []

    for fix in patch:
        ftype = fix.get("type", "dimmer").lower()
        if ftype in ("submaster", "divider", "clock"):
            continue
        name    = fix.get("name", "?")
        address = fix.get("address")
        colour  = fix.get("colour", "#2b2b2b")
        if not address:
            continue
        try:
            defn     = load_fixture_def(ftype, fixtures_dir)
            channels = []
            for i, ch in enumerate(defn.get("channels", [])):
                label  = ch.get("label", str(i + 1))
                dmx_ch = address + i
                if 1 <= dmx_ch <= 512:
                    display = name if ch.get("master") else f"{name} {label}"
                    channel_names[dmx_ch] = display
                    channels.append({"ch": dmx_ch, "label": label,
                                     "master": ch.get("master", False)})
            fixtures.append({"name": name, "address": address,
                              "colour": colour, "channels": channels})
        except Exception:
            channel_names[address] = name
            fixtures.append({"name": name, "address": address,
                              "colour": colour,
                              "channels": [{"ch": address, "label": "M",
                                            "master": True}]})
    return channel_names, fixtures


# ── Art-Net parsing ────────────────────────────────────────────────────────────

def parse_artnet(data, target_universe):
    if len(data) < 18:
        return None
    if not data.startswith(ARTNET_HEADER):
        return None
    if (data[8] | (data[9] << 8)) != ARTNET_OPCODE_DMX:
        return None
    if (data[14] | (data[15] << 8)) != target_universe:
        return None
    length = (data[16] << 8) | data[17]
    return data[18:18 + length]


# ── Main Application ───────────────────────────────────────────────────────────

class MonitorApp:
    def __init__(self, root, args):
        self.root       = root
        self.args       = args
        self.htp_merge  = not args.no_merge

        self.dmx_merged = [0] * 512
        self.dmx_prev   = [0] * 512
        self.dmx_steady    = [0] * 512   # frames unchanged
        self.dmx_direction = [0] * 512   # 1=rising, -1=falling, 0=zero
        self.STEADY_THRESHOLD = 15         # frames before showing blue (~0.5s)
        self.source_dmx = {}   # {ip: ([0]*512, timestamp)}
        self.pkt_count  = 0
        self.last_seen  = None
        SOURCE_TIMEOUT  = 10.0
        self._source_timeout = SOURCE_TIMEOUT

        self.channel_names, self.fixtures = load_patch(args.patch)

        root.title("Art-Net DMX Monitor")
        root.configure(bg=BG)
        root.geometry("1100x700")

        self._build_ui()
        self._start_network()
        self._schedule_refresh()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=BG2, pady=4)
        hdr.pack(fill=tk.X, padx=0, pady=0)

        tk.Label(hdr, text="Art-Net DMX Monitor", bg=BG2, fg=GOLD,
                 font=("Helvetica", 13, "bold")).pack(side=tk.LEFT, padx=12)

        self._status_var = tk.StringVar(value="Waiting for packets…")
        tk.Label(hdr, textvariable=self._status_var, bg=BG2, fg=FG,
                 font=("Helvetica", 9)).pack(side=tk.LEFT, padx=12)

        # Colour key
        key_frame = tk.Frame(hdr, bg=BG2)
        key_frame.pack(side=tk.RIGHT, padx=12)
        for text, fg, bg in [
            ("● Rising",  COL_RISING_TEXT,  BG2),
            ("● Falling", COL_FALLING_TEXT, BG2),
            ("● Steady",  COL_STEADY_TEXT,  BG2),
            ("● Zero",    COL_ZERO_TEXT,    BG2),
        ]:
            tk.Label(key_frame, text=text, bg=bg, fg=fg,
                     font=("Helvetica", 9)).pack(side=tk.LEFT, padx=6)

        # Sources strip
        self._sources_var = tk.StringVar(value="")
        tk.Label(hdr, textvariable=self._sources_var, bg=BG2, fg=GREY_TEXT,
                 font=("Helvetica", 8)).pack(side=tk.RIGHT, padx=8)

        # Tabs
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook",        background=BG,  borderwidth=0)
        style.configure("TNotebook.Tab",    background=BG3, foreground=FG,
                        padding=[10, 4])
        style.map("TNotebook.Tab",
                  background=[("selected", BG2)],
                  foreground=[("selected", GOLD)])

        grid_tab    = tk.Frame(nb, bg=BG)
        fixture_tab = tk.Frame(nb, bg=BG)
        nb.add(grid_tab,    text="  Channel Grid  ")
        nb.add(fixture_tab, text="  Fixture View  ")

        self._build_grid_tab(grid_tab)
        self._build_fixture_tab(fixture_tab)

    def _build_grid_tab(self, parent):
        """32 columns × 16 rows = 512 channels."""
        COLS = 32
        ROWS = 16

        canvas_frame = tk.Frame(parent, bg=BG)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Column headers
        hdr = tk.Frame(canvas_frame, bg=BG)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="   ", bg=BG, fg=GREY_TEXT,
                 font=("Courier", 7), width=4).grid(row=0, column=0)
        for c in range(COLS):
            tk.Label(hdr, text=str(c + 1), bg=BG, fg=GREY_TEXT,
                     font=("Courier", 7), width=4,
                     anchor="center").grid(row=0, column=c + 1, padx=1)

        # Grid cells
        self._grid_cells = {}  # {ch_idx: (label_widget,)}
        grid_frame = tk.Frame(canvas_frame, bg=BG)
        grid_frame.pack(fill=tk.BOTH, expand=True)

        for row in range(ROWS):
            base = row * COLS
            tk.Label(grid_frame, text=f"{base+1:>3}", bg=BG, fg=GREY_TEXT,
                     font=("Courier", 7), width=4).grid(
                     row=row, column=0, padx=(2,4), pady=1)
            for col in range(COLS):
                ch = base + col  # 0-indexed
                lbl = tk.Label(grid_frame, text=" 0 ", bg=COL_ZERO,
                               fg=COL_ZERO_TEXT,
                               font=("Courier", 7), width=4,
                               relief=tk.FLAT, anchor="center")
                lbl.grid(row=row, column=col + 1, padx=1, pady=1)
                lbl.bind("<Enter>", lambda e, c=ch: self._grid_tooltip(c))
                self._grid_cells[ch] = lbl

        # Tooltip label
        self._tooltip_var = tk.StringVar(value="Hover over a cell for channel info")
        tk.Label(canvas_frame, textvariable=self._tooltip_var,
                 bg=BG2, fg=FG, font=("Helvetica", 9),
                 anchor="w").pack(fill=tk.X, pady=(4, 0))

    def _grid_tooltip(self, ch_idx):
        ch   = ch_idx + 1
        val  = self.dmx_merged[ch_idx]
        name = self.channel_names.get(ch, "")
        pct  = int(val / 255 * 100)
        text = f"ch {ch}"
        if name:
            text += f"  —  {name}"
        text += f"  =  {val}  ({pct}%)"
        self._tooltip_var.set(text)

    def _build_fixture_tab(self, parent):
        """One row per fixture, columns per channel."""
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(
                       scrollregion=canvas.bbox("all")))

        self._fix_cells = {}  # {ch_idx: label}

        if not self.fixtures:
            tk.Label(inner, text="No patch file loaded — run with --patch patch.json",
                     bg=BG, fg=GREY_TEXT, font=("Helvetica", 10)).pack(pady=20)
            return

        # Header row
        hdr = tk.Frame(inner, bg=BG3)
        hdr.pack(fill=tk.X, pady=(0, 2))
        tk.Label(hdr, text="Fixture", bg=BG3, fg=GOLD,
                 font=("Helvetica", 9, "bold"),
                 width=22, anchor="w").pack(side=tk.LEFT, padx=(8, 4))
        tk.Label(hdr, text="Addr", bg=BG3, fg=GREY_TEXT,
                 font=("Helvetica", 8), width=5).pack(side=tk.LEFT)
        tk.Label(hdr, text="Channels", bg=BG3, fg=GREY_TEXT,
                 font=("Helvetica", 8)).pack(side=tk.LEFT, padx=8)

        for fix in self.fixtures:
            row = tk.Frame(inner, bg=BG2, pady=3)
            row.pack(fill=tk.X, pady=1, padx=2)

            # Fixture colour stripe
            try:
                stripe_bg = fix["colour"]
                # Darken the colour for the stripe
                r = int(int(stripe_bg[1:3], 16) * 0.4)
                g = int(int(stripe_bg[3:5], 16) * 0.4)
                b = int(int(stripe_bg[5:7], 16) * 0.4)
                stripe_col = f"#{r:02x}{g:02x}{b:02x}"
            except Exception:
                stripe_col = BG3

            tk.Frame(row, bg=stripe_col, width=4).pack(side=tk.LEFT)

            tk.Label(row, text=fix["name"], bg=BG2, fg=FG,
                     font=("Helvetica", 9, "bold"),
                     width=22, anchor="w").pack(side=tk.LEFT, padx=(6, 2))
            tk.Label(row, text=str(fix["address"]), bg=BG2, fg=GREY_TEXT,
                     font=("Courier", 8), width=5).pack(side=tk.LEFT)

            # Channel cells
            ch_frame = tk.Frame(row, bg=BG2)
            ch_frame.pack(side=tk.LEFT, padx=4)

            for ch_info in fix["channels"]:
                ch_idx = ch_info["ch"] - 1  # 0-indexed
                col_frame = tk.Frame(ch_frame, bg=BG2)
                col_frame.pack(side=tk.LEFT, padx=2)

                tk.Label(col_frame, text=ch_info["label"],
                         bg=BG2, fg=GREY_TEXT,
                         font=("Helvetica", 7)).pack()

                lbl = tk.Label(col_frame, text=" 0 ",
                               bg=COL_ZERO, fg=COL_ZERO_TEXT,
                               font=("Courier", 8), width=4, anchor="center")
                lbl.pack()
                self._fix_cells[ch_idx] = lbl

    # ── Network ───────────────────────────────────────────────────────────────

    def _start_network(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("0.0.0.0", self.args.port))
            self._sock.settimeout(0.5)
        except Exception as e:
            self._status_var.set(f"Socket error: {e}")
            return

        t = threading.Thread(target=self._listen_loop, daemon=True)
        t.start()

    def _listen_loop(self):
        while True:
            try:
                data, (src_ip, _) = self._sock.recvfrom(1024)
                parsed = parse_artnet(data, self.args.universe)
                if parsed is not None:
                    src = (list(parsed) + [0] * 512)[:512]
                    self.source_dmx[src_ip] = (src, time.time())
                    if self.htp_merge:
                        self._remerge()
                    else:
                        self.dmx_merged[:] = src
                    self.pkt_count += 1
                    self.last_seen = time.time()
            except socket.timeout:
                pass
            except Exception:
                break

            # Expire stale sources
            now   = time.time()
            stale = [ip for ip, (_, ts) in self.source_dmx.items()
                     if now - ts > self._source_timeout]
            if stale:
                for ip in stale:
                    del self.source_dmx[ip]
                if self.htp_merge:
                    self._remerge()

    def _remerge(self):
        if self.source_dmx:
            for ch in range(512):
                self.dmx_merged[ch] = max(
                    dmx[ch] for dmx, _ in self.source_dmx.values())
        else:
            for ch in range(512):
                self.dmx_merged[ch] = 0

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _schedule_refresh(self):
        self.root.after(100, self._refresh)  # 10fps is plenty

    def _refresh(self):
        now = self.dmx_merged
        prev = self.dmx_prev

        # Update status
        if self.last_seen:
            age = f"{time.time() - self.last_seen:.1f}s ago"
        else:
            age = "waiting…"

        mode = "HTP merge" if self.htp_merge else "last-wins"
        active = sum(1 for v in now if v > 0)
        self._status_var.set(
            f"Universe {self.args.universe}  Port {self.args.port}  "
            f"Mode: {mode}  Packets: {self.pkt_count}  "
            f"Last: {age}  Active: {active}")

        if len(self.source_dmx) > 1:
            src_text = "Sources: " + "  ".join(
                f"{ip} ({sum(1 for v in dmx if v>0)} ch)"
                for ip, (dmx, _) in sorted(self.source_dmx.items()))
            self._sources_var.set(src_text)
        else:
            self._sources_var.set("")

        # Determine cell colours
        for ch in range(512):
            v    = now[ch]
            p    = prev[ch]
            if v > p:
                self.dmx_direction[ch] = 1
                self.dmx_steady[ch]    = 0
            elif v < p:
                self.dmx_direction[ch] = -1
                self.dmx_steady[ch]    = 0
            else:
                self.dmx_steady[ch] = min(self.dmx_steady[ch] + 1, self.STEADY_THRESHOLD)

            if v == 0:
                bg, fg = COL_ZERO, COL_ZERO_TEXT
                self.dmx_direction[ch] = 0
            elif v > p:
                bg, fg = COL_RISING, COL_RISING_TEXT
            elif v < p:
                bg, fg = COL_FALLING, COL_FALLING_TEXT
            elif self.dmx_steady[ch] >= self.STEADY_THRESHOLD:
                bg, fg = COL_STEADY, COL_STEADY_TEXT
            else:
                # Unchanged this frame but not yet steady — hold last direction
                if self.dmx_direction[ch] == 1:
                    bg, fg = COL_RISING, COL_RISING_TEXT
                elif self.dmx_direction[ch] == -1:
                    bg, fg = COL_FALLING, COL_FALLING_TEXT
                else:
                    bg, fg = COL_STEADY, COL_STEADY_TEXT

            val_text = f"{v:>3}"

            # Update grid cell
            if ch in self._grid_cells:
                lbl = self._grid_cells[ch]
                lbl.config(bg=bg, fg=fg, text=val_text)

            # Update fixture cell
            if ch in self._fix_cells:
                lbl = self._fix_cells[ch]
                lbl.config(bg=bg, fg=fg, text=val_text)

        # Save previous
        self.dmx_prev = list(now)

        self._schedule_refresh()


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Art-Net DMX Monitor GUI")
    p.add_argument("--universe",  type=int, default=0)
    p.add_argument("--port",      type=int, default=6454)
    p.add_argument("--patch",     default="patch.json")
    p.add_argument("--no-merge",  action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    root = tk.Tk()
    app  = MonitorApp(root, args)
    try:
        root.mainloop()
    finally:
        try: app._sock.close()
        except Exception: pass

if __name__ == "__main__":
    main()
