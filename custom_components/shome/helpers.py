"""Shared setup helpers for sHome platforms."""
from __future__ import annotations

from .coordinator import ShomeCoordinator


def inventory_by_id(coordinator: ShomeCoordinator) -> dict[str, dict]:
    """Map inventory id (e.g. 'jm01') -> {name, location, model}."""
    out: dict[str, dict] = {}
    for item in coordinator.data.get("inventory", []):
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def device_name(inv: dict[str, dict], prefix: str, address: str, fallback: str) -> str:
    """Friendly name from inventory (location/name), keyed by <prefix><address>."""
    item = inv.get(f"{prefix}{address}", {})
    return (
        item.get("name")
        or item.get("location")
        or fallback
    )
