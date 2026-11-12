"""Labeled simulation-grade takeoff N1 estimates: A320neo/A321neo and 737 MAX 8.

Hudson accepted labeled estimates on 2026-10-30 (docs/goal.md, D-09). Nothing here is a
manufacturer N1 schedule. Method, sources, and assumptions:
docs/research/thrust-source-inventory.md.

The corrected-N1 takeoff limit shape and bleed corrections are taken from FlyByWire A32NX
ThrustLimits_A32NX.hpp (GPL-3.0, commit 66021c24448c44399a8ff569eb14715b6b26558e),
a LEAP-1A26 simulation whose data provenance is not stated.
"""

import math
from typing import Any

FBW_REF = "FlyByWire A32NX ThrustLimits_A32NX.hpp @66021c24448c (GPL-3.0; simulation, provenance unstated)"
PW_TCDS = "EASA TCDS IM.E.093 Issue 14 (16 Oct 2026), take-off flat rating"

# Every FlyByWire TO row (limits[0..20]), copied verbatim:
# (altitude ft, corner point C, limit point C, CN1 flat, CN1 at limit point, CN1 at 100 C)
FBW_TO = [
    (-2000, 48.0, 55.0, 81.351, 79.370, 61.535),
    (-1000, 46.0, 55.0, 82.605, 80.120, 62.105),
    (0, 44.0, 55.0, 83.832, 80.776, 62.655),
    (500, 42.0, 52.0, 84.210, 81.618, 62.655),
    (1000, 42.0, 52.0, 84.579, 81.712, 62.655),
    (2000, 40.0, 50.0, 85.594, 82.720, 62.655),
    (3000, 36.0, 48.0, 86.657, 83.167, 61.960),
    (4000, 32.0, 46.0, 87.452, 83.332, 61.206),
    (5000, 29.0, 44.0, 88.833, 84.166, 61.206),
    (6000, 25.0, 42.0, 90.232, 84.815, 61.206),
    (7000, 21.0, 40.0, 91.711, 85.565, 61.258),
    (8000, 17.0, 38.0, 93.247, 86.225, 61.777),
    (9000, 15.0, 36.0, 94.031, 86.889, 60.968),
    (10000, 13.0, 34.0, 94.957, 88.044, 60.935),
    (11000, 12.0, 32.0, 95.295, 88.526, 59.955),
    (12000, 11.0, 30.0, 95.568, 88.818, 58.677),
    (13000, 10.0, 28.0, 95.355, 88.819, 59.323),
    (14000, 10.0, 26.0, 95.372, 89.311, 59.965),
    (15000, 8.0, 24.0, 95.686, 89.907, 58.723),
    (16000, 5.0, 22.0, 96.160, 89.816, 57.189),
    (16600, 5.0, 22.0, 96.560, 89.816, 57.189),
]
MIN_PA, MAX_PA = FBW_TO[0][0], FBW_TO[-1][0]
# FlyByWire TO bleed N1 corrections (packs, nacelle anti-ice, wing anti-ice), keyed by
# (pressure altitude < 8000 ft, OAT below the corner point); a FLEX above the limit point
# uses FBW_FLEX_BLEED at any altitude.
FBW_TO_BLEED = {
    (True, True): (-0.4, -0.6, -0.7),
    (True, False): (-0.5, -0.6, -0.7),
    (False, True): (-0.6, -0.8, -0.8),
    (False, False): (-0.7, -0.8, -0.8),
}
FBW_FLEX_BLEED = (-0.6, -0.7, -0.7)
# Above 2,000 ft the corner point follows FlyByWire's LEAP-1A26 altitude lapse, but engines with
# the same sea-level rating can differ at altitude (EASA E.110), so the corner tolerance grows by
# this fraction of the corner's drop from its 2,000 ft value (about +/-3 C more at Denver).
HIGH_ALTITUDE_PA = 2000
HIGH_ALTITUDE_CORNER_FRACTION = 0.25

