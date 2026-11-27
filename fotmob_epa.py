#!/usr/bin/env python3
"""Coleta o Brasileirão no FotMob e calcula EPA usando build() original de epa.py.

Não altera pesos, parâmetros ou fórmulas do EPA. Gera um JSON independente em
 docs/data/brasileirao-<temporada>.json para não sobrescrever os dados atuais.
"""
from __future__ import annotations
import argparse, json, re, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests
from epa import build, W, DRAW, OFF_SHARE, PTS, REPLACEMENT, MIN90

BASE = "https://www.fotmob.com/api/data"
LEAGUE_ID = 268
# Campo principal do EPA -> ID do leaderboard FotMob -> qual valor usar na linha.
STAT_FIELDS = {
    "goals": ("goals", "statValue"),
    "assists": ("goal_assist", "statValue"),
    "xg": ("expected_goals", "statValue"),
    "xa": ("expected_assists", "statValue"),
    "minutes": ("mins_played", "statValue"),
    "tkl": ("total_tackle", "substatValue"),
    "clearances": ("effective_clearance", "substatValue"),
    "blocks": ("outfielder_block", "substatValue"),
    "interceptions": ("interception", "substatValue"),
}


# Posições oficiais do FotMob
POSITION_MAP = {
    "1": "MF",
    "11": "GK",
    "32": "RB",
    "33": "CB",
    "34": "CB",
    "35": "CB",
    "36": "CB",
    "37": "CB",
    "38": "LB",
    "39": "LWB",
    "62": "RWB",
    "64": "DM",
    "65": "DM",
    "66": "DM",
    "68": "LWB",
    "72": "RM",
    "73": "CM",
    "74": "CM",
    "75": "CM",
    "76": "CM",
    "77": "CM",
    "78": "LM",
    "82": "RW",
    "83": "RW",
    "84": "RW",
    "85": "AM",
    "86": "AM",
    "87": "AM",
    "88": "LW",
    "103": "RW",
    "104": "ST",
    "105": "ST",
    "106": "ST",
    "107": "LW",
    "115": "ST",
}

class FotMob:
    def __init__(self, delay=0.55):
        self.delay = max(0.4, float(delay))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; EPA data collector)",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.fotmob.com/",
        })
    def get(self, endpoint, params=None):
        time.sleep(self.delay)
        r = self.session.get(f"{BASE}/{endpoint}", params=params or {}, timeout=40)
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Resposta inesperada em {endpoint}: {type(payload).__name__}")
        if payload.get("action", {}).get("notFound"):
            raise RuntimeError(f"FotMob retornou notFound em {endpoint}: {r.url}")
        return payload



# Consulta a posição oficial do jogador no perfil do FotMob.
# O cache evita consultar o mesmo jogador mais de uma vez.
POSITION_PROFILE_CACHE = {}

def resolve_position(client, player_id, position_id):
    mapped = POSITION_MAP.get(str(position_id))

    if mapped:
        return mapped

    cache_key = str(player_id)

    if cache_key in POSITION_PROFILE_CACHE:
        return POSITION_PROFILE_CACHE[cache_key]

    try:
        profile = client.get("playerData", {"id": player_id})
        description = profile.get("positionDescription", {})
        positions = description.get("positions", [])

        primary = next(
            (p for p in positions if p.get("isMainPosition")),
            positions[0] if positions else None
        )

        if primary:
            position = primary.get("strPosShort", {}).get("label")
        else:
            position = description.get("primaryPosition", {}).get("label")

        generic_positions = {
            "goalkeeper": "GK",
            "defender": "DEF",
            "midfielder": "MF",
            "forward": "FWD"
        }

        if position:
            position = generic_positions.get(
                position.lower(),
                position.upper()
            )
        else:
            position = "—"

    except Exception as e:
        print(f"Não foi possível identificar posição do jogador {player_id}: {e}")
        position = "—"

    POSITION_PROFILE_CACHE[cache_key] = position
    return position


def val(obj):
    if isinstance(obj, dict): return obj.get("value")
    return obj

def season_id_from_catalog(payload, season_name):
    data = payload.get("data", payload)
    seasons = data.get("seasons", [])
    for s in seasons:
        if str(s.get("name", "")).strip() == str(season_name).strip():
            return s.get("id")
    # Compatibilidade com respostas que usem outra chave de nome.
    for s in seasons:
        label = str(s.get("name") or s.get("seasonName") or s.get("title") or "")
        if label.startswith(str(season_name)):
            return s.get("id")
    raise RuntimeError(f"Temporada {season_name} não encontrada no catálogo. Temporadas: {seasons}")

