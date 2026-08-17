#!/usr/bin/env python3
"""Generate the SVG illustrations for the interceptors story deck.

Every image is 1280x720 (the deck's slide size) and uses the demo web app's own
palette (see ../../web/static/style.css), so the slides and the live UI read as
one system.

    python3 presentation/images/build_images.py

Two sets are produced:

  * `00`-`13` plus `demo1`-`demo4`: the deck. This is the talk.
  * `x-*`: spares, kept for a longer version (one slide per interceptor, plus the
    audit and traceability problem panels). Not referenced by the deck.

Characters are caricatures, recognized by props rather than likeness: Bill's blond
spikes, Ted's dark hair and headband, Rufus's long coat and beard, the robot
doubles' plated faces, Napoleon's bicorne. Scenes are staged after the films: the
Circle K lot, the 2688 auditorium, Waterloo the water park.

Hand-editing the SVGs is fine, but they are overwritten on the next run, so change
this file instead.
"""

from __future__ import annotations

import pathlib

# ---------------------------------------------------------------------------
# Palette + type scale (mirrors web/static/style.css)
# ---------------------------------------------------------------------------

BG = "#0b1020"
PANEL = "#141b32"
PANEL2 = "#1b2444"
INK = "#e7ecff"
MUTED = "#8a95c0"
CYAN = "#6ce0ff"
PURPLE = "#b58bff"
OK = "#3ad29f"
BAD = "#ff6b8b"
WARN = "#ffcf6b"
LINE = "#263056"
MAGENTA = "#ff7ae0"

# Interceptor categories, color-coded the same way on every slide that names one.
# Hue carries the category; state (fired, refused, not used) is carried by fill and
# dashes instead, so the two never compete for the same signal.
C_CLIENT = MAGENTA    # client outbound: runs in your own process
C_WORKFLOW = WARN     # workflow inbound or outbound: runs in the workflow
C_ACTIVITY = CYAN     # activity inbound or outbound: runs per attempt
C_BOTH = PURPLE       # spans workflow and activity

SANS = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'SF Mono', Menlo, ui-monospace, monospace"

W, H = 1280, 720
ARROW_COLORS = {"cyan": CYAN, "purple": PURPLE, "ok": OK, "bad": BAD, "warn": WARN,
                "muted": MUTED, "ink": INK}


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(text: str, max_chars: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        if len(candidate) > max_chars and cur:
            lines.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def head() -> str:
    markers = "".join(
        f'<marker id="a-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        f'markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0 0 L10 5 L0 10 z" fill="{v}"/></marker>'
        for k, v in ARROW_COLORS.items()
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}" font-family="{SANS}">\n'
        f"<defs>{markers}"
        f'<radialGradient id="halo" cx="72%" cy="-6%" r="80%">'
        f'<stop offset="0" stop-color="#1a2450"/><stop offset="1" stop-color="{BG}"/>'
        f"</radialGradient>"
        f'<linearGradient id="glass" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{CYAN}" stop-opacity="0.14"/>'
        f'<stop offset="1" stop-color="{PURPLE}" stop-opacity="0.05"/></linearGradient>'
        f'<pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse">'
        f'<path d="M48 0 H0 V48" fill="none" stroke="{LINE}" stroke-width="1"/></pattern>'
        f'<linearGradient id="tlogo" x1="183" y1="192" x2="0" y2="0" '
        f'gradientUnits="userSpaceOnUse">'
        f'<stop stop-color="#444CE7"/><stop offset="1" stop-color="#B664FF"/></linearGradient>'
        f'<filter id="glow" x="-40%" y="-40%" width="180%" height="180%">'
        f'<feGaussianBlur stdDeviation="3.2" result="b"/>'
        f"<feMerge><feMergeNode in=\"b\"/><feMergeNode in=\"SourceGraphic\"/></feMerge>"
        f"</filter></defs>\n"
        f'<rect width="{W}" height="{H}" fill="url(#halo)"/>\n'
        f'<rect width="{W}" height="{H}" fill="url(#grid)" opacity="0.35"/>\n'
    )


def tail() -> str:
    return "</svg>\n"


def text(x, y, s, *, size=18, fill=INK, weight=400, anchor="start", mono=False,
         op=1.0, spacing=None, glow=False, preserve=False) -> str:
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    extra += ' filter="url(#glow)"' if glow else ""
    # SVG collapses leading whitespace unless asked not to, and code indentation needs it.
    extra += ' xml:space="preserve"' if preserve else ""
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
        f'text-anchor="{anchor}" font-family="{MONO if mono else SANS}" '
        f'opacity="{op}"{extra}>{esc(s)}</text>\n'
    )


def slide_title(title: str, subtitle: str = "", *, accent=CYAN) -> str:
    s = f'<rect x="72" y="60" width="5" height="{92 if subtitle else 46}" rx="2.5" fill="{accent}"/>\n'
    s += text(100, 100, title, size=42, weight=700)
    if subtitle:
        s += text(100, 140, subtitle, size=21, fill=MUTED)
    return s



def panel(x, y, w, h, *, title=None, accent=LINE, fill=PANEL, r=16, dash=None,
          title_color=None, sw=1.6, fill_op=1.0) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    s = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" '
         f'fill-opacity="{fill_op}" stroke="{accent}" stroke-width="{sw}"{d}/>\n')
    if title:
        s += text(x + 22, y + 34, title, size=17, weight=700,
                  fill=title_color or accent, spacing=1.2)
        s += (f'<line x1="{x + 22}" y1="{y + 50}" x2="{x + w - 22}" y2="{y + 50}" '
              f'stroke="{LINE}" stroke-width="1"/>\n')
    return s


def pill_w(s: str, size=16, mono=False, pad=16) -> float:
    return len(s) * size * (0.62 if mono else 0.56) + pad * 2


def pill(x, y, s, color=CYAN, *, size=16, mono=False, h=34, pad=16, fill_op=0.14,
         weight=600) -> str:
    w = pill_w(s, size, mono, pad)
    return (
        f'<rect x="{x}" y="{y}" width="{w:.0f}" height="{h}" rx="{h / 2}" fill="{color}" '
        f'fill-opacity="{fill_op}" stroke="{color}" stroke-width="1.4"/>\n'
        + text(x + w / 2, y + h / 2 + size * 0.36, s, size=size, fill=color,
               anchor="middle", mono=mono, weight=weight)
    )


def box(x, y, w, h, label, *, color=CYAN, sub=None, r=12, fill=PANEL2, mono=False,
        size=18, dash=None) -> str:
    s = panel(x, y, w, h, accent=color, fill=fill, r=r, dash=dash, fill_op=0.9)
    cy = y + h / 2 + (0 if sub else size * 0.36)
    if sub:
        s += text(x + w / 2, cy - 6, label, size=size, anchor="middle", weight=600, mono=mono)
        s += text(x + w / 2, cy + 18, sub, size=14, anchor="middle", fill=MUTED)
    else:
        s += text(x + w / 2, cy, label, size=size, anchor="middle", weight=600, mono=mono)
    return s


def arrow(x1, y1, x2, y2, *, color="cyan", dash=False, sw=2.4, label=None,
          label_at=0.5, label_dy=-12, label_size=15, label_fill=None, bend=0) -> str:
    c = ARROW_COLORS[color]
    d = ' stroke-dasharray="7 6"' if dash else ""
    if bend:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + bend
        path = f"M{x1} {y1} Q{mx} {my} {x2} {y2}"
    else:
        path = f"M{x1} {y1} L{x2} {y2}"
    s = (f'<path d="{path}" fill="none" stroke="{c}" stroke-width="{sw}"{d} '
         f'marker-end="url(#a-{color})"/>\n')
    if label:
        lx = x1 + (x2 - x1) * label_at
        ly = y1 + (y2 - y1) * label_at + bend * 0.5 + label_dy
        s += text(lx, ly, label, size=label_size, fill=label_fill or c, anchor="middle")
    return s



def note(x, y, w, lines, *, color=WARN, size=17, lh=24, pad=18, title=None):
    body = [lines] if isinstance(lines, str) else lines
    h = pad * 2 + lh * len(body) + (24 if title else 0)
    s = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{color}" '
         f'fill-opacity="0.10" stroke="{color}" stroke-opacity="0.5" stroke-width="1.4"/>\n'
         f'<rect x="{x}" y="{y}" width="5" height="{h}" rx="2.5" fill="{color}"/>\n')
    ty = y + pad + size
    if title:
        s += text(x + pad, ty, title, size=14, fill=color, weight=700, spacing=1.2)
        ty += 24
    for ln in body:
        s += text(x + pad, ty, ln, size=size, fill=INK, op=0.92)
        ty += lh
    return s, h


def note_only(x, y, w, lines, **kw) -> str:
    return note(x, y, w, lines, **kw)[0]


def elbow(points, *, color="cyan", sw=2.4, dash=False) -> str:
    """A right-angled arrow through the given points, arrowhead on the last one."""
    c = ARROW_COLORS[color]
    d = "M" + " L".join(f"{x} {y}" for x, y in points)
    dashes = ' stroke-dasharray="7 6"' if dash else ""
    return (f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{sw}"{dashes} '
            f'stroke-linejoin="round" marker-end="url(#a-{color})"/>\n')


def legality(x, y, w, rows, *, title="WHAT'S REPLAY-SAFE HERE", lh=28):
    """The same four-question grid, shown identically at every seam.

    rows: (label, value, kind) with kind in ok | bad | note | muted.
    """
    h = 34 + lh * len(rows) + 12
    s = panel(x, y, w, h, accent=LINE, fill=PANEL2, r=10, fill_op=0.5)
    s += text(x + 16, y + 24, title, size=12, fill=MUTED, spacing=1.2, weight=700)
    ty = y + 52
    for label, value, kind in rows:
        color = {"ok": OK, "bad": BAD, "note": WARN, "muted": MUTED}[kind]
        s += text(x + 16, ty, label, size=15, fill=INK, op=0.85)
        s += text(x + w - 16, ty, value, size=15, fill=color, weight=700, anchor="end",
                  mono=True)
        ty += lh
    return s, h


