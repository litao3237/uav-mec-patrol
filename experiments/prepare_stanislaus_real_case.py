from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

COMMUNICATION_SITES_URL = (
    "https://apps.fs.usda.gov/arcx/rest/services/EDW/"
    "EDW_SpecialUsesCommunicationsSites_01/MapServer/0/query"
)
FIRE_OCCURRENCE_URL = (
    "https://apps.fs.usda.gov/arcx/rest/services/EDW/"
    "EDW_FireOccurrenceAndPerimeter_01/MapServer/12/query"
)

EARTH_RADIUS_M = 6_371_008.8


def _fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={
            "User-Agent": (
                "uav-mec-patrol/real-geography-case "
                "(academic reproducibility)"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_arcgis_features(
    url: str,
    *,
    where: str,
    out_fields: str,
    geometry: str | None = None,
    page_size: int = 2000,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        if geometry is not None:
            params.update(
                {
                    "geometry": geometry,
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                }
            )
        payload = _fetch_json(url, params)
        page = payload.get("features", [])
        if not isinstance(page, list):
            raise RuntimeError(
                f"Unexpected ArcGIS response from {url}: {payload}"
            )
        features.extend(page)
        if len(page) < page_size:
            break
        offset += len(page)
    return features


def _haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _point_lon_lat(feature: dict[str, Any]) -> tuple[float, float]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("Feature is missing point geometry")
    coordinates = geometry.get("coordinates")
    if (
        not isinstance(coordinates, list)
        or len(coordinates) < 2
    ):
        raise ValueError("Feature has invalid point coordinates")
    return float(coordinates[0]), float(coordinates[1])


def _bbox(
    lat: float,
    lon: float,
    radius_km: float,
) -> str:
    radius_m = 1000.0 * radius_km
    dlat = math.degrees(radius_m / EARTH_RADIUS_M)
    dlon = math.degrees(
        radius_m
        / (EARTH_RADIUS_M * max(1e-9, math.cos(math.radians(lat))))
    )
    return ",".join(
        str(value)
        for value in (
            lon - dlon,
            lat - dlat,
            lon + dlon,
            lat + dlat,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scout official USFS GIS data for the Stanislaus real-geography "
            "case study."
        )
    )
    parser.add_argument("--depot-lat", type=float, default=37.821982)
    parser.add_argument("--depot-lon", type=float, default=-120.098763)
    parser.add_argument("--task-radius-km", type=float, default=12.0)
    parser.add_argument("--mec-radius-km", type=float, default=35.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.task_radius_km <= 0.0 or args.mec_radius_km <= 0.0:
        raise ValueError("search radii must be positive")

    communications = _fetch_arcgis_features(
        COMMUNICATION_SITES_URL,
        where="STATE = 'CA'",
        out_fields=(
            "OBJECTID,NATIONAL_FOREST,DISTRICT,"
            "COMMUNICATIONS_SITE_NAME,DESIGNATION,LATITUDE,LONGITUDE,"
            "SITE_ELEVATION,FIBER_OPTIC,POWER"
        ),
    )
    filtered_communications: list[dict[str, Any]] = []
    for feature in communications:
        props = feature.get("properties", {})
        forest = str(
            props.get("NATIONAL_FOREST")
            or props.get("national_forest")
            or ""
        )
        if "stanislaus" not in forest.lower():
            continue
        lon, lat = _point_lon_lat(feature)
        distance_m = _haversine_m(
            args.depot_lat,
            args.depot_lon,
            lat,
            lon,
        )
        if distance_m > args.mec_radius_km * 1000.0:
            continue
        filtered_communications.append(
            {
                "objectid": (
                    props.get("OBJECTID")
                    or props.get("objectid")
                ),
                "name": (
                    props.get("COMMUNICATIONS_SITE_NAME")
                    or props.get("communications_site_name")
                ),
                "national_forest": forest,
                "district": props.get("DISTRICT") or props.get("district"),
                "designation": (
                    props.get("DESIGNATION")
                    or props.get("designation")
                ),
                "latitude": lat,
                "longitude": lon,
                "distance_from_depot_m": distance_m,
                "site_elevation": (
                    props.get("SITE_ELEVATION")
                    or props.get("site_elevation")
                ),
                "fiber_optic": (
                    props.get("FIBER_OPTIC")
                    or props.get("fiber_optic")
                ),
                "power": props.get("POWER") or props.get("power"),
            }
        )
    filtered_communications.sort(
        key=lambda item: item["distance_from_depot_m"]
    )

    fire_features = _fetch_arcgis_features(
        FIRE_OCCURRENCE_URL,
        where="1 = 1",
        out_fields=(
            "OBJECTID,FIREOCCURID,FIRENAME,FIREYEAR,TOTALACRES,"
            "STATCAUSE,UNITIDOWNER,UNITIDPROTECT,LATDD83,LONGDD83"
        ),
        geometry=_bbox(
            args.depot_lat,
            args.depot_lon,
            args.task_radius_km,
        ),
    )
    fires: list[dict[str, Any]] = []
    for feature in fire_features:
        props = feature.get("properties", {})
        lon, lat = _point_lon_lat(feature)
        distance_m = _haversine_m(
            args.depot_lat,
            args.depot_lon,
            lat,
            lon,
        )
        if distance_m > args.task_radius_km * 1000.0:
            continue
        fires.append(
            {
                "objectid": props.get("OBJECTID") or props.get("objectid"),
                "fireoccurid": (
                    props.get("FIREOCCURID")
                    or props.get("fireoccurid")
                ),
                "fire_name": props.get("FIRENAME") or props.get("firename"),
                "fire_year": props.get("FIREYEAR") or props.get("fireyear"),
                "total_acres": (
                    props.get("TOTALACRES")
                    or props.get("totalacres")
                ),
                "stat_cause": (
                    props.get("STATCAUSE")
                    or props.get("statcause")
                ),
                "latitude": lat,
                "longitude": lon,
                "distance_from_depot_m": distance_m,
            }
        )
    fires.sort(
        key=lambda item: (
            -(int(item["fire_year"]) if item["fire_year"] else 0),
            item["distance_from_depot_m"],
            int(item["objectid"]) if item["objectid"] else 0,
        )
    )

    payload = {
        "case_name": "Stanislaus / Groveland real-geography scout",
        "depot": {
            "name": "Groveland Ranger District Office",
            "latitude": args.depot_lat,
            "longitude": args.depot_lon,
            "coordinate_note": (
                "Coordinate anchored to the published ranger-station location; "
                "the official USFS address is 24545 Highway 120, Groveland, CA."
            ),
        },
        "sources": {
            "communications": COMMUNICATION_SITES_URL,
            "fire_occurrence": FIRE_OCCURRENCE_URL,
        },
        "parameters": {
            "task_radius_km": args.task_radius_km,
            "mec_radius_km": args.mec_radius_km,
        },
        "communication_sites": filtered_communications,
        "fire_occurrences": fires,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(
        f"communications_within_{args.mec_radius_km:g}km="
        f"{len(filtered_communications)}"
    )
    for index, site in enumerate(
        filtered_communications[:12],
        start=1,
    ):
        print(
            f"MEC-CANDIDATE {index:02d} "
            f"name={site['name']!r} "
            f"distance_km={site['distance_from_depot_m']/1000.0:.3f} "
            f"lat={site['latitude']:.6f} "
            f"lon={site['longitude']:.6f} "
            f"district={site['district']!r}"
        )

    print(
        f"fire_occurrences_within_{args.task_radius_km:g}km={len(fires)}"
    )
    for radius_km in (2, 4, 6, 8, 10, 12):
        count = sum(
            item["distance_from_depot_m"] <= radius_km * 1000.0
            for item in fires
        )
        print(f"fire_count_within_km radius={radius_km} count={count}")
    for radius_km in (5, 10, 15, 20, 30, 35):
        count = sum(
            item["distance_from_depot_m"] <= radius_km * 1000.0
            for item in filtered_communications
        )
        print(
            f"communication_count_within_km "
            f"radius={radius_km} count={count}"
        )
    years = [
        int(item["fire_year"])
        for item in fires
        if item["fire_year"] is not None
    ]
    if years:
        print(f"fire_year_range={min(years)}..{max(years)}")
    if fires:
        distances = [item["distance_from_depot_m"] for item in fires]
        print(
            "fire_distance_km="
            f"min={min(distances)/1000.0:.3f},"
            f"max={max(distances)/1000.0:.3f}"
        )
    print(f"saved={out}")


if __name__ == "__main__":
    main()
