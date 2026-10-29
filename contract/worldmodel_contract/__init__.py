"""Shared contract between the worldmodel data pipeline and the app.

Holds the warehouse schema and its version, and the catalogues of entities,
indicators, sources, named streams and the driver graph. Both components
depend on this package and on nothing of each other.
"""

from worldmodel_contract.schema import SCHEMA_VERSION, is_compatible

__all__ = ["SCHEMA_VERSION", "is_compatible"]
__version__ = "0.1.0"
