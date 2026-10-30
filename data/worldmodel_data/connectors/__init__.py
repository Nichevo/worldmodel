"""Source connectors. Add a new one here and in contract sources.yaml."""

from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cia_factbook import CIAFactbook
from worldmodel_data.connectors.coups import Coups
from worldmodel_data.connectors.education import UNDPHDR, Wittgenstein
from worldmodel_data.connectors.emdat import EMDAT
from worldmodel_data.connectors.housing import BIS, OECD, DallasFedIHPD, IMFGDD
from worldmodel_data.connectors.imf_weo import IMFWEO
from worldmodel_data.connectors.imf_weo_history import IMFWEOHistory
from worldmodel_data.connectors.layers import GEMFaults, GVPVolcanoes, PlatesBird, USGSEarthquakes
from worldmodel_data.connectors.migration import UNHCR, UNIMS
from worldmodel_data.connectors.owid import OWIDEnergy, OWIDGrapher
from worldmodel_data.connectors.turnout import IDEATurnout
from worldmodel_data.connectors.ucdp import UCDPConflicts
from worldmodel_data.connectors.un_wpp import UNWPP
from worldmodel_data.connectors.wikidata import Wikidata
from worldmodel_data.connectors.world_bank_wdi import WorldBankWDI

CONNECTORS: dict[str, type[Connector]] = {c.source_id: c for c in (
    UNWPP, IMFWEO, IMFWEOHistory, WorldBankWDI, OWIDEnergy, OWIDGrapher, CIAFactbook, Wikidata,
    Coups, UCDPConflicts, EMDAT, BIS, OECD, DallasFedIHPD, IMFGDD, UNIMS, UNHCR, Wittgenstein, UNDPHDR,
    IDEATurnout, PlatesBird, GEMFaults, GVPVolcanoes, USGSEarthquakes)}

__all__ = ["CONNECTORS", "Connector", "ConnectorError"]
