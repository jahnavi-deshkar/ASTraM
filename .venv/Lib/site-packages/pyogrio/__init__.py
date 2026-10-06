"""Bulk-oriented vector I/O using OGR."""


# start delvewheel patch
def _delvewheel_patch_1_13_0():
    import os
    if os.path.isdir(libs_dir := os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'pyogrio.libs'))):
        os.add_dll_directory(libs_dir)


_delvewheel_patch_1_13_0()
del _delvewheel_patch_1_13_0
# end delvewheel patch

try:
    # we try importing shapely, to ensure it is imported (and it can load its
    # own GEOS copy) before we load GDAL and its linked GEOS
    import shapely

    if shapely.__version__ < "2.0.0":
        import shapely.geos
except Exception:
    pass

from pyogrio._version import get_versions
from pyogrio.core import (
    __gdal_geos_version__,
    __gdal_version__,
    __gdal_version_string__,
    detect_write_driver,
    get_gdal_config_option,
    get_gdal_data_path,
    list_drivers,
    list_drivers_details,
    list_layers,
    read_bounds,
    read_info,
    set_gdal_config_options,
    vsi_curl_clear_cache,
    vsi_listtree,
    vsi_rmtree,
    vsi_unlink,
)
from pyogrio.geopandas import read_dataframe, write_dataframe
from pyogrio.raw import open_arrow, read_arrow, write_arrow

__version__ = get_versions()["version"]
del get_versions

__all__ = [
    "__gdal_geos_version__",
    "__gdal_version__",
    "__gdal_version_string__",
    "__version__",
    "detect_write_driver",
    "get_gdal_config_option",
    "get_gdal_data_path",
    "list_drivers",
    "list_drivers_details",
    "list_layers",
    "open_arrow",
    "read_arrow",
    "read_bounds",
    "read_dataframe",
    "read_info",
    "set_gdal_config_options",
    "vsi_curl_clear_cache",
    "vsi_listtree",
    "vsi_rmtree",
    "vsi_unlink",
    "write_arrow",
    "write_dataframe",
]
