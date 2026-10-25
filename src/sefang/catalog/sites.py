"""Compatibility import, no independent collection implementation."""
import sys
from se_catalog.catalog import sites as _shared
sys.modules[__name__] = _shared
