# ---- CORE: geometry + classification helpers (pure functions, no network) ----
import datetime as dt

import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, substring


def _dir(coords, at_end, span=500.0):
    """Unit direction of a polyline over its last (at_end) or first ~span metres."""
    pts = np.array(coords[::-1] if at_end else coords)
    ref, acc = pts[0], 0.0
    for q in pts[1:]:
        acc = np.linalg.norm(q - ref)
        if acc >= span:
            break
    v = (pts[0] - q) if at_end else (q - pts[0])
    n = np.linalg.norm(v)
    return v / n if n else v


def _continues(chain, c, mode):
    """True if attaching piece c keeps travelling forward (rejects U-turns onto the opposite carriageway)."""
    if mode == "tail_s":   a, b = _dir(chain, True), _dir(c, False)
    elif mode == "tail_e": a, b = _dir(chain, True), -_dir(c, True)
    elif mode == "head_e": a, b = _dir(chain, False), _dir(c, True)
    else:                  a, b = _dir(chain, False), -_dir(c, False)
    return float(np.dot(a, b)) > 0.3


def order_route(lines_gdf_utm, max_gap_m=3000):
    """Chain OSM ways into one ordered LineString.
    Oneway ways (one carriageway of a dual expressway) are never reversed, so the chain
    follows a single carriageway instead of zig-zagging between both."""
    pieces = []
    for geom, oneway in zip(lines_gdf_utm.geometry, lines_gdf_utm.get("oneway", [None] * len(lines_gdf_utm))):
        for g in (geom.geoms if geom.geom_type == "MultiLineString" else [geom]):
            pieces.append((g, str(oneway).lower() in ("yes", "true", "1")))
    pieces.sort(key=lambda p: p[0].length, reverse=True)
    chain = list(pieces[0][0].coords)
    remaining = pieces[1:]
    while remaining:
        head, tail = np.array(chain[0]), np.array(chain[-1])
        best, best_d, mode = None, np.inf, None
        for i, (p, ow) in enumerate(remaining):
            s_, e_ = np.array(p.coords[0]), np.array(p.coords[-1])
            opts = [("tail_s", np.linalg.norm(tail - s_)), ("head_e", np.linalg.norm(head - e_))]
            if not ow:
                opts += [("tail_e", np.linalg.norm(tail - e_)), ("head_s", np.linalg.norm(head - s_))]
            for m, d in opts:
                if d < best_d and _continues(chain, list(p.coords), m):
                    best, best_d, mode = i, d, m
        if best is None or best_d > max_gap_m:
            break
        piece = remaining.pop(best)[0]
        # stop if this piece runs alongside what we already have (= the opposite carriageway coming back)
        if LineString(chain).distance(piece.interpolate(0.5, normalized=True)) < 100:
            continue
        c = list(piece.coords)
        if mode == "tail_s":   chain += c
        elif mode == "tail_e": chain += c[::-1]
        elif mode == "head_e": chain = c + chain
        else:                  chain = c[::-1] + chain
    return LineString(chain)


def make_segments(route, seg_km=2.0, buffer_m=60, ring_m=(150, 400), crs=None, core_m=20):
    """Cut route into chainage segments; return corridor polygons and control rings."""
    L = route.length
    step = seg_km * 1000
    rows = []
    for i, start in enumerate(np.arange(0, L, step)):
        end = min(start + step, L)
        if end - start < step * 0.25 and i > 0:
            continue
        piece = substring(route, start, end)
        corridor = piece.buffer(buffer_m, cap_style=2)
        ring = piece.buffer(ring_m[1], cap_style=2).difference(piece.buffer(ring_m[0], cap_style=2))
        rows.append({"seg_id": i, "km_start": start / 1000, "km_end": end / 1000,
                     "geometry": corridor, "ring": ring, "core": piece.buffer(core_m, cap_style=2)})
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    gdf["ring"] = gpd.GeoSeries(gdf["ring"], crs=crs)
    gdf["core"] = gpd.GeoSeries(gdf["core"], crs=crs)
    return gdf


