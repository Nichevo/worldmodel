"""Add the US states, DC and counties to the entity catalogues (run once; safe to run again).

Reads us_counties.csv beside this script (Census FIPS codes and names) and writes, into
contract/worldmodel_contract/catalogues:
  entities.csv      US-CA (states, type subnational) and US-06037 (counties)
  entity_codes.csv  iso3 scheme (the id itself, as for New Zealand's regions), us_fips
                    (06, 06037) and us_state (CA, and the state's name in capitals)
  subdivisions.csv  states with parent USA (level state), counties with parent their state
                    (level county)
Rows already there for US places are replaced, so the files stay in step with the list.
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).parent
CAT = HERE.parent.parent / "contract" / "worldmodel_contract" / "catalogues"

# Counties that no longer exist as such: kept so older figures still have a place, with the day they ended.
ENDED = {"02261": "2019-01-01", "46113": "2015-05-01", "51515": "2013-07-01",
         **{f"09{c:03d}": "2022-06-06" for c in range(1, 16, 2)}}
KIND = {"Parish": "parish", "Borough": "borough", "Census Area": "census area", "city": "independent city",
        "Municipality": "municipality", "City and Borough": "city and borough", "Planning Region": "planning region"}


def kind_of(name: str) -> str:
    for k in sorted(KIND, key=len, reverse=True):
        if name.endswith(" " + k):
            return KIND[k]
    return "county"


def main() -> None:
    counties = list(csv.DictReader((HERE / "us_counties.csv").open(encoding="utf-8")))
    states: dict[str, tuple[str, str]] = {}
    for c in counties:
        states.setdefault(c["fips"][:2], (c["state"], c["state_name"]))

    ents, codes, subs = [], [], []
    for fips, (usps, sname) in sorted(states.items()):
        eid = f"US-{usps}"
        what = "the federal district (Washington, DC)" if usps == "DC" else "one of the 50 US states"
        ents.append({"entity_id": eid, "name": sname if usps == "DC" else f"State of {sname}", "short_name": sname,
                     "type": "subnational", "synonyms": f"{sname}|{usps}",
                     "description": f"{sname}, {what} (FIPS {fips})."})
        codes += [{"entity_id": eid, "scheme": "iso3", "code": eid}, {"entity_id": eid, "scheme": "us_fips", "code": fips},
                  {"entity_id": eid, "scheme": "us_state", "code": usps}, {"entity_id": eid, "scheme": "us_state", "code": sname.upper()}]
        subs.append({"entity_id": eid, "parent_id": "USA", "level": "state", "code": fips})
    for c in counties:
        fips, name, usps, sname = c["fips"], c["name"], c["state"], c["state_name"]
        eid = f"US-{fips}"
        end = ENDED.get(fips, "")
        ents.append({"entity_id": eid, "name": f"{name}, {sname}", "short_name": f"{name}, {usps}", "type": "subnational",
                     "valid_to": end, "synonyms": name,
                     "description": f"{name}, a {kind_of(name)} of {sname} (FIPS {fips})" + (f"; replaced on {end}." if end else ".")})
        codes += [{"entity_id": eid, "scheme": "iso3", "code": eid}, {"entity_id": eid, "scheme": "us_fips", "code": fips}]
        subs.append({"entity_id": eid, "parent_id": f"US-{usps}", "level": "county", "code": fips})

    def rewrite(name: str, new: list[dict]) -> None:
        path = CAT / name
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)  # other rows kept exactly as written
        cols = next(csv.reader(lines[:1]))
        keep = [ln for ln in lines[1:] if not ln.startswith("US-")]
        if keep and not keep[-1].endswith("\n"):
            keep[-1] += "\n"
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write(lines[0])
            f.writelines(keep)
            w = csv.DictWriter(f, cols, lineterminator="\n")
            w.writerows([{k: row.get(k, "") for k in cols} for row in new])
        print(f"{name}: {len(keep)} kept, {len(new)} US rows")

    rewrite("entities.csv", ents)
    rewrite("entity_codes.csv", codes)
    rewrite("subdivisions.csv", subs)


if __name__ == "__main__":
    main()
