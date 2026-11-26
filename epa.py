"""EPA: baixa os dados do Fantasy Premier League, calcula o EPA e grava docs/data.json."""
import json, datetime, requests

W = dict(goals=.5, assists=.3, xg=.1, xa=.1, tkl=.3, clr=.23)  # clr = cortes + bloqueios + interceptações
DRAW, OFF_SHARE, PTS, REPLACEMENT, MIN90 = .33, .5, 3, .013, 1.0
API = "https://fantasy.premierleague.com/api/"
POS = {1: "GK", 2: "DF", 3: "MF", 4: "FW"}


def get(path):
    r = requests.get(API + path, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return r.json()


def build(players, rec):
    """players: dicts (name, full, pos, team, n90, goals, assists, xg, xa, tkl, clr); rec: {time: [V, E, D]}"""
    tot = {}
    for p in players:
        p["off"] = p["goals"] * W["goals"] + p["assists"] * W["assists"] + p["xg"] * W["xg"] + p["xa"] * W["xa"]
        p["def"] = p["tkl"] * W["tkl"] + p["clr"] * W["clr"]
        t = tot.setdefault(p["team"], [0, 0])
        t[0] += p["off"]; t[1] += p["def"]
    out = []
    for p in players:
        v, dr, _ = rec[p["team"]]
        pool = v + DRAW * dr
        to, td = tot[p["team"]]
        oe = p["off"] / to * pool * OFF_SHARE * PTS if to else 0
        de = p["def"] / td * pool * (1 - OFF_SHARE) * PTS if td else 0
        e90 = (oe + de) / p["n90"] if p["n90"] >= MIN90 else None
        out.append({"name": p["name"], "full": p["full"], "pos": p["pos"], "team": p["team"],
                    "n90": round(p["n90"], 2), "oepa": round(oe, 3), "depa": round(de, 3), "epa": round(oe + de, 3),
                    "epa90": None if e90 is None else round(e90, 4),
                    "paa": None if e90 is None else round(e90 - REPLACEMENT, 4)})
    out.sort(key=lambda x: -x["epa"])
    return {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
            "games": max(sum(r) for r in rec.values()), "players": out}


def main():
    boot, fx = get("bootstrap-static/"), get("fixtures/")
    tn = {t["id"]: t["name"] for t in boot["teams"]}
    rec = {n: [0, 0, 0] for n in tn.values()}
    for f in fx:
        if not f.get("finished"):
            continue
        h, a = tn[f["team_h"]], tn[f["team_a"]]
        sh, sa = f["team_h_score"], f["team_a_score"]
        if sh > sa: rec[h][0] += 1; rec[a][2] += 1
        elif sh < sa: rec[a][0] += 1; rec[h][2] += 1
        else: rec[h][1] += 1; rec[a][1] += 1
    players = [{"name": e["web_name"], "full": f'{e["first_name"]} {e["second_name"]}', "pos": POS[e["element_type"]],
                "team": tn[e["team"]], "n90": e["minutes"] / 90, "goals": e["goals_scored"], "assists": e["assists"],
                "xg": float(e["expected_goals"]), "xa": float(e["expected_assists"]),
                "tkl": e.get("tackles", 0), "clr": e.get("clearances_blocks_interceptions", 0)}
               for e in boot["elements"] if e["minutes"] > 0]
    data = build(players, rec)
    with open("docs/data.json", "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(len(data["players"]), "jogadores, até", data["games"], "jogos por time")


if __name__ == "__main__":
    main()
