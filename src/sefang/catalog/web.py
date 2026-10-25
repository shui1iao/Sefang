"""Compatibility import, no independent collection implementation."""
import sys
from se_catalog.catalog import web as _shared
sys.modules[__name__] = _shared
