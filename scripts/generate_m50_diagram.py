#!/usr/bin/env python3
"""Generate the M50 SMP 2.0 architecture diagram for the LinkedIn post."""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# ── palette ────────────────────────────────────────────────────────────────────
BG        = "#0d1117"   # GitHub dark canvas
PANEL     = "#161b22"
BLUE      = "#1f6feb"   # primary accent
BLUE_DIM  = "#0d419d"
GREEN     = "#238636"
GREEN_DIM = "#1a6329"
ORANGE    = "#f0883e"
PURPLE    = "#8b949e"
RED_DIM   = "#6e2430"
TEXT      = "#e6edf3"
TEXT_DIM  = "#8b949e"
BORDER    = "#30363d"

fig = plt.figure(figsize=(18, 10), facecolor=BG)
ax  = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 18)
ax.set_ylim(0, 10)
ax.axis("off")
ax.set_facecolor(BG)


def box(x, y, w, h, fc, ec=BORDER, lw=1.2, radius=0.18):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3,
    )
    ax.add_patch(patch)


def label(x, y, text, color=TEXT, size=9, weight="normal", ha="center", va="center"):
    ax.text(x, y, text, color=color, fontsize=size, fontweight=weight,
            ha=ha, va=va, zorder=4, fontfamily="monospace")


def plain(x, y, text, color=TEXT, size=9, weight="normal", ha="center", va="center"):
    ax.text(x, y, text, color=color, fontsize=size, fontweight=weight,
            ha=ha, va=va, zorder=4)


def arrow(x0, y0, x1, y1, color=BLUE_DIM, lw=1.5, style="->"):
    ax.annotate(
        "", xy=(x1, y1), xytext=(x0, y0),
        arrowprops=dict(arrowstyle=style, color=color, lw=lw),
        zorder=2,
    )


def dashed_arrow(x0, y0, x1, y1, color=TEXT_DIM):
    ax.annotate(
        "", xy=(x1, y1), xytext=(x0, y0),
        arrowprops=dict(arrowstyle="->", color=color, lw=1.2,
                        linestyle="dashed"),
        zorder=2,
    )


# ── title ─────────────────────────────────────────────────────────────────────
plain(9, 9.5, "opensvf  ·  Milestone M50: SMP 2.0 Model Portability",
      color=TEXT, size=15, weight="bold")
plain(9, 9.1, "ECSS-E-ST-40-07C  ·  Python ISmpModel interface layer",
      color=TEXT_DIM, size=10)

# ──────────────────────────────────────────────────────────────────────────────
# ROW 1  –  Models  (left side, 5 columns of model groups)
# ──────────────────────────────────────────────────────────────────────────────
plain(1.5, 8.55, "SIMULATION MODELS  (19 total)", color=TEXT_DIM, size=8, weight="bold")

model_groups = [
    ("AOCS\nSensors",   ["magnetometer", "gyroscope", "CSS", "star tracker", "GPS"],       BLUE_DIM,  BLUE),
    ("AOCS\nActuators", ["reaction wheel", "magnetorquer", "thruster"],                    "#1a3a1a",  GREEN),
    ("EPS",             ["battery", "PCDU", "solar array"],                                "#2d1f00",  ORANGE),
    ("Env / Dyn",       ["orbital env", "rigid body\ndynamics", "thermal"],                "#2a1f3d",  "#a371f7"),
    ("Buses",           ["CAN 2.0B", "MIL-STD-1553", "SpaceWire"],                        "#1a1a2e",  "#58a6ff"),
]

box_w = 2.8
box_h = 1.85
x0    = 0.4
gap   = 0.22

group_centers = []
for i, (title, members, fc, ec) in enumerate(model_groups):
    x = x0 + i * (box_w + gap)
    y = 6.5
    box(x, y, box_w, box_h, fc=fc, ec=ec, lw=1.4)
    label(x + box_w / 2, y + box_h - 0.28, title, color=ec, size=8.5, weight="bold")
    for j, m in enumerate(members):
        label(x + box_w / 2, y + box_h - 0.65 - j * 0.3, m, color=TEXT, size=7.5)
    group_centers.append(x + box_w / 2)

