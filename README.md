# Expressway Watch

**Tracking expressway construction progress from free satellite imagery, 2 km at a time.**

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Elmozoop/expressway-watch/blob/main/notebooks/Expressway_Watch.ipynb)

Expressway Watch takes a highway alignment, cuts it into 2 km chainage segments, and uses every quarter of Sentinel-2 imagery since 2020 to estimate what stage each segment was in: **not started → clearing → earthwork → paved**. It needs no field visits, no paid data and no login, and runs end to end in Google Colab.

**Quick links:** [one-page summary (PDF)](docs/Expressway_Watch_summary.pdf) · interactive dashboard: [`docs/dashboard.html`](docs/dashboard.html) (one self-contained file: download it and open it in any browser; to put it online, see [Deploy the dashboard](#deploy-the-dashboard)) · notebooks: [any highway](notebooks/Expressway_Watch.ipynb) · [Delhi–Amritsar–Katra preset](notebooks/Expressway_Watch_Delhi_Katra.ipynb)

Two case studies: the **Ganga Expressway** (Meerut–Prayagraj, 594 km), which opened in April 2026 and so has a known finish date to check the method against, and the **Delhi–Amritsar–Katra Expressway** (NHAI, 670 km), which is still being built.



![Construction stage by chainage along the Ganga Expressway](docs/img/whole_route_stages.png)

## Results: 7 stretches along the Ganga Expressway

I analysed 140 km of the 594 km route: seven 20 km stretches spread from Meerut to Prayagraj, one in each of seven different construction packages. That's 70 segments of 2 km.

| Stretch | Package (approx.)* | Earthwork starts (median) | Paved (median) | Median build time | Paved before opening |
|---|---|---|---|---|---|
| km 0–20 | 1 | 2022 Q4 | 2025 Q4 | 33 months | 10 / 10 |
| km 100–120 | 3 | 2022 Q3 | 2025 Q4 | 39 months | 10 / 10 |
| km 200–220 | 5 | 2022 Q3 | 2024 Q4 | 27 months | 10 / 10 |
| km 250–270 | 6 | 2022 Q3 | 2024 Q4 | 25.5 months | 10 / 10 |
| km 350–370 | 8 | 2022 Q4 | 2025 Q4 | 34.5 months | 10 / 10 |
| km 450–470 | 10 | 2023 Q1 | 2025 Q4 | 33 months | 9 / 10 |
| km 550–570 | 12 | 2023 Q1 | 2025 Q4 | 33 months | 7 / 10 |

\* Package by cumulative length along the route, from the 12 Phase-1 packages listed on [Wikipedia](https://en.wikipedia.org/wiki/Ganga_Expressway). OSM chainage can differ from official chainage by a few km.

**What the satellite timeline shows:**
- **Checked against reported dates:**
  - Earthwork starts between 2022 Q3 and 2023 Q1 almost everywhere, right after the reported start of physical work (April 2022).
  - **66 of 70 segments (94%)** show paving before the reported inauguration (29 April 2026).
- **Construction started along the whole route at about the same time.** Work didn't move from one end to the other: every package broke ground within about 6 months of the others.
- **The middle of the route finished first.** km 200–270 (packages 5–6) were paved around 2024 Q4, about a year before every other stretch sampled (around 2025 Q4). Median build time was 25.5–27 months there, against 33–39 months elsewhere.
- **The 4 misses are the model's fault, not the road's.** At km 450–452, 556–558, 564–566 and 566–568, the finished carriageway is clearly visible in the 2026 images, but the paving signal was too weak to pass the test. They're counted as misses, not as unfinished road.

![Median build time per stretch](docs/img/whole_route_build_time.png)

Paving quarters are estimates, good to about ±2 quarters. Paving has to be confirmed in a dry-season quarter, so many paving dates land on a Q4. I haven't found reported paving dates per chainage to check them against.

### The paving signal
While earthwork is going on, the exposed fill and granular layers are bright in short-wave infrared (SWIR, Sentinel-2 band 11). Once bitumen goes down, the carriageway gets much darker. Each segment is compared with its own earthwork peak, so no absolute cut-off is needed. Damp soil also darkens SWIR, so a drop only counts if it's confirmed in a dry-season quarter (January–June).

![SWIR paving indicator km 0–20](docs/img/swir_paving_indicator_km0-20.png)

### Before / after
![Before and after, km 0–2](docs/img/before_after_km0-2.png)
![Before and after, km 250–252](docs/img/before_after_km250-252.png)

### Per-stretch results
Each folder in [`results/`](results/) (`ganga_km0-20`, `ganga_km100-120`, … `ganga_km550-570`) contains:
- `segment_milestones.csv`: the first-earthwork and first-paved quarter for each segment
- `segment_quarter_stats.csv`: every metric for every segment and quarter
- `segments_latest.geojson`: can be opened in QGIS or geojson.io
- charts: stage heatmap, progress curve, paving indicator, and a before/after image

[`results/whole_route_summary.csv`](results/whole_route_summary.csv) has the table above.

## A live project: Delhi–Amritsar–Katra Expressway (NHAI)

The Ganga Expressway shows the method works on a road whose finish date is known. This one is still being built, which is where the tool is actually useful.

Six 20 km stretches were tracked along the route OpenStreetMap maps from Delhi towards Katra (about 400 km of the 670 km project), 60 pieces of 2 km in all.

![Stage of each 2 km piece along the Delhi–Amritsar–Katra Expressway](docs/img/dak_profile.png)

| Stretch | Paved | Earthwork | Not started | Earthwork began (median) | OSM tag |
|---|---|---|---|---|---|
| km 0–20 | 7/10 | 3/10 | – | 2022 Q1 | motorway |
| km 80–100 | 9/10 | 1/10 | – | 2022 Q1 | motorway |
| km 150–170 | 4/10 | 6/10 | – | 2022 Q3 | motorway |
| km 230–250 | 1/10 | 4/10 | 5/10 | 2022 Q3 | under construction |
| km 300–320 | 0/10 | 10/10 | – | 2022 Q3 | under construction |
| km 380–400 | 0/10 | 3/10 | 7/10 | 2024 Q1 | under construction |

**Progress falls away along the route.** Near Delhi, 16 of 20 pieces are paved. From km 230 onwards, almost none are: km 300–320 is entirely earthwork four years after work began, and 10 pieces (4 at km 242–250, 6 between km 380 and 394) still show no sign of work at all.

That matches what is reported: the Haryana sections are largely finished while Punjab is held up by land acquisition, with completion now put at March 2028.

**An independent check.** OpenStreetMap tags this road as *under construction* from about km 210 onward, and as an open motorway before that. The satellite timeline agrees: paving stops between km 150 and km 230. Neither source knows about the other. ([`results/dak_osm_crosscheck.csv`](results/dak_osm_crosscheck.csv))

**Where the tool is wrong:** a few pieces near Delhi read as earthwork although the road there is open, the same weakness as on the Ganga. Per-stretch results are in [`results/dak_km*/`](results/), including before/after satellite strips for every stalled piece.

## How it works

1. **Alignment.** OpenStreetMap ways for the expressway are chained into one carriageway, 594 km for the Ganga Expressway. A copy is saved in [`data/`](data/), so runs don't depend on Overpass.
2. **Segments.** The route is cut every 2 km. Each segment gets three zones:
   - a 70 m **corridor**
   - a 40 m **carriageway strip**
   - a **control ring** of untouched land 150–400 m to each side
3. **Imagery.** For each quarter, the 2 clearest Sentinel-2 L2A days are cloud-masked with the scene classification layer and combined into a median composite. Imagery comes from Microsoft Planetary Computer, with Earth Search on AWS as a fallback. Each quarter is cached as soon as it's done.
4. **Stages.**
   - **Clearing and earthwork:** the corridor loses vegetation relative to the control ring. The ring cancels out crop harvests and seasons. Earthwork has to show up again within a year, so a one-off harvest dip doesn't count.
   - **Paving:** a lasting SWIR drop on the carriageway strip, held for 2 quarters, at least one of them in the dry season (January–June).
   - **Monotone:** progress can't go backwards, so verges greening up after construction don't reset a segment.
5. **Outputs.** Progress curve, stage heatmap, paving indicator, stalled-segment list, before/after images, interactive map, CSV and GeoJSON. `EXTRA_STRETCHES` runs several stretches in one session.

More detail is in [docs/METHOD.md](docs/METHOD.md). How the method changed after checking it against real data is in [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Run it yourself

1. Click **Open in Colab** above.
2. In **Step 1**, set the stretch, for example `KM_FROM, KM_TO = 250, 270`.
3. Choose `Runtime → Run all`. About 20 minutes the first time, then a few minutes for re-runs: the notebook saves the imagery and fetches only what is new.

To add a quarter, move `END` in Step 1 to its last day (for example `"2026-12-31"`) and run all again, at least five days after that date so the last images have reached the catalogues. The notebook searches for scenes again and builds only the new quarter. It also rebuilds any quarter that was saved before it had ended, or for which clearer days have turned up since.

To try another expressway, change `EXPRESSWAY_NAME`, `SEARCH_BBOX` and `ROUTE_START`, and set `ROUTE_FILE = None` to fetch the alignment from OpenStreetMap.

## The dashboard

`tools/build_dashboard.py` builds it from `tools/highways.json`, the `results/` folders and the satellite chips in `docs/img/sat/`.

The home page explains before it asks:

- **An expressway, taken apart**: a 3D slice of road, drawn with three.js, comes apart as you scroll. The asphalt surface, binder course, base, sub-base and embankment lift off the fields one at a time, each labelled with what it is and the stage the satellite reads while it is the top layer. The slice is then rebuilt the way the satellite sees it (not started, clearing, earthwork, paved), and the camera swings overhead to the satellite's view. The layers are drawn much thicker than they are, and the page says so.
- **A satellite time-lapse** of one piece of the Ganga Expressway, 2020 to 2026, wiping from image to image with the stage the tool decided for each.
- **Pick a highway**: one card per road, with its route, status and how much is paved.
- **How to read it**: scroll through six years of that one piece. The photo, the two readings the tool takes (green cover against nearby fields, and short-wave infrared brightness) and the stage it decides move together, one quarter at a time, with the thresholds drawn on the charts.
- **The whole road, told as you scroll**: the Ganga route colours itself quarter by quarter in five chapters, from farmland to opening day. The numbers in the words follow the map.
- **Can you trust it?**: the checks against what actually happened: 66 of 70 Ganga pieces seen paved by 2026 Q1, the quarter before it opened, and on the Delhi–Katra road, OpenStreetMap's open section ends about where the satellite sees paving stop.

Each highway page:

- **Headline**: the share paved, the road laid end to end as one coloured bar, and a route map. The sticky timeline scrubs or plays every chart on the page through time.
- **Where work has stalled** (live projects): one bar per stuck stretch on a 2020–2026 time axis, from when it got stuck to today, against the reported start of work. Pieces that read as stuck where OpenStreetMap says the road is open are listed separately, as likely misses by the tool. **Did it get it right?** (finished projects) puts the reported dates next to what the satellite saw.
- **Along the route**: every tracked piece at its real distance along the road, with kilometre stones and towns, then one tile per stretch and a quarter-by-quarter grid for the stretch you pick.
- **See it for yourself**: drag-to-compare Sentinel-2 images of a finished piece and a stalled one, with the tool's stage for that exact piece in every quarter underneath.
- **Progress over time** and **Get the data** (every piece and quarter as a CSV).

It works on phones (including held sideways), in dark mode, with reduced motion, without JavaScript (a notice and the headline), and when printed. With reduced motion the opening scene is a still picture with its layers and stages listed; where there is no WebGL, it is just the lists. On a computer without a graphics card, where every 3D frame holds the page up, the scene waits for your first scroll and then runs on its plainest setting. Share links open the right highway directly (`/#delhi-amritsar-katra`).

It writes three files: `docs/index.html` (for hosting: links the satellite images, so it loads fast), `docs/dashboard.html` (the same page as one file with everything embedded, to download and open offline) and `docs/_fragment.html` (the single file without its `<html>`/`<head>` wrapper; not committed). GSAP is inlined from `tools/vendor/`; three.js is copied from there to `docs/vendor/three.min.js`, which `index.html` fetches only when the opening scene is about to be drawn (a highway page opened from a link never loads it), and is inlined into `dashboard.html`. The page needs no script CDN. **Upload `docs/vendor/` with the rest of `docs/`**, or the hosted page shows the opening scene as plain lists. `tools/test_dashboard.py` drives every screen in Chromium on a desktop, two phones and phones held sideways (359 checks, including that nothing overflows or overlaps and that the 3D model never jumps) and fails on any error. It serves the page's font from `tools/vendor/fonts/`, so it runs offline.

## Deploy the dashboard

**Netlify.** Log in at [netlify.com](https://www.netlify.com) with GitHub, choose **Add new site → Import an existing project**, pick `Elmozoop/expressway-watch`, and deploy. Leave the build settings empty: [`netlify.toml`](netlify.toml) already has them.

- It builds from `docs/` (`base = "docs"`), so Netlify doesn't try to pip-install the pipeline's `requirements.txt` at the repo root.
- The one build step, [`tools/netlify_build.sh`](tools/netlify_build.sh), turns the link-preview image into a full URL, so a link shared on WhatsApp, LinkedIn or Slack shows [`docs/og.jpg`](docs/og.jpg).
- Every push to `main` redeploys.

**GitHub Pages.** *Settings → Pages → Source: deploy from a branch → `main` / `/docs`.* Link previews won't have an image there, because the image path stays relative.

## Repository layout

```
notebooks/Expressway_Watch.ipynb   the full pipeline (generated from src/ by tools/build_notebook.py)
src/expressway_watch/core.py       geometry, pixel classes and stage logic (pure functions)
tests/test_core.py                 unit tests on synthetic data  ->  pytest
data/                              saved OSM alignments (Ganga, Delhi-Amritsar-Katra)
results/ganga_km*/                 Ganga Expressway: seven stretches
results/dak_km*/                   Delhi-Amritsar-Katra: six stretches
tools/highways.json                what the dashboard shows for each highway
tools/build_dashboard.py           builds the dashboard from tools/dashboard_template.html
tools/test_dashboard.py            browser test of the built dashboard (playwright)
tools/make_og_image.py             renders docs/og.jpg, the link-preview image
tools/cut_sat_chips.py             cuts a notebook before/after strip into chips for docs/img/sat/
tools/netlify_build.sh             Netlify's build step (see netlify.toml)
tools/vendor/                      GSAP, three.js and the Overpass font, with their licences
tools/whole_route_figures.py       whole-route chart and summary table from all results/ folders
netlify.toml                       static hosting config (builds from docs/)
pytest.ini                         points pytest at tests/ (the browser test is run directly)
docs/                              dashboard, method notes, changelog, figures, docs/img/sat/ satellite chips,
                                   docs/vendor/ the page's copy of three.js
```

## Limitations

- **Resolution:** Sentinel-2 pixels are 10 m, so lanes, bridges and other structures can't be resolved individually. Stages describe a 2 km segment as a whole.
- **Monsoon gaps:** monsoon quarters are cloudy, and gaps are filled from the previous quarter.
- **Pavement type:** paving detection assumes bituminous (asphalt) pavement. Concrete pavement is bright and would need a different signal.
- **Chainage:** this follows the OpenStreetMap line, starting at the Meerut end. It may differ from official NHAI/UPEIDA chainage by a few km.
- **Paving dates:** paving quarters are estimates, good to about ±1–2 quarters:
  - Short-wave infrared also changes with soil moisture and dust through the seasons.
  - At 10 m, the "paved" signal can't separate the upper granular layers from the bitumen itself.
- **Status:** these are independent estimates, not official progress figures.

## Roadmap

- [x] Second validation stretch (km 250–270)
- [ ] Sentinel-1 radar to fill monsoon gaps
- [x] Seven stretches across the route (140 km, 7 packages)
- [ ] Stronger paving signal, to fix the 4 missed segments
- [ ] Whole-route run (594 km) with a stalled-segment report
- [x] An expressway still under construction (Delhi–Amritsar–Katra)
- [ ] More live projects, refreshed every quarter

## Data and credits

- **Imagery:** Copernicus Sentinel-2 data (ESA), via [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/) and [Earth Search](https://earth-search.aws.element84.com/v1).
- **Alignment:** © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL.
- **Reported milestones:** [Ganga Expressway, Wikipedia](https://en.wikipedia.org/wiki/Ganga_Expressway).

Built by **Yash** ([@Elmozoop](https://github.com/Elmozoop)). Code is MIT licensed; see [LICENSE](LICENSE).
