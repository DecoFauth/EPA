"""Gera docs/data/<temporada>.json a partir do arquivo histórico público do FPL (vaastav/Fantasy-Premier-League).
Uso: python historico.py 2025-26   (só temporadas com desarmes e cortes+bloqueios+interceptações, ou seja, 2025-26 em diante)"""
import io, json, sys, requests, pandas as pd
import epa

S = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
B = f"https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{S}/"
rd = lambda f: pd.read_csv(io.StringIO(requests.get(B + f, timeout=60).text))
pr, tm, fx = rd("players_raw.csv"), rd("teams.csv"), rd("fixtures.csv")
tn = dict(zip(tm["id"], tm["name"]))
rec = {n: [0, 0, 0] for n in tn.values()}
for f in fx[fx["finished"] == True].itertuples():
    h, a = tn[f.team_h], tn[f.team_a]
    if f.team_h_score > f.team_a_score: rec[h][0] += 1; rec[a][2] += 1
    elif f.team_h_score < f.team_a_score: rec[a][0] += 1; rec[h][2] += 1
    else: rec[h][1] += 1; rec[a][1] += 1
pl = [{"name": r.web_name, "full": f"{r.first_name} {r.second_name}", "pos": epa.POS[r.element_type], "team": tn[r.team],
       "n90": r.minutes / 90, "goals": r.goals_scored, "assists": r.assists, "xg": float(r.expected_goals),
       "xa": float(r.expected_assists), "tkl": r.tackles, "clr": r.clearances_blocks_interceptions}
      for r in pr.itertuples() if r.minutes > 0]
data = epa.build(pl, rec)
json.dump(data, open(f"docs/data/{S}.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(S, len(data["players"]), "jogadores | jogos por time:", data["games"], "| EPA total:", round(sum(p["epa"] for p in data["players"]), 1),
      "| top3:", [(p["name"], p["epa"]) for p in data["players"][:3]])
