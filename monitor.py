#!/usr/bin/env python3
"""
Art-Net DMX Monitor with HTP Merge
Listens for Art-Net packets from multiple sources, merges using HTP
(Highest Takes Precedence), and displays a live readout.

No extra dependencies — uses only Python built-in socket library.

Usage:
    python3 monitor.py                        # listen on all interfaces, universe 0
    python3 monitor.py --universe 1           # watch a different universe
    python3 monitor.py --port 6454            # specify port (default 6454)
    python3 monitor.py --threshold 5          # only show channels above this value
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

def bar(value, width=20):
    filled = int(value / 255 * width)
    return "█" * filled + "░" * (width - filled)

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def render(dmx_merged, source_dmx, channel_names, threshold,
           universe, port, packet_count, last_seen, htp_merge):
    clear_screen()
    age        = f"{time.time() - last_seen:.1f}s ago" if last_seen else "waiting..."
    merge_mode = "HTP merge" if htp_merge else "last-wins"

    print(f"  Art-Net DMX Monitor  |  Universe {universe}  Port {port}  "
          f"Mode: {merge_mode}  Pkts: {packet_count}  Last: {age}")
    print(f"  {'─' * 70}")

    if htp_merge and len(source_dmx) > 1:
        print(f"  Sources:")
        for ip in sorted(source_dmx):
            dmx, ts = source_dmx[ip]
            active  = sum(1 for v in dmx if v > 0)
            age_s   = f"{time.time() - ts:.1f}s"
            print(f"    {ip:<20}  {active:>3} active ch  ({age_s} ago)")
        print()

    active = [(i + 1, v) for i, v in enumerate(dmx_merged) if v >= threshold]

    if not active:
        print("  (no active channels)")
    else:
        for ch, val in active:
            name     = channel_names.get(ch, "")
            name_col = f"{name:<26}" if name else " " * 26
            pct      = int(val / 255 * 100)
            winner   = ""
            if htp_merge and len(source_dmx) > 1:
                winners = [ip for ip, (dmx, _) in source_dmx.items()
                           if ch - 1 < len(dmx) and dmx[ch - 1] == val and val > 0]
                if len(winners) == 1:   winner = f"  ← {winners[0]}"
                elif len(winners) > 1:  winner = "  ← tied"
            print(f"  ch {ch:>3}  {name_col}  {bar(val)}  {val:>3} ({pct:>3}%){winner}")

    print()
    print("  Ctrl+C to quit.")

def parse_args():
    p = argparse.ArgumentParser(description="Art-Net DMX Monitor with HTP Merge")
    p.add_argument("--universe",  type=int, default=0)
    p.add_argument("--port",      type=int, default=6454)
    p.add_argument("--threshold", type=int, default=0)
    p.add_argument("--patch",     default="patch.json")
    p.add_argument("--no-merge",  action="store_true",
                   help="Disable HTP merge — last packet wins")
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

    source_dmx   = {}   # {ip: ([0]*512, timestamp)}
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

    print(f"Listening on port {args.port}, universe {args.universe}, "
          f"mode={'HTP merge' if htp_merge else 'last-wins'}")
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

            # Expire stale sources
            now   = time.time()
            stale = [ip for ip, (_, ts) in source_dmx.items()
                     if now - ts > SOURCE_TIMEOUT]
            if stale:
                for ip in stale:
                    del source_dmx[ip]
                if htp_merge:
                    _remerge()

            render(dmx_merged, source_dmx, channel_names,
                   args.threshold, args.universe, args.port,
                   packet_count, last_seen, htp_merge)

    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
