#!/usr/bin/env python3
"""
Build a water-temperature banner SVG for a GitHub profile README.

Pulls the last 7 days of 6-minute water temperature from NOAA CO-OPS and
renders assets/water-banner.svg. No third-party dependencies.

There is no CO-OPS gauge at Manchester itself, so STATIONS below lists the
nearest gauges in central Puget Sound. The first one returning data wins.

Usage:
    python scripts/update_banner.py
    python scripts/update_banner.py --demo    # synthetic data, no network
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

# Nearest CO-OPS gauges to Manchester, WA (47.551 N, 122.542 W), in order.
STATIONS = [
    ("9447130", "Seattle, WA"),
    ("9446484", "Tacoma, WA"),
    ("9444900", "Port Townsend, WA"),
]

SITE_LABEL = os.environ.get("SITE_LABEL", "Manchester, Puget Sound")
HOURS = int(os.environ.get("HOURS", "168"))
OUT_SVG = os.environ.get("OUT_SVG", "assets/water-banner.svg")

W, H = 1200, 280
PLOT = {"x0": 452, "x1": 1148, "y0": 74, "y1": 214}


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

def fetch(station_id):
    params = {
        "product": "water_temperature",
        "station": station_id,
        "range": str(HOURS),
        "units": "metric",
        "time_zone": "lst_ldt",
        "format": "json",
        "application": "github-profile-banner",
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "profile-banner/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)

    if "error" in payload:
        raise RuntimeError(payload["error"].get("message", "unknown API error"))

    series = []
    for row in payload.get("data", []):
        try:
            value = float(row["v"])
        except (KeyError, TypeError, ValueError):
            continue  # CO-OPS returns empty strings for flagged samples
        stamp = datetime.strptime(row["t"], "%Y-%m-%d %H:%M")
        series.append((stamp, value))

    if len(series) < 12:
        raise RuntimeError(f"only {len(series)} usable samples")
    return series


def demo_series():
    import math
    import random

    now = datetime.now().replace(second=0, microsecond=0)
    out = []
    for i in range(HOURS * 10, 0, -1):
        t = now - timedelta(minutes=6 * i)
        hours_ago = i / 10
        tidal = 0.55 * math.sin(2 * math.pi * hours_ago / 12.42)
        daily = 0.35 * math.sin(2 * math.pi * hours_ago / 24)
        drift = 0.9 * (1 - hours_ago / (HOURS * 1.4))
        out.append((t, 12.1 + tidal + daily + drift + random.gauss(0, 0.05)))
    return out


def thin(series, target=340):
    """Downsample for a readable path without dropping the extremes."""
    if len(series) <= target:
        return series
    step = len(series) / target
    keep = {int(i * step) for i in range(target)}
    keep.add(min(range(len(series)), key=lambda i: series[i][1]))
    keep.add(max(range(len(series)), key=lambda i: series[i][1]))
    keep.add(len(series) - 1)
    return [series[i] for i in sorted(keep)]


# --------------------------------------------------------------------------
# svg
# --------------------------------------------------------------------------

def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_svg(series, station_id, station_name):
    pts = thin(series)
    values = [v for _, v in pts]
    stamps = [t for t, _ in pts]

    latest_t, latest_v = series[-1]
    lo, hi = min(values), max(values)
    mean = sum(values) / len(values)
    span = max(hi - lo, 0.6)
    pad = span * 0.18
    y_lo, y_hi = lo - pad, hi + pad

    t_start, t_end = stamps[0], stamps[-1]
    total_seconds = max((t_end - t_start).total_seconds(), 1)

    def px(t):
        frac = (t - t_start).total_seconds() / total_seconds
        return PLOT["x0"] + frac * (PLOT["x1"] - PLOT["x0"])

    def py(v):
        frac = (v - y_lo) / (y_hi - y_lo)
        return PLOT["y1"] - frac * (PLOT["y1"] - PLOT["y0"])

    line = " ".join(
        f"{'M' if i == 0 else 'L'}{px(t):.1f},{py(v):.1f}"
        for i, (t, v) in enumerate(pts)
    )
    area = (
        f"{line} L{px(stamps[-1]):.1f},{PLOT['y1']} "
        f"L{px(stamps[0]):.1f},{PLOT['y1']} Z"
    )

    # Midnight ticks across the window.
    ticks = []
    day = (t_start + timedelta(days=1)).replace(hour=0, minute=0)
    while day < t_end:
        ticks.append(
            f'<line x1="{px(day):.1f}" y1="{PLOT["y0"] - 8}" '
            f'x2="{px(day):.1f}" y2="{PLOT["y1"]}" class="tick"/>'
            f'<text x="{px(day):.1f}" y="{PLOT["y1"] + 20}" '
            f'class="axis mid">{day.strftime("%b %-d")}</text>'
        )
        day += timedelta(days=1)

    mean_y = py(mean)
    fahrenheit = latest_v * 9 / 5 + 32
    delta = latest_v - mean
    trend = f"{delta:+.1f} vs 7-day mean" if abs(delta) >= 0.05 else "at the 7-day mean"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"
     width="{W}" height="{H}" role="img"
     aria-label="Water temperature near {esc(SITE_LABEL)}: {latest_v:.1f} degrees Celsius">
  <style>
    .bg     {{ fill: #F2F6F7; }}
    .rule   {{ stroke: #C2D3D8; stroke-width: 1; }}
    .tick   {{ stroke: #C2D3D8; stroke-width: 1; stroke-dasharray: 2 5; }}
    .eyebrow{{ fill: #4A6A75; font: 600 13px ui-monospace, SFMono-Regular, Menlo, monospace;
              letter-spacing: 2.4px; }}
    .big    {{ fill: #0B2B3C; font: 700 92px ui-monospace, SFMono-Regular, Menlo, monospace;
              letter-spacing: -3px; }}
    .unit   {{ fill: #1C6E8C; font: 600 30px ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .sub    {{ fill: #4A6A75; font: 400 15px ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .axis   {{ fill: #6B8792; font: 400 12px ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .mid    {{ text-anchor: middle; }}
    .foot   {{ fill: #7A929B; font: 400 12px ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .trace  {{ stroke: #1C6E8C; stroke-width: 2.4; fill: none;
              stroke-linejoin: round; stroke-linecap: round; }}
    .fill   {{ fill: url(#water); }}
    .meanln {{ stroke: #C4622D; stroke-width: 1.2; stroke-dasharray: 6 4; }}
    .meanlb {{ fill: #C4622D; font: 600 11px ui-monospace, SFMono-Regular, Menlo, monospace;
              letter-spacing: 1px; }}
    .dot    {{ fill: #C4622D; }}
    .halo   {{ fill: #C4622D; opacity: 0.18; }}
    @media (prefers-color-scheme: dark) {{
      .bg      {{ fill: #0C1B22; }}
      .rule,
      .tick    {{ stroke: #24404B; }}
      .eyebrow,
      .sub     {{ fill: #7FA3AF; }}
      .big     {{ fill: #EAF4F7; }}
      .unit    {{ fill: #63C0D8; }}
      .axis    {{ fill: #6E909C; }}
      .foot    {{ fill: #5C7C88; }}
      .trace   {{ stroke: #63C0D8; }}
      .meanln,
      .dot     {{ stroke: #E8935C; fill: #E8935C; }}
      .meanlb  {{ fill: #E8935C; }}
      .halo    {{ fill: #E8935C; }}
    }}
  </style>

  <defs>
    <linearGradient id="water" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#1C6E8C" stop-opacity="0.30"/>
      <stop offset="100%" stop-color="#1C6E8C" stop-opacity="0.02"/>
    </linearGradient>
  </defs>

  <rect class="bg" width="{W}" height="{H}" rx="10"/>

  <!-- reading -->
  <text class="eyebrow" x="48" y="62">SURFACE WATER TEMPERATURE</text>
  <text class="big" x="44" y="152">{latest_v:.1f}</text>
  <text class="unit" x="{44 + 58 * len(f'{latest_v:.1f}')}" y="152">&#176;C</text>
  <text class="sub" x="48" y="182">{fahrenheit:.1f} &#176;F &#183; {esc(trend)}</text>
  <text class="sub" x="48" y="208">{esc(SITE_LABEL)}</text>
  <text class="axis" x="48" y="230">read {latest_t.strftime('%Y-%m-%d %H:%M')} local</text>

  <line class="rule" x1="404" y1="46" x2="404" y2="234"/>

  <!-- 7-day trace -->
  {''.join(ticks)}
  <path class="fill" d="{area}"/>
  <path class="trace" d="{line}"/>
  <line class="meanln" x1="{PLOT['x0']}" y1="{mean_y:.1f}" x2="{PLOT['x1']}" y2="{mean_y:.1f}"/>
  <rect class="bg" x="{PLOT['x0'] + 1}" y="{mean_y - 20:.1f}" width="142" height="17" rx="2"/>
  <text class="meanlb" x="{PLOT['x0'] + 5}" y="{mean_y - 7:.1f}">7-DAY MEAN {mean:.1f} &#176;C</text>
  <circle class="halo" cx="{px(stamps[-1]):.1f}" cy="{py(latest_v):.1f}" r="8"/>
  <circle class="dot" cx="{px(stamps[-1]):.1f}" cy="{py(latest_v):.1f}" r="3.4"/>

  <text class="axis" x="{PLOT['x1']}" y="{PLOT['y0'] - 12}" text-anchor="end">range {lo:.1f}&#8211;{hi:.1f} &#176;C</text>
  <text class="axis" x="{PLOT['x0']}" y="{PLOT['y0'] - 12}">last 7 days</text>

  <line class="rule" x1="48" y1="252" x2="1152" y2="252"/>
  <text class="foot" x="48" y="270">NOAA CO-OPS {esc(station_id)} {esc(station_name)} &#183; 6-min observations &#183; rebuilt daily by GitHub Actions</text>
</svg>
"""


