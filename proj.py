"""Projeção de times: ratings de ataque/defesa por xG (encolhidos) -> Poisson -> pontos esperados e simulação da tabela.
Só biblioteca padrão (roda no GitHub Actions sem instalar nada além de requests)."""
import math, random, bisect, datetime

K, BASIS = 5, "xg"  # encolhimento (jogos) e base dos ratings: melhores no backtest (2024-25 e 2025-26, rodadas 8, 11 e 15)


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
            if i > j: w += x * y
            elif i == j: d += x * y
    t = sum(ph) * sum(pa)
    return w / t, d / t, 1 - (w + d) / t


def ratings(T, k=K, basis=BASIS):
    """T: {time: dict(n, xgf, xga, gf, ga)} (totais) -> {time: (ataque, defesa)} relativos à média = 1 (defesa menor = melhor)."""
    def tot(s):
        if basis == "xg": return s["xgf"], s["xga"]
        if basis == "gols": return s["gf"], s["ga"]
        return (s["xgf"] + s["gf"]) / 2, (s["xga"] + s["ga"]) / 2
    N = sum(s["n"] for s in T.values())
    if N == 0:
        return {t: (1.0, 1.0) for t in T}
    mf = sum(tot(s)[0] for s in T.values()) / N
    ma = sum(tot(s)[1] for s in T.values()) / N
    return {t: (((tot(s)[0] + k * mf) / (s["n"] + k)) / mf, ((tot(s)[1] + k * ma) / (s["n"] + k)) / ma) for t, s in T.items()}


def project(done, left, T, k=K, basis=BASIS, sims=5000, seed=1):
    """done: [(casa, fora, gols_casa, gols_fora)]; left: [(casa, fora)]. Devolve pontos esperados e, se sims>0, a simulação da tabela."""
    R = ratings(T, k, basis)
    mu_h = sum(x[2] for x in done) / len(done)
    mu_a = sum(x[3] for x in done) / len(done)
    pts, gd = {t: 0 for t in T}, {t: 0 for t in T}
    for h, a, gh, ga in done:
        gd[h] += gh - ga; gd[a] += ga - gh
        if gh > ga: pts[h] += 3
        elif gh < ga: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
    exp, fx = dict(pts), []
    for h, a in left:
        lh, la = mu_h * R[h][0] * R[a][1], mu_a * R[a][0] * R[h][1]
        pw, pd, pl = probs(lh, la)
        exp[h] += 3 * pw + pd; exp[a] += 3 * pl + pd
        if sims:
            fx.append((h, a, [sum(pmf(lh)[:i + 1]) for i in range(11)], [sum(pmf(la)[:i + 1]) for i in range(11)]))
    out = {"pts": pts, "exp": exp, "R": R}
    if not sims:
        return out
    rng, names = random.Random(seed), list(T)
    n = len(names)
    tit = {t: 0 for t in names}; top4 = dict(tit); rel = dict(tit); fin = {t: [] for t in names}
    for _ in range(sims):
        p, g = dict(pts), dict(gd)
        for h, a, ch, ca in fx:
            x = min(bisect.bisect(ch, rng.random()), 10); y = min(bisect.bisect(ca, rng.random()), 10)
            g[h] += x - y; g[a] += y - x
            if x > y: p[h] += 3
            elif x < y: p[a] += 3
            else: p[h] += 1; p[a] += 1
        for i, t in enumerate(sorted(names, key=lambda t: (-p[t], -g[t], rng.random()))):
            fin[t].append(p[t])
            tit[t] += i == 0; top4[t] += i < 4; rel[t] += i >= n - 3
    out["teams"] = []
    for t in names:
        v = sorted(fin[t])
        out["teams"].append({"team": t, "j": T[t]["n"], "pts": pts[t], "gd": gd[t], "exp": round(sum(v) / sims, 1),
                             "lo": v[int(sims * .1)], "hi": v[int(sims * .9)], "title": round(tit[t] / sims, 4),
                             "top4": round(top4[t] / sims, 4), "rel": round(rel[t] / sims, 4),
                             "att": round(R[t][0], 3), "dfn": round(R[t][1], 3)})
    out["teams"].sort(key=lambda r: -r["exp"])
    return out


def stats_from_api(boot, tn, done):
    """Totais por time a partir do bootstrap-static do FPL: xG a favor = soma do xG dos jogadores; xG contra = soma do xGC dos goleiros."""
    T = {n: dict(n=0, xgf=0.0, xga=0.0, gf=0, ga=0) for n in tn.values()}
    for h, a, gh, ga in done:
        T[h]["n"] += 1; T[a]["n"] += 1
        T[h]["gf"] += gh; T[h]["ga"] += ga; T[a]["gf"] += ga; T[a]["ga"] += gh
    for e in boot["elements"]:
        t = T[tn[e["team"]]]
        t["xgf"] += float(e["expected_goals"])
        if e["element_type"] == 1:
            t["xga"] += float(e["expected_goals_conceded"])
    return T


def run(boot, fx, tn, sims=5000):
    done = [(tn[f["team_h"]], tn[f["team_a"]], f["team_h_score"], f["team_a_score"]) for f in fx if f.get("finished")]
    left = [(tn[f["team_h"]], tn[f["team_a"]]) for f in fx if not f.get("finished")]
    res = project(done, left, stats_from_api(boot, tn, done), sims=sims)
    return {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
            "games": max(t["j"] for t in res["teams"]), "sims": sims, "teams": res["teams"]}