# Sea-level flat-rating (corner point) temperature, source, +/- C applied in the uncertainty
# range, and family. LEAP-1A and LEAP-1B flat ratings are not published in EASA E.110/E.115.
ASSUMED_A321 = "assumed by analogy with PW1133G-JM thrust class"
ENGINES = {
    "PW1124G": ("PW1124G1-JM", 51.0, PW_TCDS, 2.0, "airbus"),
    "PW1127G": ("PW1127G-JM", 47.0, PW_TCDS, 2.0, "airbus"),
    "PW1129G": ("PW1129G-JM", 44.0, PW_TCDS, 2.0, "airbus"),
    "PW1130G": ("PW1130G-JM", 30.0, PW_TCDS, 2.0, "airbus"),
    "PW1133G": ("PW1133G-JM", 30.0, PW_TCDS, 2.0, "airbus"),
    "LEAP-1A26": ("LEAP-1A26", 44.0, FBW_REF + ", sea-level corner point", 3.0, "airbus"),
    "LEAP-1A32": ("LEAP-1A32", 30.0, ASSUMED_A321, 5.0, "airbus"),
    "LEAP-1A33": ("LEAP-1A33", 30.0, ASSUMED_A321, 5.0, "airbus"),
    "LEAP-1A35A": ("LEAP-1A35A", 30.0, ASSUMED_A321, 5.0, "airbus"),
    "LEAP-1B28": (
        "LEAP-1B28",
        30.0,
        "assumed; EASA TCDS E.115 Issue 09 gives 13,041 daN but no flat rating",
        5.0,
        "boeing",
    ),
}
AIRCRAFT = {"A20N": "airbus", "A21N": "airbus", "B38M": "boeing"}
# Engines certified per aircraft (EASA TCDS A.064 for the neo family; B38M uses LEAP-1B28).
AIRCRAFT_ENGINES = {
    "A20N": ("PW1124G", "PW1127G", "PW1129G", "LEAP-1A26"),
    "A21N": ("PW1130G", "PW1133G", "LEAP-1A32", "LEAP-1A33", "LEAP-1A35A"),
    "B38M": ("LEAP-1B28",),
}
# Boeing fixed derates as a fraction of rated thrust (assumed: TO-1 ~10%, TO-2 ~20%), +/-0.02.
BOEING_DERATES = {"TO": 0.0, "TO1": 0.10, "TO2": 0.20}
DERATE_TOLERANCE = 0.02
SHAPE_SCALES = (0.8, 1.0, 1.2)  # +/-20% on the borrowed lapse slopes
THRUST_EXPONENTS = (2.4, 2.7, 3.0)  # corrected thrust ~ N1^n; low, central, high
LABEL = "SIMULATION-GRADE ESTIMATE"


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _interp(pa: float, column: int) -> float:
    for lo, hi in zip(FBW_TO, FBW_TO[1:]):
        if lo[0] <= pa <= hi[0]:
            return lo[column] + (pa - lo[0]) / (hi[0] - lo[0]) * (hi[column] - lo[column])
    raise ValueError("pressure altitude outside table")


def _engine(text: str | None):
    if not isinstance(text, str):
        return None
    key = text.upper().replace(" ", "")
    # Rating suffixes identify distinct engines; a prefix is not applicability evidence.
    return next((profile for profile in ENGINES.values() if key == profile[0]), None)


def _qnh_hpa(value: float) -> tuple[float, str]:
    # SimBrief does not label the altimeter unit; these physical ranges cannot overlap.
    if 25 <= value <= 35:
        return value * 33.8639, "inHg"
    if 850 <= value <= 1100:
        return value, "hPa"
    raise ValueError(f"unsupported_conditions: altimeter {value} outside inHg and hPa ranges")


def _shape(temp: float, corner: float, pa: float, scale: float) -> float:
    """Takeoff corrected-N1 limit at `temp`, relative to the flat value (FlyByWire shape)."""
    flat, last, hot = _interp(pa, 3), _interp(pa, 4), _interp(pa, 5)
    span = _interp(pa, 2) - _interp(pa, 1)
    s1 = (flat - last) / flat / span * scale
    s2 = (last - hot) / flat / (100 - _interp(pa, 2)) * scale
    above = max(0.0, temp - corner)
    return 1 - s1 * min(above, span) - s2 * max(0.0, above - span)


def fbw_leap1a26_n1(pa: float, oat: float, flex: float | None, packs: int, nacelle: int, wing: int):
    """FlyByWire A32NX TO limitN1 (Mach 0) for LEAP-1A26: the simulation's absolute N1."""
    cp, lp = _interp(pa, 1), _interp(pa, 2)
    flat, last, hot = _interp(pa, 3), _interp(pa, 4), _interp(pa, 5)
    temp = flex if flex else oat
    if temp <= cp:
        cn1 = flat
    elif flex and temp > lp:
        cn1 = hot + (last - hot) * (100 - temp) / (100 - lp)
    else:
        cn1 = flat + (last - flat) * (temp - cp) / (lp - cp)
    if flex and flex > lp:
        packs_c, nacelle_c, wing_c = FBW_FLEX_BLEED
    else:
        packs_c, nacelle_c, wing_c = FBW_TO_BLEED[(pa < 8000, oat < cp)]
    bleed = packs * packs_c + nacelle * nacelle_c + wing * wing_c
    return cn1 * math.sqrt((273.15 + oat) / 288.15) + bleed