# ──────────────────────────────────────────────────────────────────────────────
# ROW 2  –  SmpEquipmentMixin  (spans model columns)
# ──────────────────────────────────────────────────────────────────────────────
mixin_x  = x0
mixin_w  = 5 * box_w + 4 * gap
mixin_y  = 5.6
mixin_h  = 0.65
box(mixin_x, mixin_y, mixin_w, mixin_h, fc="#0d2444", ec=BLUE, lw=1.6)
label(mixin_x + mixin_w / 2, mixin_y + mixin_h / 2,
      "SmpEquipmentMixin   ·   bridges Equipment.ports → ISmpModel.smp_fields   ·   lazy state, MRO-safe",
      color=BLUE, size=8.5, weight="bold")

# arrows from model groups down into mixin
for cx in group_centers:
    arrow(cx, 6.5, cx, mixin_y + mixin_h, color=BLUE_DIM, lw=1.0)

# ──────────────────────────────────────────────────────────────────────────────
# ROW 3  –  ISmpModel interface + lifecycle states  (centre)
# ──────────────────────────────────────────────────────────────────────────────
iface_x = x0
iface_y = 4.4
iface_w = mixin_w
iface_h = 0.95
box(iface_x, iface_y, iface_w, iface_h, fc="#05141f", ec="#388bfd", lw=2.0)
label(iface_x + iface_w / 2, iface_y + 0.68,
      "ISmpModel   (ECSS-E-ST-40-07C §4.7.1)",
      color="#79c0ff", size=9.5, weight="bold")

states = ["CREATED", "PUBLISHING", "CONFIGURED", "CONNECTED", "INITIALISED", "EXECUTING", "TERMINATED"]
cols   = ["#8b949e", "#1f6feb", "#388bfd", "#3fb950", "#3fb950", "#3fb950", "#f0883e"]
sw     = iface_w / len(states)
for k, (s, c) in enumerate(zip(states, cols)):
    sx = iface_x + k * sw + sw / 2
    label(sx, iface_y + 0.28, s, color=c, size=7, weight="bold")
    if k < len(states) - 1:
        ax.annotate("", xy=(sx + sw * 0.38, iface_y + 0.28),
                    xytext=(sx + sw * 0.12, iface_y + 0.28),
                    arrowprops=dict(arrowstyle="->", color="#30363d", lw=0.9), zorder=4)

arrow(mixin_x + mixin_w / 2, mixin_y, mixin_x + mixin_w / 2, iface_y + iface_h,
      color="#388bfd", lw=1.8)

# ──────────────────────────────────────────────────────────────────────────────
# ROW 4  –  Artifacts  +  MinimalSmpHost  +  Future  (bottom, horizontal)
# ──────────────────────────────────────────────────────────────────────────────
art_y  = 2.45
art_h  = 1.6
art_gap= 0.35

# smpcat
cat_x = x0
cat_w = 3.6
box(cat_x, art_y, cat_w, art_h, fc="#1a2f1a", ec=GREEN, lw=1.3)
label(cat_x + cat_w / 2, art_y + 1.3,  "smp/opensvf.smpcat",   color=GREEN,  size=8.5, weight="bold")
label(cat_x + cat_w / 2, art_y + 0.95, "SMP 2.0 Catalogue XML", color=TEXT,   size=7.5)
label(cat_x + cat_w / 2, art_y + 0.65, "128 fields",            color=TEXT_DIM, size=7.5)
label(cat_x + cat_w / 2, art_y + 0.38, "6 domains · 19 models", color=TEXT_DIM, size=7.5)
label(cat_x + cat_w / 2, art_y + 0.12, "TM→Output  TC→Input",   color=TEXT_DIM, size=7.5)