OUTSIDE_SANDBOX = [("wall clock", "yes", "ok"), ("randomness", "yes", "ok"),
                   ("network I/O", "yes", "ok"), ("re-runs on replay", "no", "muted")]
INSIDE_SANDBOX = [("wall clock", "no", "bad"), ("randomness", "no", "bad"),
                  ("network I/O", "no", "bad"), ("re-runs on replay", "yes", "note")]


def mark(x, y, kind="ok", *, r=16) -> str:
    """A tick, cross or bang badge."""
    color = {"ok": OK, "bad": BAD, "warn": WARN}[kind]
    glyph = {
        "ok": f'<path d="M{x - 7} {y} l5.5 6 l9 -12" fill="none" stroke="{color}" '
              f'stroke-width="2.8" stroke-linecap="round"/>',
        "bad": f'<path d="M{x - 6} {y - 6} l12 12 M{x + 6} {y - 6} l-12 12" fill="none" '
               f'stroke="{color}" stroke-width="2.8" stroke-linecap="round"/>',
        "warn": f'<path d="M{x} {y - 7} v8" stroke="{color}" stroke-width="2.8" '
                f'stroke-linecap="round"/><circle cx="{x}" cy="{y + 6}" r="1.7" fill="{color}"/>',
    }[kind]
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}" fill-opacity="0.15" '
            f'stroke="{color}" stroke-width="1.8"/>{glyph}\n')



# Exact override points, read off temporalio 1.30.0 rather than paraphrased. "execute" or
# "signal" are not method names; these are. Each list is the handful you are most likely to
# override, plus the true total, so nobody reads four names as the whole surface.
_CLIENT_OUT = (["start_workflow", "signal_workflow", "query_workflow",
                "start_workflow_update"], 40)
_WF_IN = (["execute_workflow", "handle_signal", "handle_query",
           "handle_update_handler"], 6)
_WF_OUT = (["start_activity", "start_child_workflow", "signal_external_workflow",
            "continue_as_new"], 8)
_ACT_IN = (["init", "execute_activity"], 2)
_ACT_OUT = (["heartbeat", "info"], 2)

# What the sandbox rules are actually about, named as the calls people reach for.
INSIDE_CALLS = [("time.time()", "no", "bad"), ("random.random()", "no", "bad"),
                ("socket, HTTP", "no", "bad"), ("re-runs on replay", "yes", "note")]
OUTSIDE_CALLS = [("time.time()", "yes", "ok"), ("random.random()", "yes", "ok"),
                 ("socket, HTTP", "yes", "ok"), ("re-runs on replay", "no", "muted")]


def seam_methods(x, y, w, name, spec, *, color=CYAN) -> str:
    """A hook, a few of the methods you override on it, and how many there are in all."""
    methods, total = spec
    rows = methods + ([f"… {total} in all"] if total > len(methods)
                      else [f"{total} in all"])
    h = 42 + len(rows) * 15 + 8
    s = panel(x, y, w, h, accent=color, fill=PANEL2, r=10, fill_op=0.9)
    s += f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2" fill="{color}"/>\n'
    s += text(x + 18, y + 27, name, size=16, mono=True, weight=700, fill=color)
    for i, m in enumerate(rows):
        muted = m.startswith("…") or m.endswith("in all")
        s += text(x + 18, y + 50 + i * 15, m, size=11, mono=True,
                  fill=color if not muted else MUTED, op=0.75 if muted else 1.0)
    return s


def legality_calls(x, y, w, rows, *, lh=22) -> str:
    """The replay grid, with the rows named as the Python calls they are really about."""
    h = 30 + lh * len(rows) + 14
    s = panel(x, y, w, h, accent=LINE, fill=PANEL2, r=10, fill_op=0.5)
    s += text(x + 16, y + 20, "PYTHON CALL", size=10, fill=MUTED, spacing=1.2, weight=700)
    s += text(x + w - 16, y + 20, "OK HERE", size=10, fill=MUTED, spacing=1.2, weight=700,
              anchor="end")
    ty = y + 44
    for label, value, kind in rows:
        color = {"ok": OK, "bad": BAD, "note": WARN, "muted": MUTED}[kind]
        s += text(x + 16, ty, label, size=13, fill=INK, op=0.85, mono=True)
        s += text(x + w - 16, ty, value, size=13, fill=color, weight=700, anchor="end",
                  mono=True)
        ty += lh
    return s


def seam_chip(x, y, name, where, *, color=CYAN, w=250, h=64) -> str:
    s = panel(x, y, w, h, accent=color, fill=PANEL2, r=10, fill_op=0.9)
    s += f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2" fill="{color}"/>\n'
    s += text(x + 18, y + 27, name, size=16, mono=True, weight=700, fill=color)
    s += text(x + 18, y + 49, where, size=13, fill=MUTED)
    return s



# ---------------------------------------------------------------------------
# Characters: caricatures, recognized by props
# ---------------------------------------------------------------------------


def _label(x, y, label, sub, color, scale=1.0) -> str:
    """Caption under a figure. Offset follows the figure's scale so tall characters
    (Rufus's coat) never collide with their own label."""
    base = y + 26 * scale + 12
    s = ""
    if label:
        s += text(x, base, label, size=16, anchor="middle", weight=700, fill=color)
    if sub:
        s += text(x, base + 20, sub, size=13, anchor="middle", fill=MUTED)
    return s


def _torso(color, *, fill=PANEL2, sleeveless=False, straps=False) -> str:
    s = (f'<path d="M-24 0 L-24 -22 Q-24 -38 0 -38 Q24 -38 24 -22 L24 0 Z" fill="{fill}" '
         f'stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>')
    if sleeveless:  # armholes
        s += (f'<path d="M-16 -34 q-5 12 -3 22" fill="none" stroke="{color}" stroke-width="1.6"/>'
              f'<path d="M16 -34 q5 12 3 22" fill="none" stroke="{color}" stroke-width="1.6"/>')
    if straps:
        s += (f'<path d="M-11 -37 v22 M11 -37 v22" fill="none" stroke="{color}" '
              f'stroke-width="1.6"/>')
    return s


def _vest(color, v=-20) -> str:
    """A vest worn over the shirt. `v` is where the V bottoms out; deeper reads as a vest
    rather than a V-neck top, which is the whole point of drawing one."""
    return (f'<path d="M-19 0 L-19 -27 Q-19 -35 -10 -37 L0 {v} L10 -37 Q19 -35 19 -27 '
            f'L19 0 Z" fill="{PANEL}" fill-opacity="0.55" stroke="{color}" '
            f'stroke-width="1.8" stroke-linejoin="round"/>')


def _face(color, *, grin=True) -> str:
    s = f'<circle cx="-6" cy="-56" r="2.2" fill="{color}"/><circle cx="6" cy="-56" r="2.2" fill="{color}"/>'
    if grin:
        s += f'<path d="M-7 -47 q7 6 14 0" fill="none" stroke="{color}" stroke-width="1.8"/>'
    return s


def _robot_face(color) -> str:
    return (
        f'<rect x="-13" y="-64" width="26" height="20" rx="4" fill="#0d132a" stroke="{color}" '
        f'stroke-width="1.8"/>'
        f'<rect x="-9" y="-58" width="6" height="4" rx="1" fill="{color}"/>'
        f'<rect x="3" y="-58" width="6" height="4" rx="1" fill="{color}"/>'
        f'<path d="M-10 -44 h20" stroke="{color}" stroke-width="1.6"/>'
        f'<path d="M-8 -44 v4 M0 -44 v4 M8 -44 v4" stroke="{color}" stroke-width="1.4"/>'
        f'<circle cx="-16" cy="-54" r="2.4" fill="{color}"/>'
        f'<circle cx="16" cy="-54" r="2.4" fill="{color}"/>'
    )


# Bill's mop. The curls are drawn at full size and the group is then scaled about the
# HAIRLINE, not the head center: scaling about the center drags the fringe down over the
# eyes. Stroke widths are divided by _MOP_K so the outlines keep their weight afterwards.
_MOP_K = 0.6
_MOP_HAIRLINE_Y = -60
_MOP_CURLS = ((-17, -66, 8), (-8, -75, 9), (3, -77, 9), (13, -71, 8.5),
              (20, -60, 7.5), (-21, -57, 7))


def bill(x, y, *, scale=1.0, robot=False, label=None, sub=None) -> str:
    """Curly blond mop, vest over a sleeveless tee, horse head on the chest.

    The double keeps the blond hair rather than turning red, so it reads as a double of
    Bill instead of a separate red character. The chest glyph follows `hair`, so it stays
    blond on the double too: same shirt, same person.
    """
    color = BAD if robot else CYAN
    hair = WARN
    sw = f"{2 / _MOP_K:.2f}"
    g = f'<g transform="translate({x} {y}) scale({scale})">'
    g += f'<circle cx="0" cy="-54" r="17" fill="{PANEL2}" stroke="{color}" stroke-width="2.2"/>'
    g += (f'<g transform="translate(0 {_MOP_HAIRLINE_Y}) scale({_MOP_K}) '
          f'translate(0 {-_MOP_HAIRLINE_Y})">')
    g += (f'<path d="M-21 -56 q-5 -27 21 -27 q26 0 21 27 q-4 -7 -9 -4 q-5 -6 -11 -2 '
          f'q-7 -4 -12 3 q-5 -4 -10 3 z" fill="{hair}" fill-opacity="0.30" '
          f'stroke="{hair}" stroke-width="{sw}" stroke-linejoin="round"/>')
    for cx, cy, r in _MOP_CURLS:
        g += (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{hair}" fill-opacity="0.30" '
              f'stroke="{hair}" stroke-width="{sw}"/>')
    g += "</g>"
    g += _robot_face(color) if robot else _face(color)
    g += _torso(color, sleeveless=True)
    if robot:
        g += f'<path d="M-14 -22 v20 M14 -22 v20" stroke="{color}" stroke-width="1.4"/>'
    g += _vest(color, -20)
    # Wyld Stallyns. This is the chess-knight glyph, not a path: a hand-drawn horse head at
    # 20px reads as a cat, and four attempts confirmed it. Depends on a system font having
    # U+2658, which is fine when presenting from a Mac.
    g += f'<text x="0" y="-3" font-size="22" fill="{hair}" text-anchor="middle">&#9816;</text>'
    g += "</g>\n"
    return g + _label(x, y, label, sub, color, scale)


