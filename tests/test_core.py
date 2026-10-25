"""Unit tests for the pure functions in expressway_watch.core (no network, synthetic data)."""
import datetime as dt
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from expressway_watch.core import (  # noqa: E402
    classify, composite_is_current, finalize, first_period, indices, make_segments, order_route,
    quarter_end, scene_list_is_complete, swir_step_paved, zone_rasters,
)


# ---------- alignment ----------

def test_order_route_chains_unordered_pieces():
    ways = gpd.GeoDataFrame({"oneway": [None, None]},
                            geometry=[LineString([(5000, 0), (10000, 0)]), LineString([(0, 0), (5000, 0)])])
    assert order_route(ways).length == pytest.approx(10000)


def test_order_route_does_not_come_back_on_opposite_carriageway():
    # out along y=0, a terminal loop, then back along y=40 (the other carriageway)
    ways = gpd.GeoDataFrame({"oneway": ["yes"] * 3}, geometry=[
        LineString([(0, 0), (10000, 0)]),
        LineString([(10000, 0), (10300, 150), (10000, 40)]),
        LineString([(10000, 40), (0, 40)]),
    ])
    assert order_route(ways).length == pytest.approx(10000)


def test_make_segments_chainage():
    segs = make_segments(LineString([(0, 0), (10000, 0)]), seg_km=2.0, buffer_m=35, core_m=20)
    assert len(segs) == 5
    assert list(segs.km_start) == [0, 2, 4, 6, 8]
    assert segs.core.iloc[0].area < segs.geometry.iloc[0].area   # carriageway strip inside corridor


# ---------- pixel classes ----------

def _pixel(blue, green, red, nir, swir):
    return xr.Dataset({k: (("y", "x"), np.array([[v]], dtype="float32"))
                       for k, v in dict(blue=blue, green=green, red=red, nir=nir, swir16=swir).items()})


@pytest.mark.parametrize("bands, expected", [
    ((0.04, 0.07, 0.05, 0.35, 0.18), 1),   # vegetation
    ((0.12, 0.15, 0.18, 0.24, 0.32), 2),   # bright bare earth
    ((0.08, 0.09, 0.10, 0.12, 0.14), 3),   # dark bituminous surface
])
def test_classify(bands, expected):
    assert int(classify(indices(_pixel(*bands))).values[0, 0]) == expected


# ---------- stage logic ----------

def _row(p, **kw):
    base = dict(seg_id=0, period=p, valid_frac=1.0, vegetation=0.9, bare_soil=0.0, paved=0.0,
                water=0.0, other=0.0, d_ndvi=0.0, paved_core=0.0, swir_bare_core=np.nan)
    base.update(kw)
    return base


def test_crop_harvest_is_not_construction():
    # corridor bare but so is the control ring (d_ndvi ~ 0) -> harvest, not earthwork
    df = finalize([_row("2021Q1"), _row("2021Q2", vegetation=0.3, bare_soil=0.6, d_ndvi=0.01)])
    assert set(df.stage) == {"Not started"}


def test_progress_is_monotone_after_earthwork():
    rows = [_row("2022Q1"), _row("2022Q4", d_ndvi=-0.5, bare_soil=0.9), _row("2023Q1", d_ndvi=-0.5, bare_soil=0.9),
            _row("2023Q3", d_ndvi=0.0, vegetation=0.8)]            # verges green up in monsoon
    df = finalize(rows)
    assert df.stage.tolist() == ["Not started"] + ["Earthwork / active"] * 3


def test_swir_step_marks_paving():
    swir = [np.nan, 0.38, 0.40, 0.33, 0.24, 0.22, 0.22]
    per = ["2022Q2", "2022Q4", "2023Q1", "2024Q1", "2024Q4", "2025Q1", "2025Q2"]
    rows = [_row(p, d_ndvi=-0.5 if i else 0.0, bare_soil=0.9 if i else 0.0, swir_bare_core=s)
            for i, (p, s) in enumerate(zip(per, swir))]
    df = finalize(rows)
    assert first_period(df, "Paved / near-complete").iloc[0] == "2024Q4"
    assert df.stage.iloc[-1] == "Paved / near-complete"


def test_swir_step_ignores_monsoon_only_dip():
    g = pd.DataFrame({"period": ["2023Q1", "2023Q3", "2024Q3"],
                      "stage_raw": ["Earthwork / active"] * 3,
                      "swir_bare_core": [0.40, 0.25, 0.25]})       # both dips in Q3 (wet soil)
    assert not swir_step_paved(g).any()


