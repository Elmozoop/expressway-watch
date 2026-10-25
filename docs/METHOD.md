# Method

## 1. Alignment and segments
- OpenStreetMap ways named after the expressway are downloaded through Overpass. Slip roads (`*_link`) are dropped.
- Dual carriageways appear as two one-way lines, so the chaining step (`order_route`) follows only one of them:
  - one-way pieces are never reversed
  - U-turns are rejected
  - any piece that runs within 100 m of the chain built so far is treated as the opposite carriageway and skipped
- km 0 is set to the end nearest `ROUTE_START`, the Meerut end for the Ganga Expressway.
- The line is cut into segments of `SEG_KM` (2 km). Each segment has three zones:

| Zone | Size | Purpose |
|---|---|---|
| Corridor | ±35 m | where construction happens |
| Carriageway strip | ±20 m | where the pavement is, used for paving detection |
| Control ring | 150–400 m either side | farmland that construction doesn't touch, used to cancel crop cycles and seasons |

## 2. Imagery
- **Data:** Sentinel-2 L2A, scenes with less than 30% cloud cover, 2020 onwards.
- **Scene selection:** in each quarter, the `BEST_PER_QUARTER` (2) days with the least cloud are kept.
- **Cloud masking:** pixels are kept only if the scene classification layer (SCL) marks them 2, 4, 5, 6 or 7. That removes clouds, shadows and snow.
- **Reflectance correction:** processing baseline 04.00 and later adds +1000 to stored values. This is removed item by item, using `s2:processing_baseline`, unless the catalogue has already done it (`earthsearch:boa_offset_applied`).
- **Compositing:** the kept days are combined into a per-pixel median on a fixed 10 m grid in UTM. Band 11 (20 m) is resampled bilinearly.

## 3. Pixel classes (`classify`)
| Class | Rule |
|---|---|
| vegetation | NDVI ≥ 0.30 |
| bare earth | NDVI < 0.20 and not dark |
| dark sealed surface | NDVI < 0.20, NIR < 0.20 and SWIR < 0.20 |
| water | NDWI > 0.10 |

The fixed "dark surface" rule turned out to be too strict on real data: new asphalt measured SWIR 0.20–0.25, because each 10 m pixel also takes in the grassy median and verges. Paving is therefore decided by the relative SWIR test in step 4, not by this class.

## 4. Stages per segment and quarter
- **d_ndvi** is the median NDVI of the corridor minus the median NDVI of the control ring.
  - A crop harvest lowers both, so d_ndvi stays near 0.
  - Construction lowers only the corridor.
- **Early clearing:** d_ndvi ≤ −0.08.
- **Earthwork / active:** d_ndvi ≤ −0.20, or bare earth ≥ 35% of the corridor with d_ndvi ≤ −0.08. It has to show up again within the next 4 valid quarters; otherwise that quarter counts as early clearing.
- **Paved (`swir_step_paved`):**
  - The signal is `swir_bare_core`, the 25th percentile of SWIR over non-vegetated pixels on the carriageway strip.
  - Once earthwork has started, a segment counts as paved when this value falls at least `swir_drop` (0.12) below that segment's own earthwork peak.
  - The drop has to be seen in 2 consecutive valid quarters, and at least one of them must be in the dry season (Q1 Jan–Mar or Q2 Apr–Jun). Monsoon and post-monsoon moisture (Q3, Q4) also darkens SWIR, so a Q3+Q4 dip alone doesn't count.
- **Clean-up (`finalize`):**
  - "Paved" seen in only a single quarter is discarded.
  - Once earthwork has been reached, a segment can't go back to an earlier stage.
- **Stalled:** earthwork in the latest `STALL_Q` (6) quarters or more, with no paving.

## 5. Validation
Stages are checked against publicly reported milestones, drawn as dashed lines on every chart:
- start of physical work
- inauguration (a piece counts as paved before it only if it was seen paved in a quarter that ended before the opening date)

The before/after images and the calibration scatter plot (Step 9 of the notebook) are for visual checks.