def get_rows(payload):
    data = payload.get("data", payload)
    rows = data.get("statsData", [])
    if not isinstance(rows, list):
        raise RuntimeError("FotMob não retornou statsData como lista.")
    return rows

def find_standing_rows(obj):
    """Localiza table.all / table.total em respostas com pequenas variações de formato."""
    found = []
    def walk(x):
        if isinstance(x, dict):
            table = x.get("table")
            if isinstance(table, dict):
                for key in ("all", "total", "overall"):
                    rows = table.get(key)
                    if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
                        if any(any(k in r for k in ("wins", "draws", "losses", "played")) for r in rows):
                            found.append(rows)
            # Algumas respostas expõem a tabela diretamente.
            if isinstance(x.get("all"), list):
                rows=x["all"]
                if rows and all(isinstance(r,dict) for r in rows) and any("wins" in r for r in rows):
                    found.append(rows)
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(obj)
    return max(found, key=len) if found else []

def team_identity(row):
    team = row.get("team") or row.get("participant") or row.get("teamData") or {}
    if isinstance(team, dict):
        tid = team.get("id") or team.get("teamId") or row.get("teamId") or row.get("id")
        name = team.get("name") or team.get("shortName") or row.get("teamName") or row.get("name")
    else:
        tid = row.get("teamId") or row.get("id")
        name = str(team) if team else row.get("teamName")
    return tid, name

def parse_records(league_payload):
    rows = find_standing_rows(league_payload)
    rec, names = {}, {}
    for row in rows:
        tid, name = team_identity(row)
        wins = row.get("wins", row.get("W"))
        draws = row.get("draws", row.get("D"))
        losses = row.get("losses", row.get("L"))
        if tid is None or wins is None or draws is None or losses is None:
            continue
        rec[str(tid)] = [int(wins), int(draws), int(losses)]
        if name: names[str(tid)] = name
    if not rec:
        raise RuntimeError(
            "Não consegui localizar a tabela com vitórias/empates/derrotas na resposta de /leagues. "
            "O coletor parou para não calcular EPA com resultados incorretos. "
            "A resposta bruta foi salva em data/fotmob/raw_league_response.json."
        )
    return rec, names