def test_zone_rasters_shapes():
    from rasterio.transform import from_origin
    segs = make_segments(LineString([(500, 0), (1500, 0)]), seg_km=0.5, buffer_m=35, core_m=20)
    corr, ring, core = zone_rasters(segs, (100, 200), from_origin(0, 500, 10, 10))
    assert corr.shape == ring.shape == core.shape == (100, 200)
    assert not ((corr > 0) & (ring > 0)).any()   # control ring never overlaps the road corridor


def test_swir_step_needs_a_dry_season_quarter():
    # dark only in Q3 + Q4 (monsoon / post-monsoon moisture), bright again in dry Q1 -> not paving
    g = pd.DataFrame({"period": ["2023Q2", "2023Q3", "2023Q4", "2024Q1"],
                      "stage_raw": ["Earthwork / active"] * 4,
                      "swir_bare_core": [0.42, 0.28, 0.28, 0.38]})
    assert not swir_step_paved(g).any()


def test_single_quarter_earthwork_blip_is_ignored():
    rows = [_row("2021Q3"), _row("2021Q4", d_ndvi=-0.26), _row("2022Q1"), _row("2022Q2"), _row("2022Q3"), _row("2022Q4")]
    df = finalize(rows)
    assert "Earthwork / active" not in set(df.stage)


def test_swir_dip_that_climbs_back_is_not_paving():
    # real shape from Delhi-Katra km 18-20: dark in 2022, then back up near the earthwork peak for years
    per = ["2022Q1", "2022Q2", "2022Q3", "2022Q4", "2023Q1", "2023Q2", "2023Q3", "2023Q4",
           "2024Q1", "2024Q2", "2024Q3", "2025Q1", "2025Q2"]
    sw = [0.17, 0.34, 0.13, 0.18, 0.21, 0.27, 0.18, 0.28, 0.25, 0.33, 0.21, 0.26, 0.30]
    g = pd.DataFrame({"period": per, "stage_raw": ["Earthwork / active"] * len(per), "swir_bare_core": sw})
    assert not swir_step_paved(g).any()


def test_swir_drop_that_lasts_is_paving():
    g = pd.DataFrame({"period": ["2022Q2", "2022Q3", "2022Q4", "2023Q1", "2023Q2", "2023Q3", "2023Q4"],
                      "stage_raw": ["Earthwork / active"] * 7,
                      "swir_bare_core": [0.34, 0.33, 0.20, 0.19, 0.20, 0.21, 0.20]})
    assert swir_step_paved(g).tolist() == [False, False, True, True, True, True, True]


# ---------- saved imagery: refetch what was saved too early ----------

def test_quarter_end():
    assert quarter_end("2026Q3") == dt.date(2026, 9, 30)
    assert quarter_end("2024Q1") == dt.date(2024, 3, 31)


def test_scene_list_searched_before_the_end_date_is_searched_again():
    rec = {"start": "2020-01-01", "end": "2026-09-30", "searched_on": "2026-09-24"}
    assert not scene_list_is_complete(rec, "2020-01-01", "2026-09-30")
    assert scene_list_is_complete({**rec, "searched_on": "2026-10-21"}, "2020-01-01", "2026-09-30")


def test_scene_list_without_a_record_or_for_other_dates_is_searched_again():
    assert not scene_list_is_complete(None, "2020-01-01", "2026-09-30")
    rec = {"start": "2020-01-01", "end": "2026-09-30", "searched_on": "2026-10-21"}
    assert not scene_list_is_complete(rec, "2020-01-01", "2026-12-31")     # a new quarter was added


def test_composite_made_before_its_quarter_ended_is_rebuilt():
    days = ["2026-08-15", "2026-09-29"]
    assert not composite_is_current("2026Q3", days, saved={"built_on": "2026-09-24", "days": days})
    assert composite_is_current("2026Q3", days, saved={"built_on": "2026-10-21", "days": days})


def test_composite_from_other_days_is_rebuilt():
    saved = {"built_on": "2026-10-21", "days": ["2026-08-15", "2026-09-10"]}
    assert not composite_is_current("2026Q3", ["2026-08-15", "2026-09-29"], saved=saved)


def test_old_composite_without_a_record_is_judged_by_its_file_date():
    assert composite_is_current("2026Q2", ["2026-05-02"], built_on=dt.date(2026, 9, 24))
    assert not composite_is_current("2026Q3", ["2026-09-10"], built_on=dt.date(2026, 9, 24))
    assert not composite_is_current("2026Q3", ["2026-09-10"])
