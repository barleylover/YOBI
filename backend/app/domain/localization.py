from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any


def localization_ids_complete(
    localized_groups: Mapping[str, Any],
    localized_items: Mapping[str, Any],
    group_ids: Collection[str],
    item_ids: Collection[str],
) -> bool:
    """Require exact option ID coverage before serving a localized projection."""

    return set(localized_groups) == set(group_ids) and set(localized_items) == set(item_ids)
