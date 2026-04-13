#!/usr/bin/env python3
"""
Art-Net DMX Monitor with HTP Merge
Listens for Art-Net packets from multiple sources, merges using HTP
(Highest Takes Precedence), and displays a live readout.

No extra dependencies — uses only Python built-in socket library.

Usage:
    python3 monitor.py                        # list view, universe 0
    python3 monitor.py --grid                 # compact 32x16 grid of all 512 channels
    python3 monitor.py --universe 1           # watch a different universe
    python3 monitor.py --port 6454            # specify port (default 6454)
    python3 monitor.py --threshold 5          # only show channels at or above this value
    python3 monitor.py --patch patch.json     # show fixture names alongside channels
    python3 monitor.py --no-merge             # last packet wins (no HTP merge)
"""

import socket
import json
import argparse
import os
import time
from pathlib import Path

ARTNET_HEADER     = b"Art-Net\x00"
ARTNET_OPCODE_DMX = 0x5000

# ── ANSI colour codes ──────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

def ansi_fg(r, g, b):    return f"\033[38;2;{r};{g};{b}m"
def ansi_bg(r, g, b):    return f"\033[48;2;{r};{g};{b}m"

GOLD   = ansi_fg(255, 204, 0)
BLUE   = ansi_fg(100, 160, 255)
GREY   = ansi_fg(100, 100, 100)
GREEN  = ansi_fg(80,  220, 80)
AMBER  = ansi_fg(220, 160, 0)
RED    = ansi_fg(220, 80,  80)

# Direction tracking — previous frame values
_prev_dmx = [0] * 512

def dir_colour(ch_idx, v):
    """ANSI colour based on direction of change: green=rising, red=falling,
    white=steady non-zero, grey=zero."""
    if v == 0:
        return GREY
    prev = _prev_dmx[ch_idx]
    if v > prev:   return GREEN
    if v < prev:   return RED
    return BLUE   # steady non-zero

def update_prev(dmx_merged):
    """Call once per render to update previous frame."""
    for i in range(512):
        _prev_dmx[i] = dmx_merged[i]


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
    p = Path(patch_path)
    if not p.exists():
        return {}
    fixtures_dir = p.parent / "fixtures"
    with open(p) as f:
        patch = json.load(f)
    lookup = {}
    for fix in patch:
        ftype = fix.get("type", "dimmer").lower()
        if ftype in ("submaster", "divider", "clock"):
            continue
        name    = fix.get("name", "?")
        address = fix.get("address")
        if not address:
            continue
        try:
            defn = load_fixture_def(ftype, fixtures_dir)
            for i, ch in enumerate(defn.get("channels", [])):
                if not ch.get("show", True):
                    continue
                label  = ch.get("label", str(i + 1))
                dmx_ch = address + i
                if 1 <= dmx_ch <= 512:
                    lookup[dmx_ch] = name if ch.get("master") else f"{name} {label}"
        except Exception:
            lookup[address] = name
    return lookup


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


# ── Display ────────────────────────────────────────────────────────────────────

def clear_screen():
    # \033[H = cursor home, \033[J = clear from cursor to end
    if os.name == "nt":
        os.system("cls")
    else:
        print("\033[H\033[J", end="", flush=True)

def header_line(universe, port, merge_mode, packet_count, last_seen, source_dmx):
    age  = f"{time.time() - last_seen:.1f}s ago" if last_seen else "waiting..."
    srcs = f"  Sources: {len(source_dmx)}" if len(source_dmx) > 1 else ""
    return (f"{GOLD}{BOLD}  Art-Net DMX Monitor{RESET}  "
            f"Universe {universe}  Port {port}  "
            f"Mode: {merge_mode}  Pkts: {packet_count}  Last: {age}{srcs}")

def render_list(dmx_merged, source_dmx, channel_names, threshold,
                universe, port, packet_count, last_seen, htp_merge):
    clear_screen()
    merge_mode = "HTP merge" if htp_merge else "last-wins"
    print(header_line(universe, port, merge_mode, packet_count, last_seen, source_dmx))
    print(f"  {'─' * 70}")

    if htp_merge and len(source_dmx) > 1:
        print(f"  {GOLD}Sources:{RESET}")
        for ip in sorted(source_dmx):
            dmx, ts = source_dmx[ip]
            active  = sum(1 for v in dmx if v > 0)
            age_s   = f"{time.time() - ts:.1f}s"
            print(f"    {ip:<20}  {active:>3} active ch  ({age_s} ago)")
        print()

    active = [(i + 1, v) for i, v in enumerate(dmx_merged) if v >= threshold]
    if not active:
        print(f"  {GREY}(no active channels){RESET}")
    else:
        for ch, val in active:
            name     = channel_names.get(ch, "")
            name_col = f"{name:<26}" if name else " " * 26
            pct      = int(val / 255 * 100)
            bar_w    = 20
            filled   = int(val / 255 * bar_w)
            bar      = dir_colour(ch-1, val) + "█" * filled + GREY + "░" * (bar_w - filled) + RESET
            winner   = ""
            if htp_merge and len(source_dmx) > 1:
                winners = [ip for ip, (dmx, _) in source_dmx.items()
                           if ch - 1 < len(dmx) and dmx[ch - 1] == val and val > 0]
                if len(winners) == 1:  winner = f"  {GREY}← {winners[0]}{RESET}"
                elif len(winners) > 1: winner = f"  {GREY}← tied{RESET}"
            print(f"  ch {ch:>3}  {name_col}  {bar}  "
                  f"{dir_colour(ch-1, val)}{val:>3}{RESET} ({pct:>3}%){winner}")

    print(f"\n  {GREY}Ctrl+C to quit  |  all 512 channels: --grid{RESET}")
    update_prev(dmx_merged)

