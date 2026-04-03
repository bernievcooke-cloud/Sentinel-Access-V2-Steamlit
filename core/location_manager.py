#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class LocationManager:
    """
    Flexible, case-insensitive Location Manager with auto-save.

    Goals:
    - Case-insensitive lookups
    - Flexible alias matching:
        "Bells Beach" == "BellsBeach" == "bells beach" == "Bells Beach, VIC"
    - Consistent on-disk schema:
        {
          "Bells Beach, VIC": {
            "display_name": "Bells Beach, VIC",
            "latitude": -38.37,
            "longitude": 144.28,
            "state": "VIC"
          }
        }

    Compatibility:
    - Reads legacy coordinate keys: lat/lon/LAT/LON/lng/x/y etc.
    - Reads older JSON top-level keys like "BellsBeach"
    - Saves canonical keys: display_name, latitude, longitude, state
    - Preserves extra fields already present
    """

    CANON_LAT_KEYS = ["latitude", "lat", "LAT", "Latitude", "y", "Y"]
    CANON_LON_KEYS = ["longitude", "lon", "lng", "LON", "LNG", "Longitude", "x", "X"]

    STATE_CODES = {
        "ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"
    }

    def __init__(self, locations_path: str | None = None):
        project_root = Path(__file__).resolve().parents[1]
        self.locations_path = Path(locations_path) if locations_path else (project_root / "config" / "locations.json")

        # canonical display_name -> payload
        self._locations: dict[str, dict[str, Any]] = {}

        # alias -> canonical display_name
        self._index: dict[str, str] = {}

        self._load()

    # -----------------------------
    # Public API
    # -----------------------------
    def locations(self) -> list[str]:
        """Return canonical display names in stable sorted order."""
        return sorted(self._locations.keys(), key=lambda s: s.casefold())

    def get(self, name: str) -> dict[str, Any] | None:
        """
        Flexible lookup by name.

        Supports:
        - exact / case-insensitive
        - spaces removed
        - punctuation-normalized
        - optional ', STATE' stripping
        - old source-key forms like BellsBeach
        """
        for alias in self._name_variants(name):
            display = self._index.get(alias)
            if display:
                return self._locations.get(display)
        return None

    def add_or_update(self, name: str, lat: float, lon: float, **extra_fields: Any) -> str:
        """
        Add or update a location using flexible name matching.

        Returns the stored canonical display name.
        """
        if not name or not name.strip():
            raise ValueError("Location name cannot be empty.")

        display_name_input = self._canonical_display_name(name.strip(), extra_fields.get("state"))

        lat = float(lat)
        lon = float(lon)

        existing_display = self._find_existing_display_name(display_name_input)
        display = existing_display or display_name_input

        payload: dict[str, Any] = {}
        if existing_display and existing_display in self._locations:
            payload = dict(self._locations[existing_display])

        payload["display_name"] = display
        payload["latitude"] = lat
        payload["longitude"] = lon

        for k, v in extra_fields.items():
            if k in ("lat", "lon", "LAT", "LON", "lng", "LNG", "x", "X", "y", "Y"):
                continue
            if k in ("latitude", "longitude"):
                continue
            payload[k] = v

        # When user updates/creates directly, the new canonical record should
        # become the authoritative version. We do not preserve old _source_key
        # values here because saving uses canonical display_name keys anyway.
        payload.pop("_source_key", None)

        self._locations[display] = payload
        self._rebuild_index()

        self._save()
        return display

    def rename(self, old_name: str, new_name: str) -> str:
        old_display = self._find_existing_display_name(old_name)
        if not old_display:
            raise KeyError(f"Location not found: {old_name}")

        new_display = (new_name or "").strip()
        if not new_display:
            raise ValueError("New name cannot be empty.")

        collision = self._find_existing_display_name(new_display)
        if collision and collision != old_display:
            raise ValueError(f"Cannot rename: '{new_name}' would collide with existing '{collision}'.")

        payload = self._locations.pop(old_display)
        payload["display_name"] = new_display
        payload.pop("_source_key", None)

        self._locations[new_display] = payload
        self._rebuild_index()

        self._save()
        return new_display

    def delete(self, name: str) -> bool:
        display = self._find_existing_display_name(name)
        if not display:
            return False

        self._locations.pop(display, None)
        self._rebuild_index()

        self._save()
        return True

    def reload(self) -> None:
        self._load()

    # -----------------------------
    # Internal helpers
    # -----------------------------
    @staticmethod
    def _first_number(payload: dict[str, Any], keys: list[str]) -> float | None:
        for k in keys:
            if k in payload:
                try:
                    v = payload.get(k)
                    if v is None:
                        continue
                    return float(v)
                except Exception:
                    continue
        return None

    @staticmethod
    def _normalize_text(value: str) -> str:
        """
        Lowercase, trim, normalize punctuation/spaces.
        Keeps commas for state parsing, then compresses whitespace.
        """
        s = (value or "").strip().casefold()
        s = s.replace("_", " ")
        s = re.sub(r"[^\w\s,]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def _compact_text(value: str) -> str:
        """Remove all non-alphanumeric characters."""
        return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())

    def _strip_trailing_state(self, value: str) -> str:
        """
        Strip trailing ', VIC' / ', NSW' etc if present.
        """
        s = self._normalize_text(value)
        m = re.match(r"^(.*?),\s*([a-z]{2,3})$", s)
        if not m:
            return s
        base, maybe_state = m.group(1).strip(), m.group(2).upper()
        if maybe_state in self.STATE_CODES:
            return base
        return s

    def _name_variants(self, name: str) -> list[str]:
        """
        Generate all aliases that should map to the same location.
        """
        raw = (name or "").strip()
        if not raw:
            return []

        normalized = self._normalize_text(raw)
        stripped_state = self._strip_trailing_state(raw)

        candidates = {
            normalized,
            self._compact_text(normalized),
            stripped_state,
            self._compact_text(stripped_state),
        }

        # Also add versions with commas removed but spaces preserved
        no_comma = normalized.replace(",", " ")
        no_comma = re.sub(r"\s+", " ", no_comma).strip()

        stripped_no_comma = stripped_state.replace(",", " ")
        stripped_no_comma = re.sub(r"\s+", " ", stripped_no_comma).strip()

        candidates.update({
            no_comma,
            self._compact_text(no_comma),
            stripped_no_comma,
            self._compact_text(stripped_no_comma),
        })

        return [c for c in candidates if c]

    def _canonical_display_name(self, name: str, state: Any = None) -> str:
        """
        Prefer a clean display name.
        If state is supplied and name doesn't already end with ', ST', append it.
        """
        clean = re.sub(r"\s+", " ", (name or "").strip())
        if not clean:
            raise ValueError("Location name cannot be empty.")

        state_str = str(state).strip().upper() if state is not None else ""
        if state_str in self.STATE_CODES:
            norm = self._normalize_text(clean)
            if not re.search(rf",\s*{state_str.casefold()}$", norm):
                return f"{clean}, {state_str}"

        return clean

    def _normalize_payload(self, key_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize to internal canonical keys:
          display_name, latitude, longitude, state (optional), extras preserved
        """
        out = dict(payload)

        lat = self._first_number(out, self.CANON_LAT_KEYS)
        lon = self._first_number(out, self.CANON_LON_KEYS)

        if lat is not None:
            out["latitude"] = lat
        if lon is not None:
            out["longitude"] = lon

        display_name = str(out.get("display_name") or key_name).strip()
        out["display_name"] = display_name

        # Preserve the original JSON key so older compact keys like BellsBeach
        # can still be indexed and resolved during this run.
        out["_source_key"] = str(key_name).strip()

        for k in ["lat", "lon", "LAT", "LON", "lng", "LNG", "x", "X", "y", "Y", "Latitude", "Longitude"]:
            out.pop(k, None)

        return out

    def _find_existing_display_name(self, name: str) -> str | None:
        for alias in self._name_variants(name):
            display = self._index.get(alias)
            if display:
                return display
        return None

    def _register_aliases_for_display(self, display_name: str, payload: dict[str, Any]) -> None:
        """
        Register aliases from:
        - canonical display name
        - payload display_name
        - original JSON top-level key (e.g. BellsBeach)
        - display_name without trailing state
        """
        values_to_index = {
            display_name,
            str(payload.get("display_name", "")).strip(),
        }

        source_key = str(payload.get("_source_key", "")).strip()
        if source_key:
            values_to_index.add(source_key)

        state = str(payload.get("state", "")).strip().upper()
        if state:
            stripped = self._strip_trailing_state(display_name)
            if stripped:
                values_to_index.add(stripped)

        for value in values_to_index:
            for alias in self._name_variants(value):
                self._index[alias] = display_name

    def _rebuild_index(self) -> None:
        self._index.clear()
        rebuilt: dict[str, dict[str, Any]] = {}

        for display_name, payload in list(self._locations.items()):
            canonical_display = str(payload.get("display_name") or display_name).strip()
            payload["display_name"] = canonical_display
            rebuilt[canonical_display] = payload

        self._locations = rebuilt

        for display_name, payload in self._locations.items():
            self._register_aliases_for_display(display_name, payload)

    # -----------------------------
    # Internal load/save
    # -----------------------------
    def _load(self) -> None:
        self._locations.clear()
        self._index.clear()

        if not self.locations_path.exists():
            self.locations_path.parent.mkdir(parents=True, exist_ok=True)
            self._save()
            return

        raw = self.locations_path.read_text(encoding="utf-8").strip()
        if not raw:
            return

        data = json.loads(raw)

        if isinstance(data, dict):
            for key_name, payload in data.items():
                if not isinstance(payload, dict):
                    continue
                norm = self._normalize_payload(str(key_name), payload)
                display_name = str(norm.get("display_name") or key_name).strip()
                self._locations[display_name] = norm

        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                key_name = str(item.get("name", "")).strip()
                if not key_name:
                    continue
                payload = dict(item)
                payload.pop("name", None)

                norm = self._normalize_payload(key_name, payload)
                display_name = str(norm.get("display_name") or key_name).strip()
                self._locations[display_name] = norm

        self._rebuild_index()

    def _save(self) -> None:
        """
        Save as dict keyed by canonical display name.
        Writes atomically.
        """
        self.locations_path.parent.mkdir(parents=True, exist_ok=True)

        cleaned: dict[str, dict[str, Any]] = {}

        for name, payload in sorted(self._locations.items(), key=lambda x: x[0].casefold()):
            if not isinstance(payload, dict):
                continue

            p = dict(payload)
            p["display_name"] = str(p.get("display_name") or name).strip()

            lat = self._first_number(p, ["latitude"])
            lon = self._first_number(p, ["longitude"])

            if lat is not None:
                p["latitude"] = float(lat)
            if lon is not None:
                p["longitude"] = float(lon)

            # internal-only helper; do not persist
            p.pop("_source_key", None)

            for k in ["lat", "lon", "LAT", "LON", "lng", "LNG", "x", "X", "y", "Y", "Latitude", "Longitude"]:
                p.pop(k, None)

            cleaned[p["display_name"]] = p

        tmp = self.locations_path.with_suffix(self.locations_path.suffix + ".tmp")
        tmp.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.locations_path)