def indices(ds):
    """Spectral indices from a reflectance dataset (bands scaled 0-1)."""
    b, g, r, n, s1 = ds.blue, ds.green, ds.red, ds.nir, ds.swir16
    eps = 1e-6
    out = xr.Dataset({
        "ndvi": (n - r) / (n + r + eps),
        "bsi":  ((s1 + r) - (n + b)) / ((s1 + r) + (n + b) + eps),
        "ndwi": (g - n) / (g + n + eps),
        "bright": (b + g + r) / 3,
        "nir": n, "swir": s1,
    })
    return out


# land-cover classes used for stage inference
CLASSES = {0: "nodata", 1: "vegetation", 2: "bare_soil", 3: "paved", 4: "water", 5: "other"}


DEFAULT_TH = dict(veg_ndvi=0.30, low_ndvi=0.20, water_ndwi=0.10,
                  paved_swir_max=0.20, paved_nir_max=0.20)


def classify(ix, t=None):
    """Rule-based per-pixel class. Thresholds are tunable starting points, not ground truth.
    Key idea: both fresh earth and asphalt have low NDVI, but asphalt is DARK in NIR and SWIR
    (~0.10-0.18) while dry exposed soil is bright (SWIR ~0.25-0.40)."""
    t = {**DEFAULT_TH, **(t or {})}
    ndvi, ndwi = ix.ndvi, ix.ndwi
    valid = ndvi.notnull()
    low = valid & (ndvi < t["low_ndvi"])
    dark = (ix.swir < t["paved_swir_max"]) & (ix.nir < t["paved_nir_max"])
    cls = xr.where(valid, 5, 0)                       # 5 = valid but mixed/other
    cls = xr.where(valid & (ndvi >= t["veg_ndvi"]), 1, cls)
    cls = xr.where(low & ~dark, 2, cls)               # bright bare earth / fill / GSB-WMM layers
    cls = xr.where(low & dark, 3, cls)                # dark sealed surface = bituminous pavement
    cls = xr.where(valid & (ndwi > t["water_ndwi"]), 4, cls)
    return cls.astype(np.uint8)


def infer_stage(row, bare_thr=0.35, paved_thr=0.25, clear_dndvi=-0.08, work_dndvi=-0.20):
    """Map one segment/quarter to a stage. The main signal is d_ndvi = corridor NDVI minus the
    NDVI of untouched land 150-400 m away, so crop harvests (which hit both) don't look like construction."""
    if row["valid_frac"] < 0.3:
        return "No data"
    if row.get("paved_core", row["paved"]) >= paved_thr:
        return "Paved / near-complete"
    if row["d_ndvi"] <= work_dndvi or (row["bare_soil"] >= bare_thr and row["d_ndvi"] <= clear_dndvi):
        return "Earthwork / active"
    if row["d_ndvi"] <= clear_dndvi:
        return "Early clearing"
    return "Not started"


STAGE_ORDER = ["No data", "Not started", "Early clearing", "Earthwork / active", "Paved / near-complete"]


def first_period(df, stage):
    """First period each segment reached `stage` or later (monotone progress assumption)."""
    rank = {s: i for i, s in enumerate(STAGE_ORDER)}
    hit = df[df["stage"].map(rank) >= rank[stage]]
    return hit.groupby("seg_id")["period"].min()


def zone_rasters(segs, shape, transform):
    """Rasterize corridor + ring polygons to integer id grids (id = seg_id+1) on the data grid."""
    from rasterio.features import rasterize
    corr = rasterize([(g, i + 1) for i, g in zip(segs.seg_id, segs.geometry)],
                     out_shape=shape, transform=transform, fill=0, dtype="int32")
    ring = rasterize([(g, i + 1) for i, g in zip(segs.seg_id, segs.ring)],
                     out_shape=shape, transform=transform, fill=0, dtype="int32")
    ring[corr > 0] = 0   # never count road pixels as control
    core = rasterize([(g, i + 1) for i, g in zip(segs.seg_id, segs.core)],
                     out_shape=shape, transform=transform, fill=0, dtype="int32")
    return corr, ring, core


