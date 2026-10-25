import nbformat as nbf

import pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
core = (ROOT / "src" / "expressway_watch" / "core.py").read_text()
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Expressway Watch
**Satellite-based construction progress tracking for Indian expressways** · [GitHub](https://github.com/Elmozoop/expressway-watch)

Pipeline: expressway alignment (OpenStreetMap) → 2 km chainage segments → quarterly cloud-free Sentinel-2 composites → per-segment construction stage (not started → clearing → earthwork → paved) → progress charts, stalled-segment list, map, CSV/GeoJSON.

**How to run:** `Runtime → Run all`. A 20 km stretch takes ~20 min the first time (imagery download); re-runs reuse the saved imagery and fetch only what is new.
Change **Step 1** to pick a different stretch or expressway.

> Stages are inferred from 10 m imagery. They are estimates to be checked against the before/after images (Step 7) — not official NHAI progress figures.
""")

code("""
# Step 0 — install (about 1 min)
!pip -q install pystac-client planetary-computer odc-stac odc-geo rioxarray folium mapclassify
""")

md("## Step 1 — Settings")
code("""
EXPRESSWAY_NAME = "Ganga Expressway"    # matched (case-insensitive) against OSM name / name:en tags
NAME_PATTERN = None                      # optional regex for the fallback OSM search, e.g. "Amritsar.{0,4}Katra"
SEARCH_BBOX = (24.0, 77.0, 30.5, 84.8)   # (south, west, north, east) area to search OSM — here Uttar Pradesh
# Alignment: a saved copy of the Ganga Expressway OSM ways lives in the repo, so no Overpass call is needed.
# Set ROUTE_FILE = None to fetch from OpenStreetMap instead, or point it at your own GeoJSON/KML line.
ROUTE_FILE = "https://raw.githubusercontent.com/Elmozoop/expressway-watch/main/data/ganga_expressway_osm.geojson"

KM_FROM, KM_TO = 0, 20      # stretch of the route to analyse (km along the OSM line; direction follows OSM)
SEG_KM   = 2.0              # chainage segment length
BUFFER_M = 35               # half-width of the road corridor analysed
RING_M   = (150, 400)       # control ring (untouched land either side) used to cancel out seasons

START, END = "2020-01-01", "2026-09-30"   # to add a quarter, move END to its last day and Run all
MAX_CLOUD = 30              # scene cloud-cover filter (%)
BEST_PER_QUARTER = 2        # clearest acquisition days kept per quarter (more = cleaner but slower)
KEEP_ON_DRIVE = False   # True -> results + imagery cache go to your Google Drive, so a disconnect loses nothing
                        #         (recommended when running several stretches; asks for Drive access once, now)
OUT_ROOT = "/content/expressway_watch_outputs"
if KEEP_ON_DRIVE:
    from google.colab import drive
    drive.mount("/content/drive")
    OUT_ROOT = "/content/drive/MyDrive/expressway_watch_outputs"
OUT_DIR = f"{OUT_ROOT}/km{KM_FROM}-{KM_TO}"   # each stretch gets its own folder
CORE_M = 20                 # half-width of the carriageway strip used to detect paving
EXTRA_STRETCHES = []          # more stretches to run after the main one, in the same session, e.g.
                              # [(200, 220), (350, 370), (450, 470), (550, 570)]  (~20 min each)
ROUTE_START = (77.74, 28.87)  # (lon, lat) near the end that should be km 0 — here the Meerut (Bijauli) end
MAX_GAP_KM = 3                # join OSM pieces across gaps up to this long (raise it for roads with unbuilt/unmapped gaps)
AUTO_STRETCHES = 0            # >0: ignore KM_FROM/EXTRA_STRETCHES and pick this many evenly spaced 20 km stretches

# Publicly reported milestones to check the satellite timeline against (drawn on the charts).
# Ganga Expressway (Wikipedia): physical work began Apr 2022; inaugurated 29 Apr 2026.
MILESTONES = {"Physical work began (reported)": "2022Q2", "Inaugurated (reported)": "2026Q2"}
""")

md("## Step 2 — Core functions (geometry, spectral rules, stage logic)")
code(core)

md("## Step 3 — Get the expressway alignment")
code("""
import os, json, time, requests, warnings
import numpy as np, pandas as pd, geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import substring
warnings.filterwarnings("ignore")
os.makedirs(OUT_DIR, exist_ok=True)

def _overpass(q, max_s=90):
    headers = {"User-Agent": "ExpresswayWatch/1.0 (student research project; Colab)", "Accept": "application/json"}
    mirrors = ["https://overpass-api.de/api/interpreter",
               "https://overpass.private.coffee/api/interpreter",
               "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
    for url in mirrors:
        t0 = time.time()
        print(f"  asking {url.split('/')[2]} ...", end=" ", flush=True)
        try:
            r = requests.post(url, data={"data": q}, headers=headers, timeout=max_s)
            r.raise_for_status()
            els = r.json()["elements"]
            print(f"ok ({time.time()-t0:.0f}s, {len(els)} ways)")
            return els
        except Exception as ex:
            print(f"failed after {time.time()-t0:.0f}s: {str(ex)[:70]}")
    return None

def fetch_osm(name, bbox):
    s, w, n, e = bbox
    bb = f"({s},{w},{n},{e})"
    # 1) fast: exact name match on roads (uses Overpass's tag index)
    q_fast = f'''[out:json][timeout:60];
    ( way["highway"]["name"="{name}"]{bb}; way["highway"]["name:en"="{name}"]{bb}; );
    out tags geom;'''
    # 2) slower fallback: case-insensitive partial match
    q_slow = f'''[out:json][timeout:80];
    way["highway"]["name"~"{NAME_PATTERN or name}",i]{bb};
    out tags geom;'''
    print("Fast exact-name query:")
    els = _overpass(q_fast, 70)
    if not els:
        print("Nothing with the exact name — trying partial match (slower):")
        els = _overpass(q_slow, 90)
    if els is None:
        raise RuntimeError("Overpass unavailable right now. Re-run this cell in a few minutes, or use ROUTE_FILE.")
    rows = []
    for el in els:
        if "geometry" not in el or len(el["geometry"]) < 2:
            continue
        t = el.get("tags", {})
        hw = t.get("highway", "")
        if "link" in hw or "link" in t.get("construction", "") or hw in ("service", "footway", "track"):
            continue
        rows.append({"osm_id": el["id"], "highway": hw, "oneway": t.get("oneway"),
                     "name": t.get("name"), "geometry": LineString([(p["lon"], p["lat"]) for p in el["geometry"]])})
    return gpd.GeoDataFrame(rows, crs=4326)

def _ask_for_route_file():
    from google.colab import files
    print("Please upload the route file (osm_Ganga_Expressway.geojson):")
    up = files.upload()
    return "/content/" + list(up)[0]

if ROUTE_FILE and ROUTE_FILE.startswith("http"):
    try:
        ways = gpd.read_file(ROUTE_FILE)
    except Exception as ex:
        print("Couldn't read the route from GitHub:", str(ex)[:80])
        ROUTE_FILE = _ask_for_route_file()
elif ROUTE_FILE and not os.path.exists(ROUTE_FILE):
    ROUTE_FILE = _ask_for_route_file()

if ROUTE_FILE:
    ways = gpd.read_file(ROUTE_FILE).to_crs(4326)
    ways = ways[ways.geom_type.isin(["LineString", "MultiLineString"])]
else:
    cache = f"{OUT_DIR}/osm_{EXPRESSWAY_NAME.replace(' ', '_')}.geojson"
    if os.path.exists(cache):
        ways = gpd.read_file(cache); print("Loaded cached OSM route:", cache)
    else:
        ways = fetch_osm(EXPRESSWAY_NAME, SEARCH_BBOX)
        if len(ways): ways.to_file(cache, driver="GeoJSON")   # re-runs won't hit Overpass again
print(len(ways), "OSM ways found")
assert len(ways), "Nothing found — check EXPRESSWAY_NAME/SEARCH_BBOX, or draw the line at geojson.io and set ROUTE_FILE."
display(ways.drop(columns="geometry").value_counts(["highway"]).rename("ways").to_frame())

lon, lat = ways.unary_union.centroid.coords[0]
EPSG = (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1
ways_utm = ways.to_crs(EPSG)
route_full = order_route(ways_utm, max_gap_m=MAX_GAP_KM * 1000)
from shapely.geometry import Point
p0 = gpd.GeoSeries([Point(ROUTE_START)], crs=4326).to_crs(EPSG).iloc[0]
if p0.distance(Point(route_full.coords[-1])) < p0.distance(Point(route_full.coords[0])):
    route_full = LineString(route_full.coords[::-1])     # make km 0 the ROUTE_START end
print(f"UTM EPSG:{EPSG} | chained route length: {route_full.length/1000:.1f} km "
      f"(sum of all OSM ways: {ways_utm.length.sum()/1000:.1f} km — dual carriageways count twice)")

if AUTO_STRETCHES and not globals().get("_auto_done"):
    _L = route_full.length / 1000
    _starts = [int(round(x / 10) * 10) for x in np.linspace(0, max(_L - 20, 0), AUTO_STRETCHES)]
    KM_FROM, KM_TO = _starts[0], _starts[0] + 20
    EXTRA_STRETCHES = [(a, a + 20) for a in _starts[1:]]
    OUT_DIR = f"{OUT_ROOT}/km{KM_FROM}-{KM_TO}"; os.makedirs(OUT_DIR, exist_ok=True)
    _auto_done = True
    print("Stretches picked automatically:", [(KM_FROM, KM_TO)] + EXTRA_STRETCHES)

if not globals().get("_overview_done"):
    # overview of the alignment (saved with the results so it can be checked later)
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 7))
    ways_utm.plot(ax=ax, color="#bbbbbb", lw=0.8)
    gpd.GeoSeries([route_full], crs=EPSG).plot(ax=ax, color="#16202a", lw=1.4)
    for a, b in [(KM_FROM, KM_TO)] + list(EXTRA_STRETCHES):
        if a < route_full.length / 1000:
            gpd.GeoSeries([substring(route_full, a * 1000, min(b, route_full.length / 1000) * 1000)], crs=EPSG).plot(ax=ax, color="#d9713b", lw=4)
            if a > 0:
                pt = route_full.interpolate(a * 1000); ax.annotate(f"km {a}", (pt.x, pt.y), xytext=(6, 6), textcoords="offset points", fontsize=8)
    s0 = Point(route_full.coords[0]); ax.plot(s0.x, s0.y, "ko"); ax.annotate("km 0", (s0.x, s0.y), xytext=(6, -12), textcoords="offset points", fontsize=8)
    ax.set_title(f"{EXPRESSWAY_NAME}: OSM ways (grey), chained route (black), analysed stretches (orange)", fontsize=8)
    ax.set_axis_off(); os.makedirs(OUT_ROOT, exist_ok=True)
    plt.savefig(f"{OUT_ROOT}/route_overview.png", dpi=130, bbox_inches="tight"); plt.show(); plt.close()
    _overview_done = True

km_to = min(KM_TO, route_full.length / 1000)
route = substring(route_full, KM_FROM * 1000, km_to * 1000)
segs = make_segments(route, SEG_KM, BUFFER_M, RING_M, crs=EPSG, core_m=CORE_M)
segs["km_start"] += KM_FROM; segs["km_end"] += KM_FROM
segs["label"] = segs.apply(lambda r: f"km {r.km_start:.0f}–{r.km_end:.0f}", axis=1)
print(len(segs), "segments between km", KM_FROM, "and", round(km_to, 1))
""")
code("""
import folium
m = folium.Map(tiles="Esri.WorldImagery")
folium.GeoJson(gpd.GeoSeries([route_full], crs=EPSG).to_crs(4326), style_function=lambda f: {"color": "#aaaaaa", "weight": 2}).add_to(m)
folium.GeoJson(segs[["label", "geometry"]].to_crs(4326), tooltip="label",
               style_function=lambda f: {"color": "#ffcc00", "weight": 2, "fillOpacity": 0.3}).add_to(m)
b = segs.to_crs(4326).total_bounds; m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
m
""")

md("## Step 4 — Find Sentinel-2 scenes and keep the clearest days per quarter\n"
   "Uses Microsoft Planetary Computer; if it rate-limits you, it waits and retries, then falls back to Earth Search (AWS). "
   "The scene list is saved and reused, unless it was searched before `END` had passed (new images take a few days to appear): "
   "then it is searched again, so a re-run picks up the newest scenes.")
code("""
import pystac_client, planetary_computer, odc.stac, pystac
from odc.geo.geobox import GeoBox

aoi_utm = gpd.GeoSeries(list(segs.ring) + list(segs.geometry), crs=EPSG).unary_union.buffer(50)
bbox_ll = gpd.GeoSeries([aoi_utm], crs=EPSG).to_crs(4326).total_bounds.tolist()
gbox = GeoBox.from_bbox(aoi_utm.bounds, crs=f"EPSG:{EPSG}", resolution=10)
print("grid", gbox.shape, "pixels at 10 m")

SOURCES = {
    "planetary":    dict(url="https://planetarycomputer.microsoft.com/api/stac/v1",
                         bands={"B02": "blue", "B03": "green", "B04": "red", "B08": "nir", "B11": "swir16"}, scl="SCL"),
    "earth-search": dict(url="https://earth-search.aws.element84.com/v1",
                         bands={"blue": "blue", "green": "green", "red": "red", "nir": "nir", "swir16": "swir16"}, scl="scl"),
}

def search(source, tries=4):
    for k in range(tries):
        try:
            cat = pystac_client.Client.open(SOURCES[source]["url"])
            return cat.search(collections=["sentinel-2-l2a"], bbox=bbox_ll, datetime=f"{START}/{END}",
                              query={"eo:cloud_cover": {"lt": MAX_CLOUD}}, limit=200).item_collection()
        except Exception as ex:
            wait = 30 * (k + 1)
            print(f"  {source}: {str(ex)[:90]} — retry in {wait}s ({k+1}/{tries})")
            time.sleep(wait)
    return None

import datetime as dt
ITEMS_CACHE = f"{OUT_DIR}/stac_items_km{KM_FROM}-{KM_TO}.json"
cached = json.load(open(ITEMS_CACHE)) if os.path.exists(ITEMS_CACHE) else None
if cached and scene_list_is_complete(cached.get("searched"), START, END):
    SOURCE, items = cached["source"], pystac.ItemCollection.from_dict(cached["items"])
    print("Loaded saved scene list:", len(items), "scenes from", SOURCE)
else:
    if cached:
        print("The saved scene list was searched before", END, "had passed, so it may miss newer scenes — searching again")
    items = None
    for SOURCE in ["planetary", "earth-search"]:
        print("Searching", SOURCE, "...")
        items = search(SOURCE)
        if items is not None and len(items):
            break
    if (items is None or not len(items)) and cached:
        SOURCE, items = cached["source"], pystac.ItemCollection.from_dict(cached["items"])
        print("Both catalogues failed, so the saved list is used and the newest scenes may be missing. Re-run later.")
    else:
        assert items is not None and len(items), "Both imagery catalogues failed — wait ~15 min and re-run this cell."
        json.dump({"source": SOURCE, "items": items.to_dict(),
                   "searched": {"start": START, "end": END, "searched_on": dt.date.today().isoformat()}},
                  open(ITEMS_CACHE, "w"))
        print(len(items), "scenes from", SOURCE)
_complete_on = dt.date.fromisoformat(END) + dt.timedelta(days=LATENCY_DAYS)
if dt.date.today() < _complete_on:
    print(f"Note: the last quarter up to {END} is not complete yet (new images take a few days to appear). "
          f"Run again on or after {_complete_on} to complete it.")
BANDS, SCL = SOURCES[SOURCE]["bands"], SOURCES[SOURCE]["scl"]

meta = pd.DataFrame([{"i": k, "day": it.datetime.date(), "cloud": it.properties["eo:cloud_cover"]}
                     for k, it in enumerate(items)])
meta["day"] = pd.to_datetime(meta["day"])
days = meta.groupby("day")["cloud"].mean().reset_index()
days["period"] = days["day"].dt.to_period("Q").astype(str)
keep_days = days.sort_values("cloud").groupby("period").head(BEST_PER_QUARTER)
plan = {p: [items[i] for i in meta[meta.day.isin(g.day)].i] for p, g in keep_days.groupby("period")}
PERIODS = sorted(plan)
print(len(PERIODS), "quarters:", PERIODS[0], "→", PERIODS[-1])
""")

md("## Step 5 — Download quarterly composites (slow, ~15 min — cached after the first run)\n"
   "Cloud/shadow pixels are removed with the Sentinel-2 scene-classification layer (SCL), then the median of the kept days is taken. "
   "Each quarter is saved as soon as it's done, so if you get rate-limited or disconnected, just re-run this cell and it continues where it stopped. "
   "A saved quarter is rebuilt if it was made before the quarter ended, or if clearer days have been found for it since.")
code("""
from tqdm.auto import tqdm
GOOD_SCL = [2, 4, 5, 6, 7]   # dark area, vegetation, not-vegetated, water, unclassified
NAMES = list(BANDS.values())
CACHE_DIR = f"{OUT_DIR}/composites_km{KM_FROM}-{KM_TO}"
os.makedirs(CACHE_DIR, exist_ok=True)

def day_offset(it):
    # Processing baseline >= 04.00 (from 25 Jan 2022) stores reflectance +1000 — remove it unless the catalogue already did.
    if it.properties.get("earthsearch:boa_offset_applied"):
        return 0
    pb = it.properties.get("s2:processing_baseline")
    if pb is not None:
        try: return 1000 if float(pb) >= 4.0 else 0
        except ValueError: pass
    return 1000 if it.datetime.date() >= pd.Timestamp("2022-01-25").date() else 0

def composite(its):
    if SOURCE == "planetary":
        its = [planetary_computer.sign(i) for i in its]
    ds = odc.stac.load(its, bands=list(BANDS) + [SCL], geobox=gbox, groupby="solar_day",
                       resampling={"*": "bilinear", SCL: "nearest"}, fail_on_error=False)
    offs = {}
    for it in its:
        offs[str(it.datetime.date())] = max(offs.get(str(it.datetime.date()), 0), day_offset(it))
    offset = xr.DataArray([offs.get(str(pd.Timestamp(t).date()), 0) for t in ds.time.values], dims="time", coords={"time": ds.time})
    ok = ds[SCL].isin(GOOD_SCL)
    out = {}
    for b, name in BANDS.items():
        v = ds[b].where((ds[b] > 0) & ok).astype("float32")
        out[name] = ((v - offset) / 10000).clip(0, 1)
    return xr.Dataset(out).median("time", skipna=True)

def plan_days(p):
    return sorted({str(it.datetime.date()) for it in plan[p]})

def is_current(p):
    # a saved quarter is reused only if it was made after the quarter ended, from the days picked now
    f, rec = f"{CACHE_DIR}/{p}.npy", f"{CACHE_DIR}/{p}.json"
    if not os.path.exists(f):
        return False
    saved = json.load(open(rec)) if os.path.exists(rec) else None
    return composite_is_current(p, plan_days(p), saved=saved, built_on=dt.date.fromtimestamp(os.path.getmtime(f)))

todo = [p for p in PERIODS if not is_current(p)]
redo = [p for p in todo if os.path.exists(f"{CACHE_DIR}/{p}.npy")]
print(len(PERIODS) - len(todo), "quarters already saved,", len(todo), "to download",
      *([f"(rebuilding {', '.join(redo)}: saved before the quarter ended, or clearer days found since)"] if redo else []))
for p in tqdm(todo):
    for k in range(3):
        try:
            c = composite(plan[p])
            np.save(f"{CACHE_DIR}/{p}.npy", np.stack([c[n].values for n in NAMES]).astype("float16"))   # (5, y, x)
            json.dump({"built_on": dt.date.today().isoformat(), "days": plan_days(p)}, open(f"{CACHE_DIR}/{p}.json", "w"))
            break
        except Exception as ex:
            msg = str(ex)[:90]
            if k < 2:
                print(f"  {p}: {msg} — retry in {45*(k+1)}s"); time.sleep(45 * (k + 1))
            else:
                print(f"  skip {p}: {msg}" + (" (keeping the earlier copy)" if os.path.exists(f"{CACHE_DIR}/{p}.npy") else ""))

STORE = {os.path.basename(f)[:-4]: np.load(f"{CACHE_DIR}/{f}") for f in sorted(os.listdir(CACHE_DIR)) if f.endswith(".npy")}
PERIODS = sorted(STORE)
print(len(PERIODS), "quarters ready")
assert PERIODS, "No quarter could be processed — check the scene search in Step 4."

def as_ds(p):
    a = STORE[p].astype("float32")
    return xr.Dataset({n: (("y", "x"), a[k]) for k, n in enumerate(["blue", "green", "red", "nir", "swir16"])})
""")

md("## Step 5b — Classify and score segments (fast — tune thresholds here and re-run from this cell)")
code("""
TH = dict(DEFAULT_TH)          # e.g. TH["paved_swir_max"] = 0.22
STAGE_KW = dict(bare_thr=0.35, paved_thr=0.25, clear_dndvi=-0.08, work_dndvi=-0.20,
                swir_drop=0.12)   # paved = SWIR falls this far below the segment's own earthwork peak
print("pixel thresholds:", TH); print("stage thresholds:", STAGE_KW)

corr_id, ring_id, core_id = zone_rasters(segs, (gbox.height, gbox.width), gbox.affine)
rows = []
for p in PERIODS:
    ix = indices(as_ds(p)); cls = classify(ix, TH)
    rows += stats_one(cls.values, ix.ndvi.values, corr_id, ring_id, p, core=core_id,
                      swir2d=ix.swir.values, low_ndvi=TH["low_ndvi"])
df = finalize(rows, **STAGE_KW).merge(segs[["seg_id", "km_start", "km_end", "label"]], on="seg_id")
df.to_csv(f"{OUT_DIR}/segment_quarter_stats.csv", index=False)
df[["seg_id", "period", "vegetation", "bare_soil", "paved_core", "d_ndvi", "stage_raw", "stage"]].tail(10)
""")

md("## Step 6 — Progress charts (checked against reported milestones)")
code("""
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
STAGE_COLORS = {"No data": "#d9d9d9", "Not started": "#4a9e5c", "Early clearing": "#e8c547",
                "Earthwork / active": "#d9713b", "Paved / near-complete": "#3b4a6b"}
rank = {s: i for i, s in enumerate(STAGE_ORDER)}
grid = df.pivot(index="seg_id", columns="period", values="stage").reindex(columns=PERIODS)
labels = segs.set_index("seg_id").loc[grid.index, "label"]

def mark_milestones(ax, ymax=None):
    for name, q in MILESTONES.items():
        if q in PERIODS:
            x = PERIODS.index(q)
            ax.axvline(x, color="#222", lw=1, ls="--")
            ax.text(x + 0.15, (ymax if ymax is not None else ax.get_ylim()[1]), name, rotation=90, va="top", fontsize=7)

fig, ax = plt.subplots(figsize=(max(8, len(PERIODS) * 0.45), max(3, len(grid) * 0.35)))
cmap = ListedColormap([STAGE_COLORS[s] for s in STAGE_ORDER])
ax.imshow(grid.apply(lambda c: c.map(rank)).values.astype(float), aspect="auto", cmap=cmap,
          norm=BoundaryNorm(np.arange(-0.5, len(STAGE_ORDER)), cmap.N), interpolation="nearest")
ax.set_yticks(range(len(grid))); ax.set_yticklabels(labels, fontsize=8)
ax.set_xticks(range(len(PERIODS))); ax.set_xticklabels(PERIODS, rotation=90, fontsize=8)
mark_milestones(ax, ymax=-0.5)
ax.set_title(f"{EXPRESSWAY_NAME}: inferred construction stage by segment and quarter")
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=STAGE_COLORS[s]) for s in STAGE_ORDER],
          labels=STAGE_ORDER, bbox_to_anchor=(1.01, 1), loc="upper left", frameon=False)
