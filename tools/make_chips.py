"""Cut the satellite chips for a before/after comparison from a notebook run's saved quarterly composites.

    python tools/make_chips.py NOTEBOOK RESULTS_ROOT STRETCH PIECE PLACE_ID QUARTER [QUARTER ...]

    e.g. python tools/make_chips.py notebooks/Expressway_Watch_Samruddhi.ipynb runs/expressway_watch_samruddhi \
             km0-20 "km 4–6" sam_km4-6 2020Q1 2022Q2 2026Q3

NOTEBOOK gives the expressway's settings and route code; RESULTS_ROOT is the run's output folder (the one with
a km<a>-<b> folder per stretch, each with its composites_km<a>-<b>/ cache of <quarter>.npy files). Writes
docs/img/sat/PLACE_ID/<quarter>.jpg: true colour, the 2 km piece plus 400 m around it, north up.
No network needed: the route comes from the run's saved OpenStreetMap file."""
import sys, os, json, pathlib, warnings
import numpy as np
from PIL import Image

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]
PAD_M, LONG_SIDE = 400, 400          # metres around the piece; output size of the longer side in pixels

def setup(notebook, results_root, stretch):
    """Run the notebook's settings, core and route cells for one stretch, offline, and return their globals."""
    nb = json.load(open(notebook, encoding="utf-8"))
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    settings, core, route = code[1], code[2], code[3]
    a, b = stretch[2:].split("-")
    root = str(results_root).replace("\\", "/")
    settings = settings.replace("KEEP_ON_DRIVE = True", "KEEP_ON_DRIVE = False")
    # the route file is in this repo: read it from disk rather than from GitHub
    settings = settings.replace("https://raw.githubusercontent.com/Elmozoop/expressway-watch/main/", ROOT.as_posix() + "/")
    g = {"display": lambda *x, **k: None, "__name__": "chips"}
    exec(settings, g)
    g.update(OUT_ROOT=root, KM_FROM=int(a), KM_TO=int(b), OUT_DIR=f"{root}/{stretch}")
    exec(core, g)
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt; plt.show = lambda *x, **k: None
    exec(route.replace("os.makedirs(OUT_DIR, exist_ok=True)", ""), g)
    return g

def chips(g, piece, place_id, quarters):
    from odc.geo.geobox import GeoBox
    import geopandas as gpd
    from rasterio.transform import rowcol
    segs, epsg = g["segs"], g["EPSG"]
    aoi = gpd.GeoSeries(list(segs.ring) + list(segs.geometry), crs=epsg).unary_union.buffer(50)
    gbox = GeoBox.from_bbox(aoi.bounds, crs=f"EPSG:{epsg}", resolution=10)       # the same grid as Step 4
    row = segs[segs.label == piece]
    if row.empty:
        raise SystemExit(f"{piece!r} not in this stretch; pieces: {list(segs.label)}")
    x0, y0, x1, y1 = row.geometry.iloc[0].buffer(PAD_M).bounds
    r0, c0 = rowcol(gbox.affine, x0, y1); r1, c1 = rowcol(gbox.affine, x1, y0)
    r0, c0 = max(r0, 0), max(c0, 0)
    cache = f"{g['OUT_DIR']}/composites_km{g['KM_FROM']}-{g['KM_TO']}"
    out = ROOT / "docs/img/sat" / place_id
    out.mkdir(parents=True, exist_ok=True)
    for q in quarters:
        a = np.load(f"{cache}/{q}.npy")[[2, 1, 0], r0:r1, c0:c1].astype("float32").transpose(1, 2, 0)   # red, green, blue
        a = np.clip(np.nan_to_num(a) * 3.5, 0, 1) ** 0.9
        im = Image.fromarray((a * 255).round().astype("uint8"))
        s = LONG_SIDE / max(im.size)
        im = im.resize((round(im.size[0] * s), round(im.size[1] * s)), Image.LANCZOS)
        im.save(out / f"{q}.jpg", quality=86, optimize=True, progressive=True)
        print(f"wrote {out.relative_to(ROOT)}/{q}.jpg {im.size}")

if __name__ == "__main__":
    nb, root, stretch, piece, place_id, *quarters = sys.argv[1:]
    chips(setup(nb, root, stretch), piece, place_id, quarters)
