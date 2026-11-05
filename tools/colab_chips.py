"""Run inside a finished Expressway Watch notebook (Colab), after the last stretch:

    import requests; exec(requests.get("https://raw.githubusercontent.com/Elmozoop/expressway-watch/main/tools/colab_chips.py").text)

Cuts a true-colour satellite chip of every 2 km piece, for a few quarters, from the composites the run saved,
into <OUT_ROOT>/chips/<stretch>/<piece>/<quarter>.jpg (small JPEGs, so they go in the results zip). The site's
before/after comparisons are picked from these. Then re-zips the results like the notebook's last cell."""
import os, glob, json, subprocess
import numpy as np, geopandas as gpd
from PIL import Image
from odc.geo.geobox import GeoBox
from rasterio.transform import rowcol

PAD_M, LONG_SIDE = 400, 400
made = 0
for sdir in sorted(glob.glob(f"{OUT_ROOT}/km*-*")):
    tag = os.path.basename(sdir)
    cache = f"{sdir}/composites_{tag}"
    segf = f"{sdir}/segments_latest.geojson"
    if not (os.path.isdir(cache) and os.path.exists(segf)):
        print(tag, "skipped (no composites or segments)"); continue
    quarters = sorted(f[:-4] for f in os.listdir(cache) if f.endswith(".npy"))
    shape = np.load(f"{cache}/{quarters[0]}.npy", mmap_mode="r").shape[1:]
    # rebuild this stretch's segments and grid exactly as the run did: its Step 3 (route, from the saved copy), then Step 4's grid
    a_, b_ = tag[2:].split("-")
    G = dict(globals()); G.update(KM_FROM=int(a_), KM_TO=int(b_), OUT_DIR=sdir, display=lambda *x, **k: None)
    step3 = open("/content/ew_pipeline.py").read().split("import pystac_client")[0] if os.path.exists("/content/ew_pipeline.py") else STEP3_SRC
    exec(step3, G)
    segs_, epsg = G["segs"], G["EPSG"]
    aoi = gpd.GeoSeries(list(segs_.ring) + list(segs_.geometry), crs=epsg).unary_union.buffer(50)
    gb = GeoBox.from_bbox(aoi.bounds, crs=f"EPSG:{epsg}", resolution=10)
    if tuple(gb.shape) != tuple(shape):
        print(tag, "skipped: grid", tuple(gb.shape), "is not the saved", tuple(shape)); continue
    want = sorted({quarters[0], *[q for q in ("2022Q2", "2023Q2", "2024Q3", "2025Q2") if q in quarters], quarters[-1]})
    import matplotlib.pyplot as plt; plt.close("all")
    for _, s in segs_.iterrows():
        bx0, by0, bx1, by1 = s.geometry.buffer(PAD_M).bounds
        r0, c0 = rowcol(gb.affine, bx0, by1); r1, c1 = rowcol(gb.affine, bx1, by0)
        r0, c0 = max(r0, 0), max(c0, 0)
        out = f"{OUT_ROOT}/chips/{tag}/{s['label'].replace(' ', '').replace('–', '-')}"
        os.makedirs(out, exist_ok=True)
        for q in want:
            a = np.load(f"{cache}/{q}.npy", mmap_mode="r")[[2, 1, 0], r0:r1, c0:c1].astype("float32").transpose(1, 2, 0)
            a = np.clip(np.nan_to_num(a) * 3.5, 0, 1) ** 0.9
            im = Image.fromarray((a * 255).round().astype("uint8"))
            k = LONG_SIDE / max(im.size)
            im = im.resize((max(1, round(im.size[0] * k)), max(1, round(im.size[1] * k))), Image.LANCZOS)
            im.save(f"{out}/{q}.jpg", quality=86, optimize=True, progressive=True)
            made += 1
    print(tag, "chips for", len(segs_), "pieces x", len(want), "quarters")
print(made, "chips made")

zip_path = f"/content/{os.path.basename(OUT_ROOT)}.zip"
if os.path.exists(zip_path): os.remove(zip_path)
subprocess.run(["zip", "-qr", zip_path, os.path.basename(OUT_ROOT), "-x", "*.npy", "*.npz", "*composites_km*"],
               cwd=os.path.dirname(OUT_ROOT), check=True)
print(f"zip ready: {zip_path} ({os.path.getsize(zip_path)/1e6:.1f} MB)")
