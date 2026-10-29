#!/usr/bin/env python3
"""Assembla la console da web/parts/ in due versioni.

  --mode artifact  → dist/console.html, file unico con i dati dentro (da pubblicare)
  --mode web       → web/index.html, che carica i dati da file esterni e si
                     aggiorna da solo chiamando il server locale (scripts/serve.py)

Le parti sono le stesse: cambia solo come arrivano i dati.
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = os.path.join(ROOT, "web", "parts")
ASSETS = os.path.join(ROOT, "data", "build", "console-assets")

ORDER = [
    "p1_head.html", "p2_ccss.html", "pA_css.html",
    "p3_plan_a.html", "p3b_topina.html", "p4_plan_b.html", "p5_plan_c.html",
    "p6_plan_d.html", "p7_plan_e.html",
    "p8_console.html", "pB_views.html", "pE_views.html", "pF_views.html",
    "pH_views.html", "pK_views.html", "pL_views.html", "pN_views.html",
    "pT_data.html", "p9_js1.html", "p10_js2.html",
    "pC_js.html", "pD_js.html", "pG_js.html", "pI_js.html", "pJ_modal.html", "pM_js.html", "pN_js.html",
]
# segnaposto nel codice  ->  file dei dati
DATA = {
    "__SEED__": "seed_draft.json",
    "__POOL__": "seed_pool.json",
    "__BUNDLE__": "bundle.json",
    "__HIST__": "history_cards.json",
    "__SCHED__": "sched.json",
    "__PICKS26__": "picks.json",
    "__TEAMCTX__": "teamctx.json",
    "__IMAGES__": "images.json",
}


def read(name):
    with open(os.path.join(PARTS, name), encoding="utf-8") as f:
        return f.read()


def assemble():
    out = []
    for name in ORDER:
        s = read(name)
        if name == "p9_js1.html":            # p9 e p10 sono un unico script
            s = s.rstrip()
            assert s.endswith("</script>")
            s = s[: -len("</script>")] + "\n"
        out.append(s)
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("artifact", "web"), default="artifact")
    a = ap.parse_args()
    html = assemble()

    if a.mode == "artifact":
        for key, fname in DATA.items():
            with open(os.path.join(ASSETS, fname), encoding="utf-8") as f:
                html = html.replace(key, f.read().strip())
        dest = os.path.join(ROOT, "dist", "console.html")
    else:
        # i dati diventano file esterni caricati prima dell'applicazione, e il
        # segnaposto diventa la variabile globale che quei file riempiono
        tags = []
        # numero di versione negli indirizzi: una pagina nuova non riusa mai dati vecchi dalla cache
        version = __import__("time").strftime("%Y%m%d%H%M%S")
        os.makedirs(os.path.join(ROOT, "web", "data"), exist_ok=True)
        for key, fname in DATA.items():
            var = key.strip("_")
            if key == "__IMAGES__":
                payload = '{"players":{},"teams":{}}'      # in locale si caricano da web/img/
            else:
                with open(os.path.join(ASSETS, fname), encoding="utf-8") as f:
                    payload = f.read().strip()
            js_name = f"{var.lower()}.js"
            with open(os.path.join(ROOT, "web", "data", js_name), "w", encoding="utf-8") as f:
                f.write(f"window.DATA_{var}={payload};\n")
            tags.append(f'<script src="data/{js_name}?v={version}"></script>')
            html = html.replace(key, f"window.DATA_{var}")
        # i tag dei dati vanno prima del primo script dell'applicazione
        anchor = "<script>window.TOPINA="
        # qui i dati si aggiornano da soli; DWR_SERVER dice se c'è serve.py dietro
        # (in locale sì, su GitHub Pages no: lì il live lo calcola il browser)
        tags.insert(0, "<script>window.DWR_LIVE=true;"
                       "window.DWR_SERVER=!/\\.github\\.io$/.test(location.hostname);</script>")
        html = html.replace(anchor, "\n".join(tags) + "\n" + anchor, 1)
        html = html.replace("</script>\n<script>\n(()=>{\n'use strict';\nconst D=window.DWR,A=window.DWR2,M=window.DWR3;",
                            "</script>\n<script>\n(()=>{\n'use strict';\nconst D=window.DWR,A=window.DWR2,M=window.DWR3;")
        html += f'\n<script src="live.js?v={version}"></script>\n'
        # guscio della pagina: nella versione artifact lo mette la piattaforma,
        # qui va scritto a mano (charset, viewport e lo stesso azzeramento)
        html = ("""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="icon" href="icon-192.png" type="image/png" sizes="192x192">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#0F1412">
<meta name="apple-mobile-web-app-title" content="War Room">
<style>
  :root{color-scheme:light dark;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
  body{margin:0;font:14px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#faf9f7}
  img{max-width:100%}
  [hidden]{display:none!important}
</style>
</head>
<body>
""" + html + """
</body>
</html>
""")
        dest = os.path.join(ROOT, "web", "index.html")

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"scritto {dest}: {os.path.getsize(dest)/1024:.0f} KB")


if __name__ == "__main__":
    sys.exit(main())
