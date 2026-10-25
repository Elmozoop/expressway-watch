"""Build the dashboard from tools/highways.json, the results/ folders, the satellite chips in
docs/img/sat/ and tools/dashboard_template.html.

    python tools/build_dashboard.py

Writes docs/index.html (served at "/" by Netlify or GitHub Pages; links to the satellite images in
docs/img/sat/, and fetches three.js from docs/vendor/, which it copies there from tools/vendor/),
docs/dashboard.html (the same page as one self-contained file, images and three.js embedded, for
downloading and opening anywhere) and docs/_fragment.html (the single-file page without its
<html>/<head>/<body> shell, for hosts that add their own). GSAP is inlined into both pages."""
import base64, datetime, glob, json, os, pathlib, re, shutil, sys
import numpy as np, pandas as pd, geopandas as gpd
from PIL import Image
from shapely.geometry import Point, LineString
from shapely.ops import substring
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from expressway_watch.core import order_route

STAGES = ["No data", "Not started", "Early clearing", "Earthwork / active", "Paved / near-complete"]
STUCK_QUARTERS = 12          # a piece still in earthwork after this many quarters (3 years) counts as stalled
q2i = lambda q: int(q[:4]) * 4 + int(q[-1]) - 1
pretty = lambda q: q[:4] + " " + q[4:]
WORDS = "zero one two three four five six seven eight nine".split()

def ll(g, crs):
    return [[round(x, 4), round(y, 4)] for x, y in gpd.GeoSeries([g], crs=crs).to_crs(4326).iloc[0].coords]

def current_run(row, periods):
    """Stage in the latest quarter, how many quarters it has lasted, and the quarter it began."""
    stage, n = row[-1][0], 0
    for v, _ in reversed(row):
        if v != stage:
            break
        n += 1
    return stage, n, periods[len(row) - n]

def osm_map(hw):
    """Share of each stretch that OpenStreetMap tags as under construction (live projects with a cross-check)."""
    if not hw.get("osm_check"):
        return {}
    return {"km" + r.stretch.split(" ")[1].replace("–", "-"): float(str(r.osm_under_construction).rstrip("%")) / 100
            for _, r in pd.read_csv(ROOT / hw["osm_check"]).iterrows()}

def stretch_note(hw, tag, n_unpaved, osm):
    """The note under a stretch's grid. With an OSM cross-check, the 'likely a miss' note only goes where
    OSM says the road is open; where OSM says under construction, say that instead."""
    o = osm.get(tag)
    if o is None:
        return hw.get("segnote") if n_unpaved else None
    if o >= .5:
        return "OpenStreetMap also maps this stretch as under construction."
    return hw.get("segnote") if n_unpaved else None

def stall_list(hw, segs, stretches, periods):
    """Groups of neighbouring pieces that are stuck, as of the latest quarter (live projects only).
    kind: "earthwork" (in earthwork for STUCK_QUARTERS or more), "none" (no earthwork yet), or
    "miss" (reads as stuck, but OpenStreetMap maps the road there as open, so the tool is the likelier culprit)."""
    if not hw.get("live"):
        return None
    osm, out = osm_map(hw), []
    for st in stretches:
        ss = [s for s in segs if s["stretch"] == st["id"]]
        cur = None
        for i, s in enumerate(ss):
            stage, n, since = current_run(s["row"], periods)
            kind = "earthwork" if stage == 3 and n >= STUCK_QUARTERS else "none" if stage in (1, 2) else None
            if kind is None:
                continue
            if cur and cur["kind"] == kind and i - cur["last"] <= 2:      # allow one different piece inside a group
                cur["last"], cur["n"] = i, cur["n"] + 1
                if kind == "earthwork" and q2i(since) < q2i(cur["since"]):
                    cur["since"] = since
            else:
                cur = dict(kind=kind, stretch=st["id"], first=i, last=i, n=1, since=since if kind == "earthwork" else None)
                out.append(cur)
            cur["_ss"] = ss
    for g in out:
        ss = g.pop("_ss")
        a = ss[g.pop("first")]["label"].split(" ")[1].split("–")[0]
        b = ss[g.pop("last")]["label"].split("–")[1]
        g["km"], g["osm"] = f"km {a}–{b}", osm.get(g["stretch"])
        if g["osm"] is not None and g["osm"] < 0.5:
            g["kind"] = "miss"
    return out

