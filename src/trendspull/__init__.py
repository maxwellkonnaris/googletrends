"""Collect Google Trends timelines as a portable tidy table."""
from ._api import _VERSION as __version__
from ._api import pull_trends
from ._transform import selected_proportions

__all__ = ["pull_trends", "selected_proportions"]
