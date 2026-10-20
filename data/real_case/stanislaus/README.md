# Stanislaus Real-Geography Case Study

This directory is reserved for the GIS-driven real-geography validation case
centered on the Groveland Ranger District of Stanislaus National Forest,
California.

The optimization model remains unchanged. Real-world information is used only
to anchor geometry:

- UAV depot: Groveland Ranger District Office;
- MEC candidate sites: USDA Forest Service designated communication sites;
- monitoring-node candidate locations: USDA Forest Service historical fire
  occurrence points;
- all latitude/longitude points will be projected to a local metric coordinate
  system before entering the existing UAV-MEC optimizer.

The communication-site and fire-occurrence datasets are retrieved from official
USDA Forest Service ArcGIS REST services by
`experiments/prepare_stanislaus_real_case.py`.

Important interpretation:

- a communication-site coordinate is a real existing/designated communications
  facility location, but the MEC server itself is a modeled deployment at that
  location;
- a historical fire-occurrence coordinate is used as a prospective monitoring
  location, not as a claim that a sensor is physically installed there;
- this experiment is a real-geography/GIS-driven case study, not a field-flight
  experiment.

## Pinned formal snapshot

The formal K=59 case uses
`usfs_fire_occurrences_selected59_2026-09-22.json`.
It pins the exact 59 unique USFS historical fire-occurrence coordinates
used by the formal 2026-09-22 experiment, so future reruns do not depend
on changes to the live ArcGIS service. The live scout workflow remains
available for provenance checks and future dataset refreshes.
