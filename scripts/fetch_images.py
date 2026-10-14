#!/usr/bin/env python3
"""Scarica da ESPN le foto dei giocatori e i loghi delle squadre NFL.

Le immagini servono alla scheda del giocatore. Vengono ridotte e salvate in
web/img/: il sito locale le usa da lì, e la copia a file unico le incorpora come
data URI (le pagine pubblicate non possono caricare immagini esterne).

  python3 scripts/fetch_images.py            # rose della lega + loghi
  python3 scripts/fetch_images.py --top 200  # anche i primi 200 del pool
"""
import argparse, base64, io, json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "data", "build")
IMG = os.path.join(ROOT, "web", "img")
HEAD = "https://a.espncdn.com/combiner/i?img=/i/headshots/nfl/players/full/{id}.png&w=240&h=175&scale=crop"
LOGO = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/nfl/500/{abbr}.png&w=120&h=120"


def get(url, timeout=25):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
        return r.read()


def shrink(data, width):
    """Riduce e converte in WebP, che pesa un quarto del PNG originale."""
    try:
        from PIL import Image
    except ImportError:
        return data, "png"
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=82, method=6)
    return buf.getvalue(), "webp"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="quanti giocatori del pool oltre alle rose")
    a = ap.parse_args()
    with open(os.path.join(BUILD, "console.json"), encoding="utf-8") as f:
        d = json.load(f)

    wanted = {p["id"]: p["name"] for p in d["pool"] if p.get("own")}
    if a.top:
        for p in sorted(d["pool"], key=lambda p: p["rank"])[: a.top]:
            wanted.setdefault(p["id"], p["name"])
    teams = sorted({p["nfl"] for p in d["pool"] if p.get("nfl") and p["nfl"] != "FA"})

    os.makedirs(os.path.join(IMG, "players"), exist_ok=True)
    os.makedirs(os.path.join(IMG, "teams"), exist_ok=True)
    images = {"players": {}, "teams": {}}
    ok = skipped = failed = 0

    for pid, name in wanted.items():
        dest = os.path.join(IMG, "players", f"{pid}.webp")
        if os.path.exists(dest):
            skipped += 1
        else:
            try:
                data, ext = shrink(get(HEAD.format(id=pid)), 240)
                with open(dest, "wb") as f:
                    f.write(data)
                ok += 1
            except Exception:                     # un giocatore senza foto non ferma il resto
                failed += 1
                continue
        with open(dest, "rb") as f:
            images["players"][str(pid)] = "data:image/webp;base64," + base64.b64encode(f.read()).decode()

    for abbr in teams:
        dest = os.path.join(IMG, "teams", f"{abbr}.webp")
        if not os.path.exists(dest):
            try:
                data, ext = shrink(get(LOGO.format(abbr=abbr.lower())), 120)
                with open(dest, "wb") as f:
                    f.write(data)
            except Exception:
                continue
        with open(dest, "rb") as f:
            images["teams"][abbr] = "data:image/webp;base64," + base64.b64encode(f.read()).decode()

    out = os.path.join(BUILD, "console-assets", "images.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(images, f, separators=(",", ":"))
    print(f"foto: {ok} scaricate, {skipped} già presenti, {failed} senza immagine")
    print(f"loghi: {len(images['teams'])} squadre")
    print(f"{out}: {os.path.getsize(out)/1024:.0f} KB")


if __name__ == "__main__":
    sys.exit(main())