def load_places(hw, inline):
    """Satellite chips for the before/after comparisons: docs/img/sat/<place id>/<quarter>.jpg.
    inline=True embeds them in the page (a single file that works offline); otherwise the page links
    to the image files, so a browser only downloads the ones it shows."""
    out = []
    for p in hw.get("places", []):
        d = ROOT / "docs/img/sat" / p["id"]
        files = sorted(d.glob("*.jpg"))
        if not files:
            raise SystemExit(f"no satellite chips in {d}")
        imgs = {f.stem: ("data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode() if inline
                         else f"img/sat/{p['id']}/{f.name}") for f in files}
        for q in (p["before"], p["after"], p.get("hero_after")):
            if q and q not in imgs:
                raise SystemExit(f"missing satellite chip {d}/{q}.jpg")
        w, h = Image.open(files[0]).size
        # quarters whose image has visible cloud (bright white patches), so the page can say so
        cloudy = [f.stem for f in files if (np.asarray(Image.open(f).convert("RGB")) > 225).all(axis=2).mean() > .005]
        out.append({**p, "imgs": imgs, "w": w, "h": h, "cloudy": cloudy})
    return out

def explainer(hw, periods, segs):
    """The two readings the tool takes for one piece, every quarter, for the 'how to read it' section."""
    ex = hw.get("explainer")
    if not ex:
        return None
    d = pd.read_csv(ROOT / ex["results"] / "segment_quarter_stats.csv")
    g = d[d.label == ex["piece"]].set_index("period")
    if g.empty:
        raise SystemExit(f"explainer piece {ex['piece']} not found in {ex['results']}")
    def series(col):
        return [round(float(g.loc[p, col]), 3) if p in g.index and g.loc[p, "valid_frac"] >= .3 and pd.notna(g.loc[p, col]) else None
                for p in periods]
    stage = [v for v, _ in next(s for s in segs if s["label"] == ex["piece"])["row"]]
    swir = series("swir_bare_core")
    ew = next(i for i, v in enumerate(stage) if v >= 3)
    pv = next((i for i, v in enumerate(stage) if v == 4), len(stage) - 1)
    peak, peak_i = max((swir[i], i) for i in range(ew, pv + 1) if swir[i] is not None)
    return dict(hw=hw["id"], piece=ex["piece"], place=ex["place"], where=ex.get("where", ""), steps=ex["steps"],
                dndvi=series("d_ndvi"), swir=swir, stage=stage, peak=round(peak, 3), peakI=peak_i,
                threshold=round(peak - .12, 3), clear=-.08, work=-.20)

