"""Hunch: theses ("takes") turned into managed portfolios on Main Sequence.

The package is the installable backend of the Hunch product. It owns the product layer (user
profiles, their linked venue accounts, takes and Hunch portfolios), while every market primitive
lives in ms-markets tables and every brokerage interaction goes through the venue connector APIs.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