for sp in ax.spines.values(): sp.set_visible(False)
plt.tight_layout(); plt.savefig(f"{OUT_DIR}/stage_heatmap.png", dpi=160); plt.show()
""")
code("""
g = grid.replace("No data", np.nan).T.ffill().T.fillna("No data")
seg_len = (segs.set_index("seg_id").km_end - segs.set_index("seg_id").km_start).loc[g.index]
share = pd.DataFrame({s: [(seg_len[g[p] == s]).sum() / seg_len.sum() * 100 for p in PERIODS] for s in STAGE_ORDER},
                     index=PERIODS)

fig, ax = plt.subplots(figsize=(10, 4))
ax.stackplot(range(len(PERIODS)), *[share[s] for s in STAGE_ORDER], colors=[STAGE_COLORS[s] for s in STAGE_ORDER],
             labels=STAGE_ORDER, alpha=0.95)
ax.set_xticks(range(len(PERIODS))); ax.set_xticklabels(PERIODS, rotation=90, fontsize=8)
ax.set_ylabel("% of stretch length"); ax.set_ylim(0, 100); ax.margins(x=0)
mark_milestones(ax, ymax=98)
ax.set_title(f"{EXPRESSWAY_NAME} km {KM_FROM}–{km_to:.0f}: progress over time")
ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", frameon=False)
for sp in ["top", "right"]: ax.spines[sp].set_visible(False)
plt.tight_layout(); plt.savefig(f"{OUT_DIR}/progress_curve.png", dpi=160); plt.show()