def checks(hw, segs, periods):
    """Reported dates next to what the satellite saw (finished projects)."""
    nb = lambda q: q[:4] + "\u00a0" + q[4:]                  # "2026 Q2" never splits across two lines
    def later(q, reported):                                     # how far the satellite date is from the reported one
        n = q2i(q) - q2i(reported)
        if n == 0:
            return "the same quarter as reported"
        k = abs(n); w = WORDS[k] if k < len(WORDS) else str(k)
        return f"{w} quarter{'s' if k > 1 else ''} {'after' if n > 0 else 'before'} the reported date"
    out = []
    for c in hw.get("checks", []):
        if c["measure"] == "earthwork_median":
            first = sorted(next(i for i, (v, _) in enumerate(s["row"]) if v >= 3) for s in segs if any(v >= 3 for v, _ in s["row"]))
            q = periods[first[len(first) // 2]]                 # by this quarter, at least half of the pieces show earthwork
            out.append(dict(label=c["label"], reported=c["reported"], seen=f"Earthwork on half of the {len(first)} pieces by {nb(q)}",
                            detail=later(q, c["quarter"]) if c.get("quarter") else ""))
        elif c["measure"] == "paved_by":
            i = periods.index(c["quarter"]); n = sum(1 for s in segs if s["row"][i][0] == 4)
            seen = f"{n} of {len(segs)} pieces paved by {nb(c['quarter'])}" + (", before it opened" if c.get("before_opening") else "")
            out.append(dict(label=c["label"], reported=c["reported"], seen=seen,
                            detail=f"{round(100 * n / len(segs))}% of the tracked road", n=n, of=len(segs),
                            q=nb(c["quarter"]), before=bool(c.get("before_opening"))))
    return out

def build(hw):
    if "results" not in hw:
        return {k: v for k, v in hw.items()}
    w = gpd.read_file(ROOT / hw["route_file"]); lon, lat = w.union_all().centroid.coords[0]
    epsg = 32600 + int((lon + 180) // 6) + 1
    r = order_route(w.to_crs(epsg), max_gap_m=hw.get("max_gap_km", 3) * 1000)
    p0 = gpd.GeoSeries([Point(hw["route_start"])], crs=4326).to_crs(epsg).iloc[0]
    if p0.distance(Point(r.coords[-1])) < p0.distance(Point(r.coords[0])):
        r = LineString(r.coords[::-1])
    periods = [str(p) for p in pd.period_range("2020Q1", "2026Q3", freq="Q")]
    segs, stretches, osm = [], [], osm_map(hw)
    folders = sorted(glob.glob(str(ROOT / hw["results"])), key=lambda f: int(f.split("_km")[-1].split("-")[0]))
    for f in folders:
        tag = pathlib.Path(f).name.split("_")[-1]
        d = pd.read_csv(f"{f}/segment_quarter_stats.csv"); ms = pd.read_csv(f"{f}/segment_milestones.csv")
        latest = []
        for sid, g in d.groupby("seg_id"):
            g = g.set_index("period"); last = 0; row = []
            for p in periods:
                v = STAGES.index(g.stage[p]) if p in g.index else 0
                if v == 0: row.append([last, 1])
                else: row.append([v, 0]); last = v
            a, b = float(g.km_start.iloc[0]), float(g.km_end.iloc[0])
            segs.append(dict(stretch=tag, label=g.label.iloc[0], row=row, line=ll(substring(r, a * 1000, b * 1000), epsg)))
            latest.append(row[-1][0])
        med = lambda s: sorted(s.dropna())[len(s.dropna()) // 2] if s.notna().any() else None
        m = [3 * (q2i(p) - q2i(e)) for e, p in zip(ms.first_earthwork, ms.first_paved) if isinstance(p, str) and isinstance(e, str)]
        n_unpaved = sum(1 for v in latest if v != 4)
        stretches.append(dict(id=tag, label="km " + tag[2:].replace("-", "–"), pkg=hw.get("packages", {}).get(tag),
                              ew=med(ms.first_earthwork), pv=med(ms.first_paved), months=float(np.median(m)) if m else None,
                              latest=int(np.bincount(latest).argmax()),
                              note=stretch_note(hw, tag, n_unpaved, osm)))
    share = [[sum(1 for s in segs if s["row"][i][0] == k) for k in range(5)] for i in range(len(periods))]
    towns = [[n, ll(LineString([r.interpolate(km * 1000), r.interpolate(km * 1000 + 5)]), epsg)[0]] for n, km in hw.get("towns_km", [])]
    out = {k: v for k, v in hw.items() if k not in ("results", "route_file", "route_start", "packages", "towns_km", "max_gap_km", "places", "osm_check", "explainer", "checks")}
    out["towns"] = towns
    out["townsKm"] = hw.get("towns_km", [])            # chainage of each town, for the along-the-route diagram
    out["routeKm"] = round(r.length / 1000, 1)
    # fill numbers in the text from the data, so the words can never disagree with the charts
    def fill(t):
        t = re.sub(r"\{q:(\d{4}Q\d)\}", lambda m: pretty(m.group(1)), t)
        return re.sub(r"\{p(\d):(\d{4}Q\d)\}", lambda m: str(round(100 * share[periods.index(m.group(2))][int(m.group(1))] / len(segs))), t)
    for c in out.get("story", []):
        c["text"] = fill(c["text"])
    for k in ("missText", "context", "intro"):
        if out.get(k):
            out[k] = fill(out[k])
    out.update(route=ll(r.simplify(150), epsg), segs=segs, stretches=stretches, periods=periods, share=share,
               misses=[s["label"] for s in segs if s["row"][-1][0] != 4],
               stalls=stall_list(hw, segs, stretches, periods), checks=checks(hw, segs, periods))
    return out, explainer(hw, periods, segs)

def hero_stats(data):
    ready = [h for h in data if h.get("segs")]
    n = len(ready)
    stats = [(sum(len(h["segs"]) for h in ready) * 2, " km", f"tracked on {WORDS[n] if n < 10 else n} expressways"),
             (max(len(h["periods"]) for h in ready), "", "quarters of satellite images")]
    for h in ready:
        if h.get("validation"):
            q, label = h["validation"]
            stats.append((round(100 * h["share"][h["periods"].index(q)][4] / len(h["segs"])), "%", label))
            break
    return "".join(f'<div><b data-to="{v}" data-suf="{s}">{v}{s}</b><span>{t}</span></div>' for v, s, t in stats)

highways = json.load(open(ROOT / "tools/highways.json"))
built_hw = [build(h) for h in highways]
data = [b[0] if isinstance(b, tuple) else b for b in built_hw]
EXPLAIN = next((b[1] for b in built_hw if isinstance(b, tuple) and b[1]), None)
built = os.environ.get("EW_BUILD_DATE") or datetime.date.today().strftime("%-d %B %Y")
gsap = "\n".join(f"<script>\n{(ROOT / 'tools/vendor' / f).read_text().strip()}\n</script>" for f in ("gsap.min.js", "ScrollTrigger.min.js"))
template = (ROOT / "tools/dashboard_template.html").read_text()

def render(inline):
    images = {h["id"]: load_places(h, inline) for h in highways if h.get("places")}
    # three.js draws the opening scene: inlined in the single file; the hosted page fetches docs/vendor/three.min.js
    # itself, only when the scene is about to be drawn (not on a highway page, not before a scroll where WebGL is slow)
    three = f"<script>\n{(ROOT / 'tools/vendor/three.min.js').read_text().strip()}\n</script>" if inline else ""
    html = template
    for key, val in [("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":"))),
                     ("__IMAGES__", json.dumps(images, separators=(",", ":"))),
                     ("__EXPLAIN__", json.dumps(EXPLAIN, ensure_ascii=False, separators=(",", ":"))),
                     ("__HEROSTATS__", hero_stats(data)),
                     ("__BUILT__", built),

                     ("__HWIDS__", json.dumps([h["id"] for h in data if h.get("segs")]))]:
        if key not in html:
            raise SystemExit(f"placeholder {key} missing from the template")
        html = html.replace(key, val)
    return html.replace("__GSAP__", gsap, 1).replace("__THREE__", three, 1)    # last, so library code is never scanned for placeholders

web, single = render(inline=False), render(inline=True)
(ROOT / "docs/vendor").mkdir(exist_ok=True)
shutil.copyfile(ROOT / "tools/vendor/three.min.js", ROOT / "docs/vendor/three.min.js")   # served beside index.html
(ROOT / "docs/index.html").write_text(web)             # served at "/" by Netlify / GitHub Pages; images load from docs/img/sat/
(ROOT / "docs/dashboard.html").write_text(single)      # one self-contained file, to download and open anywhere
frag = "<title>" + single.split("<title>", 1)[1]
frag = frag.replace("</head>\n<body>", "").replace("\n</body>\n</html>", "")
(ROOT / "docs/_fragment.html").write_text(frag)        # the same page without its <html>/<head>/<body> shell
print(f"index.html {len(web) // 1000} KB, dashboard.html {len(single) // 1000} KB; built {built};",
      [(h["name"], len(h.get("segs") or [])) for h in data])
