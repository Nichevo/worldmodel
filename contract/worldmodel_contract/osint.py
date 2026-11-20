"""Detail from the open-source intelligence (OSINT) communities: located fighting and unrest,
war trackers (equipment lost, ground held), internet outages, sanctions in force, military
strength by country and arms deals. Shared by the data side (connectors/conflict_events.py,
wars.py, outages.py, sanctions_now.py, military.py; osint_tables.py) and the app.

Everything here is about naming and grouping: which kinds of event there are, which wars are
tracked (wars.yaml), who a sanctions list belongs to, and what Global Firepower measures."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

CATALOGUES = Path(__file__).parent / "catalogues"

# ----------------------------------------------------------------------------- located events
# kind -> (label, colour group). UCDP's three types of violence and ACLED's six event types.
EVENT_KINDS: dict[str, tuple[str, str]] = {
    "state": ("Fighting between a state and an armed group", "fight"),
    "nonstate": ("Fighting between armed groups", "fight"),
    "onesided": ("Killing of civilians by an armed group or state", "civilian"),
    "battle": ("Battle", "fight"),
    "explosion": ("Explosion or remote violence (shelling, air and drone strikes, mines)", "fight"),
    "civilians": ("Violence against civilians", "civilian"),
    "protest": ("Protest", "protest"),
    "riot": ("Riot", "riot"),
    "strategic": ("Strategic development (arrests, looting, troop moves, agreements)", "other"),
}
UCDP_TYPES = {"1": "state", "2": "nonstate", "3": "onesided"}
ACLED_TYPES = {"battles": "battle", "explosions/remote violence": "explosion", "violence against civilians": "civilians",
               "protests": "protest", "riots": "riot", "strategic developments": "strategic"}
# Kinds counted as political violence (ACLED's own grouping); protests and riots are unrest.
VIOLENCE = {"state", "nonstate", "onesided", "battle", "explosion", "civilians"}
UNREST = {"protest", "riot"}


def acled_kind(event_type: str) -> str:
    return ACLED_TYPES.get((event_type or "").strip().lower(), "strategic")


# ----------------------------------------------------------------------------- wars
@lru_cache
def wars() -> list[dict]:
    """The wars tracked (wars.yaml): id, name, sides (entity ids), when it began, and where
    each kind of data comes from. A new war is a new entry; nothing else has to change."""
    data = yaml.safe_load((CATALOGUES / "wars.yaml").read_text(encoding="utf-8")) or {}
    return list(data.get("wars") or [])


def war(war_id: str) -> dict | None:
    return next((w for w in wars() if w["id"] == war_id), None)


# Oryx's equipment categories, in its own words, with a short id each.
LOSS_CATEGORIES: dict[str, str] = {
    "tanks": "Tanks", "afv": "Armoured fighting vehicles", "ifv": "Infantry fighting vehicles",
    "apc": "Armoured personnel carriers", "mrap": "Mine-resistant ambush protected vehicles",
    "imv": "Infantry mobility vehicles", "command": "Command posts and communications stations",
    "engineering": "Engineering vehicles and equipment", "ugv": "Unmanned ground vehicles",
    "sp_atgm": "Self-propelled anti-tank missile systems", "artillery_support": "Artillery support vehicles and equipment",
    "towed_artillery": "Towed artillery", "sp_artillery": "Self-propelled artillery", "mrl": "Multiple rocket launchers",
    "aa_guns": "Anti-aircraft guns", "sp_aa_guns": "Self-propelled anti-aircraft guns", "sam": "Surface-to-air missile systems",
    "radars": "Radars", "jammers": "Jammers and deception systems", "aircraft": "Aircraft", "helicopters": "Helicopters",
    "uav": "Unmanned aerial vehicles", "naval": "Naval ships and submarines", "logistics": "Trucks, vehicles and jeeps",
    "total": "All equipment",
}
_CATEGORY_WORDS = [  # (pattern on Oryx's heading, id): first match wins
    (r"^tanks?\b", "tanks"), (r"^armou?red fighting", "afv"), (r"^infantry fighting", "ifv"),
    (r"^armou?red personnel", "apc"), (r"^mine-resistant|^mrap", "mrap"), (r"^infantry mobility", "imv"),
    (r"^command posts|^communications", "command"), (r"^engineering", "engineering"), (r"^unmanned ground", "ugv"),
    (r"^self-propelled anti-tank", "sp_atgm"), (r"^artillery support", "artillery_support"), (r"^towed artillery", "towed_artillery"),
    (r"^self-propelled artillery", "sp_artillery"), (r"^multiple rocket", "mrl"), (r"^anti-aircraft guns", "aa_guns"),
    (r"^self-propelled anti-aircraft", "sp_aa_guns"), (r"^surface-to-air", "sam"), (r"^radars?", "radars"),
    (r"^jammers", "jammers"), (r"^aircraft", "aircraft"), (r"^helicopters", "helicopters"),
    (r"^unmanned aerial|^reconnaissance unmanned|^combat unmanned", "uav"), (r"^naval|^ships|^submarines", "naval"),
    (r"^trucks|^vehicles", "logistics"),
]
LOSS_STATUSES = ("destroyed", "damaged", "abandoned", "captured")
# The Ukrainian General Staff's claimed figures (keys as published) to the same ids.
CLAIMED_CATEGORIES = {"tank": "tanks", "APC": "afv", "field artillery": "towed_artillery", "MRL": "mrl",
                      "anti-aircraft warfare": "sam", "aircraft": "aircraft", "helicopter": "helicopters", "drone": "uav",
                      "naval ship": "naval", "vehicles and fuel tanks": "logistics", "personnel": "personnel"}
LOSS_CATEGORIES["personnel"] = "Soldiers killed or wounded (claimed)"


def loss_category(heading: str) -> str | None:
    h = (heading or "").strip().lower()
    for pat, cid in _CATEGORY_WORDS:
        if re.search(pat, h):
            return cid
    return None


# ----------------------------------------------------------------------------- sanctions
# Who a sanctions list belongs to, from its name in OpenSanctions (first match wins). The code
# is an entity id where there is one (eu is the European Union bloc), else "un" or "other".
AUTHORITIES: list[tuple[str, str, str]] = [
    (r"\bnew zealand|\bnz\b", "NZL", "New Zealand"),
    (r"\baustralia|\bdfat\b|\bau\b", "AUS", "Australia"),
    (r"\bunited kingdom|\buk\b|\bhm treasury|\bofsi\b|\bgb\b|\bfcdo\b", "GBR", "United Kingdom"),
    (r"\bunited states|\bus\b|\bofac\b|\bbis\b|\bstate department|\bu\.s\.", "USA", "United States"),
    (r"\beuropean union|\beu\b|\bfsf\b", "eu", "European Union"),
    (r"\bun security council|\bunited nations|\bun sc\b|\bun\b", "un", "UN Security Council"),
    (r"\bcanada|\bcanadian|\bsema\b|\bca\b", "CAN", "Canada"),
    (r"\bjapan|\bjp\b", "JPN", "Japan"),
    (r"\bswitzerland|\bswiss|\bseco\b|\bch\b", "CHE", "Switzerland"),
    (r"\bukraine|\bnsdc\b|\bua\b", "UKR", "Ukraine"),
    (r"\bfrance|\bfr\b", "FRA", "France"),
    (r"\bsingapore|\bsg\b", "SGP", "Singapore"),
    (r"\bkorea|\bkr\b", "KOR", "South Korea"),
    (r"\bchina|\bmofcom\b|\bcn\b", "CHN", "China"),
    (r"\brussia|\bru\b", "RUS", "Russia"),
]
AUTHORITY_NAMES = {code: name for _, code, name in AUTHORITIES} | {"other": "Other lists"}
# The columns of the Relationships page's matrix, in order (key countries first).
MATRIX_AUTHORITIES = ("NZL", "AUS", "GBR", "USA", "eu", "CAN", "JPN", "CHE", "un")


def authority(list_name: str) -> str:
    t = (list_name or "").lower().replace("_", " ")
    for pat, code, _ in AUTHORITIES:
        if re.search(pat, t):
            return code
    return "other"


# ----------------------------------------------------------------------------- military strength
# Global Firepower's measures: (id, its label on a country page as a pattern, name, unit, group).
# The page shows "<label>: <number>"; the reader takes the first number after each label.
GFP_MEASURES: list[tuple[str, str, str, str, str]] = [
    ("gfp_power_index", r"PwrIndx", "PowerIndex (Global Firepower's own score; lower is stronger)", "score", "score"),
    ("gfp_personnel_total", r"Total Military Personnel", "Military personnel, all", "people", "people"),
    ("gfp_personnel_active", r"Active Personnel", "Active troops", "people", "people"),
    ("gfp_personnel_reserve", r"Reserve Personnel", "Reserve troops", "people", "people"),
    ("gfp_personnel_paramilitary", r"Paramilitary", "Paramilitary", "people", "people"),
    ("gfp_aircraft_total", r"(?:Total )?Aircraft Strength|Aircraft Total", "Aircraft, all", "aircraft", "air"),
    ("gfp_aircraft_fighters", r"Fighters?(?:/Interceptors)?", "Fighters", "aircraft", "air"),
    ("gfp_aircraft_attack", r"Attack Types|Dedicated Attack", "Attack aircraft", "aircraft", "air"),
    ("gfp_aircraft_transports", r"Transports", "Transport aircraft", "aircraft", "air"),
    ("gfp_aircraft_trainers", r"Trainers", "Trainer aircraft", "aircraft", "air"),
    ("gfp_aircraft_special", r"Special-Mission", "Special-mission aircraft", "aircraft", "air"),
    ("gfp_aircraft_tankers", r"Tanker Fleet|Tankers", "Tanker aircraft", "aircraft", "air"),
    ("gfp_helicopters", r"Helicopters", "Helicopters, all", "helicopters", "air"),
    ("gfp_helicopters_attack", r"Attack Helicopters", "Attack helicopters", "helicopters", "air"),
    ("gfp_tanks", r"Tanks|Tank Strength", "Tanks", "tanks", "land"),
    ("gfp_vehicles", r"(?:Armou?red )?Vehicles|AFVs", "Armoured vehicles", "vehicles", "land"),
    ("gfp_sp_artillery", r"Self-Propelled Artillery", "Self-propelled artillery", "guns", "land"),
    ("gfp_towed_artillery", r"Towed Artillery", "Towed artillery", "guns", "land"),
    ("gfp_mlrs", r"(?:Rocket Projectors|MLRS)", "Rocket launchers", "launchers", "land"),
    ("gfp_navy_total", r"(?:Total )?Naval (?:Assets|Strength)|Navy Fleet Strength|Fleet Strength", "Navy ships, all", "ships", "sea"),
    ("gfp_carriers", r"Aircraft Carriers", "Aircraft carriers", "ships", "sea"),
    ("gfp_helo_carriers", r"Helo(?:copter)? Carriers", "Helicopter carriers", "ships", "sea"),
    ("gfp_submarines", r"Submarines", "Submarines", "ships", "sea"),
    ("gfp_destroyers", r"Destroyers", "Destroyers", "ships", "sea"),
    ("gfp_frigates", r"Frigates", "Frigates", "ships", "sea"),
    ("gfp_corvettes", r"Corvettes", "Corvettes", "ships", "sea"),
    ("gfp_patrol", r"Patrol Vessels", "Patrol vessels", "ships", "sea"),
    ("gfp_mine_warfare", r"Mine Warfare", "Mine warfare ships", "ships", "sea"),
    ("gfp_budget_usd", r"Defen[cs]e Budget", "Defence budget (Global Firepower)", "US$", "money"),
    ("gfp_merchant_fleet", r"Merchant Marine(?: Fleet)?", "Merchant ships", "ships", "logistics"),
    ("gfp_airports", r"Airports", "Airports", "airports", "logistics"),
    ("gfp_ports", r"Ports(?: & Terminals)?", "Ports and terminals", "ports", "logistics"),
]
GFP_GROUPS = {"score": "Score", "people": "People", "air": "Air", "land": "Land", "sea": "Sea", "money": "Money",
              "logistics": "Logistics"}
# A second source shown beside a Global Firepower measure, where the app already has one.
GFP_ALSO = {"gfp_personnel_active": "armed_forces", "gfp_budget_usd": "military_spending_usd"}