first_work = first_period(df, "Earthwork / active").rename("first_earthwork")
first_paved = first_period(df, "Paved / near-complete").rename("first_paved")
milestones = segs[["seg_id", "label"]].set_index("seg_id").join([first_work, first_paved])
milestones["latest_stage"] = g[PERIODS[-1]]
milestones.to_csv(f"{OUT_DIR}/segment_milestones.csv")
milestones
""")

md("### Paving indicator (threshold-free)\nSWIR reflectance of the darkest quarter of non-vegetated pixels on the carriageway strip. "
   "Bright bare earth ≈ 0.25–0.40; bituminous surface ≈ 0.10–0.20. A lasting **step down** = the segment got paved, "
   "independent of any class threshold. Each segment is judged against its own earthwork peak: a drop of ≥ `swir_drop` (0.12) held for 2 quarters = paved.")
code("""
piv = df.pivot(index="period", columns="label", values="swir_bare_core").reindex(PERIODS)[list(segs.sort_values("km_start").label)]
fig, ax = plt.subplots(figsize=(10, 4))
for c in piv.columns:
    ax.plot(range(len(PERIODS)), piv[c].values, lw=1.2, alpha=0.8, label=c)
ax.plot(range(len(PERIODS)), piv.median(axis=1).values, color="k", lw=2.5, label="median of segments")
ax.set_xticks(range(len(PERIODS))); ax.set_xticklabels(PERIODS, rotation=90, fontsize=8)
ax.set_ylabel("SWIR (B11) reflectance"); ax.set_ylim(0.1, None); mark_milestones(ax)
ax.set_title("Carriageway surface brightness in SWIR (step down = paving)")
ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", frameon=False, fontsize=7)
for sp in ["top", "right"]: ax.spines[sp].set_visible(False)
plt.tight_layout(); plt.savefig(f"{OUT_DIR}/swir_paving_indicator.png", dpi=160); plt.show()
""")

md("### Stalled segments\nSegments that have been in earthwork for many quarters without reaching paving — the kind of list a project monitoring unit would want.")
code("""
STALL_Q = 6    # quarters (1.5 years) of earthwork without paving
rows_ = []
for sid, gdf_ in df.groupby("seg_id"):
    st = gdf_.sort_values("period")["stage"].tolist()
    n_work = sum(s == "Earthwork / active" for s in st)
    trailing = 0
    for s in reversed(st):
        if s == "Earthwork / active": trailing += 1
        elif s == "No data": continue
        else: break
    rows_.append({"seg_id": sid, "label": segs.set_index("seg_id").loc[sid, "label"],
                  "quarters_in_earthwork": n_work, "current_run": trailing,
                  "stalled": trailing >= STALL_Q})
