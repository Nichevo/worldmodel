"""Source connectors. Add a new one here and in contract sources.yaml."""

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.imf_weo import IMFWEO
from worldmodel_data.connectors.un_wpp import UNWPP

CONNECTORS: dict[str, type[Connector]] = {c.source_id: c for c in (UNWPP, IMFWEO)}

__all__ = ["CONNECTORS", "Connector", "ConnectorError"]
