"""Gera docs/data/goleiros.json (temporadas 2022-23 a 2025-26) a partir do arquivo histórico público do FPL."""
import io, json, datetime, requests, pandas as pd, epa

B = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/"
rd = lambda s, f: pd.read_csv(io.StringIO(requests.get(f"{B}{s}/{f}", timeout=60).text))
out = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")}
for s in ["2022-23", "2023-24", "2024-25", "2025-26"]:
    p, t = rd(s, "players_raw.csv"), rd(s, "teams.csv")
    out[s] = epa.gk_list(p.to_dict("records"), dict(zip(t["id"], t["name"])))
    print(s, len(out[s]), "goleiros")
json.dump(out, open("docs/data/goleiros.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