stall = pd.DataFrame(rows_)
stall.to_csv(f"{OUT_DIR}/stalled_segments.csv", index=False)
print(f"{stall.stalled.sum()} of {len(stall)} segments flagged (earthwork for ≥ {STALL_Q} quarters, still not paved)")
stall
""")

md("## Step 7 — Before / after check (visual validation)\n"
   "One strip per segment of interest: the segment where work started first, plus every segment flagged as stalled — "
   "so a 'stalled' call can be checked against the pictures.")
code("""
from rasterio.transform import rowcol
PAD_M = 400

def strip(seg_id, fname):
    x0, y0, x1, y1 = segs.set_index("seg_id").loc[seg_id, "geometry"].buffer(PAD_M).bounds
    r0, c0 = rowcol(gbox.affine, x0, y1); r1, c1 = rowcol(gbox.affine, x1, y0)
    r0, c0 = max(r0, 0), max(c0, 0)
    def chip(p):
        a = STORE[p][[2, 1, 0], r0:r1, c0:c1].astype("float32").transpose(1, 2, 0)   # red, green, blue
        return np.clip(np.nan_to_num(a) * 3.5, 0, 1)
    pick = sorted(set([PERIODS[0], PERIODS[len(PERIODS) // 3], PERIODS[2 * len(PERIODS) // 3], PERIODS[-1]]))
    fig, axs = plt.subplots(1, len(pick), figsize=(4 * len(pick), 4))
    for ax, p in zip(np.atleast_1d(axs), pick):
        ax.imshow(chip(p)); ax.set_title(f"{p}\\n{grid.loc[seg_id, p]}", fontsize=9); ax.axis("off")
    fig.suptitle(f"{EXPRESSWAY_NAME} — {segs.set_index('seg_id').loc[seg_id, 'label']}")
    plt.tight_layout(); plt.savefig(f"{OUT_DIR}/{fname}.png", dpi=150); plt.show()

FOCUS_SEG = int(milestones["first_earthwork"].notna().idxmax()) if milestones["first_earthwork"].notna().any() else 0
strip(FOCUS_SEG, f"before_after_seg{FOCUS_SEG}")
for sid in stall[stall.stalled].seg_id.tolist()[:4]:      # evidence for each stalled segment
    if sid != FOCUS_SEG:
        strip(int(sid), f"stalled_seg{sid}")
""")

md("## Step 8 — Interactive status map + exports")
code("""
latest = segs.merge(milestones.reset_index()[["seg_id", "first_earthwork", "first_paved", "latest_stage"]], on="seg_id")
latest_ll = latest.drop(columns=["ring", "core"]).to_crs(4326)
latest_ll.to_file(f"{OUT_DIR}/segments_latest.geojson", driver="GeoJSON")

m = folium.Map(tiles="Esri.WorldImagery")
folium.GeoJson(latest_ll, tooltip=folium.GeoJsonTooltip(["label", "latest_stage", "first_earthwork", "first_paved"]),
               style_function=lambda f: {"color": STAGE_COLORS.get(f["properties"]["latest_stage"], "#d9d9d9"), "weight": 3,
                                         "fillColor": STAGE_COLORS.get(f["properties"]["latest_stage"], "#d9d9d9"), "fillOpacity": 0.7}).add_to(m)
b = latest_ll.total_bounds; m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
m.save(f"{OUT_DIR}/status_map.html")
m
""")
md("""
## Step 9 — Calibrate the pixel thresholds
Each dot is one pixel on the carriageway strip. Three quarters are shown: before construction, peak earthwork, and latest.
Paved pixels should form a cluster at **low NDVI + low SWIR** in the latest quarter that is absent before construction.
If the dotted SWIR line cuts through that cluster, change `TH["paved_swir_max"]` in Step 5b and re-run from 5b (seconds, no download).
""")
code("""
m_ = core_id > 0
bare_q = df.groupby("period")["bare_soil"].mean().idxmax()
qs = [PERIODS[0], bare_q, PERIODS[-1]]
fig, axs = plt.subplots(1, 3, figsize=(15, 4), sharex=True, sharey=True)
for ax, p in zip(axs, qs):
    ix = indices(as_ds(p))
    nd, sw = ix.ndvi.values[m_], ix.swir.values[m_]
    ax.scatter(nd, sw, s=2, alpha=0.25, color="#3b4a6b")
    ax.axvline(TH["low_ndvi"], color="#4a9e5c", ls=":"); ax.axhline(TH["paved_swir_max"], color="#d9713b", ls=":")
    ax.set_title(p); ax.set_xlabel("NDVI")
    ax.text(-0.15, 0.02, "paved zone", fontsize=8, color="#d9713b")
axs[0].set_ylabel("SWIR (B11)"); axs[0].set_xlim(-0.2, 0.9); axs[0].set_ylim(0, 0.5)
plt.tight_layout(); plt.savefig(f"{OUT_DIR}/calibration_scatter.png", dpi=150); plt.show()
""")

md("""
### What you have now
- Chainage-wise stage per quarter since 2020 (`segment_quarter_stats.csv`) and first-earthwork / first-paved per segment (`segment_milestones.csv`)
- Timeline checked against publicly reported milestones (dashed lines)
- Threshold-free paving indicator, stalled-segment list, before/after chips, interactive map

**Known limits:** 10 m pixels can't resolve lanes or structures; monsoon quarters are cloud-heavy; OSM chainage may differ from official chainage; asphalt detection assumes bituminous (not concrete) pavement.
""")


# ---------- batch mode: re-run steps 3-8 for each extra stretch ----------
_code = [c for c in cells if c.cell_type == "code"]
_PIPE = [3, 5, 6, 7, 8, 9, 10, 11, 12, 13]   # step 3, 4, 5, 5b, 6 (x2), paving, stalled, 7, 8
_pipeline_src = "\n\n# ---------------- next step ----------------\n\n".join(_code[i].source for i in _PIPE)
assert "!" not in "".join(l.lstrip()[:1] for l in _pipeline_src.splitlines()), "shell line in pipeline"
md("""
## Extra stretches (batch mode)
If you listed stretches in `EXTRA_STRETCHES` (Step 1), Steps 3–8 run again for each one here, with results in its own folder.
Allow about 20 minutes per stretch, and keep this tab open.
""")
code("%%writefile /content/ew_pipeline.py\n# Steps 3-8 of this notebook, generated automatically, re-run once per extra stretch\n" + _pipeline_src)
code("""
if EXTRA_STRETCHES:
    for KM_FROM, KM_TO in EXTRA_STRETCHES:
        OUT_DIR = f"{OUT_ROOT}/km{KM_FROM}-{KM_TO}"
        print(f"\\n==================== Stretch km {KM_FROM}–{KM_TO} ====================")
        plt.close("all")
        try:
            exec(open("/content/ew_pipeline.py").read(), globals())
        except Exception as ex:
            print(f"Stretch km {KM_FROM}–{KM_TO} failed: {ex} — carrying on with the next one")
        plt.close("all")
    print("\\nFinished:", sorted(os.listdir(OUT_ROOT)))
else:
    print("No extra stretches set in Step 1 — skipping.")
""")

md("## Download results\\nEverything in one zip (one folder per stretch), without the large imagery cache.")
code("""
# One zip with a folder per stretch, without the large imagery cache
import shutil, subprocess
zip_path = "/content/expressway_watch_outputs.zip"
if os.path.exists(zip_path): os.remove(zip_path)
subprocess.run(["zip", "-qr", zip_path, os.path.basename(OUT_ROOT), "-x", "*.npy", "*.npz", "*composites_km*"],
               cwd=os.path.dirname(OUT_ROOT), check=True)
print(f"{os.path.getsize(zip_path)/1e6:.1f} MB")
from google.colab import files; files.download(zip_path)
""")


nb = nbf.v4.new_notebook(cells=cells, metadata={"colab": {"provenance": [], "name": "Expressway_Watch.ipynb"},
                                                  "kernelspec": {"name": "python3", "display_name": "Python 3"}})
nbf.write(nb, ROOT / "notebooks" / "Expressway_Watch.ipynb")

# ---- preset: Delhi-Amritsar-Katra Expressway (NHAI, under construction) ----
import copy, re
dak = copy.deepcopy(nb)
cfg = dak.cells[[i for i, c in enumerate(dak.cells) if c.cell_type == "code"][1]]
src = cfg.source
for k, v in {
    "EXPRESSWAY_NAME": '"Delhi–Amritsar–Katra Expressway"',
    "NAME_PATTERN": '"Amritsar.{0,4}Katra"',
    "SEARCH_BBOX": "(28.4, 74.3, 33.2, 77.4)",
    "ROUTE_FILE": "None",
    "KEEP_ON_DRIVE": "True",
    "ROUTE_START": "(76.85, 28.75)",
    "MAX_GAP_KM": "25",
    "AUTO_STRETCHES": "6",
    "MILESTONES": '{"Foundation stone (reported)": "2022Q1"}',
}.items():
    src, n = re.subn(rf"^{k} = [^#\n]*", f"{k} = {v}   ", src, count=1, flags=re.M)
    assert n == 1, k
for a, b in [("area to search OSM — here Uttar Pradesh", "area to search OSM — here Haryana, Punjab and J&K"),
             ("# Alignment: a saved copy of the Ganga Expressway OSM ways lives in the repo, so no Overpass call is needed.\n", ""),
             ("near the end that should be km 0 — here the Meerut (Bijauli) end", "near the end that should be km 0 — here the Delhi end"),
             ('"/content/expressway_watch_outputs"', '"/content/expressway_watch_delhi_katra"'),
             ('"/content/drive/MyDrive/expressway_watch_outputs"', '"/content/drive/MyDrive/expressway_watch_delhi_katra"')]:
    assert a in src, a
    src = src.replace(a, b)
src = src.replace("# Ganga Expressway (Wikipedia): physical work began Apr 2022; inaugurated 29 Apr 2026.",
                  "# Delhi–Amritsar–Katra (Wikipedia): foundation stone 5 Jan 2022; Punjab delayed by land acquisition, completion now March 2028.")
cfg.source = src
dak.cells[0].source = dak.cells[0].source.replace("# Expressway Watch", "# Expressway Watch: Delhi–Amritsar–Katra Expressway (live NHAI project)", 1)
dak.metadata["colab"]["name"] = "Expressway_Watch_Delhi_Katra.ipynb"
nbf.write(dak, ROOT / "notebooks" / "Expressway_Watch_Delhi_Katra.ipynb")
print("cells:", len(cells))
