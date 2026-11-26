"""Collect Google Trends timelines as a portable tidy table."""
from ._api import _VERSION as __version__
from ._api import pull_trends

__all__ = ["pull_trends"]
