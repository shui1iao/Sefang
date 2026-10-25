"""Compatibility import; implementation lives only in the versioned shared wheel."""
import sys
from se_catalog import codes as _shared
sys.modules[__name__] = _shared