# smpconf
conf_x = cat_x + cat_w + art_gap
conf_w = 3.6
box(conf_x, art_y, conf_w, art_h, fc="#1f1a0d", ec=ORANGE, lw=1.3)
label(conf_x + conf_w / 2, art_y + 1.3,  "smp/mysat1.smpconf",     color=ORANGE,   size=8.5, weight="bold")
label(conf_x + conf_w / 2, art_y + 0.95, "SMP 2.0 Assembly XML",   color=TEXT,     size=7.5)
label(conf_x + conf_w / 2, art_y + 0.65, "7 instances",            color=TEXT_DIM, size=7.5)
label(conf_x + conf_w / 2, art_y + 0.38, "from spacecraft.yaml",   color=TEXT_DIM, size=7.5)
label(conf_x + conf_w / 2, art_y + 0.12, "auto-wiring aware",      color=TEXT_DIM, size=7.5)

# MinimalSmpHost
host_x = conf_x + conf_w + art_gap
host_w = 3.8
box(host_x, art_y, host_w, art_h, fc="#05141f", ec="#58a6ff", lw=1.3)
label(host_x + host_w / 2, art_y + 1.3,  "MinimalSmpHost",          color="#58a6ff", size=8.5, weight="bold")
label(host_x + host_w / 2, art_y + 0.95, "Python SE host contract", color=TEXT,      size=7.5)
label(host_x + host_w / 2, art_y + 0.65, "776 tests · 4 L2 cases",  color=TEXT_DIM,  size=7.5)
label(host_x + host_w / 2, art_y + 0.38, "round-trip verified",     color=TEXT_DIM,  size=7.5)
label(host_x + host_w / 2, art_y + 0.12, "+ FMU co-sim",            color=TEXT_DIM,  size=7.5)

# Future: C++ bridge
fut_x = host_x + host_w + art_gap
fut_w = 3.7
box(fut_x, art_y, fut_w, art_h, fc="#1a0d0d", ec="#f0883e", lw=1.0, radius=0.18)
label(fut_x + fut_w / 2, art_y + 1.3,  "C++ ABI bridge",         color="#f0883e", size=8.5, weight="bold")
label(fut_x + fut_w / 2, art_y + 0.95, "⟶  NEXT MILESTONE",      color=TEXT_DIM, size=7.5)
label(fut_x + fut_w / 2, art_y + 0.65, "dlopen() ISmpModel",     color=TEXT_DIM, size=7.5)
label(fut_x + fut_w / 2, art_y + 0.38, "vtable handshake",       color=TEXT_DIM, size=7.5)
label(fut_x + fut_w / 2, art_y + 0.12, "BASILES · EuroSim · ...",color=TEXT_DIM, size=7)

# arrows down from ISmpModel to artifacts
art_centers = [
    cat_x  + cat_w  / 2,
    conf_x + conf_w / 2,
    host_x + host_w / 2,
]
for cx in art_centers:
    arrow(cx, iface_y, cx, art_y + art_h, color="#30363d", lw=1.2)

# dashed arrow to future
dashed_arrow(host_x + host_w / 2, art_y + art_h / 2,
             fut_x, art_y + art_h / 2, color="#f0883e")

# ──────────────────────────────────────────────────────────────────────────────
# legend / footer
# ──────────────────────────────────────────────────────────────────────────────
plain(0.4, 1.9, "M50 scope:", color=TEXT_DIM, size=7.5, ha="left")
legend_items = [
    (BLUE,      "ISmpModel interface  (Python ABC)"),
    (GREEN,     "Catalogue XML  (generated from SRDB)"),
    (ORANGE,    "Assembly XML  (generated from spacecraft.yaml)"),
    ("#58a6ff", "MinimalSmpHost  (Python SE, round-trip tests)"),
    ("#f0883e", "C++ ABI bridge  (next milestone)"),
]
for k, (c, txt) in enumerate(legend_items):
    lx = 0.4 + k * 3.45
    ax.add_patch(mpatches.FancyBboxPatch(
        (lx, 1.55), 0.28, 0.22,
        boxstyle="round,pad=0,rounding_size=0.06",
        facecolor=c, edgecolor="none", zorder=4,
    ))
    plain(lx + 0.38, 1.66, txt, color=TEXT_DIM, size=7, ha="left")

plain(9, 0.7, "github.com/lipofefeyt/opensvf", color=TEXT_DIM, size=8)

fig.savefig("docs/m50_diagram.png", dpi=180, bbox_inches="tight",
            facecolor=BG, edgecolor="none")
print("Saved: docs/m50_diagram.png")
