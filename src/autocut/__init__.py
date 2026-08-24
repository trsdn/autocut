"""autocut — automated video re-cut pipeline."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("trsdn-autocut")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
