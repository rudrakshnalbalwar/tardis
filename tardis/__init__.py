# Licensed under a 3-clause BSD style license - see LICENSE.rst

# Packages may add whatever they like to this file, but
# should keep this content at the top.
# ----------------------------------------------------------------------------
import os

__all__ = ['__version__', 'test']

try:
    from .version import version as __version__
except ImportError:
    __version__ = ''

# ----------------------------------------------------------------------------

import sys
import warnings

# ----------------------------------------------------------------------------

if ("astropy.units" in sys.modules) or ("astropy.constants" in sys.modules):
    warnings.warn(
        "Astropy is already imported externally. Astropy should be imported"
        " after TARDIS."
    )
else:
    from astropy import astronomical_constants, physical_constants

    physical_constants.set("codata2014")
    astronomical_constants.set("iau2012")

# ----------------------------------------------------------------------------

from tardis.base import run_tardis
from tardis.io.util import yaml_load_file as yaml_load