def process_season(client, season_name, league_id, out_dir):
    raw=Path("data/fotmob/raw")/f"brasileirao_{season_name}"
    raw.mkdir(parents=True,exist_ok=True)
    print(f"\n========== BRASILEIRÃO {season_name} ==========")
    print(f"[1/4] Identificando temporada {season_name}...")
    season_catalog=client.get("leagueseasondeepstats",{"id":league_id,"type":"players"})
    (raw/"season_catalog.json").write_text(json.dumps(season_catalog,ensure_ascii=False,indent=2),encoding="utf-8")
    season_id=season_id_from_catalog(season_catalog,season_name)
    print(f"      ID interno FotMob: {season_id}")

    print("[2/4] Baixando estatísticas dos jogadores...")
    players={}
    for field,(stat_id,value_key) in STAT_FIELDS.items():
        payload=client.get("leagueseasondeepstats",{"id":league_id,"season":season_id,"type":"players","stat":stat_id})
        (raw/f"{stat_id}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        rows=get_rows(payload)
        print(f"      {field}: {len(rows)} linhas")
        for row in rows:
            pid=row.get("id")
            if pid is None: continue
            player=players.setdefault(str(pid),{"fotmob_id":pid,"name":row.get("name"),"team_id":row.get("teamId"),"position_id":row.get("position"),"source":{}})
            raw_value=val(row.get(value_key))
            if raw_value is not None: player["source"][field]=float(raw_value)
            if player.get("team_id") is None: player["team_id"]=row.get("teamId")
            if player.get("position_id") is None: player["position_id"]=row.get("position")
    players={pid:player for pid,player in players.items() if player["source"].get("minutes",0)>0}
    if not players: raise RuntimeError(f"Nenhum jogador com minutos foi retornado para {season_name}.")

    print("[3/4] Baixando tabela e resultados da temporada...")
    league=client.get("leagues",{"id":league_id,"season":season_name})
    (raw/"league_overview.json").write_text(json.dumps(league,ensure_ascii=False,indent=2),encoding="utf-8")
    rec_by_id,team_names=parse_records(league)
    team_ids={str(player.get("team_id")) for player in players.values() if player.get("team_id") is not None}
    missing=team_ids-set(rec_by_id)
    if missing: raise RuntimeError(f"{season_name}: tabela sem W/D/L para teamId(s): {sorted(missing)}")
    rec={}
    for tid in team_ids:
        team_name=team_names.get(tid)
        if not team_name: raise RuntimeError(f"{season_name}: nome não identificado para teamId {tid}; cálculo interrompido.")
        rec[team_name]=rec_by_id[tid]

    epa_players=[]
    for player in players.values():
        source=player["source"]
        team=team_names.get(str(player["team_id"]))
        if not team: raise RuntimeError(f"Time ausente para jogador {player['name']} ({player['fotmob_id']}).")
        epa_players.append({"fotmob_id":player["fotmob_id"],"name":player["name"],"full":player["name"],"pos":resolve_position(client, player["fotmob_id"], player.get("position_id")),"team":team,
            "n90":source.get("minutes",0)/90,"goals":source.get("goals",0),"assists":source.get("assists",0),
            "xg":source.get("xg",0),"xa":source.get("xa",0),"tkl":source.get("tkl",0),
            "clr":source.get("clearances",0)+source.get("blocks",0)+source.get("interceptions",0)})
    assert W==dict(goals=.5,assists=.3,xg=.1,xa=.1,tkl=.3,clr=.23)
    assert (DRAW,OFF_SHARE,PTS,REPLACEMENT,MIN90)==(.33,.5,3,.013,1.0)
    result=build(epa_players,rec)

    # Adiciona IDs ao resultado sem alterar os cálculos do EPA
    ids_por_jogador = {
        (p["name"], p["team"]): p["fotmob_id"]
        for p in epa_players
    }
    for p in result["players"]:
        p["fotmob_id"] = ids_por_jogador.get((p["name"], p["team"]))

    result.update({"competition":"Brasileirão Série A","season":str(season_name),"source":"FotMob",
        "source_league_id":league_id,"source_season_id":season_id,
        "methodology":"EPA original preservado; fonte e mapeamento dos dados FotMob.",
        "coverage":{"players_with_minutes":len(epa_players),"teams":len(rec),"team_results":"FotMob league table"},
        "notes":["Posição ainda não mapeada para GK/DF/MF/FW; exibida como —.",
        "Ausência em leaderboard de estatística de contagem foi tratada como zero para atletas com minutos.",
        "effective_clearance ainda requer validação de equivalência com clearances do provedor anterior."]})
    out_dir.mkdir(parents=True,exist_ok=True)
    outfile=out_dir/f"brasileirao-{season_name}.json"
    outfile.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("[4/4] Concluído.")
    print(f"Arquivo: {outfile}")
    print(f"Jogadores: {len(epa_players)} | Times: {len(rec)} | Partidas equivalentes por time: {result['games']}")
    return {"season":str(season_name),"players":len(epa_players),"teams":len(rec),"games":result["games"],"file":str(outfile)}

def main():
    ap=argparse.ArgumentParser(description="Coleta várias temporadas do Brasileirão e calcula o EPA original.")
    ap.add_argument("--season",default=None,help="Uma temporada (compatibilidade com versão anterior).")
    ap.add_argument("--seasons",default="2026,2025,2024,2023",help="Temporadas separadas por vírgula. Padrão: 2026,2025,2024,2023.")
    ap.add_argument("--league-id",type=int,default=LEAGUE_ID)
    ap.add_argument("--delay",type=float,default=0.55)
    ap.add_argument("--out",type=Path,default=Path("docs/data"))
    args=ap.parse_args()
    seasons=[args.season] if args.season else [x.strip() for x in args.seasons.split(",") if x.strip()]
    if not seasons: raise SystemExit("Nenhuma temporada informada.")
    client=FotMob(args.delay)
    completed=[]
    for season in seasons: completed.append(process_season(client,season,args.league_id,args.out))
    print("\n========== RESUMO GERAL ==========")
    for item in completed: print(f"{item['season']}: {item['players']} jogadores | {item['teams']} times | {item['games']} jogos/time")
    print(f"Temporadas concluídas: {len(completed)} de {len(seasons)}")
    print("EPA: fórmula original preservada em todas as temporadas.")

if __name__=="__main__":
    main()