# --------------------------------------------------------------------------
# readme block
# --------------------------------------------------------------------------

def update_readme(latest_v, latest_t, station_name, path="README.md"):
    start, end = "<!-- WATER:START -->", "<!-- WATER:END -->"
    if not os.path.exists(path):
        return
    text = open(path, encoding="utf-8").read()
    if start not in text or end not in text:
        return
    block = (
        f"{start}\n"
        f"![Water temperature near {SITE_LABEL}]({OUT_SVG})\n\n"
        f"`{latest_v:.1f} °C` in the water off {SITE_LABEL}, "
        f"{latest_t.strftime('%b %-d %H:%M')} local, via NOAA CO-OPS {station_name}.\n"
        f"{end}"
    )
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    open(path, "w", encoding="utf-8").write(head + block + tail)


def main():
    demo = "--demo" in sys.argv

    if demo:
        series, sid, sname = demo_series(), "DEMO", "synthetic data"
    else:
        series = sid = sname = None
        for candidate_id, candidate_name in STATIONS:
            try:
                series = fetch(candidate_id)
                sid, sname = candidate_id, candidate_name
                break
            except (urllib.error.URLError, RuntimeError, ValueError, TimeoutError) as exc:
                print(f"station {candidate_id}: {exc}", file=sys.stderr)
        if series is None:
            # Leave the last good banner in place rather than publishing a gap.
            print("no station returned data, banner left unchanged", file=sys.stderr)
            return 0

    os.makedirs(os.path.dirname(OUT_SVG) or ".", exist_ok=True)
    with open(OUT_SVG, "w", encoding="utf-8") as fh:
        fh.write(build_svg(series, sid, sname))

    latest_t, latest_v = series[-1]
    update_readme(latest_v, latest_t, sname)
    print(f"{OUT_SVG}: {latest_v:.1f} C at {latest_t} ({sid} {sname})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