# Ted's hair. Solid rather than translucent: a see-through fill in a smooth symmetric
# shape reads as a veil, not hair. The edge stroke is load-bearing, because near-black on
# the near-black background has no silhouette without it.
_TED_HAIR = "#151a33"
_TED_HAIR_EDGE = "#3a4570"
# Top y -78, bottom y -37, height 41. The inner fringe curve sits at about y -62, which
# clears the eyes at cy -56; the shorter earlier version crossed them.
_TED_HAIR_PATH = ("M-23 -37 q-6 -41 23 -41 q29 0 23 41 q-5 -26 -12 -28 q-11 5 -22 0 "
                  "q-7 2 -12 28 z")


def ted(x, y, *, scale=1.0, robot=False, label=None, sub=None) -> str:
    """Long black hair, vest. No headband: the hair is the silhouette that identifies him.

    The double keeps this hair rather than turning red, so it reads as a double of Ted
    instead of a separate red character. Same rule in `bill`.
    """
    color = BAD if robot else PURPLE
    g = f'<g transform="translate({x} {y}) scale({scale})">'
    g += f'<circle cx="0" cy="-54" r="17" fill="{PANEL2}" stroke="{color}" stroke-width="2.2"/>'
    g += (f'<path d="{_TED_HAIR_PATH}" fill="{_TED_HAIR}" stroke="{_TED_HAIR}" '
          f'stroke-width="2" stroke-linejoin="round"/>')
    g += (f'<path d="{_TED_HAIR_PATH}" fill="none" stroke="{_TED_HAIR_EDGE}" '
          f'stroke-width="1.8" stroke-linejoin="round"/>')
    g += _robot_face(color) if robot else _face(color)
    g += _torso(color)
    if robot:
        g += f'<path d="M-14 -22 v20 M14 -22 v20" stroke="{color}" stroke-width="1.4"/>'
    g += _vest(color, -14)
    g += "</g>\n"
    return g + _label(x, y, label, sub, color, scale)


def rufus(x, y, *, scale=1.0, label=None, sub=None, guitar=True) -> str:
    """Long coat, beard, shades, guitar slung on his back."""
    color = CYAN
    g = f'<g transform="translate({x} {y}) scale({scale})">'
    if guitar:
        g += (f'<g transform="rotate(-24) translate(-30 -6)" opacity="0.85">'
              f'<ellipse cx="0" cy="0" rx="13" ry="16" fill="{PANEL}" stroke="{PURPLE}" '
              f'stroke-width="1.8"/>'
              f'<rect x="-2.5" y="-46" width="5" height="32" rx="2" fill="{PANEL}" '
              f'stroke="{PURPLE}" stroke-width="1.6"/>'
              f'<circle cx="0" cy="2" r="4" fill="none" stroke="{PURPLE}" stroke-width="1.4"/></g>')
    # Long coat.
    g += (f'<path d="M-27 20 L-23 -24 Q-23 -38 0 -38 Q23 -38 23 -24 L27 20 Z" fill="{PANEL2}" '
          f'stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>')
    g += f'<path d="M0 -34 V20" stroke="{color}" stroke-width="1.4" opacity="0.7"/>'
    g += (f'<path d="M-11 -36 l11 10 11 -10" fill="none" stroke="{color}" stroke-width="1.8"/>')
    g += f'<circle cx="0" cy="-54" r="17" fill="{PANEL2}" stroke="{color}" stroke-width="2.2"/>'
    g += (f'<path d="M-17 -56 q0 -17 17 -17 q17 0 17 17 q-5 -9 -17 -9 q-12 0 -17 9 z" '
          f'fill="{LINE}" stroke="{color}" stroke-width="1.8"/>')
    # Shades + beard.
    g += (f'<rect x="-12" y="-60" width="24" height="8" rx="3" fill="#0d132a" stroke="{color}" '
          f'stroke-width="1.6"/>')
    g += (f'<path d="M-11 -47 q11 13 22 0 q-3 11 -11 11 q-8 0 -11 -11 z" fill="{LINE}" '
          f'stroke="{color}" stroke-width="1.6"/>')
    g += "</g>\n"
    return g + _label(x, y, label, sub, color, scale)


def councilor(x, y, *, scale=1.0, instrument="sax", color=PURPLE) -> str:
    """One of the Three Most Important People in the Universe, holding an instrument."""
    g = f'<g transform="translate({x} {y}) scale({scale})">'
    g += f'<circle cx="0" cy="-54" r="17" fill="{PANEL2}" stroke="{color}" stroke-width="2.2"/>'
    g += (f'<path d="M-18 -55 q1 -18 18 -18 q17 0 18 18 q-6 -10 -18 -10 q-12 0 -18 10 z" '
          f'fill="{color}" fill-opacity="0.3" stroke="{color}" stroke-width="1.8"/>')
    g += _face(color)
    g += _torso(color)
    if instrument == "sax":
        g += (f'<path d="M18 -30 q10 4 8 16 q-2 12 -12 14" fill="none" stroke="{WARN}" '
              f'stroke-width="2.6"/><circle cx="12" cy="2" r="6" fill="none" stroke="{WARN}" '
              f'stroke-width="2.4"/>')
    elif instrument == "guitar":
        g += (f'<ellipse cx="16" cy="-6" rx="11" ry="13" fill="none" stroke="{WARN}" '
              f'stroke-width="2.2"/><rect x="8" y="-42" width="4" height="26" rx="2" '
              f'fill="none" stroke="{WARN}" stroke-width="1.8"/>')
    else:  # keys
        g += (f'<rect x="-22" y="-16" width="44" height="12" rx="3" fill="#0d132a" '
              f'stroke={WARN!r} stroke-width="2"/>'
              f'<path d="M-14 -16 v12 M-6 -16 v12 M2 -16 v12 M10 -16 v12" stroke="{WARN}" '
              f'stroke-width="1.4"/>')
    g += "</g>\n"
    return g


