# Modelo de projeção do Brasileirão
# Implementação separada do modelo original da Premier League.

import math
import random
import bisect
import datetime
import json
import requests
import os

K = 5
BASIS = "xg"


def pmf(l, n=10):
    p = [math.exp(-l)]
    for k in range(1, n + 1):
        p.append(p[-1] * l / k)
    return p


def probs(lh, la):
    ph, pa = pmf(lh), pmf(la)
    w = d = 0.0

    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            if i > j:
                w += x * y
            elif i == j:
                d += x * y

    t = sum(ph) * sum(pa)
    return w / t, d / t, 1 - (w + d) / t


def ratings(T, k=K, basis=BASIS):
    def tot(s):
        if basis == "xg":
            return s["xgf"], s["xga"]
        if basis == "gols":
            return s["gf"], s["ga"]
        return (s["xgf"] + s["gf"]) / 2, (s["xga"] + s["ga"]) / 2

    N = sum(s["n"] for s in T.values())

    if N == 0:
        return {t: (1.0, 1.0) for t in T}

    mf = sum(tot(s)[0] for s in T.values()) / N
    ma = sum(tot(s)[1] for s in T.values()) / N

    return {
        t: (
            ((tot(s)[0] + k * mf) / (s["n"] + k)) / mf,
            ((tot(s)[1] + k * ma) / (s["n"] + k)) / ma
        )
        for t, s in T.items()
    }

def project(done, left, T, k=K, basis=BASIS, sims=5000, seed=1):
    R = ratings(T, k, basis)

    mu_h = sum(x[2] for x in done) / len(done)
    mu_a = sum(x[3] for x in done) / len(done)

    pts = {t: 0 for t in T}
    gd = {t: 0 for t in T}

    for h, a, gh, ga in done:
        gd[h] += gh - ga
        gd[a] += ga - gh

        if gh > ga:
            pts[h] += 3
        elif gh < ga:
            pts[a] += 3
        else:
            pts[h] += 1
            pts[a] += 1

    exp = dict(pts)
    fx = []

    for h, a in left:
        lh = mu_h * R[h][0] * R[a][1]
        la = mu_a * R[a][0] * R[h][1]

        pw, pd, pl = probs(lh, la)

        exp[h] += 3 * pw + pd
        exp[a] += 3 * pl + pd

        if sims:
            fx.append((
                h, a,
                [sum(pmf(lh)[:i + 1]) for i in range(11)],
                [sum(pmf(la)[:i + 1]) for i in range(11)]
            ))

    out = {"pts": pts, "exp": exp, "R": R}

    if not sims:
        return out

    rng = random.Random(seed)
    names = list(T)

    tit = {t: 0 for t in names}
    top4 = dict(tit)
    prelib = dict(tit)
    sula = dict(tit)
    rel = dict(tit)
    fin = {t: [] for t in names}

    for _ in range(sims):
        p, g = dict(pts), dict(gd)

        for h, a, ch, ca in fx:
            x = min(bisect.bisect(ch, rng.random()), 10)
            y = min(bisect.bisect(ca, rng.random()), 10)

            g[h] += x - y
            g[a] += y - x

            if x > y:
                p[h] += 3
            elif x < y:
                p[a] += 3
            else:
                p[h] += 1
                p[a] += 1

        for i, t in enumerate(
            sorted(names, key=lambda t: (-p[t], -g[t], rng.random()))
        ):
            fin[t].append(p[t])
            tit[t] += i == 0
            top4[t] += i < 4
            prelib[t] += i == 4
            sula[t] += 5 <= i <= 10
            rel[t] += i >= len(names) - 4

    out["teams"] = []

    for t in names:
        v = sorted(fin[t])

        out["teams"].append({
            "team": t,
            "j": T[t]["n"],
            "pts": pts[t],
            "gd": gd[t],
            "exp": round(sum(v) / sims, 1),
            "lo": v[int(sims * .1)],
            "hi": v[int(sims * .9)],
            "title": round(tit[t] / sims, 4),
            "top4": round(top4[t] / sims, 4),
            "prelib": round(prelib[t] / sims, 4),
            "sula": round(sula[t] / sims, 4),
            "rel": round(rel[t] / sims, 4),
            "att": round(R[t][0], 3),
            "dfn": round(R[t][1], 3)
        })

    out["teams"].sort(key=lambda r: -r["exp"])

    return out

SEASON_IDS = {
    2026: 1000000388,
    2025: 25077,
    2024: 22978,
    2023: 18982
}

FOTMOB_BASE = "https://data.fotmob.com/stats/268/season"


def fetch_team_stat(season_id, stat):
    url = f"{FOTMOB_BASE}/{season_id}/{stat}.json"

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    data = response.json()
    records = data["TopLists"][0]["StatList"]

    return {
        str(item["TeamId"]): float(item["StatValue"])
        for item in records
    }


def load_season(season):
    arquivo = (
        f"data/fotmob/raw/brasileirao_{season}/league_overview.json"
    )

    with open(arquivo, encoding="utf-8") as f:
        overview = json.load(f)

    matches = overview["fixtures"]["allMatches"]
    table = overview["table"][0]["data"]["table"]["all"]

    season_id = SEASON_IDS[season]

    xgf = fetch_team_stat(season_id, "expected_goals_team")
    xga = fetch_team_stat(season_id, "expected_goals_conceded_team")

    teams = {}

    for team in table:
        team_id = str(team["id"])
        name = team["name"]

        teams[team_id] = {
            "name": name,
            "n": int(team["played"]),
            "xgf": xgf[team_id],
            "xga": xga[team_id],
            "gf": 0,
            "ga": 0
        }

    done = []
    left = []

    for match in matches:
        if match["status"].get("cancelled"):
            continue

        home_id = str(match["home"]["id"])
        away_id = str(match["away"]["id"])

        home = teams[home_id]["name"]
        away = teams[away_id]["name"]

        if match["status"].get("finished"):
            score = match["status"]["scoreStr"]
            gh, ga = [
                int(value.strip())
                for value in score.split("-")
            ]

            done.append((home, away, gh, ga))

            teams[home_id]["gf"] += gh
            teams[home_id]["ga"] += ga
            teams[away_id]["gf"] += ga
            teams[away_id]["ga"] += gh

        else:
            left.append((home, away))

    T = {team["name"]: team for team in teams.values()}

    return {
        "season": season,
        "teams": T,
        "done": done,
        "left": left
    }


def generate_projection(season=2026, sims=5000):
    data = load_season(season)

    result = project(
        data["done"],
        data["left"],
        data["teams"],
        sims=sims
    )

    output = {
        "updated": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(timespec="minutes"),
        "competition": "Brasileirão Série A",
        "season": season,
        "games": max(team["n"] for team in data["teams"].values()),
        "sims": sims,
        "teams": result["teams"]
    }

    output_path = (
        __import__("pathlib").Path("docs/projecao-brasileirao.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Projeção de {season} gerada com sucesso!")
    print(f"Arquivo: {output_path}")
    print(f"Times: {len(output['teams'])}")
    print(f"Jogos por time: {output['games']}")
    print(f"Simulações: {sims}")

    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--sims", type=int, default=5000)
    args = parser.parse_args()

    generate_projection(args.season, args.sims)
