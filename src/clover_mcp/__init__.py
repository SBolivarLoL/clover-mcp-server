"""clover-mcp — MCP server for the Clover POS REST API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("clover-mcp")
except PackageNotFoundError:  # not installed (e.g. running from a raw source tree)
    __version__ = "0.0.0+unknown"
