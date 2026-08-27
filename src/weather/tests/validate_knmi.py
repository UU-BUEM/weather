"""Validate a provider's output against KNMI ground observations.

This is the repo's first validation against MEASURED data rather than
against another derivation of the same model.  Every other check here --
``verify_months.py``, ``compare_providers.py``, the physical-plausibility
bounds in ``docs/dni_methodology.md`` -- compares reanalysis output to
itself, to another reanalysis, or to physical law.  None of them can
detect a bias that all reanalyses share, and none can tell you whether
the numbers match reality at a specific location.

KNMI's open hourly climate API is a good reference for this repo
specifically: it is free, needs no key or registration, covers the
Netherlands densely (32 stations report global radiation), and -- the
part that matters most -- it stamps hours the SAME way COSMO-REA6 does,
so the two series align with no shift to get wrong.

Usage
-----
Validate the shipped Netherlands file::

    python -m weather.tests.validate_knmi \\
        --file data/cosmo_rea6/output/COSMO_REA6_NL_2018_annual_all_attrs.nc \\
        --year 2018

Validate a whole provider archive for one year::

    python -m weather.tests.validate_knmi --provider cosmo-rea6 --year 2018

Results are written to ``data/validation/NL/`` by default: a per-station
CSV, a summary CSV, and a Markdown report.

Reading the results
-------------------
A negative GHI bias alone does not mean the pipeline is wrong.  Two
diagnostics in this module separate a real model bias from a pipeline
defect, and both are printed automatically:

* **Bias by sky condition.**  A units or scaling error is multiplicative
  and therefore roughly constant across conditions.  A radiative-transfer
  bias is not: COSMO-REA6 measured +10.5 % under overcast skies and
  -14.2 % under clear ones in 2018.  Sign reversal across the bins is
  strong evidence the pipeline arithmetic is fine.
* **Lag correlation.**  A one-hour labelling mistake shows up as the
  correlation peaking at a non-zero lag, which no amount of bias
  inspection would reveal.

KNMI variable traps
-------------------
Two of these have bitten real analyses and are worth stating plainly:

* ``RH`` in the KNMI API is **hourly precipitation**, NOT relative
  humidity.  Relative humidity is ``U``.
* ``P`` is air pressure **reduced to mean sea level**, so it is not
  comparable with a provider's surface pressure ``PS``.  Pressure is
  therefore deliberately excluded from the comparison rather than
  reported with a large spurious bias.

Temporal semantics also differ per variable and are reported, not
silently averaged away: KNMI ``Q`` is an hourly sum and ``FH`` an hourly
mean, while ``T``/``TD``/``U`` are instantaneous at the observation time.
COSMO-REA6's fields are all instantaneous (see
``docs/dni_methodology.md`` sec 11.3), so ``T``/``T_DEW``/``RH`` compare
like for like while ``WS_10M`` does not.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)

KNMI_URL = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"

#: Provider variable -> (KNMI code, scale to provider units, note).
#: ``PS`` is absent on purpose -- see the module docstring.
VARIABLE_MAP: dict[str, tuple[str, float, str]] = {
    "GHI": ("Q", 1e4 / 3600.0,
            "KNMI hourly SUM (J/cm2) vs instantaneous W/m2"),
    "T": ("T", 0.1, "both instantaneous; KNMI at 1.50 m, provider at 2 m"),
    "T_DEW": ("TD", 0.1, "both instantaneous; KNMI at 1.50 m"),
    "RH": ("U", 1.0, "both instantaneous; KNMI code is U, not RH"),
    "WS_10M": ("FH", 0.1,
               "KNMI hourly MEAN vs instantaneous -- not like for like"),
}

DEFAULT_OUT_DIR = Path("data/validation/NL")


# ---------------------------------------------------------------------------
# KNMI access
# ---------------------------------------------------------------------------


def _post(payload: dict[str, str], timeout: int = 300) -> str:
    """POST to the KNMI API and return the raw response body."""
    data = urllib.parse.urlencode(payload).encode()
    request = urllib.request.Request(KNMI_URL, data=data)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _post_checked(payload: dict[str, str], timeout: int = 300) -> str:
    """POST and reject an HTML body.

    KNMI answers an over-large query with a 200 status and an HTML error
    page rather than a machine-readable error.  Left unchecked that
    parses to an empty frame and fails much later with an unrelated
    message, so it is caught here where the cause is obvious.
    """
    text = _post(payload, timeout=timeout)
    head = text.lstrip()[:400].lower()
    if head.startswith("<!doctype") or "<html" in head:
        raise RuntimeError(
            "KNMI returned an HTML page instead of data for "
            f"{payload.get('start')}..{payload.get('end')} "
            f"(stns={payload.get('stns')}). The query is probably too "
            "large; reduce the station list or the time span."
        )
    return text


def _parse(text: str) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    """Parse a KNMI hourly response into a frame plus station metadata.

    Returns
    -------
    frame : pandas.DataFrame
        Columns ``station`` plus one per requested KNMI code, indexed by
        the hour-ENDING UTC timestamp.  KNMI's ``HH`` runs 1..24 and
        division ``HH`` covers ``(HH-1):00`` to ``HH:00`` UT, so the
        stamp is ``date + HH hours`` -- the same convention COSMO uses.
    stations : dict
        ``{code: {"lat": .., "lon": .., "name": ..}}``.
    """
    stations: dict[str, dict[str, Any]] = {}
    header: list[str] = []
    rows: list[list[str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip()
            parts = body.split()
            # Station rows look like: "260  5.180  52.100  1.90  De Bilt"
            if len(parts) >= 5 and parts[0].isdigit() and len(parts[0]) == 3:
                with contextlib.suppress(ValueError):
                    stations[parts[0]] = {
                        "lon": float(parts[1]),
                        "lat": float(parts[2]),
                        "altitude": float(parts[3]),
                        "name": " ".join(parts[4:]),
                    }
            elif body.startswith("STN,"):
                header = [c.strip() for c in body.split(",")]
            continue
        rows.append([c.strip() for c in stripped.split(",")])

    if not header or not rows:
        return pd.DataFrame(), stations

    frame = pd.DataFrame(rows, columns=header[: len(rows[0])])
    days = pd.to_datetime(frame["YYYYMMDD"], format="%Y%m%d")
    stamps = days + pd.to_timedelta(pd.to_numeric(frame["HH"]), unit="h")
    frame = frame.drop(columns=["YYYYMMDD", "HH"])
    frame = frame.rename(columns={"STN": "station"})
    for column in frame.columns:
        if column != "station":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.index = pd.DatetimeIndex(stamps, name="time")
    return frame, stations


def fetch_knmi(
    stations: str,
    year: int,
    codes: list[str],
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    """Fetch one year of hourly KNMI data, one month per request.

    The API silently refuses a whole-year, all-stations query: instead of
    an error status it returns an HTML page, which parses to zero rows
    and would otherwise surface much later as a confusing dtype error.
    Requesting a month at a time stays well inside whatever the real
    limit is, and :func:`_post_checked` rejects an HTML body outright so
    a future limit change fails loudly rather than silently.

    Parameters
    ----------
    stations : str
        ``"ALL"`` or a colon-separated list of station codes.
    year : int
        Calendar year.
    codes : list of str
        KNMI variable codes (e.g. ``["Q", "T", "U"]``).

    Returns
    -------
    tuple
        Concatenated frame and merged station metadata.
    """
    logger.info("fetching KNMI %s for %d (%s)", stations, year, ",".join(codes))
    frames: list[pd.DataFrame] = []
    meta: dict[str, dict[str, Any]] = {}

    for month in range(1, 13):
        last = pd.Period(f"{year}-{month:02d}").days_in_month
        payload = {
            "start": f"{year}{month:02d}0101",
            "end": f"{year}{month:02d}{last:02d}24",
            "vars": ":".join(codes),
            "stns": stations,
        }
        frame, month_meta = _parse(_post_checked(payload))
        meta.update(month_meta)
        if not frame.empty:
            # KNMI returns trailing hours past the requested end, so
            # adjacent chunks would overlap and produce duplicate
            # (station, timestamp) rows. Clip each chunk to its own
            # month, hour-ending: (01:00 of day 1) .. (00:00 of day 1
            # of the next month).
            start = pd.Timestamp(year=year, month=month, day=1, hour=1)
            stop = start + pd.offsets.MonthBegin(1) - pd.Timedelta(hours=1)
            frame = frame[(frame.index >= start) & (frame.index <= stop)]
            frames.append(frame)
        logger.info("  %04d-%02d: %d rows", year, month, len(frame))

    if not frames:
        raise RuntimeError("KNMI returned no usable rows for any month")

    # Index duplicates are expected and correct here: one row per station
    # per timestamp. Do not de-duplicate on the index.
    combined = pd.concat(frames).sort_index()
    combined = combined[
        (combined.index >= f"{year}-01-01 01:00")
        & (combined.index <= f"{year + 1}-01-01 00:00")
    ]
    logger.info("  total %d rows, %d stations described", len(combined), len(meta))
    return combined, meta


# ---------------------------------------------------------------------------
# Provider access
# ---------------------------------------------------------------------------


#: Provider name -> the ``EnvSettings`` getter for its output directory.
#: Mirrors ``api/app.py``'s own mapping; ``registry.get_provider()``
#: returns a provider OBJECT (``ERA5LandProvider`` etc.), which exposes
#: ``get_config_summary()`` but no ``get_config``, so resolving the
#: directory through the settings layer is both correct and cheaper
#: than importing a provider package.
PROVIDER_OUTPUT_DIR_GETTERS: dict[str, str] = {
    "cosmo-rea6": "cosmo_output_dir",
    "era5-land": "era5_output_dir",
    "merra-2": "merra2_output_dir",
}


def provider_output_dir(provider: str) -> Path:
    """Resolve *provider*'s ``output/`` directory.

    Accepts the hyphenated CLI spelling as well as the underscored
    package spelling (``era5_land``), since both are used in this repo.
    """
    from weather.settings import EnvSettings

    key = provider.strip().lower().replace("_", "-")
    attr = PROVIDER_OUTPUT_DIR_GETTERS.get(key)
    if attr is None:
        raise ValueError(
            f"unknown provider {provider!r}; expected one of "
            f"{sorted(PROVIDER_OUTPUT_DIR_GETTERS)}"
        )
    return Path(getattr(EnvSettings, attr)())


def open_provider(
    file: Path | None, provider: str | None, year: int
) -> xr.Dataset:
    """Open the dataset to validate.

    A single already-exported file is preferred (fast, unambiguous).
    Falling back to a provider archive opens that year's monthly files.
    """
    if file is not None:
        logger.info("opening %s", file)
        return xr.open_dataset(file, decode_timedelta=False)

    if provider is None:
        raise ValueError("pass either --file or --provider")

    out_dir = provider_output_dir(provider)
    matches = sorted(out_dir.glob(f"*{year}_[01][0-9]*.nc"))
    if not matches:
        raise FileNotFoundError(f"no {year} monthly files in {out_dir}")
    logger.info("opening %d monthly files from %s", len(matches), out_dir)

    # Chunk when dask is available so the concatenated dataset stays
    # lazy: this tool only ever reads a few dozen grid columns out of a
    # full-domain year, and materialising the grids instead is the
    # difference between seconds and (measured on ERA5-Land) more than
    # half an hour with no result.
    try:
        import dask  # noqa: F401

        kwargs: dict[str, Any] = {"chunks": {"time": -1}}
    except ImportError:
        kwargs = {}

    parts = [
        xr.open_dataset(p, decode_timedelta=False, **kwargs) for p in matches
    ]
    combined = xr.concat(parts, dim="time")

    # NOT sortby("time"): on an eagerly-opened dataset that reindexes
    # every variable in memory, which is what made the first ERA5-Land
    # run hang. `sorted(glob)` already yields the months in order, so
    # verify that cheaply on the time coordinate alone instead.
    stamps = pd.DatetimeIndex(combined["time"].values)
    if not stamps.is_monotonic_increasing:
        logger.warning("time axis not sorted; sorting (this is expensive)")
        combined = combined.sortby("time")
    return combined


def align_to_hour_ending(index: pd.DatetimeIndex) -> tuple[pd.DatetimeIndex, int]:
    """Snap a model time axis onto KNMI's hour-ENDING convention.

    MERRA-2 stamps its hourly collections at ``HH:30`` -- the centre of
    the hour the value averages over.  KNMI labels that same hour
    ``HH+1:00`` (its division ``HH`` covers ``(HH-1):00..HH:00``).  Since
    the comparison joins on exact timestamps, a half-hour offset means
    NO pair ever matches and every statistic silently drops out: the
    first MERRA-2 run failed this way and reported it as "no station in
    domain", which was the wrong diagnosis entirely.

    Shifting a ``HH:30`` centre forward by 30 minutes lands it on the
    hour-ending label for the same physical hour.  The shift is only
    applied when the axis genuinely sits off the hour, and the lag
    diagnostic then verifies the result rather than trusting it.

    Returns
    -------
    tuple
        The aligned index and the shift applied, in minutes.
    """
    minutes = pd.Index(index.minute).unique()
    if len(minutes) != 1 or int(minutes[0]) == 0:
        return index, 0
    offset = int(minutes[0])
    shift = 60 - offset
    logger.info(
        "model stamps sit at :%02d -- shifting +%d min onto KNMI's "
        "hour-ending labels", offset, shift,
    )
    return index + pd.Timedelta(minutes=shift), shift


def grid_spacing_km(ds: xr.Dataset) -> float:
    """Median centre-to-centre spacing of neighbouring cells, in km.

    Used to size the station-matching tolerance per provider instead of
    hardcoding one distance.  A fixed 15 km silently excluded EVERY
    station on MERRA-2, whose 0.5 x 0.625 deg cells are ~55 x 43 km at
    Dutch latitudes -- no station centre can possibly be within 15 km of
    a cell centre there, so the tool reported "no station in domain"
    for a perfectly good archive.
    """
    lat_values = np.asarray(ds["latitude"].values, dtype="float64")
    lon_values = np.asarray(ds["longitude"].values, dtype="float64")
    if lat_values.ndim == 1:
        lat_values, lon_values = np.meshgrid(
            lat_values, lon_values, indexing="ij"
        )
    scale = float(np.cos(np.radians(np.nanmean(lat_values))))
    dlat = np.abs(np.diff(lat_values, axis=0)) * 111.32
    dlon = np.abs(np.diff(lon_values, axis=1)) * 111.32 * scale
    steps = [s for s in (np.nanmedian(dlat), np.nanmedian(dlon))
             if np.isfinite(s) and s > 0]
    return float(np.mean(steps)) if steps else 10.0


def default_match_distance_km(ds: xr.Dataset) -> float:
    """Tolerance for accepting a station's nearest cell.

    Half a cell diagonal is the largest distance a point inside the grid
    can be from the nearest centre; a small margin absorbs grid
    irregularity.
    """
    spacing = grid_spacing_km(ds)
    return round(spacing * 0.75 + 2.0, 1)


def nearest_cell(ds: xr.Dataset, lat: float, lon: float) -> tuple[int, int, float]:
    """Nearest grid cell to (*lat*, *lon*), plus its distance in km.

    Handles both 1-D (regular) and 2-D (curvilinear) coordinates, since
    COSMO-REA6's rotated-pole grid gives 2-D latitude/longitude.
    """
    lat_values = ds["latitude"].values
    lon_values = ds["longitude"].values
    if lat_values.ndim == 1:
        lat_values, lon_values = np.meshgrid(lat_values, lon_values, indexing="ij")
    scale = np.cos(np.radians(lat))
    squared = (lat_values - lat) ** 2 + ((lon_values - lon) * scale) ** 2
    iy, ix = np.unravel_index(int(np.argmin(squared)), squared.shape)
    return int(iy), int(ix), float(np.sqrt(squared[iy, ix]) * 111.32)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def paired_stats(model: pd.Series, observed: pd.Series) -> dict[str, float]:
    """Bias/MAE/RMSE/correlation for one aligned pair."""
    pair = pd.concat([model, observed], axis=1, keys=["m", "o"]).dropna()
    if len(pair) < 24:
        return {"n": float(len(pair))}
    difference = pair["m"] - pair["o"]
    mean_observed = float(pair["o"].mean())
    return {
        "n": float(len(pair)),
        "model_mean": float(pair["m"].mean()),
        "obs_mean": mean_observed,
        "bias": float(difference.mean()),
        "bias_pct": (
            100.0 * float(difference.mean()) / mean_observed
            if mean_observed
            else float("nan")
        ),
        "mae": float(difference.abs().mean()),
        "rmse": float(np.sqrt((difference**2).mean())),
        "r": float(pair["m"].corr(pair["o"])),
    }


def sky_condition_bias(
    model: pd.Series, observed: pd.Series
) -> pd.DataFrame:
    """GHI bias split by clear-sky index.

    Distinguishes a radiative-transfer bias (sign varies with cloud
    cover) from a units/scaling error (roughly constant).  The clear-sky
    reference is a per-hour-of-day rolling 97th percentile of the
    OBSERVED series, so no clear-sky model or extra dependency is needed.
    """
    pair = pd.concat([model, observed], axis=1, keys=["m", "o"]).dropna()
    day = pair[pair["o"] > 20].copy()
    if day.empty:
        return pd.DataFrame()
    envelope = day.groupby(day.index.hour)["o"].transform(
        lambda s: s.rolling(400, center=True, min_periods=50).quantile(0.97)
    )
    day["kt"] = day["o"] / envelope
    bins = [(0.0, 0.3, "overcast"), (0.3, 0.6, "broken"),
            (0.6, 0.85, "hazy"), (0.85, 9.9, "clear")]
    records = []
    for low, high, label in bins:
        subset = day[(day["kt"] >= low) & (day["kt"] < high)]
        if len(subset) < 50:
            continue
        bias = float((subset["m"] - subset["o"]).mean())
        records.append({
            "sky": label,
            "n": len(subset),
            "obs_mean": float(subset["o"].mean()),
            "model_mean": float(subset["m"].mean()),
            "bias": bias,
            "bias_pct": 100.0 * bias / float(subset["o"].mean()),
        })
    return pd.DataFrame(records)


def lag_correlation(
    model: pd.Series, observed: pd.Series, lags: tuple[int, ...] = (-2, -1, 0, 1, 2)
) -> dict[int, float]:
    """Correlation at several hour offsets.

    The peak should sit at lag 0.  A peak elsewhere means the two series
    are labelled with different hour conventions -- the single most
    consequential mistake a consumer of this data can make, and one that
    bias statistics alone will not reveal.
    """
    pair = pd.concat([model, observed], axis=1, keys=["m", "o"]).dropna()
    return {lag: float(pair["m"].corr(pair["o"].shift(lag))) for lag in lags}


def temporal_semantics(
    model: pd.Series, observed: pd.Series
) -> dict[str, float]:
    """Test whether the model series is an hourly mean or instantaneous.

    Hypothesis A treats the model value as the mean over ``(t-1h, t]``,
    comparing it against the KNMI hourly sum directly.  Hypothesis B
    treats it as the instantaneous value at ``t``, whose best estimate
    from hourly means is the average of the two adjacent hours.  The
    winner is whichever gives the higher correlation and the lower
    debiased RMSE.
    """
    hour_mean = observed
    instantaneous = (observed + observed.shift(-1)) / 2.0
    result: dict[str, float] = {}
    for label, reference in (("hourly_mean", hour_mean),
                             ("instantaneous", instantaneous)):
        pair = pd.concat([model, reference], axis=1, keys=["m", "o"]).dropna()
        pair = pair[(pair["m"] > 20) | (pair["o"] > 20)]
        if len(pair) < 100:
            continue
        residual = pair["m"] - pair["o"]
        result[f"r_{label}"] = float(pair["m"].corr(pair["o"]))
        result[f"rmse_{label}"] = float(
            np.sqrt(((residual - residual.mean()) ** 2).mean())
        )
    if "r_hourly_mean" in result and "r_instantaneous" in result:
        result["verdict_instantaneous"] = float(
            result["r_instantaneous"] > result["r_hourly_mean"]
            and result["rmse_instantaneous"] < result["rmse_hourly_mean"]
        )
    return result


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def validate(
    ds: xr.Dataset,
    year: int,
    *,
    out_dir: Path,
    stations: str = "ALL",
    max_distance_km: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the full comparison and write results to *out_dir*.

    Returns
    -------
    tuple of DataFrame
        Per-station/per-variable statistics, and the sky-condition table.
    """
    if max_distance_km is None:
        max_distance_km = default_match_distance_km(ds)
        logger.info(
            "grid spacing ~%.1f km -> station match tolerance %.1f km",
            grid_spacing_km(ds), max_distance_km,
        )

    available = [v for v in VARIABLE_MAP if v in ds.data_vars]
    if not available:
        raise ValueError(
            f"dataset has none of {sorted(VARIABLE_MAP)}; "
            f"found {sorted(str(v) for v in ds.data_vars)}"
        )
    codes = [VARIABLE_MAP[v][0] for v in available]
    logger.info("comparing %s", ", ".join(available))

    observations, meta = fetch_knmi(stations, year, codes)
    if observations.empty:
        raise RuntimeError("KNMI returned no rows")

    lat_values = np.asarray(ds["latitude"].values, dtype="float64")
    lon_values = np.asarray(ds["longitude"].values, dtype="float64")
    lat_lo, lat_hi = np.nanmin(lat_values), np.nanmax(lat_values)
    lon_lo, lon_hi = np.nanmin(lon_values), np.nanmax(lon_values)

    rows: list[dict[str, Any]] = []
    sky_rows: list[dict[str, Any]] = []
    used = 0

    for code, info in sorted(meta.items()):
        lat, lon = info["lat"], info["lon"]
        if not (lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi):
            continue
        station_obs = observations[observations["station"] == code]
        if station_obs.empty:
            continue

        iy, ix, distance = nearest_cell(ds, lat, lon)
        if distance > max_distance_km:
            logger.info("  skipping %s (%s): %.1f km from nearest cell",
                        code, info["name"], distance)
            continue
        used += 1
        point = ds.isel(y=iy, x=ix)
        model_index, _shift = align_to_hour_ending(
            pd.DatetimeIndex(pd.to_datetime(point["time"].values))
        )

        for variable in available:
            knmi_code, scale, note = VARIABLE_MAP[variable]
            if knmi_code not in station_obs.columns:
                continue
            model = pd.Series(np.asarray(point[variable].values, dtype="float64"),
                              index=model_index)
            observed = station_obs[knmi_code].astype("float64") * scale
            stats = paired_stats(model, observed)
            if "bias" not in stats:
                continue
            rows.append({
                "station": code,
                "name": info["name"],
                "lat": lat,
                "lon": lon,
                "distance_km": round(distance, 2),
                "variable": variable,
                "knmi_code": knmi_code,
                "note": note,
                **{k: round(v, 4) for k, v in stats.items()},
            })

            if variable == "GHI":
                total_model = float(model.sum()) / 1000.0
                total_obs = float(observed.sum()) / 1000.0
                rows[-1]["annual_model_kwh_m2"] = round(total_model, 1)
                rows[-1]["annual_obs_kwh_m2"] = round(total_obs, 1)
                for lag, value in lag_correlation(model, observed).items():
                    rows[-1][f"r_lag{lag:+d}"] = round(value, 4)
                for key, value in temporal_semantics(model, observed).items():
                    rows[-1][key] = round(value, 4)
                for record in sky_condition_bias(model, observed).to_dict("records"):
                    sky_rows.append({"station": code, "name": info["name"],
                                     **record})

    if not rows:
        raise RuntimeError(
            (
                f"{used} station(s) matched a grid cell, but none "
                "produced any overlapping hours -- the model and "
                "observation time axes do not intersect. Check the "
                "stamp convention (see align_to_hour_ending)."
            )
            if used
            else (
                "no KNMI station fell inside the dataset domain within "
                f"{max_distance_km:.1f} km (grid spacing ~"
                f"{grid_spacing_km(ds):.1f} km) -- is this a "
                "Netherlands file? Raise --max-distance-km if the grid "
                "is coarse."
            )
        )
    logger.info("compared %d stations", used)

    detail = pd.DataFrame(rows)
    sky = pd.DataFrame(sky_rows)

    summary = (
        detail.groupby("variable")
        .agg(
            stations=("station", "nunique"),
            bias=("bias", "mean"),
            bias_pct=("bias_pct", "mean"),
            mae=("mae", "mean"),
            rmse=("rmse", "mean"),
            r=("r", "mean"),
        )
        .round(4)
        .reset_index()
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(out_dir / f"knmi_validation_{year}_stations.csv", index=False)
    summary.to_csv(out_dir / f"knmi_validation_{year}_summary.csv", index=False)
    if not sky.empty:
        sky.to_csv(out_dir / f"knmi_validation_{year}_sky.csv", index=False)
    _write_report(out_dir, year, detail, summary, sky, used)
    logger.info("wrote results to %s", out_dir)

    return detail, summary


def _md_table(frame: pd.DataFrame, index: bool = False) -> str:
    """Render *frame* as a Markdown table.

    Hand-rolled rather than via ``DataFrame.to_markdown`` so the report
    needs no ``tabulate`` dependency, and so every ``|`` lines up across
    rows -- markdownlint's MD060 (table-column-style) is on by default
    and this repo's docs are checked with it.
    """
    work = frame.reset_index() if index else frame
    headers = [str(c) for c in work.columns]
    rows = [[("" if pd.isna(v) else str(v)) for v in row]
            for row in work.itertuples(index=False)]
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows)) if rows
        else len(headers[i])
        for i in range(len(headers))
    ]
    out = [
        "| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)) + " |",
        "|" + "|".join("-" * (w + 2) for w in widths) + "|",
    ]
    out += [
        "| " + " | ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) + " |"
        for row in rows
    ]
    return "\n".join(out)