def stats_one(cls2d, ndvi2d, corr, ring, period, core=None, swir2d=None, low_ndvi=0.20):
    """Stats for ONE period: class fractions in each corridor, NDVI corridor minus control ring."""
    rows = []
    for sid in np.unique(corr[corr > 0]):
        m = corr == sid
        cv = cls2d[m]
        valid = cv > 0
        nv = int(valid.sum())
        row = {"seg_id": int(sid) - 1, "period": period, "valid_frac": nv / max(int(m.sum()), 1)}
        for code, name in CLASSES.items():
            if code:
                row[name] = float((cv[valid] == code).sum()) / max(nv, 1)
        rm = (ring == sid) & np.isfinite(ndvi2d)
        row["ndvi_corr"] = float(np.nanmedian(ndvi2d[m])) if nv else np.nan
        row["ndvi_ring"] = float(np.median(ndvi2d[rm])) if rm.any() else np.nan
        row["d_ndvi"] = row["ndvi_corr"] - row["ndvi_ring"]
        if core is not None:
            cm = (core == sid) & (cls2d > 0)
            row["paved_core"] = float((cls2d[cm] == 3).sum()) / max(int(cm.sum()), 1)
            # threshold-free paving indicator: median SWIR of non-vegetated pixels on the carriageway strip
            if swir2d is not None:
                lowm = cm & (ndvi2d < low_ndvi)
                row["swir_bare_core"] = float(np.nanpercentile(swir2d[lowm], 25)) if lowm.sum() > 5 else np.nan   # darkest quarter = road surface, not shoulders
        rows.append(row)
    return rows


def _dry(period):
    return period.endswith("Q1") or period.endswith("Q2")


def swir_step_paved(g, drop=0.12, back=2):
    """Relative paving test for one segment (rows sorted by period).
    During earthwork the exposed surface (fill, GSB, WMM) is bright in SWIR; once bitumen goes down the
    darkest non-vegetated pixels on the carriageway strip get much darker. Each segment is its own baseline:
    paved when SWIR falls >= `drop` below its earthwork peak in 2 consecutive valid quarters, at least one of
    them in the dry season (Q1 Jan-Mar or Q2 Apr-Jun). Monsoon and post-monsoon moisture (Q3, Q4) also darkens
    SWIR, so a Q3+Q4 dip alone is not accepted as paving. The drop must also last: if SWIR later climbs back
    above halfway to the earthwork peak in `back` or more quarters, the segment was not paved."""
    out = np.zeros(len(g), bool)
    sw = np.asarray(g["swir_bare_core"], dtype=float)
    started, peak, prev = False, 0.0, None
    for i, (st, s, p) in enumerate(zip(g["stage_raw"], sw, g["period"])):
        if st == "Earthwork / active":
            started = True
        if not started or not np.isfinite(s):
            continue
        peak = max(peak, s)
        hit = s <= peak - drop
        if hit and prev is not None and prev[1] and (_dry(p) or _dry(prev[2])):
            # and the drop has to last: a segment that climbs back towards its earthwork brightness
            # later was not paved (bare ground can look dark for a quarter or two)
            rest = sw[i + 1:]
            if (rest[np.isfinite(rest)] > peak - drop / 2).sum() < back:
                out[prev[0]] = out[i] = True
        prev = (i, hit, p)
    # once confirmed, the segment stays paved
    if out.any():
        out[np.argmax(out):] = True
    return out


def rank_of(stage):
    return STAGE_ORDER.index(stage)


