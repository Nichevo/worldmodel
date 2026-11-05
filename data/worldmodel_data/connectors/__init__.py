"""Source connectors. Add a new one here and in contract sources.yaml."""

from worldmodel_data.connectors.ai_use import AnthropicAEI, EurostatAI, MicrosoftAIDiffusion
from worldmodel_data.connectors.base import Connector, ConnectorError
from worldmodel_data.connectors.cia_factbook import CIAFactbook
from worldmodel_data.connectors.cities import UNWUP, GeoNames, ILOEarnings, Numbeo, WhereNext
from worldmodel_data.connectors.coups import Coups
from worldmodel_data.connectors.crisiswatch import CrisisWatch
from worldmodel_data.connectors.education import UNDPHDR, Wittgenstein
from worldmodel_data.connectors.emdat import EMDAT
from worldmodel_data.connectors.forecasters import OECDEO, WorldBankGEP
from worldmodel_data.connectors.housing import BIS, OECD, DallasFedIHPD, IMFGDD
from worldmodel_data.connectors.imf_weo import IMFWEO
from worldmodel_data.connectors.imf_weo_history import IMFWEOHistory
from worldmodel_data.connectors.laws import WBL, GunPolicy, NagerHolidays, RulesCurated, UNODCCrime, WorldPolicy, WorldPrisonBrief
from worldmodel_data.connectors.layers import GEMFaults, GVPVolcanoes, PlatesBird, USGSEarthquakes
from worldmodel_data.connectors.migration import UNHCR, UNIMS
from worldmodel_data.connectors.nz import RBNZ, MBIEEnergy, NZCorrections
from worldmodel_data.connectors.owid import OWIDEnergy, OWIDGrapher
from worldmodel_data.connectors.turnout import IDEATurnout
from worldmodel_data.connectors.ucdp import UCDPConflicts
from worldmodel_data.connectors.un_wpp import UNWPP
from worldmodel_data.connectors.voters import NZElectionTurnout, USCensusVoting
from worldmodel_data.connectors.wikidata import Wikidata
from worldmodel_data.connectors.places import WikidataPlaces
from worldmodel_data.connectors.sectors import BACI, FAOSTAT, IEAEV, PinkSheet, USGSMinerals, WorldMiningData
from worldmodel_data.connectors.world_bank_wdi import WorldBankWDI
from worldmodel_data.connectors.world_bodies import GlobalSanctions, IMFMona, UNGAVotes, UNTreaties, UNVetoes, WTODisputes
from worldmodel_data.connectors.zones import CelesTrakSatcat, NSIDCSeaIce

CONNECTORS: dict[str, type[Connector]] = {c.source_id: c for c in (
    UNWPP, IMFWEO, IMFWEOHistory, WorldBankWDI, OWIDEnergy, OWIDGrapher, CIAFactbook, Wikidata,
    Coups, UCDPConflicts, EMDAT, BIS, OECD, DallasFedIHPD, IMFGDD, UNIMS, UNHCR, Wittgenstein, UNDPHDR,
    IDEATurnout, PlatesBird, GEMFaults, GVPVolcanoes, USGSEarthquakes, OECDEO, WorldBankGEP, EurostatAI, AnthropicAEI,
    MicrosoftAIDiffusion, RBNZ, NZCorrections, MBIEEnergy, USCensusVoting, NZElectionTurnout,
    GeoNames, UNWUP, WhereNext, ILOEarnings, Numbeo, WikidataPlaces,
    UNGAVotes, UNVetoes, GlobalSanctions, IMFMona, WTODisputes, UNTreaties, CrisisWatch, NSIDCSeaIce, CelesTrakSatcat,
    NagerHolidays, WBL, UNODCCrime, RulesCurated, WorldPolicy, GunPolicy, WorldPrisonBrief,
    BACI, USGSMinerals, WorldMiningData, FAOSTAT, PinkSheet, IEAEV)}

__all__ = ["CONNECTORS", "Connector", "ConnectorError"]