def napoleon(x, y, *, scale=1.0, label=None, tube=True) -> str:
    """Bicorne hat, hand in coat, optional inner tube."""
    color = WARN
    g = f'<g transform="translate({x} {y}) scale({scale})">'
    if tube:
        g += (f'<ellipse cx="0" cy="-10" rx="40" ry="17" fill="none" stroke="{CYAN}" '
              f'stroke-width="7" stroke-opacity="0.45"/>')
    g += (f'<path d="M-20 -6 L-18 -26 Q-18 -38 0 -38 Q18 -38 18 -26 L20 -6 Z" fill="{PANEL2}" '
          f'stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>')
    g += f'<circle cx="0" cy="-54" r="16" fill="{PANEL2}" stroke="{color}" stroke-width="2.2"/>'
    g += _face(color, grin=False)
    # Bicorne.
    g += (f'<path d="M-24 -68 q24 -16 48 0 q-14 6 -24 6 q-10 0 -24 -6 z" fill="{LINE}" '
          f'stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
    g += f'<circle cx="0" cy="-70" r="3" fill="{color}"/>'
    # Hand in coat.
    g += (f'<path d="M-16 -24 q10 6 14 -2" fill="none" stroke="{color}" stroke-width="2"/>')
    g += "</g>\n"
    return g + _label(x, y, label, None, color, scale)


def booth(x, y, *, scale=1.0, color=CYAN, op=0.9, sign="PHONE") -> str:
    """The Circuits of History booth, reusing the shapes from web/static/phonebooth.svg.
    (x, y) is the top-left of a 240x460 box, scaled."""
    return (
        f'<g transform="translate({x} {y}) scale({scale})" opacity="{op}">'
        f'<g stroke="{color}" stroke-width="2.5" stroke-linejoin="round" fill="none">'
        f'<rect x="46" y="26" width="148" height="40" rx="6" fill="#0d1430"/>'
        f'<rect x="52" y="66" width="136" height="352" rx="10" fill="url(#glass)"/>'
        f'<rect x="64" y="78" width="112" height="300" rx="6" stroke-width="1.6"/>'
        f'<line x1="64" y1="150" x2="176" y2="150" stroke-width="1.4"/>'
        f'<line x1="64" y1="230" x2="176" y2="230" stroke-width="1.4"/>'
        f'<line x1="120" y1="78" x2="120" y2="378" stroke-width="1.4"/>'
        f'<rect x="44" y="418" width="152" height="18" rx="4" fill="#0d1430"/></g>'
        f'<text x="120" y="53" text-anchor="middle" font-family="{MONO}" font-size="17" '
        f'font-weight="700" letter-spacing="3" fill="{color}">{sign}</text>'
        f'<g stroke="{PURPLE}" stroke-width="2.5" fill="none" opacity="0.9">'
        f'<path d="M26 118 l14 -6 -6 16 14 -4"/><path d="M214 302 l-14 6 6 -16 -14 4"/>'
        f"</g></g>\n"
    )


_TEMPORAL_MARK = (
    "M123.34 68.6596C119.655 41.0484 110.327 18 96 18C81.6731 18 72.3454 41.0484 68.6596 "
    "68.6596C41.0484 72.3454 18 81.6731 18 96C18 110.327 41.0525 119.655 68.6596 123.34C72.3454 "
    "150.948 81.6731 174 96 174C110.327 174 119.655 150.948 123.34 123.34C150.952 119.655 174 "
    "110.327 174 96C174 81.6731 150.948 72.3454 123.34 68.6596ZM67.7583 115.298C41.3151 111.479 "
    "25.893 102.737 25.893 96C25.893 89.2629 41.3151 80.5212 67.7583 76.7021C67.1764 83.0674 "
    "66.8733 89.566 66.8733 96C66.8733 102.434 67.1764 108.937 67.7583 115.298ZM96 25.893C102.737 "
    "25.893 111.479 41.3151 115.298 67.7583C108.937 67.1764 102.434 66.8733 96 66.8733C89.566 "
    "66.8733 83.0633 67.1764 76.7021 67.7583C80.5212 41.3151 89.2629 25.893 96 25.893ZM124.242 "
    "115.298C122.94 115.488 117.602 116.114 116.252 116.248C116.118 117.602 115.488 122.936 "
    "115.302 124.238C111.483 150.681 102.741 166.103 96.0041 166.103C89.267 166.103 80.5253 "
    "150.681 76.7061 124.238C76.5202 122.936 75.8898 117.598 75.7564 116.248C75.1421 109.979 "
    "74.7703 103.246 74.7703 96C74.7703 88.7537 75.1421 82.0206 75.7564 75.7483C82.0247 75.134 "
    "88.7577 74.7622 96.0041 74.7622C103.25 74.7622 109.983 75.134 116.252 75.7483C117.606 "
    "75.8817 122.94 76.5121 124.242 76.698C150.685 80.5172 166.111 89.2629 166.111 95.996C166.111 "
    "102.729 150.685 111.479 124.242 115.298Z"
)


def temporal_logo(x, y, *, size=96) -> str:
    """The Temporal mark, from web/static/temporal.svg. (x, y) is the top-left."""
    k = size / 192
    return (f'<g transform="translate({x} {y}) scale({k:.4f})">'
            f'<rect width="192" height="192" rx="24" fill="url(#tlogo)"/>'
            f'<path d="{_TEMPORAL_MARK}" fill="#F2F2F2"/></g>\n')


def time_swirl(cx, cy, *, r=110, op=0.5) -> str:
    """The arrival vortex behind the booth."""
    s = f'<g opacity="{op}" fill="none" stroke="{PURPLE}" stroke-linecap="round">'
    for i, k in enumerate((1.0, 0.76, 0.54, 0.36)):
        s += (f'<ellipse cx="{cx}" cy="{cy}" rx="{r * k:.0f}" ry="{r * k * 0.42:.0f}" '
              f'stroke-width="{2.4 - i * 0.3:.1f}" stroke-dasharray="{34 - i * 6} {14 + i * 4}" '
              f'transform="rotate({-18 + i * 9} {cx} {cy})"/>')
    s += "</g>\n"
    return s


def circle_k(x, y, *, w=300, color=BAD) -> str:
    """The storefront the booth lands outside of."""
    hh = 128
    s = (f'<rect x="{x}" y="{y}" width="{w}" height="{hh}" rx="6" fill="{PANEL}" '
         f'stroke="{LINE}" stroke-width="1.6"/>\n')
    s += (f'<rect x="{x - 10}" y="{y - 16}" width="{w + 20}" height="22" rx="5" fill="{PANEL2}" '
          f'stroke="{LINE}" stroke-width="1.4"/>\n')
    s += (f'<rect x="{x + w / 2 - 74}" y="{y - 74}" width="148" height="48" rx="8" '
          f'fill="#0d1430" stroke="{color}" stroke-width="2"/>\n')
    s += text(x + w / 2, y - 42, "CIRCLE K", size=22, anchor="middle", weight=700,
              fill=color, mono=True, spacing=2, glow=True)
    for i in range(2):
        s += (f'<rect x="{x + 22 + i * 96}" y="{y + 26}" width="70" height="64" rx="4" '
              f'fill="{CYAN}" fill-opacity="0.10" stroke="{CYAN}" stroke-opacity="0.5" '
              f'stroke-width="1.4"/>\n')
    return s


def stage(x, y, w, *, color=PURPLE, truss_y=452) -> str:
    """The 2688 auditorium stage: riser, plus a lighting truss with short beams."""
    s = (f'<path d="M{x} {y} h{w} l-26 42 h{-(w - 52)} Z" fill="{PANEL}" stroke="{LINE}" '
         f'stroke-width="1.6"/>\n')
    s += (f'<rect x="{x}" y="{y - 20}" width="{w}" height="22" rx="6" fill="{PANEL2}" '
          f'stroke="{color}" stroke-width="1.4"/>\n')
    s += (f'<line x1="{x + 12}" y1="{truss_y}" x2="{x + w - 12}" y2="{truss_y}" '
          f'stroke="{LINE}" stroke-width="3"/>\n')
    for i in range(4):
        lx = x + 44 + i * (w - 88) / 3
        s += (f'<circle cx="{lx}" cy="{truss_y + 4}" r="5.5" fill="{WARN}" fill-opacity="0.55" '
              f'stroke="{WARN}" stroke-width="1.4"/>\n')
        s += (f'<line x1="{lx}" y1="{truss_y + 10}" x2="{lx}" y2="{truss_y + 24}" '
              f'stroke="{WARN}" stroke-width="1.4" opacity="0.4"/>\n')
    return s


# ---------------------------------------------------------------------------
# THE DECK
# ---------------------------------------------------------------------------


def img_00_title():
    s = head()
    s += time_swirl(980, 430, r=250, op=0.35)
    s += booth(880, 208, scale=0.62, op=0.95)

    s += f'<rect x="96" y="176" width="6" height="112" rx="3" fill="{CYAN}"/>\n'
    s += text(128, 250, "The Next Universe", size=72, weight=700)
    s += text(128, 302, "Six business requirements, six interceptors,", size=30, fill=CYAN)
    s += text(128, 342, "and a workflow nobody had to touch", size=30, fill=CYAN)

    s += temporal_logo(128, 400, size=64)
    s += text(210, 428, "Temporal Interceptors, told as a story", size=22, fill=INK)
    s += text(210, 456, "Wyld Stallyns Time Travel, San Dimas, 2691", size=17, fill=MUTED)

    s += rufus(180, 660, scale=1.15, label=None)
    s += bill(300, 660, scale=1.0)
    s += ted(392, 660, scale=1.0)
    s += text(470, 632, "Rufus, Bill and Ted", size=16, fill=MUTED)
    s += text(470, 656, "still saving universes, now with an audit trail",
              size=16, fill=MUTED)

    # Lower right, clear of the characters, which end around x=520.
    s += text(1184, 600, "PRESENTED BY", size=12, anchor="end", fill=MUTED, spacing=1.4,
              weight=700)
    s += text(1184, 638, "Tim Bruce", size=28, anchor="end", weight=700)
    s += text(1184, 666, "Solutions Architect", size=19, anchor="end", fill=CYAN)
    return s


def img_01_san_dimas():
    s = head()
    s += slide_title("San Dimas, 2691",
                     "Rufus built the Circuits of History on Temporal. Nothing has beaten it since.")
    s += temporal_logo(1096, 66, size=86)

    towers = [(60, 96, 210), (168, 62, 300), (242, 118, 168), (372, 74, 250), (458, 54, 196),
              (524, 132, 322), (668, 68, 214), (748, 92, 268), (852, 58, 176), (922, 110, 236),
              (1044, 72, 300), (1128, 96, 190)]
    base = 632
    for tx, tw, th in towers:
        s += (f'<rect x="{tx}" y="{base - th}" width="{tw}" height="{th}" rx="8" '
              f'fill="{PANEL}" stroke="{LINE}" stroke-width="1.4"/>\n')
        for row in range(int(th // 34)):
            for col in range(int(tw // 26)):
                wx = tx + 12 + col * 26
                wy = base - th + 22 + row * 34
                if wx < tx + tw - 10 and wy < base - 14:
                    op = 0.10 + 0.42 * (((row * 7 + col * 5 + tx) % 5) / 5)
                    s += (f'<rect x="{wx}" y="{wy}" width="11" height="9" rx="2" '
                          f'fill="{CYAN}" opacity="{op:.2f}"/>\n')
        if th > 240:
            s += (f'<line x1="{tx + tw / 2}" y1="{base - th}" x2="{tx + tw / 2}" '
                  f'y2="{base - th - 26}" stroke="{PURPLE}" stroke-width="1.6"/>\n'
                  f'<circle cx="{tx + tw / 2}" cy="{base - th - 30}" r="3.4" fill="{PURPLE}"/>\n')
    s += (f'<line x1="0" y1="{base}" x2="{W}" y2="{base}" stroke="{CYAN}" stroke-width="2" '
          f'opacity="0.55" filter="url(#glow)"/>\n')

    s += booth(300, 460, scale=0.375, op=0.95)
    s += booth(880, 494, scale=0.30, op=0.8)

    s += panel(660, 196, 540, 214, title="CIRCUITS OF HISTORY · OPS BOARD", accent=CYAN)
    rows = [("running on Temporal since", "2687", CYAN),
            ("time-travel workflows running now", "1,204,981", OK),
            ("travelers lost to a crash", "0", OK),
            ("hand-written retry loops", "0", OK)]
    ry = 284
    for k, v, c in rows:
        s += text(682, ry, k, size=16, fill=MUTED)
        s += text(1178, ry, v, size=16, mono=True, fill=c, anchor="end", weight=700)
        ry += 34

    s += rufus(600, 630, scale=1.15, label="Rufus", sub="he picked it in 2687")
    return s


def img_02_v1_no_auth():
    s = head()
    s += slide_title("2687: the software that saved a universe",
                     "Rufus built it on Temporal, a year before he went back for Bill and Ted.",
                     accent=PURPLE)

    # Circle K parking lot, at night.
    s += circle_k(88, 384, w=240)
    s += time_swirl(430, 512, r=134, op=0.45)
    s += (f'<line x1="72" y1="592" x2="580" y2="592" stroke="{LINE}" stroke-width="2"/>\n')
    for i in range(3):
        s += (f'<path d="M{356 + i * 104} 606 l-10 34" stroke="{LINE}" stroke-width="2"/>\n')
    s += booth(372, 383, scale=0.48, op=0.95)
    s += bill(136, 590, scale=1.2, label="Bill")
    s += ted(244, 590, scale=1.2, label="Ted")
    s += rufus(516, 592, scale=1.2, label="Rufus")

    s += note_only(604, 208, 604, [
        "Two teenagers walked in and traveled. So did",
        "Napoleon, Beethoven and Genghis Khan.",
        "Nothing checked who anyone was.",
    ], color=OK, title="HOW IT WAS USED IN 1988")

    # The workflow diagram lives inside its own box. It used to sit loose above a list that
    # restated it a step at a time; the pills say the same thing without the words.
    s += panel(604, 396, 604, 118, title="THE WORKFLOW", accent=CYAN)
    nodes = [("paradox_scan", CYAN), ("hold for Rufus", WARN), ("execute_jump", CYAN),
             ("arrival", OK)]
    # Padding and gaps are tighter than elsewhere so the four pills clear the panel's
    # 22px inset. At pad=12/gap=26 the row is 565 wide against 560 of interior.
    x = 626
    for i, (label, color) in enumerate(nodes):
        w = pill_w(label, 14, True, 10)
        s += pill(x, 452, label, color, mono=True, h=38, size=14, pad=10)
        if i < len(nodes) - 1:
            s += arrow(x + w + 2, 471, x + w + 18, 471, color="muted", sw=1.8)
        x += w + 20
    return s


def img_03_next_universe():
    s = head()
    s += slide_title("The next universe",
                     "Same timeline, different universe. This time the business has requirements.",
                     accent=PURPLE)

    # The briefing screen behind the stage.
    s += panel(112, 194, 372, 216, title="UNIVERSE 2 · TIMELINE MATCH", accent=CYAN)
    s += text(298, 286, "99.2%", size=44, anchor="middle", weight=700, fill=CYAN, mono=True)
    s += text(298, 314, "same history, same heinous risks", size=14, anchor="middle", fill=MUTED)
    for row, color in ((344, PURPLE), (374, CYAN)):
        s += (f'<line x1="146" y1="{row}" x2="450" y2="{row}" stroke="{color}" '
              f'stroke-width="2" opacity="0.55"/>\n')
        for i in range(9):
            s += (f'<circle cx="{152 + i * 37}" cy="{row}" r="3.4" fill="{color}"/>\n')
    s += text(146, 396, "ours", size=12, fill=PURPLE)
    s += text(450, 396, "theirs", size=12, fill=CYAN, anchor="end")

    # The 2688 auditorium.
    s += stage(112, 546, 372, truss_y=440)
    for px, sc, inst in ((184, 1.05, "sax"), (298, 1.2, "guitar"), (412, 1.05, "keys")):
        s += councilor(px, 544, scale=sc, instrument=inst)
    s += text(298, 620, "The Three Most Important People", size=16, anchor="middle",
              weight=700, fill=PURPLE)
    s += text(298, 642, "in the Universe", size=16, anchor="middle", weight=700, fill=PURPLE)

    # The business terms.
    s += panel(536, 176, 672, 492, title="WHAT THE BUSINESS NEEDS THIS TIME", accent=WARN)
    asks = [
        ("1", "Only real travelers ever ride the booth."),
        ("2", "Only cleared travelers can run Save the Future."),
        ("3", "We can prove who approved a trip, and when."),
        ("4", "We can see what the worker did on a trip."),
        ("5", "Auditors can see exactly who each action was for."),
    ]
    ay = 248
    for n, txt in asks:
        s += (f'<circle cx="574" cy="{ay + 12}" r="17" fill="{CYAN}" fill-opacity="0.14" '
              f'stroke="{CYAN}" stroke-width="1.6"/>\n')
        s += text(574, ay + 18, n, size=15, anchor="middle", fill=CYAN, weight=700, mono=True)
        s += text(606, ay + 18, txt, size=19)
        ay += 58
    s += (f'<line x1="558" y1="{ay + 4}" x2="1186" y2="{ay + 4}" stroke="{LINE}" '
          f'stroke-width="1"/>\n')
    s += (f'<circle cx="574" cy="{ay + 54}" r="17" fill="{WARN}" fill-opacity="0.16" '
          f'stroke="{WARN}" stroke-width="1.8"/>\n')
    s += text(574, ay + 60, "6", size=15, anchor="middle", fill=WARN, weight=700, mono=True)
    s += text(606, ay + 52, "True of every system we run.", size=20, weight=700, fill=WARN)
    s += text(606, ay + 78, "Not just the booth, Rufus.", size=18, fill=WARN, op=0.85)
    return s


def img_04_two_ways_to_lose():
    s = head()
    s += slide_title("Why the requirements exist",
                     "Two things that already happened. Both nearly cost everyone the future.",
                     accent=BAD)

    # Left: the robot doubles.
    s += panel(88, 176, 552, 340, accent=BAD, fill=PANEL, r=16, fill_op=0.55)
    s += text(112, 212, "THE ROBOT DOUBLES", size=15, weight=700, fill=BAD, spacing=1.4)
    s += booth(452, 200, scale=0.40, op=0.55)
    s += bill(186, 466, scale=1.1, robot=True, label="Evil Bill")
    s += ted(330, 466, scale=1.1, robot=True, label="Evil Ted")
    s += (f'<rect x="112" y="238" width="200" height="52" rx="8" fill="{PANEL2}" '
          f'stroke="{BAD}" stroke-width="1.6"/>\n')
    s += text(212, 262, "license: n/a", size=14, anchor="middle", mono=True, fill=BAD)
    s += text(212, 282, "signature: n/a", size=14, anchor="middle", mono=True, fill=BAD)
    s += arrow(320, 300, 448, 300, color="bad", sw=2)
    s += text(384, 286, "and in they went", size=13, fill=BAD, anchor="middle")

    # Right: the water park.
    s += panel(664, 176, 528, 340, accent=WARN, fill=PANEL, r=16, fill_op=0.55)
    s += text(688, 212, "WATERLOO, THE WATER PARK", size=15, weight=700, fill=WARN, spacing=1.4)
    s += (f'<path d="M700 250 C 820 282, 790 350, 900 372 C 1010 392, 1010 400, 1064 404" '
          f'fill="none" stroke="{CYAN}" stroke-width="15" stroke-opacity="0.16" '
          f'stroke-linecap="round"/>\n')
    s += (f'<path d="M700 250 C 820 282, 790 350, 900 372 C 1010 392, 1010 400, 1064 404" '
          f'fill="none" stroke="{CYAN}" stroke-width="2.2" stroke-dasharray="9 8"/>\n')
    s += (f'<ellipse cx="1082" cy="418" rx="92" ry="18" fill="{CYAN}" fill-opacity="0.12" '
          f'stroke="{CYAN}" stroke-width="1.4"/>\n')
    s += napoleon(1082, 400, scale=0.8)
    s += pill(1006, 240, "the Ziggy Piggy", PURPLE, size=14, h=32)
    s += text(1082, 448, "Napoleon, 1805", size=15, anchor="middle", weight=700, fill=WARN)
    s += text(688, 470, "mission: (none)", size=15, mono=True, fill=MUTED)
    s += text(688, 496, "licensed for this trip: nobody asked", size=15, mono=True, fill=BAD)

    s += note_only(88, 548, 1104, [
        "One universe nearly went to De Nomolos. A head of state was left on a water slide.",
        "Neither was a durability problem. Both were the business asking a question the software could not answer.",
    ], color=BAD, title="WHAT WAS ACTUALLY AT RISK")
    return s


def img_05_every_workflow():
    s = head()
    s += slide_title("Requirement 6: every system, not just the booth",
                     "The Circuits of History is one workflow out of forty-eight.", accent=WARN)

    names = ["ChronoTripWorkflow", "BoothMaintenance", "LicenseRenewal", "ParadoxCleanup",
             "TravelerBilling", "HistoryReportGrade", "BandBookingWorkflow", "DeNomolosWatch"]
    for i, n in enumerate(names):
        cx = 96 + (i % 4) * 274
        cy = 182 + (i // 4) * 92
        color = CYAN if i == 0 else MUTED
        s += panel(cx, cy, 250, 74, accent=color, fill=PANEL, r=12, fill_op=0.85)
        s += text(cx + 18, cy + 32, n, size=15, mono=True, weight=600,
                  fill=INK if i == 0 else MUTED)
        s += text(cx + 18, cy + 55, "must satisfy all five requirements", size=12, fill=MUTED)
    s += text(1184, 366, "…and forty more", size=15, fill=MUTED, anchor="end")

    s += panel(96, 388, 1088, 214, title="THE OBVIOUS ANSWER: PUT IT IN EVERY WORKFLOW",
               accent=BAD)
    s += text(640, 470, "5 requirements × 48 workflows × every activity inside them",
              size=25,
              anchor="middle", weight=700, fill=BAD, mono=True)
    cols = [("drifts inside a week", "missing on workflow forty-nine"),
            ("no review can enforce it", "still absent from the next system")]
    for c, pair in enumerate(cols):
        for r, ln in enumerate(pair):
            x = 150 + c * 520
            s += mark(x, 528 + r * 36, "bad", r=11)
            s += text(x + 24, 534 + r * 36, ln, size=17)

    s += text(640, 654, "So where does something go when every workflow needs it and no "
                        "workflow should own it?", size=21, fill=WARN, anchor="middle")
    s += rufus(1120, 366, scale=0.8)
    return s


def img_06_middleware():
    s = head()
    s += slide_title("Rufus needed to research the answer",
                     "on to Temporal's AI Developer Skill", accent=CYAN)
    s += rufus(1148, 168, scale=0.72)

    # Down the left (on the way in), across to the work, back up the right (on the way out).
    a_top, a_bot = 202, 270
    b_top, b_bot = 320, 388
    bot = 470
    lx, rx = 208, 860

    s += box(112, a_top, 192, 68, "Interceptor A", color=CYAN, size=18)
    s += box(112, b_top, 192, 68, "Interceptor B", color=PURPLE, size=18)
    s += box(764, b_top, 192, 68, "Interceptor B", color=PURPLE, size=18)
    s += box(764, a_top, 192, 68, "Interceptor A", color=CYAN, size=18)
    s += box(444, bot - 44, 224, 88, "Temporal's work", color=OK, size=18,
             sub="start_workflow · execute_activity")

    s += arrow(lx, a_bot + 2, lx, b_top - 6, color="cyan", sw=2.2)
    s += elbow([(lx, b_bot + 2), (lx, bot), (438, bot)], color="purple", sw=2.2)
    s += elbow([(674, bot), (rx, bot), (rx, b_bot + 6)], color="ok", sw=2.2)
    s += arrow(rx, b_top - 2, rx, a_bot + 6, color="purple", sw=2.2)

    # Below the return line, where neither vertical leg can run through the text.
    s += text(112, bot + 44, "on the way in", size=19, weight=700, fill=CYAN)
    s += text(112, bot + 68, "inspect, reject, stamp the header", size=14, fill=MUTED)
    s += text(764, bot + 44, "on the way out", size=19, weight=700, fill=OK)
    s += text(764, bot + 68, "log, measure, react", size=14, fill=MUTED)

    s += note_only(72, 556, 1136, [
        "Timers, queues and state management just work in Temporal. Auth, logging, tracing "
        "and audit should too.",
        "Interceptors are where you write them: one place, every workflow, and not one line "
        "of domain code touched.",
    ], color=OK, title="INTERCEPTORS ARE BUSINESS GLUE")
    return s


def img_07_five_seams():
    s = head()
    s += slide_title("Five places to hook in",
                     "Where the call happens decides what you are allowed to do about it.",
                     accent=PURPLE)

    s += panel(88, 176, 344, 512, title="YOUR APP PROCESS", accent=C_CLIENT)
    s += seam_methods(114, 264, 292, "client outbound", _CLIENT_OUT, color=C_CLIENT)
    s += legality_calls(114, 536, 292, OUTSIDE_CALLS)

    # Purple because this box holds both the workflow and the activity groups. Same hue as
    # C_BOTH, written as the plain color: the panel is a process, not a category.
    s += panel(456, 176, 736, 512, title="ONE WORKER PROCESS  (you run many)", accent=PURPLE)

    s += panel(480, 238, 332, 434, accent=C_WORKFLOW, fill=PANEL2, r=12, dash="7 6",
               fill_op=0.55)
    s += text(646, 258, "workflow interceptors", size=15, anchor="middle", weight=700,
              fill=C_WORKFLOW)
    s += seam_methods(500, 268, 292, "workflow inbound", _WF_IN, color=C_WORKFLOW)
    s += seam_methods(500, 400, 292, "workflow outbound", _WF_OUT, color=C_WORKFLOW)
    s += legality_calls(500, 536, 292, INSIDE_CALLS)

    s += panel(836, 238, 332, 434, accent=C_ACTIVITY, fill=PANEL2, r=12, fill_op=0.55)
    s += text(1002, 258, "activity interceptors", size=15, anchor="middle", weight=700,
              fill=C_ACTIVITY)
    s += seam_methods(856, 268, 292, "activity inbound", _ACT_IN, color=C_ACTIVITY)
    s += seam_methods(856, 400, 292, "activity outbound", _ACT_OUT, color=C_ACTIVITY)
    s += legality_calls(856, 536, 292, OUTSIDE_CALLS)

    return s


def img_08_how_to_build():
    """Slide 9: the three moves that make an interceptor.

    The code is `workflows/interceptors/workflow_audit.py` with the argument summary
    dropped, so what is on the slide is what is in the repo. The circled numbers on the
    right of the code tie each line back to the step card above it.
    """
    s = head()
    s += slide_title("How to build one",
                     "Three moves. The SDK does the chaining.", accent=CYAN)

    # One color for all three cards: these are steps, not interceptor categories, and
    # the category hues are spoken for on the slides either side of this one.
    steps = [
        ("1", "Extend the class that intercepts",
         "worker.Interceptor on a worker,",
         "client.Interceptor on a client."),
        ("2", "Override, then call through",
         "super() runs the rest of the chain.",
         "Skip it and the operation never happens."),
        ("3", "Hand yours back",
         "An instance, or for workflows the class,",
         "and the SDK builds it into the chain."),
    ]
    for i, (n, head_line, sub1, sub2) in enumerate(steps):
        x = 96 + i * 374
        s += panel(x, 170, 340, 104, accent=CYAN, fill=PANEL, r=12, fill_op=0.85)
        s += (f'<circle cx="{x + 30}" cy="204" r="15" fill="{CYAN}" fill-opacity="0.14" '
              f'stroke="{CYAN}" stroke-width="1.8"/>\n')
        s += text(x + 30, 210, n, size=14, anchor="middle", fill=CYAN, weight=700, mono=True)
        s += text(x + 56, 210, head_line, size=17, weight=700)
        s += text(x + 20, 240, sub1, size=13, fill=MUTED)
        s += text(x + 20, 260, sub2, size=13, fill=MUTED)

    s += panel(96, 292, 1088, 336, title="workflows/interceptors/workflow_audit.py",
               accent=LINE, fill=PANEL, r=14, fill_op=0.7, title_color=MUTED)

    # (line, step it demonstrates). None means no callout on that line.
    #
    # This sample is deliberately the audit interceptor rather than the logging one.
    # handle_signal returns nothing, so there is no value held across the call and no
    # `return result` line for the room to puzzle over; super() is simply the last thing
    # the method does. handle_query is kept for three rows because it shows the other
    # half: when there IS a result, you return the call through rather than a saved value.
    code = [
        ("class WorkflowAuditInterceptor(Interceptor):", "1"),
        ("    def workflow_interceptor_class(", None),
        ("        self, input: WorkflowInterceptorClassInput", None),
        ("    ) -> Optional[Type[WorkflowInboundInterceptor]]:", None),
        ("        return _AuditWorkflowInbound", "3"),
        ("", None),
        ("class _AuditWorkflowInbound(WorkflowInboundInterceptor):", "2"),
        ("    async def handle_signal(self, input: HandleSignalInput) -> None:", None),
        ('        workflow.logger.info("signal received: %s", input.signal)', None),
        ("        await super().handle_signal(input)", "2"),
        ("", None),
        ("    async def handle_query(self, input: HandleQueryInput) -> Any:", None),
        ('        workflow.logger.info("query received: %s", input.query)', None),
        ("        return await super().handle_query(input)", "2"),
    ]
    y = 362
    for line, step in code:
        if line:
            s += text(120, y, line, size=15, mono=True, preserve=True, op=0.95)
        if step:
            s += (f'<circle cx="1148" cy="{y - 5}" r="13" fill="{CYAN}" fill-opacity="0.14" '
                  f'stroke="{CYAN}" stroke-width="1.6"/>\n')
            s += text(1148, y, step, size=13, anchor="middle", fill=CYAN, weight=700,
                      mono=True)
        y += 20

    s += panel(96, 638, 1088, 58, accent=OK, fill=PANEL2, r=12, fill_op=0.7)
    s += text(120, 674, "Worker(client, ..., interceptors=[WorkflowAuditInterceptor()])",
              size=16, mono=True, weight=700, fill=OK)
    s += text(1160, 674, "wired once, every workflow on this worker", size=15, fill=MUTED,
              anchor="end")
    return s


def img_09_should_it_be():
    """Slide 10: guidance on when to consider an interceptor.

    Deliberately not a decision tree. The earlier version was one, and a tree forces every
    item to be a gate with a single path through, which these are not: they are independent
    signals. Several can be true at once and there is no order to them. What replaces the
    branches is a second column naming the things that are somebody else's job.
    """
    s = head()
    s += slide_title("When to reach for one",
                     "Cross-cutting behavior, across many calls, without touching business "
                     "logic.", accent=WARN)

    reasons = [
        ("OBSERVABILITY",
         "Correlation ids, request ids and trace spans, on every workflow and activity."),
        ("CONTEXT PROPAGATION",
         "Metadata on headers, client to workflow to activity. No signature changes."),
        ("AUTHENTICATION AND AUTHORIZATION",
         "Check the caller before a workflow, signal or update is ever handled."),
        ("VALIDATION, IN ONE PLACE",
         "Arguments and results, before your code sees them or a request goes out."),
        ("CONTEXT LIFECYCLE",
         "Set it and clear it around the boundary, in a finally, every time."),
    ]
    y = 192
    for label, detail in reasons:
        s += panel(88, y, 672, 78, accent=CYAN, fill=PANEL, r=12, fill_op=0.85)
        s += f'<rect x="88" y="{y}" width="4" height="78" rx="2" fill="{CYAN}"/>\n'
        s += text(112, y + 30, label, size=15, weight=700, fill=CYAN, spacing=1.1)
        s += text(112, y + 58, detail, size=15, fill=INK, op=0.88)
        y += 92

    s += panel(792, 192, 400, 268, title="USE SOMETHING ELSE INSTEAD", accent=MUTED)
    others = [
        ("Sharing logic between workflows", "a base class or a helper"),
        ("Changing the bytes in a payload", "a data converter or codec"),
        ("Needs to be a step in Event History", "an activity"),
    ]
    # Keep each answer tight to its own item: at even spacing the answer reads as though it
    # belongs to the item below it.
    oy = 246
    for what, instead in others:
        lines = wrap(what, 38)
        for j, ln in enumerate(lines):
            s += text(814, oy + j * 20, ln, size=14, fill=INK, op=0.85)
        s += text(824, oy + 20 * len(lines) + 2, f"\u2192  {instead}", size=14, fill=OK,
                  mono=True)
        oy += 20 * len(lines) + 40

    s += note_only(792, 484, 400, [
        "Workflow interceptors must be replay safe",
        "and avoid non-deterministic side effects. If",
        "you need a clock or the network, schedule an",
        "activity.",
    ], color=WARN, title="THE ONE CONSTRAINT", size=13, lh=18, pad=12)
    return s


def img_10_terms_to_interceptors():
    s = head()
    s += slide_title("Six business requirements, six interceptors",
                     "One file each. None of it in the workflow.", accent=OK)

    rows = [
        ("1", "Only real travelers ride", "client_auth", "client outbound", C_CLIENT),
        ("2", "Save the Future needs clearance", "client_auth", "client outbound", C_CLIENT),
        ("3", "Prove who approved it", "workflow_audit", "workflow inbound", C_WORKFLOW),
        ("4", "See what happened on a trip", "workflow_startup + activity_logging",
         "workflow in and out, activity in", C_BOTH),
        ("5", "Name the traveler acted for", "grant_propagation + token_exchange",
         "workflow in and out, activity in", C_BOTH),
        ("6", "Can be added to every workflow", "all six, wired up the same way", "", OK),
    ]
    y = 190
    for n, term, interceptor, seam, color in rows:
        s += (f'<circle cx="118" cy="{y + 28}" r="17" fill="{color}" fill-opacity="0.14" '
              f'stroke="{color}" stroke-width="1.8"/>\n')
        s += text(118, y + 34, n, size=15, anchor="middle", fill=color, weight=700, mono=True)
        s += panel(154, y, 402, 56, accent=LINE, fill=PANEL, r=12, fill_op=0.85)
        s += text(176, y + 35, term, size=20, weight=600)
        s += arrow(566, y + 28, 606, y + 28, color="muted", sw=2)
        s += panel(614, y, 570, 56, accent=color, fill=PANEL2, r=12, fill_op=0.85)
        s += text(636, y + 34, interceptor, size=16, mono=True, weight=700, fill=color)
        if seam:
            s += text(1162, y + 34, seam, size=12, fill=MUTED, anchor="end")
        y += 66

    # One before five: that is the order the request travels, and the order rows 1 and 2
    # of this slide already imply.
    s += note_only(154, 588, 1030, [
        "One is wired into every client that starts a trip. Five are wired once on the worker",
        "and inherited by every workflow there, including the ones nobody has written yet.",
    ], color=OK, title="INTERCEPTORS HELP MEET REQUIREMENT 6")
    return s


def img_11_one_booking():
    s = head()
    s += slide_title("One booking, all six",
                     "In firing order. No workflow or activity code decides any of it.",
                     accent=OK)

    s += (f'<line x1="130" y1="196" x2="130" y2="640" stroke="{LINE}" stroke-width="2"/>\n')
    s += text(130, 182, "time", size=13, fill=MUTED, anchor="middle")

    rows = [
        ("1", "client_auth", "client outbound", C_CLIENT,
         "verify the license, authorize the trip, mint a grant", "a refusal costs nothing"),
        ("2", "workflow_startup", "workflow inbound", C_WORKFLOW,
         "one id for the trip, a guardrail, searchable tags", "the trip is findable"),
        ("3", "grant_propagation", "workflow in and out", C_BOTH,
         "carry the context onto every activity", "no argument plumbing"),
        ("4", "activity_logging", "activity inbound", C_ACTIVITY,
         "start, duration, outcome and the trip id, one format", "one line per activity"),
        ("5", "token_exchange", "activity inbound", C_ACTIVITY,
         "grant plus worker identity for a 120s credential", "acting on behalf of"),
        ("6", "workflow_audit", "workflow inbound", C_WORKFLOW,
         "every signal and query that arrives", "who approved it, and when"),
    ]
    y = 210
    for n, name, where, color, what, artifact in rows:
        s += (f'<circle cx="130" cy="{y + 30}" r="17" fill="{BG}" stroke="{color}" '
              f'stroke-width="2.2"/>\n')
        s += text(130, y + 36, n, size=15, anchor="middle", fill=color, weight=700, mono=True)
        s += panel(178, y, 620, 60, accent=color, fill=PANEL, r=12, fill_op=0.85)
        s += text(198, y + 26, name, size=17, mono=True, weight=700, fill=color)
        s += text(198, y + 48, what, size=14, fill=MUTED)
        s += text(786, y + 26, where, size=13, fill=color, anchor="end", op=0.8)
        s += arrow(806, y + 30, 844, y + 30, color="muted", sw=1.8)
        s += pill(850, y + 12, artifact, OK, size=13, h=32, fill_op=0.10)
        y += 74
    return s


def img_12_other_systems():
    s = head()
    s += slide_title("Then Rufus told the rest of IT",
                     "Same five places to hook in. Every other system had similar requirements.",
                     accent=PURPLE)

    tiles = [
        ("Distributed tracing", "One OpenTelemetry span per workflow "
                                "and activity, context on the header.", "client and worker",
         C_BOTH),
        ("Metrics by workflow type", "Count and time every execution "
                                     "without touching a workflow.",
         "activity and workflow inbound", C_BOTH),
        ("Tenant and locale context", "Carry tenant, region and feature "
                                      "flags to every child and activity.",
         "client and workflow outbound", C_BOTH),
        ("PII-safe logging", "Log shapes, not payloads. One "
                             "redaction rule, applied everywhere.", "inbound hooks", C_BOTH),
        ("Refuse work before it starts", "Unauthorized requests never begin, "
                                         "so nothing is spent running them.", "client outbound",
         C_CLIENT),
        ("Fault injection in test", "Make the booth act up on purpose. "
                                    "Delete the interceptor in prod.", "activity inbound",
         C_ACTIVITY),
    ]
    for i, (title_, body, seam, color) in enumerate(tiles):
        cx = 96 + (i % 3) * 366
        cy = 196 + (i // 3) * 236
        s += panel(cx, cy, 342, 208, accent=color, fill=PANEL, r=14, fill_op=0.85)
        s += f'<rect x="{cx}" y="{cy}" width="4" height="208" rx="2" fill="{color}"/>\n'
        s += text(cx + 22, cy + 44, title_, size=19, weight=700)
        ty = cy + 78
        for ln in wrap(body, 34):
            s += text(cx + 22, ty, ln, size=15, fill=MUTED)
            ty += 22
        s += pill(cx + 22, cy + 156, seam, color, size=12, h=28, fill_op=0.12)

    s += rufus(1150, 700, scale=0.68)
    return s


# ---------------------------------------------------------------------------
# Demo cards: the workflow, with the interceptors drawn where they run
# ---------------------------------------------------------------------------

# (label, center x) for the booking, left to right.
_TRACK = [("book", 185), ("workflow start", 368), ("paradox scan", 551),
          ("hold for Rufus", 734), ("execute jump", 917), ("arrival", 1100)]

# key -> (label, where it runs, node index, on the inbound row?, category color)
# Inbound hooks sit above the track, outbound hooks below it. The color is the
# category, matching slides 8 to 10; state comes from fill, dashes and label color.
# The leading digits are FIRING order, not registration order. activity_logging is\n# registered before token_exchange in worker.py, so it is outer on the activity-inbound\n# chain and runs first. See workflows/worker.py:52. Do not renumber these to match the\n# order of the worker's interceptors= list.\n# key -> (chip label, chip seam, node index, on the inbound row?, category color, every
# hook it installs). The chip names the hook that puts it where it sits on the track and
# adds "+2" when there are more; the legend at the foot of the slide spells them all out.
# Two of these install three hooks each, so a single-hook chip understated them.
_BADGES = {
    "workflow_startup": ("2 workflow_startup", "workflow inbound +2", 1, True, C_WORKFLOW,
                         "workflow in · workflow out · activity in"),
    "token_exchange": ("5 token_exchange", "activity inbound", 2, True, C_ACTIVITY,
                       "activity inbound"),
    "workflow_audit": ("6 workflow_audit", "workflow inbound", 3, True, C_WORKFLOW,
                       "workflow inbound"),
    "activity_logging": ("4 activity_logging", "activity inbound", 4, True, C_ACTIVITY,
                         "activity inbound"),
    "client_auth": ("1 client_auth", "client outbound", 0, False, C_CLIENT,
                    "client outbound"),
    "grant_propagation": ("3 grant_propagation", "workflow outbound +2", 1, False, C_BOTH,
                          "workflow in · workflow out · activity in"),
}


def workflow_track(*, reached, states, stop_note=None, skip=()):
    """Draw the booking as a track, with the interceptors on it where they run.

    reached: how many of the six steps this run reaches.
    skip:    step indexes this run does not need (drawn faint, not blocked).
    states:  key -> "on" | "off" | "gate" for each of the six interceptors.
    """
    ny, nh, nw = 396, 58, 150
    s = ""
    s += text(1196, ny - 26, "inbound", size=14, anchor="end", fill=MUTED, weight=700)
    s += text(1196, ny + nh + 40, "outbound", size=14, anchor="end", fill=MUTED, weight=700)
    for i, (label, cx) in enumerate(_TRACK):
        live = i < reached and i not in skip
        color = CYAN if live else MUTED
        s += panel(cx - nw / 2, ny, nw, nh, accent=color, fill=PANEL2 if live else PANEL,
                   r=10, fill_op=0.9 if live else 0.4, dash=None if live else "5 5")
        s += text(cx, ny + 35, label, size=15, anchor="middle", weight=600,
                  fill=INK if live else MUTED, op=1 if live else 0.55)
        if i:
            px = _TRACK[i - 1][1] + nw / 2
            drawn = i < reached
            s += arrow(px + 4, ny + nh / 2, cx - nw / 2 - 6, ny + nh / 2,
                       color="cyan" if drawn else "muted", sw=2, dash=not drawn)
    if reached < len(_TRACK):
        # Center the block marker in the gap between the last live node and the next.
        if reached:
            gx = (_TRACK[reached - 1][1] + nw / 2 + _TRACK[reached][1] - nw / 2) / 2
        else:
            gx = _TRACK[0][1] - nw / 2 - 26
        s += mark(gx, ny + nh / 2, "bad", r=17)
        if stop_note:
            s += text(gx, ny + nh + 34, stop_note, size=14, anchor="middle", fill=BAD,
                      weight=600)

    bw, bh = 178, 54
    for key, (label, seam, node, above, category, _hooks) in _BADGES.items():
        state = states.get(key, "off")
        live = state != "off"
        color = category if live else MUTED
        label_fill = BAD if state == "gate" else color
        cx = _TRACK[node][1]
        by = ny - 116 if above else ny + nh + 62
        s += panel(cx - bw / 2, by, bw, bh, accent=color, fill=PANEL2, r=10,
                   fill_op=0.9 if live else 0.35, dash=None if live else "5 5")
        s += text(cx, by + 24, label, size=13, mono=True, weight=700, anchor="middle",
                  fill=label_fill, op=1 if live else 0.6)
        s += text(cx, by + 43, seam, size=12, anchor="middle", fill=MUTED,
                  op=1 if live else 0.6)
        y1, y2 = (by + bh, ny - 4) if above else (ny + nh + 4, by)
        s += (f'<line x1="{cx}" y1="{y1}" x2="{cx}" y2="{y2}" stroke="{color}" '
              f'stroke-width="1.6" stroke-dasharray="4 4" '
              f'opacity="{0.9 if live else 0.3}"/>\n')
    return s


def demo_card(*, title, subtitle, accent, terms, reached, states, stop_note,
              skip=()):
    s = head()
    s += slide_title(title, subtitle, accent=accent)

    # The business requirements in play on this run. Requirement 1 is on all four,
    # because authentication is the precondition for every run rather than something a
    # particular one proves.
    tx = 96
    for term in terms:
        s += pill(tx, 186, term, accent, size=14, h=34, fill_op=0.12)
        tx += pill_w(term, 14, False, 16) + 12

    s += workflow_track(reached=reached, states=states, stop_note=stop_note, skip=skip)

    # The bottom line used to be a one-sentence verdict. That was a talking point rather
    # than something the slide had to carry, and the space it freed is what lets every hook
    # be named: two of the six install three hooks each, which a chip cannot hold.
    s += text(96, 604, "WHERE EACH ONE HOOKS IN", size=11, fill=MUTED, spacing=1.3,
              weight=700)
    order = sorted(_BADGES.items(), key=lambda kv: kv[1][0])
    for i, (key, (label, _seam, _node, _above, category, hooks)) in enumerate(order):
        col, row = i % 3, i // 3
        x = 96 + col * 364
        y = 628 + row * 40
        live = states.get(key, "off") != "off"
        s += text(x, y, label.split(" ", 1)[1], size=12, mono=True, weight=700,
                  fill=category, op=1 if live else 0.45)
        s += text(x, y + 16, hooks, size=11, fill=MUTED, op=1 if live else 0.45)
    return s


def img_demo1():
    return demo_card(
        title="Demo 1: run a cleared mission, and act for the traveler",
        subtitle="Requirements 1, 2 and 5. Bill is cleared for this mission, and the booth "
                 "travels as Bill.",
        accent=OK,
        terms=["1 · only real travelers", "2 · cleared missions only",
               "5 · name the traveler"],
        reached=6, skip={3},
        states={k: ("off" if k == "workflow_audit" else "on") for k in _BADGES},
        stop_note=None)


def img_demo2():
    return demo_card(
        title="Demo 2: refuse a mission the traveler is not cleared for",
        subtitle="Requirements 1 and 2, enforced before the request leaves our own process.",
        accent=WARN,
        terms=["1 · only real travelers", "2 · cleared missions only"],
        reached=1,
        states={"client_auth": "gate"},
        stop_note="refused here. No workflow, no Action, nothing in Temporal")


def img_demo3():
    return demo_card(
        title="Demo 3: see what happened on a trip, in seconds",
        subtitle="Requirements 1 and 4. One id ties every step of that trip together, "
                 "and every trip is searchable.",
        accent=CYAN,
        terms=["1 · only real travelers", "4 · see what happened on a trip"],
        reached=6, skip={3},
        states={k: ("off" if k == "workflow_audit" else "on") for k in _BADGES},
        stop_note=None)


def img_demo4():
    return demo_card(
        title="Demo 4: prove who approved a questionable trip",
        subtitle="Requirements 1 and 3. The trip waits for Rufus, and the record says "
                 "who released it and when.",
        accent=PURPLE,
        terms=["1 · only real travelers", "3 · prove who approved",
               "5 · name the traveler"],
        reached=6,
        states={k: "on" for k in _BADGES},
        stop_note=None)


# ---------------------------------------------------------------------------
# The close
# ---------------------------------------------------------------------------


def img_13_what_shipped():
    s = head()
    s += slide_title("What Rufus shipped",
                     "Six business requirements met. The original workflow, unchanged.", accent=OK)

    tiles = [("6", "requirements", "met in the right place", OK),
             ("7", "files", "six interceptors, and the activity one of them needs", CYAN),
             ("2", "wiring points", "the client tier, and the worker", PURPLE),
             ("0", "auth decisions in workflow.py", "it reads who; it never checks", WARN)]
    for i, (big, label, sub, color) in enumerate(tiles):
        cx = 96 + i * 274
        s += panel(cx, 196, 250, 196, accent=color, fill=PANEL, r=14, fill_op=0.85)
        s += f'<rect x="{cx}" y="196" width="4" height="196" rx="2" fill="{color}"/>\n'
        s += text(cx + 125, 296, big, size=66, anchor="middle", weight=700, fill=color,
                  mono=True)
        s += text(cx + 125, 332, label, size=18, anchor="middle", weight=700)
        for j, ln in enumerate(wrap(sub, 26)):
            s += text(cx + 125, 358 + j * 20, ln, size=13, anchor="middle", fill=MUTED)

    s += panel(96, 424, 1088, 140, accent=WARN, fill=PANEL, r=14, fill_op=0.6)
    s += text(120, 462, "THE QUESTION TO TAKE TO THE FUTURE", size=14, fill=WARN,
              weight=700, spacing=1.4)
    s += text(120, 504, "What cross-cutting requirements do your customers have that "
                        "interceptors could meet,", size=23, fill=INK)
    s += text(120, 534, "instead of copying code into every workflow or paying for extra "
                        "billable Actions?", size=23, fill=INK)

    s += rufus(300, 686, scale=1.15, guitar=True)
    s += bill(420, 686, scale=1.0)
    s += ted(510, 686, scale=1.0)
    s += text(600, 668, "Six requirements. Seven files. One workflow that never mentions "
                        "any of them.", size=19, fill=OK)
    return s


def img_14_questions():
    s = head()
    s += slide_title("Questions", "And where to go deeper.", accent=CYAN)

    # Four boxes of one size: Temporal's own docs first, then this repo's three entries.
    rows = [("docs.temporal.io/encyclopedia/interceptors", "Temporal's own reference", CYAN),
            ("github.com/timjbruce/interceptors", "the whole demo, running", C_CLIENT),
            ("README.md", "run it in four terminals, then prove each part is real", OK),
            ("interceptors.md", "interceptor by interceptor, with the field notes", PURPLE)]
    y = 200
    for name, what, color in rows:
        s += panel(96, y, 940, 76, accent=color, fill=PANEL, r=12, fill_op=0.85)
        s += f'<rect x="96" y="{y}" width="5" height="76" rx="2.5" fill="{color}"/>\n'
        s += text(126, y + 34, name, size=20, mono=True, weight=700, fill=color)
        s += text(126, y + 58, what, size=15, fill=MUTED)
        y += 90

    s += temporal_logo(1076, 200, size=76)
    s += rufus(1116, 470, scale=1.15, guitar=True)

    s += panel(96, 552, 1088, 116, accent=LINE, fill=PANEL, r=14, fill_op=0.7)
    s += text(120, 592, "Everything in the talk runs locally in four terminals: the "
                        "workflow, all six interceptors, a JWT-protected", size=19)
    s += text(120, 620, "backend, the web client and the tests. The README proves each part "
                        "is real rather than asserting it,", size=19)
    s += text(120, 648, "and interceptors.md is the walkthrough this deck deliberately "
                        "left out.", size=19)
    return s


# ---------------------------------------------------------------------------


IMAGES = {
    # The deck.
    "00-title": img_00_title,
    "01-san-dimas-2691": img_01_san_dimas,
    "02-v1-no-auth": img_02_v1_no_auth,
    "03-next-universe": img_03_next_universe,
    "04-two-ways-to-lose": img_04_two_ways_to_lose,
    "05-every-workflow": img_05_every_workflow,
    "06-middleware": img_06_middleware,
    "07-five-seams": img_07_five_seams,
    "08-how-to-build": img_08_how_to_build,
    "09-should-it-be-an-interceptor": img_09_should_it_be,
    "10-terms-to-interceptors": img_10_terms_to_interceptors,
    "11-one-booking-six": img_11_one_booking,
    "12-other-systems": img_12_other_systems,
    "13-what-shipped": img_13_what_shipped,
    "14-questions": img_14_questions,
    "demo1-premium-approved": img_demo1,
    "demo2-not-entitled": img_demo2,
    "demo3-clean-trip": img_demo3,
    "demo4-impostors": img_demo4,
}


def main() -> None:
    out = pathlib.Path(__file__).parent
    known = {f"{name}.svg" for name in IMAGES}
    for stale in sorted(out.glob("*.svg")):
        if stale.name not in known:
            stale.unlink()
            print(f"removed {stale.name} (no longer generated)")
    for name, fn in IMAGES.items():
        (out / f"{name}.svg").write_text(fn() + tail(), encoding="utf-8")
        print(f"wrote {name}.svg")


if __name__ == "__main__":
    main()