def finalize(rows, ratchet=True, swir_drop=0.12, **stage_kw):
    """Raw per-quarter stage, then 'progress' stage:
    - Earthwork must be seen again within the next 4 valid quarters (a single harvest dip doesn't count).
    - Paved must be seen in 2 consecutive valid quarters to count (kills one-off false positives).
    - Progress is monotone: once earthwork/paving is reached, later greening of verges/embankment
      grass doesn't send a segment back to 'Not started'."""
    df = pd.DataFrame(rows)
    df["d_ndvi"] = df["d_ndvi"].fillna(0)
    df["stage_raw"] = df.apply(lambda r: infer_stage(r, **stage_kw), axis=1)
    # what each quarter would say with no paving evidence at all: the fallback when a single
    # "paved" quarter is not confirmed by its neighbour (otherwise one bright-field quarter in
    # 2020 could lock a segment into "earthwork" for years)
    no_pav = df.assign(paved=0.0, paved_core=0.0).apply(lambda r: infer_stage(r, **stage_kw), axis=1)
    df["_nopav"] = no_pav.map(lambda v: rank_of(v))
    rank = {s: i for i, s in enumerate(STAGE_ORDER)}
    out = []
    work = rank["Earthwork / active"]
    for sid, g in df.sort_values("period").groupby("seg_id"):
        g = g.copy()
        # earthwork must be seen again within the next 4 valid quarters (one year). A single harvest dip
        # doesn't count; a real site can look "not started" in one or two quarters (in the Apr-Jun harvest
        # the fields are bare too, so the corridor-vs-ring contrast vanishes) but shows up again within a year.
        r0 = g["stage_raw"].map(rank).to_numpy()
        v0 = np.where(r0 > 0)[0]
        st = g["stage_raw"].to_numpy(dtype=object).copy()
        for k, i in enumerate(v0):
            nxt = v0[k + 1:k + 5]
            if r0[i] == work and len(nxt) and not any(r0[j] >= work for j in nxt):
                st[i] = "Early clearing"
        g["_st"] = st
        if "swir_bare_core" in g and swir_drop:
            step = swir_step_paved(g.assign(stage_raw=g["_st"]), swir_drop)
            g.loc[step & (g["_st"] != "No data"), "_st"] = "Paved / near-complete"
        r = g["_st"].map(rank).to_numpy()
        g = g.drop(columns="_st")
        valid = r > 0
        pav = rank["Paved / near-complete"]
        conf = r.copy()
        vidx = np.where(valid)[0]
        for k, i in enumerate(vidx):
            if r[i] == pav:
                prev_ok = k > 0 and r[vidx[k - 1]] == pav
                next_ok = k < len(vidx) - 1 and r[vidx[k + 1]] == pav
                if not (prev_ok or next_ok):
                    conf[i] = int(g["_nopav"].to_numpy()[i])
        if ratchet:
            best = 0
            for i in range(len(conf)):
                if conf[i] > 0:
                    best = max(best, conf[i]) if best >= rank["Earthwork / active"] or conf[i] >= rank["Earthwork / active"] else conf[i]
                    conf[i] = best
        g = g.copy()
        g["stage"] = [STAGE_ORDER[i] for i in conf]
        out.append(g.drop(columns="_nopav"))
    return pd.concat(out).sort_values(["seg_id", "period"]).reset_index(drop=True)


# ---- saved imagery: when a scene list or a quarterly composite has to be fetched again ----
LATENCY_DAYS = 5    # Sentinel-2 L2A scenes usually reach the catalogues within a few days of being taken


def quarter_end(period):
    """Last day of a quarter label, e.g. "2026Q3" -> 2026-09-30."""
    return pd.Period(period, freq="Q").end_time.date()


def scene_list_is_complete(searched, start, end, latency_days=LATENCY_DAYS):
    """True if a saved scene search can be reused for the dates start..end.

    `searched` is the record saved with the list, {"start", "end", "searched_on"}; lists saved
    before this check existed have none. A list is reused only if it was searched for the same
    dates, once `end` and the catalogues' processing delay had passed, so no scene in the range
    can be missing from it.
    """
    if not searched or searched.get("start") != start or searched.get("end") != end:
        return False
    if not searched.get("searched_on"):
        return False
    done = dt.date.fromisoformat(end) + dt.timedelta(days=latency_days)
    return dt.date.fromisoformat(searched["searched_on"]) >= done


def composite_is_current(period, days, saved=None, built_on=None, latency_days=LATENCY_DAYS):
    """True if a saved quarterly composite can be reused.

    It must have been built after the quarter was over (plus the processing delay), from the
    same acquisition days that would be picked for it now. `saved` is the record written next to
    the composite, {"built_on", "days"}; a composite saved before such records existed has none,
    and is judged by `built_on` (the file's modification date) alone.
    """
    if saved:
        if sorted(saved.get("days", [])) != sorted(days):
            return False
        built_on = dt.date.fromisoformat(saved["built_on"])
    if built_on is None:
        return False
    return built_on >= quarter_end(period) + dt.timedelta(days=latency_days)