# Pressure altitude differs from field elevation with the day's pressure (roughly +/-1,000 ft
# across normal QNH), so an airport this close to the band edge can fall on either side.
PA_MARGIN_FT = 1000


def support_note(
    aircraft_icao: str | None, airport: str | None = None, elevation_ft: float | None = None
) -> str:
    """One line for approval prompts: will a takeoff N1 estimate be available here?"""
    code = (aircraft_icao or "").upper()
    if code not in AIRCRAFT:
        return f"{code or 'aircraft'}: takeoff N1 estimate unavailable (not modeled)"
    if elevation_ft is None:
        return f"{code}: simulation-grade takeoff N1 estimate available" + (
            f" (elevation of {airport} unknown)" if airport else ""
        )
    where = f"{code} at {airport} ({elevation_ft:,.0f} ft field elevation)"
    band = f"the modeled {MIN_PA:,}..{MAX_PA:,} ft pressure-altitude band"
    if not MIN_PA - PA_MARGIN_FT <= elevation_ft <= MAX_PA + PA_MARGIN_FT:
        return f"{where}: takeoff N1 estimate unavailable (outside {band})"
    if not MIN_PA + PA_MARGIN_FT <= elevation_ft <= MAX_PA - PA_MARGIN_FT:
        return (
            f"{where}: takeoff N1 estimate may be unavailable (near the edge of {band}; "
            "depends on the day's pressure)"
        )
    return f"{where}: simulation-grade takeoff N1 estimate available"


def supported_profiles() -> dict[str, Any]:
    """Which aircraft/engines/thrust modes the estimator handles, and what it reads."""
    return {
        "label": LABEL,
        "aircraft": {
            icao: {
                "engines": {
                    ENGINES[k][0]: f"corner {ENGINES[k][1]:.0f} C, {ENGINES[k][2]}" for k in keys
                },
                "thrust_modes": ["TOGA", "FLEX"]
                if AIRCRAFT[icao] == "airbus"
                else ["TO", "TO-1", "TO-2", "optional D- (assumed temperature)"],
            }
            for icao, keys in AIRCRAFT_ENGINES.items()
        },
        "reads_from_simbrief": [
            "aircraft.icao_code",
            "aircraft.engines",
            "tlr.takeoff.conditions: temperature, altimeter",
            "selected runway: thrust_setting, flex_temperature, elevation, bleed/anti-ice",
        ],
        "optional_inputs": {
            "engine_override": "engine of the Infinite Flight livery when it differs",
            "full_thrust_n1": "N1 read in Infinite Flight at full throttle (calibration)",
        },
        "limits": f"pressure altitude {MIN_PA}..{MAX_PA} ft; other aircraft return unavailable",
    }


def _result(status: str, **fields) -> dict[str, Any]:
    return {"status": status, "label": LABEL, **fields}


def _thrust_mode(family: str, mode: str) -> tuple[float, bool] | None:
    """Return (fixed derate fraction, assumed temperature applies) or None if unmodeled."""
    if family == "airbus":
        if mode == "TOGA":
            return 0.0, False
        if mode in ("FLEX", "FLX"):
            return 0.0, True
        return None
    assumed = mode.startswith("D-")
    base = mode.removeprefix("D-")
    base = {"TO-1": "TO1", "TO-2": "TO2"}.get(base, base)
    return (BOEING_DERATES[base], assumed) if base in BOEING_DERATES else None


