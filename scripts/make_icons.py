#!/usr/bin/env python3
"""Disegna le icone del sito in web/icons/<nome>/: favicon SVG, PNG per la Home
del telefono e manifest. Ogni forma esce sia in SVG sia in PNG dallo stesso
disegno. Le icone si scelgono dalle impostazioni della pagina (⚙ in alto).

    python3 scripts/make_icons.py
"""
import json, math, os
from PIL import Image, ImageDraw
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "icons")
BG, Y, G, INK, DIM, FIELD = "#0F1412", "#F1D62B", "#58CFA0", "#E4EAE5", "#2A3530", "#0E3B2A"

def bez(p0, p1, p2, p3, n=40):
    return [tuple((1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t*t*c + t**3*d for a, b, c, d in zip(p0, p1, p2, p3))
            for t in (i/n for i in range(n+1))]
def lens(cx, cy, h, r, ang, n=60):
    c = math.sqrt(r*r - h*h); a = math.radians(ang); out = []
    xs = [-h + 2*h*i/n for i in range(n+1)]
    pts = [(x, -(math.sqrt(r*r-x*x)-c)) for x in xs] + [(-x, (math.sqrt(r*r-x*x)-c)) for x in xs[1:-1]]
    return [(cx + x*math.cos(a) - y*math.sin(a), cy + x*math.sin(a) + y*math.cos(a)) for x, y in pts]

class Icon:
    def __init__(s, name, bg=BG): s.name, s.ops = name, [("bg", bg)]
    def poly(s, pts, fill): s.ops.append(("poly", pts, fill)); return s
    def rect(s, x, y, w, h, fill, r=0): s.ops.append(("rect", x, y, w, h, fill, r)); return s
    def circle(s, cx, cy, r, fill=None, stroke=None, w=0): s.ops.append(("circ", cx, cy, r, fill, stroke, w)); return s
    def line(s, pts, color, w): s.ops.append(("line", pts, color, w)); return s
    def pie(s, cx, cy, r, a0, a1, fill):    # gradi, 0 = ore 12, senso orario
        pts = [(cx, cy)] + [(cx + r*math.sin(math.radians(a)), cy - r*math.cos(math.radians(a)))
                            for a in [a0 + (a1-a0)*i/40 for i in range(41)]]
        return s.poly(pts, fill)
    def svg(s):
        f = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")
        P = lambda pts: " ".join(f"{f(x)},{f(y)}" for x, y in pts)
        o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">']
        for op in s.ops:
            k = op[0]
            if k == "bg": o.append(f'<rect width="64" height="64" rx="14" fill="{op[1]}"/>')
            elif k == "poly": o.append(f'<polygon points="{P(op[1])}" fill="{op[2]}"/>')
            elif k == "rect": o.append(f'<rect x="{f(op[1])}" y="{f(op[2])}" width="{f(op[3])}" height="{f(op[4])}" rx="{f(op[6])}" fill="{op[5]}"/>')
            elif k == "circ":
                _, cx, cy, r, fill, st, w = op
                o.append(f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" fill="{fill or "none"}"' + (f' stroke="{st}" stroke-width="{f(w)}"' if st else "") + "/>")
            elif k == "line": o.append(f'<polyline points="{P(op[1])}" fill="none" stroke="{op[2]}" stroke-width="{f(op[3])}" stroke-linecap="round" stroke-linejoin="round"/>')
        return "\n".join(o + ["</svg>"]) + "\n"
    def png(s, size, square=False):
        S = 8; W = size*S; k = W/64
        im = Image.new("RGBA", (W, W), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        T = lambda pts: [(x*k, y*k) for x, y in pts]
        def dot(x, y, r, c): d.ellipse([(x-r)*k, (y-r)*k, (x+r)*k, (y+r)*k], fill=c)
        for op in s.ops:
            kd = op[0]
            if kd == "bg":
                if square: d.rectangle([0, 0, W, W], fill=op[1])
                else: d.rounded_rectangle([0, 0, W-1, W-1], radius=14*k, fill=op[1])
            elif kd == "poly": d.polygon(T(op[1]), fill=op[2])
            elif kd == "rect":
                _, x, y, w, h, c, r = op; d.rounded_rectangle([x*k, y*k, (x+w)*k, (y+h)*k], radius=r*k, fill=c)
            elif kd == "circ":
                _, cx, cy, r, fill, st, w = op
                if st: d.ellipse([(cx-r-w/2)*k, (cy-r-w/2)*k, (cx+r+w/2)*k, (cy+r+w/2)*k], fill=st)
                inner = fill or (BG if st else None)
                if st and not fill:
                    # anello: ritaglia il centro col colore che c'era sotto (qui sempre lo sfondo dell'icona)
                    d.ellipse([(cx-r+w/2)*k, (cy-r+w/2)*k, (cx+r-w/2)*k, (cy+r-w/2)*k], fill=s.ops[0][1])
                elif fill: d.ellipse([(cx-r+(w/2 if st else 0))*k, (cy-r+(w/2 if st else 0))*k, (cx+r-(w/2 if st else 0))*k, (cy+r-(w/2 if st else 0))*k], fill=fill)
            elif kd == "line":
                _, pts, c, w = op
                for a, b in zip(pts, pts[1:]): d.line([(a[0]*k, a[1]*k), (b[0]*k, b[1]*k)], fill=c, width=round(w*k))
                for x, y in pts: dot(x, y, w/2, c)
        return im.resize((size, size), Image.LANCZOS)

icons = []

# 1 · Draft board: la griglia delle pick, la tua cella accesa
i = Icon("board")
cols = [[DIM, G, DIM, DIM], [G, DIM, DIM, G], [DIM, DIM, Y, None], [None, None, None, None]]
for r in range(4):
    for c in range(4):
        col = cols[r][c]
        i.rect(11 + c*11, 11 + r*11, 9, 9, col or "#1A221E", 2)
icons.append(i)

# 2 · Playbook: "Smash" — hitch esterno, corner dello slot sopra il cornerback, slant sul lato debole
i = Icon("playbook", FIELD)
i.line([(8, 44), (56, 44)], "#2C5E49", 1.6)                       # linea di scrimmage
def arrow(i, tip, frm, col, L=5.2, W=3.4):
    dx, dy = tip[0]-frm[0], tip[1]-frm[1]; n = math.hypot(dx, dy); ux, uy = dx/n, dy/n
    bx, by = tip[0]-ux*L, tip[1]-uy*L
    i.poly([tip, (bx-uy*W, by+ux*W), (bx+uy*W, by-ux*W)], col)
i.line([(12, 45), (12, 29), (15, 32)], G, 3)                   # hitch
arrow(i, (17.2, 34.2), (14.6, 31.6), G)
i.line([(32, 45), (32, 30), (20.5, 18.5)], Y, 3.2)                     # corner: la giocata
arrow(i, (17.4, 15.4), (21, 19), Y)
i.line([(50, 45), (50, 37), (42.5, 29.5)], G, 3)                  # slant
arrow(i, (40.2, 27.2), (43, 30), G)
for cx in (12, 32, 50): i.circle(cx, 51, 4.3, stroke=INK, w=2.6)
for cx, cy in ((23.5, 32), (46, 15)):
    i.line([(cx-3.6, cy-3.6), (cx+3.6, cy+3.6)], INK, 2.6).line([(cx-3.6, cy+3.6), (cx+3.6, cy-3.6)], INK, 2.6)
icons.append(i)

# 5 · On the clock: il cronometro della pick, spicchio di tempo giallo
i = Icon("clock")
i.rect(27, 7, 10, 5, INK, 1.5).rect(30, 11, 4, 5, INK, 0)
i.line([(47, 17), (50.5, 13.5)], INK, 3.4)
i.circle(32, 36, 19, stroke=INK, w=4)
i.pie(32, 36, 14.5, 0, 125, Y)
i.line([(32, 36), (32, 23)], INK, 2.6)
i.circle(32, 36, 2.8, fill=INK)
icons.append(i)

NAMES = {"board": "Draft board", "playbook": "Playbook", "clock": "On the clock"}
for ic in icons:
    d = os.path.join(OUT, ic.name); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "favicon.svg"), "w").write(ic.svg())
    ic.png(180, square=True).save(os.path.join(d, "apple-touch-icon.png"))   # iOS arrotonda da sé
    ic.png(192).save(os.path.join(d, "icon-192.png"))
    ic.png(512).save(os.path.join(d, "icon-512.png"))
    with open(os.path.join(d, "manifest.webmanifest"), "w") as f:
        json.dump({"name": "Draft War Room", "short_name": "War Room", "start_url": "../../", "scope": "../../",
                   "display": "standalone", "background_color": "#0F1412", "theme_color": "#0F1412",
                   "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                             {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
                             {"src": "apple-touch-icon.png", "sizes": "180x180", "type": "image/png", "purpose": "maskable"},
                             {"src": "favicon.svg", "sizes": "any", "type": "image/svg+xml"}]}, f, indent=2)
    print("scritto", os.path.relpath(d, ROOT), "·", NAMES[ic.name])
