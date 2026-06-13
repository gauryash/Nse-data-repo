"""
Parse NSE F&O tradingsymbols into underlying name and expiry components.
"""

from __future__ import annotations

import re


class FnoSymbolParser:
    """Extract underlying name and expiry short-code from a tradingsymbol.

    Handles two symbol formats:

    **Stock options / futures** (``YYMON``):
        ``WIPRO26JUN160CE`` -> (``WIPRO``, ``26JUN``)

    **Index options** (``YYMMDD``):
        ``NIFTY26060921100CE`` -> (``NIFTY``, ``260609``)
    """

    _STOCK_PATTERN = re.compile(r"^([A-Za-z]+)(\d{2}[A-Za-z]{3})")
    _INDEX_PATTERN = re.compile(r"^([A-Za-z]+)(\d{2}(?:0[1-9]|1[012])(?:0[1-9]|[12]\d|3[01]))")

    @staticmethod
    def extract_underlying(symbol: str) -> str:
        """Return the leading alpha characters (e.g. ``'WIPRO'``, ``'NIFTY'``)."""
        m = re.match(r"^([A-Za-z]+)", symbol)
        return m.group(1).upper() if m else ""

    @staticmethod
    def parse(symbol: str) -> tuple[str, str]:
        """Parse into ``(underlying, expiry_short)``.

        Returns ``('', '')`` if no format matches.
        """
        m = FnoSymbolParser._STOCK_PATTERN.match(symbol)
        if m:
            return m.group(1).upper(), m.group(2).upper()
        m = FnoSymbolParser._INDEX_PATTERN.match(symbol)
        if m:
            return m.group(1).upper(), m.group(2)
        return "", ""
