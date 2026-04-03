#!/usr/bin/env python3
"""
Report Wrapper - Traffic Controller for all workers.
Ensures the right worker gets the right data payload.
"""

from __future__ import annotations

import inspect

try:
    from core import surf_report_any_location
except Exception as e:
    surf_report_any_location = None
    print(f"IMPORT ERROR: surf_report_any_location -> {e}")

try:
    from core import sky_worker
except Exception as e:
    sky_worker = None
    print(f"IMPORT ERROR: sky_worker -> {e}")

try:
    from core import weather_worker
except Exception as e:
    weather_worker = None
    print(f"IMPORT ERROR: weather_worker -> {e}")

try:
    from core import trip_worker
except Exception as e:
    trip_worker = None
    print(f"IMPORT ERROR: trip_worker -> {e}")


def generate_report(target, kind, data, output_dir, logger=print):
    workers = {
        "surf": surf_report_any_location,
        "sky": sky_worker,
        "weather": weather_worker,
        "trip": trip_worker,
    }

    kind_clean = str(kind or "").lower().strip()
    worker = workers.get(kind_clean)

    if not worker:
        logger(f"❌ Error: No worker found for report type '{kind}'")
        return None

    if worker is None:
        logger(f"❌ Error: {kind_clean}_worker failed to import.")
        return None

    fn = getattr(worker, "generate_report", None)
    if not callable(fn):
        logger(f"❌ Error: {kind_clean}_worker.generate_report not found.")
        return None

    try:
        logger(f"➡ Generating {kind_clean} report for {target}")

        try:
            sig = inspect.signature(fn)
            if "logger" in sig.parameters:
                return fn(target, data, output_dir, logger=logger)
        except Exception:
            pass

        return fn(target, data, output_dir)

    except Exception as e:
        logger(f"❌ Critical failure in {kind_clean}_worker: {e}")
        return None