def _write_report(
    out_dir: Path,
    year: int,
    detail: pd.DataFrame,
    summary: pd.DataFrame,
    sky: pd.DataFrame,
    n_stations: int,
) -> None:
    """Write a short Markdown report next to the CSVs."""
    lines = [
        f"# KNMI validation — {year}",
        "",
        f"{n_stations} KNMI stations compared against the nearest grid cell.",
        "",
        "KNMI hour divisions are hour-ENDING in UT, the same convention "
        "COSMO-REA6 uses, so the series align with no time shift.",
        "",
        "## Summary by variable",
        "",
        _md_table(summary),
        "",
        "## Annual GHI totals by station (kWh/m²)",
        "",
    ]
    ghi = detail[detail["variable"] == "GHI"]
    if not ghi.empty:
        columns = ["station", "name", "distance_km", "annual_model_kwh_m2",
                   "annual_obs_kwh_m2", "bias_pct", "r"]
        available = [c for c in columns if c in ghi.columns]
        lines += [_md_table(ghi[available]), ""]

    if not sky.empty:
        pooled = (
            sky.groupby("sky")
            .agg(n=("n", "sum"), obs_mean=("obs_mean", "mean"),
                 model_mean=("model_mean", "mean"),
                 bias_pct=("bias_pct", "mean"))
            .round(2)
            .reset_index()
        )
        lines += [
            "## GHI bias by sky condition",
            "",
            "A units or scaling error would be roughly constant across "
            "these bins. A sign reversal indicates a radiative-transfer "
            "bias in the model, not a pipeline defect.",
            "",
            _md_table(pooled),
            "",
        ]

    lag_columns = [c for c in detail.columns if c.startswith("r_lag")]
    if lag_columns and not ghi.empty:
        peak = ghi[lag_columns].mean().idxmax()
        lines += [
            "## Time alignment",
            "",
            f"Mean GHI correlation peaks at **{peak}**; `r_lag+0` means "
            "the two series are correctly aligned.",
            "",
            _md_table(
                ghi[lag_columns].mean().round(4).to_frame("mean r"),
                index=True,
            ),
            "",
        ]

    if "verdict_instantaneous" in detail.columns and not ghi.empty:
        share = float(ghi["verdict_instantaneous"].mean())
        instantaneous = share > 0.5
        verdict = "INSTANTANEOUS" if instantaneous else "an HOURLY MEAN"
        agreeing = share if instantaneous else 1.0 - share
        detail = (
            "Instantaneous samples should be integrated trapezoidally "
            "rather than treated as hour-means; annual totals are "
            "unaffected because both series endpoints are night. "
            "CF cell_methods: 'time: point'."
            if instantaneous
            else "Each value represents the mean over the preceding "
                 "hour, so rectangle integration is correct and no "
                 "trapezoidal correction is needed. "
                 "CF cell_methods: 'time: mean'."
        )
        lines += [
            "## Temporal semantics",
            "",
            f"{agreeing:.0%} of stations indicate the model's GHI is "
            f"**{verdict}** at the timestamp. {detail}",
            "",
        ]

    (out_dir / f"knmi_validation_{year}.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validate provider output against KNMI observations."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="A single exported NetCDF.")
    source.add_argument("--provider", help="Provider name; uses its output/.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--stations", default="ALL",
        help="KNMI station codes, colon-separated, or ALL (default).",
    )
    parser.add_argument(
        "--max-distance-km", type=float, default=None,
        help=(
            "Skip stations further than this from the nearest cell. "
            "Default: derived from the grid spacing, since a fixed "
            "distance excludes every station on a coarse grid "
            "(MERRA-2 cells are ~55x43 km at Dutch latitudes)."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    ds = open_provider(args.file, args.provider, args.year)
    try:
        _, summary = validate(
            ds,
            args.year,
            out_dir=args.out_dir,
            stations=args.stations,
            max_distance_km=args.max_distance_km,
        )
    finally:
        ds.close()

    print()
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