def render_grid(dmx_merged, source_dmx, channel_names, threshold,
                universe, port, packet_count, last_seen, htp_merge):
    """Compact 32-column grid showing all 512 DMX channels."""
    clear_screen()
    merge_mode = "HTP merge" if htp_merge else "last-wins"
    print(header_line(universe, port, merge_mode, packet_count, last_seen, source_dmx))

    COLS = 32
    # Column headers
    hdr = "     "
    for c in range(COLS):
        hdr += f"{c+1:>4} "
    print(f"\n{GREY}{hdr}{RESET}")
    print(f"  {'─' * (COLS * 5 + 4)}")

    for row in range(16):   # 16 rows × 32 cols = 512 channels
        base    = row * COLS
        row_lbl = f"{GREY}{base+1:>3}│{RESET} "
        cells   = ""
        has_active = False
        for col in range(COLS):
            ch  = base + col       # 0-indexed
            val = dmx_merged[ch]
            if val > 0:
                has_active = True
            cells += dir_colour(ch, val) + f"{val:>4} " + RESET
        print(f"  {row_lbl}{cells}")

    # Key
    print(f"\n  {GREY}{'─'*40}{RESET}")
    print(f"  {GREY}0 = zero{RESET}   {GREEN}green = rising{RESET}   {RED}red = falling{RESET}   {BLUE}blue = steady{RESET}")

    # Active channel summary with names
    named = [(i+1, dmx_merged[i]) for i in range(512)
             if dmx_merged[i] >= threshold and (i+1) in channel_names]
    if named:
        print(f"\n  {GOLD}Named active channels:{RESET}")
        for ch, val in named:
            print(f"    ch {ch:>3}  {channel_names[ch]:<28}  "
                  f"{dir_colour(ch-1, val)}{val:>3}{RESET}  ({int(val/255*100):>3}%)")

    print(f"\n  {GREY}Ctrl+C to quit  |  list view: remove --grid{RESET}")
    update_prev(dmx_merged)


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Art-Net DMX Monitor with HTP Merge")
    p.add_argument("--universe",  type=int, default=0)
    p.add_argument("--port",      type=int, default=6454)
    p.add_argument("--threshold", type=int, default=0)
    p.add_argument("--patch",     default="patch.json")
    p.add_argument("--no-merge",  action="store_true",
                   help="Disable HTP merge — last packet wins")
    p.add_argument("--grid",      action="store_true",
                   help="Show compact 32x16 grid of all 512 channels")
    return p.parse_args()

def main():
    args          = parse_args()
    htp_merge     = not args.no_merge
    channel_names = load_patch(args.patch)
    SOURCE_TIMEOUT = 10.0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.5)

    source_dmx   = {}
    dmx_merged   = [0] * 512
    packet_count = 0
    last_seen    = None

    def _remerge():
        if source_dmx:
            for ch in range(512):
                dmx_merged[ch] = max(dmx[ch] for dmx, _ in source_dmx.values())
        else:
            for ch in range(512):
                dmx_merged[ch] = 0

    render_fn = render_grid if args.grid else render_list

    print(f"Listening on port {args.port}, universe {args.universe}, "
          f"mode={'HTP merge' if htp_merge else 'last-wins'}, "
          f"view={'grid' if args.grid else 'list'}")
    print(f"Patch: {len(channel_names)} channels named.")
    print()

    try:
        while True:
            try:
                data, (src_ip, _) = sock.recvfrom(1024)
                parsed = parse_artnet(data, args.universe)
                if parsed is not None:
                    src = (list(parsed) + [0] * 512)[:512]
                    source_dmx[src_ip] = (src, time.time())
                    if htp_merge:
                        _remerge()
                    else:
                        dmx_merged[:] = src
                    packet_count += 1
                    last_seen = time.time()
            except socket.timeout:
                pass

            now   = time.time()
            stale = [ip for ip, (_, ts) in source_dmx.items()
                     if now - ts > SOURCE_TIMEOUT]
            if stale:
                for ip in stale:
                    del source_dmx[ip]
                if htp_merge:
                    _remerge()

            render_fn(dmx_merged, source_dmx, channel_names,
                      args.threshold, args.universe, args.port,
                      packet_count, last_seen, htp_merge)

    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
