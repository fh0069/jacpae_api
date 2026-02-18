"""
Offer service — discovers the active offer PDF from the local/NAS filesystem.

Naming convention : oferta_YYYYMMDD.pdf  (YYYYMMDD = expiry date)
Location          : <pdf_base_dir>/offers/

Rules
-----
- Only files whose name matches the pattern exactly are considered.
- An offer is active when its expiry date >= today.
- When multiple active offers exist the one with the nearest expiry is chosen.
- If the folder does not exist the function returns None (no exception).
- Files with unexpected names are silently ignored (logged at debug/warning
  level; the full filesystem path is never logged).
"""
import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

from ..core.config import settings

logger = logging.getLogger(__name__)

# Strict pattern: oferta_ + exactly 8 digits + .pdf
_OFFER_RE = re.compile(r"^oferta_(\d{8})\.pdf$")


async def get_active_offer_path() -> Optional[Path]:
    """
    Return the Path of the currently active offer file, or None.

    Scans ``<pdf_base_dir>/offers/`` and applies the selection rules
    described in the module docstring.
    """
    offers_dir = Path(settings.pdf_base_dir) / "offers"

    if not offers_dir.is_dir():
        return None

    today = date.today()
    best: Optional[tuple[date, Path]] = None

    for entry in offers_dir.iterdir():
        if not entry.is_file():
            continue

        m = _OFFER_RE.match(entry.name)
        if not m:
            logger.debug(
                "Offer scan: ignoring '%s' (does not match pattern oferta_YYYYMMDD.pdf)",
                entry.name,
            )
            continue

        date_str = m.group(1)
        try:
            expiry = date(
                int(date_str[:4]),
                int(date_str[4:6]),
                int(date_str[6:8]),
            )
        except ValueError:
            logger.warning(
                "Offer scan: '%s' matches pattern but contains an invalid date — skipping",
                entry.name,
            )
            continue

        if expiry < today:
            continue  # expired — not eligible

        if best is None or expiry < best[0]:
            best = (expiry, entry)

    return best[1] if best is not None else None