def estimate_takeoff_n1(
    aircraft_icao: str | None,
    engines: str | None,
    conditions: dict | None,
    runway: dict | None,
    engine_override: str | None = None,
    full_thrust_n1: float | None = None,
) -> dict[str, Any]:
    """Estimate takeoff N1 from one SimBrief takeoff solution (conditions + selected runway).

    Returns N1 as a ratio of full rated (TOGA/TO) N1 at the same conditions, plus an absolute
    target when `full_thrust_n1` (read in Infinite Flight at full throttle) is supplied.
    """
    if full_thrust_n1 is not None:
        full_thrust_n1 = _number(full_thrust_n1)
        if full_thrust_n1 is None or not 40 < full_thrust_n1 <= 120:
            return _result(
                "invalid_input",
                reason="full_thrust_n1 must be an observed N1 percentage above 40 and at most 120",
            )
    family = AIRCRAFT.get(aircraft_icao or "")
    if not family:
        return _result(
            "unsupported_profile",
            reason=f"aircraft {aircraft_icao!r} is not modeled (A20N, A21N, B38M)",
        )
    engine_text = engine_override or engines
    profile = _engine(engine_text)
    allowed = [ENGINES[k][0] for k in AIRCRAFT_ENGINES[aircraft_icao]]
    if not profile or profile[0] not in allowed:
        return _result(
            "unsupported_profile",
            reason=f"no {aircraft_icao} engine profile for {engine_text!r}",
        )
    model, corner_sl, corner_source, corner_tolerance, _ = profile
    if not isinstance(conditions, dict) or not isinstance(runway, dict):
        return _result("missing_input", missing_inputs=["takeoff conditions or selected runway"])

    mode = str(runway.get("thrust_setting") or "").upper().replace(" ", "")
    oat = _number(conditions.get("temperature"))
    altimeter = _number(conditions.get("altimeter"))
    elevation = _number(runway.get("elevation"))
    assumed_temp = _number(runway.get("flex_temperature"))
    bleed = str(runway.get("bleed_setting") or "").strip().upper()
    anti_ice = str(runway.get("anti_ice_setting") or "").strip().upper()
    missing = [
        name
        for name, value in (
            ("temperature", oat),
            ("altimeter", altimeter),
            ("runway elevation", elevation),
            ("thrust_setting", mode or None),
            ("bleed_setting", bleed or None),
            ("anti_ice_setting", anti_ice or None),
        )
        if value is None
    ]
    parsed = _thrust_mode(family, mode) if mode else (0.0, False)
    if parsed and parsed[1] and assumed_temp is None:
        missing.append("flex_temperature (FLEX / assumed temperature)")
    if missing:
        return _result("missing_input", missing_inputs=missing)
    if parsed is None:
        modeled = "TOGA and FLEX" if family == "airbus" else "TO, TO-1, TO-2 with optional D-"
        return _result(
            "unsupported_thrust_mode",
            reason=f"thrust setting {mode!r}; only {modeled} are modeled for {aircraft_icao}",
        )
    derate, uses_assumed = parsed

    # This is a computational bound on the borrowed table, not an aircraft envelope.
    if not -273.15 < oat <= 100 or (uses_assumed and not oat <= assumed_temp <= 100):
        return _result(
            "unsupported_conditions",
            reason="OAT must be above absolute zero and at most the 100 C model endpoint; "
            "assumed temperature must be between OAT and that endpoint. Aircraft limits "
            "and simulator applicability remain unverified.",
        )
    if bleed not in {"ON", "OFF"} or anti_ice not in {"OFF", "ON", "ENG", "ALL", "WING"}:
        return _result(
            "unsupported_conditions",
            reason="unrecognized bleed/anti-ice setting; cannot assume an OFF configuration",
        )

    try:
        qnh, qnh_unit = _qnh_hpa(altimeter)
    except ValueError as exc:
        return _result("unsupported_conditions", reason=str(exc))
    pa = elevation + (1013.25 - qnh) * 27.0
    if not MIN_PA <= pa <= MAX_PA:
        return _result(
            "unsupported_conditions",
            reason=f"pressure altitude {pa:.0f} ft outside the modeled {MIN_PA}..{MAX_PA} ft band",
        )

    packs = int(bleed == "ON")
    nacelle = int(anti_ice in ("ON", "ENG", "ALL"))
    wing = int(anti_ice in ("ALL", "WING"))
    corner_shift = _interp(pa, 1) - FBW_TO[2][1]
    high_altitude = HIGH_ALTITUDE_CORNER_FRACTION * max(
        0.0, _interp(HIGH_ALTITUDE_PA, 1) - _interp(pa, 1)
    )
    tolerance = corner_tolerance + high_altitude
    temp_used = assumed_temp if uses_assumed else None

    def temp_ratio(corner_delta: float, scale: float) -> float:
        corner = corner_sl + corner_shift + corner_delta
        if temp_used is None or temp_used <= max(corner, oat):
            return 1.0
        return _shape(temp_used, corner, pa, scale) / _shape(oat, corner, pa, scale)

    def ratio(corner_delta: float, scale: float, n: float, derate_delta: float) -> float:
        fraction = 1 - (derate + derate_delta if derate else 0.0)
        return fraction ** (1 / n) * temp_ratio(corner_delta, scale)

    n_mid = THRUST_EXPONENTS[1]
    nominal = ratio(0.0, 1.0, n_mid, 0.0)
    grid = [
        ratio(d, s, n, dd)
        for d in (-tolerance, 0.0, tolerance)
        for s in SHAPE_SCALES
        for n in (THRUST_EXPONENTS if derate else (n_mid,))
        for dd in ((-DERATE_TOLERANCE, 0.0, DERATE_TOLERANCE) if derate else (0.0,))
    ]
    low, high = min(grid), max(grid)
    temp_thrust = temp_ratio(0.0, 1.0) ** n_mid  # vs the (derated) rating; AC 25-13 applies here

    notes = []
    # Warnings also go into the briefing line, so they reach the pilot without relying on the
    # model to relay them; the most serious first.
    warnings = []
    if temp_used is not None and temp_ratio(0.0, 1.0) == 1.0:
        notes.append("assumed temperature at or below the flat rating or OAT: no extra reduction")
    if temp_thrust < 0.75:
        notes.append(
            "assumed-temperature reduction exceeds 25% of the rating (FAA AC 25-13); treat as suspect"
        )
        warnings.append("SUSPECT: thrust reduction over the 25% FAA AC 25-13 limit")
    if high_altitude:
        notes.append(
            f"pressure altitude {pa:,.0f} ft: above {HIGH_ALTITUDE_PA:,} ft the engine's corner "
            f"point is extrapolated with FlyByWire's LEAP-1A26 lapse, so the range is wider"
        )
        warnings.append(f"high altitude ({pa:,.0f} ft): engine behavior extrapolated, wider range")

    data: dict[str, Any] = {
        "engine": model,
        "engine_source": "user override" if engine_override else "SimBrief aircraft.engines",
        "thrust_mode": mode,
        "fixed_derate_thrust_fraction": derate,
        "assumed_temperature_c": temp_used,
        "oat_c": oat,
        "pressure_altitude_ft": round(pa),
        "n1_ratio_to_full_thrust": round(nominal, 3),
        "n1_ratio_range": [round(low, 3), round(high, 3)],
        "thrust_fraction_of_full_estimate": round((1 - derate) * temp_thrust, 2),
    }
    if full_thrust_n1 is not None:
        data["calibration_full_thrust_n1"] = full_thrust_n1
        data["target_n1"] = round(full_thrust_n1 * nominal, 1)
        data["target_n1_range"] = [round(full_thrust_n1 * low, 1), round(full_thrust_n1 * high, 1)]
    if model == "LEAP-1A26":
        data["fbw_model_n1"] = round(fbw_leap1a26_n1(pa, oat, temp_used, packs, nacelle, wing), 1)

    if "target_n1" in data:
        lo_n1, hi_n1 = data["target_n1_range"]
        target = f"set N1 {data['target_n1']}% (range {lo_n1}-{hi_n1}%)"
    else:
        target = f"set N1 {nominal:.3f} x full-thrust N1 (range {low:.3f}-{high:.3f})"
        if "fbw_model_n1" in data:
            target += f"; FlyByWire model N1 {data['fbw_model_n1']}%"
    briefing = f"TAKEOFF THRUST ({LABEL.lower()}): {mode}, {model}: {target}"
    if warnings:
        briefing += " — " + "; ".join(warnings)

    assumptions = [
        f"corner point {corner_sl:.0f} C at sea level ({corner_source}), +/-{corner_tolerance:.0f} C",
        "lapse slopes borrowed from a LEAP-1A26 simulation, +/-20%",
        *(
            [
                f"above {HIGH_ALTITUDE_PA:,} ft the corner point follows FlyByWire's LEAP-1A26 "
                "altitude lapse; engines with equal sea-level ratings can differ at altitude "
                f"(EASA E.110), so +/-{high_altitude:.1f} C more"
            ]
            if high_altitude
            else []
        ),
        f"altimeter unit {qnh_unit} inferred from its physical range (SimBrief gives none)",
        "temperatures in degrees C; elevation in feet",
        "bleed/anti-ice effects inside the ratio are ignored (<~0.5% N1)",
        "displayed N1 only; equal real or simulator thrust is not established",
    ]
    if family == "boeing":
        assumptions += [
            "TO-1 ~10% and TO-2 ~20% fixed derates (+/-2%), scaling the full-rating curve",
            "corrected thrust ~ N1^n, n = 2.7 (2.4-3.0), converts the derate to N1",
            "a 'D-' prefix means the assumed (SEL) temperature is applied on top of the rating",
        ]
    return _result(
        "estimated",
        data=data,
        briefing=briefing,
        method=(
            "N1 = full-thrust N1 x (1 - derate)^(1/n) x CN1(assumed temp)/CN1(OAT); CN1 flat to "
            "the engine corner point, then the FlyByWire LEAP-1A26 lapse shape; corner shifted "
            "with pressure altitude per FlyByWire"
        ),
        assumptions=assumptions,
        notes=notes,
        warnings=warnings,
        sources=[corner_source, FBW_REF, "FAA AC 25-13 (75% minimum reduced thrust)"],
    )
