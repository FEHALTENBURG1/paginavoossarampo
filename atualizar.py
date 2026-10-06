#!/usr/bin/env python3
"""Atualiza o dashboard de chegadas internacionais (sarampo) em Brasília, Rio e São Paulo.

Fluxo: baixa a programação diária da ANAC (SIROS /voos) -> filtra -> gera site/index.html.

Uso:
    python atualizar.py                       # de hoje (Brasília) até 31/12 do ano corrente
    python atualizar.py --fim 2027-03-27      # estende o período
    python atualizar.py --inicio 2026-10-07 --fim 2026-10-08
    python atualizar.py --offline             # só reprocessa o cache em dados_brutos/
"""
import argparse
import gettext
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

import airportsdata
import pycountry

AQUI = os.path.dirname(os.path.abspath(__file__))
URL = "https://sas.anac.gov.br/sas/siros_api/api/voos?dataReferencia={}"
UA = "dashboard-sarampo/1.0 (vigilancia epidemiologica; atualizacao diaria)"
PAUSA = 3.0                 # s entre requisições (o WAF da ANAC rejeita paralelismo)
ESPERAS = (5, 15, 45)       # s entre tentativas
MIN_REGISTROS_DIA = 500     # um dia normal tem ~3.000; abaixo disso, resposta suspeita
BRT = timedelta(hours=-3)

ALVOS = {"SBBR": "BSB", "SBGL": "GIG", "SBRJ": "SDU", "SBGR": "GRU", "SBKP": "VCP", "SBSP": "CGH"}
CIDADE_DESTINO = {"SBBR": "Brasília", "SBGL": "Rio de Janeiro", "SBRJ": "Rio de Janeiro",
                  "SBGR": "São Paulo", "SBKP": "São Paulo", "SBSP": "São Paulo"}
NOME_AEROPORTO_BR = {"SBBR": "Brasília (BSB)", "SBGL": "Galeão (GIG)", "SBRJ": "Santos Dumont (SDU)",
                     "SBGR": "Guarulhos (GRU)", "SBKP": "Viracopos (VCP)", "SBSP": "Congonhas (CGH)"}
PREFIXO_BR = ("SB", "SD", "SI", "SJ", "SN", "SS", "SW")

INTERESSE_PADRAO = ["CA", "US", "GT", "PE", "MX", "CO", "BO", "AR", "PY", "CL", "EC", "PA", "PT", "ES"]

CIAS = {
    "TAM": "LATAM Brasil", "GLO": "Gol", "AZU": "Azul", "LAN": "LATAM Chile", "LPE": "LATAM Perú",
    "LAP": "LATAM Paraguai", "ARE": "LATAM Colômbia", "CMP": "Copa Airlines", "ARG": "Aerolíneas Argentinas",
    "AAL": "American Airlines", "AVA": "Avianca", "TAP": "TAP Air Portugal", "UAL": "United Airlines",
    "DAL": "Delta Air Lines", "THY": "Turkish Airlines", "AFR": "Air France", "UAE": "Emirates",
    "JAT": "JetSMART Chile", "JES": "JetSMART Argentina", "QTR": "Qatar Airways", "ITY": "ITA Airways",
    "SKX": "Sky Airline Perú", "GXA": "Global Crossing Airlines", "AWC": "Titan Airways",
    "SKU": "Sky Airline", "BAW": "British Airways", "IBE": "Iberia", "DLH": "Lufthansa", "ACA": "Air Canada",
    "ETH": "Ethiopian Airlines", "BOV": "BoA", "KLM": "KLM", "DWI": "Arajet", "SWR": "Swiss",
    "AMX": "Aeroméxico", "AEA": "Air Europa", "RAM": "Royal Air Maroc", "CCA": "Air China",
    "SAA": "South African Airways", "DTA": "TAAG Angola", "WJA": "WestJet", "TSC": "Air Transat",
}
CIDADE_PT = {
    "Lisbon": "Lisboa", "Mexico City": "Cidade do México", "Tocumen": "Cidade do Panamá",
    "Bogota": "Bogotá", "Asuncion": "Assunção", "Ezeiza": "Buenos Aires", "Cordoba": "Córdoba",
    "Ushuahia": "Ushuaia", "San Carlos de Bariloche": "Bariloche", "Santa Cruz": "Santa Cruz de la Sierra",
    "Mississauga": "Toronto", "Dorval": "Montreal", "New York": "Nova York", "Dallas-Fort Worth": "Dallas",
    "Frankfurt am Main": "Frankfurt", "Munich": "Munique", "London": "Londres", "Rome": "Roma",
    "Fiumicino": "Roma", "Roissy": "Paris", "Istanbul": "Istambul", "Zurich": "Zurique",
    "Addis Ababa": "Adis Abeba", "Johannesburg": "Joanesburgo", "Brussels": "Bruxelas", "Geneva": "Genebra",
    "Maiquetia": "Caracas", "Schiphol": "Amsterdã", "Amsterdam": "Amsterdã", "Heathrow": "Londres",
    "Gatwick": "Londres", "Arnavutköy, Istanbul": "Istambul", "Cape Town": "Cidade do Cabo", "Milan": "Milão",
}
PAIS_PT = {"BO": "Bolívia", "VE": "Venezuela", "GB": "Reino Unido", "US": "Estados Unidos",
           "NL": "Países Baixos", "AE": "Emirados Árabes Unidos", "TR": "Turquia"}

AP_ICAO = airportsdata.load("ICAO")


# ---------------------------------------------------------------- download
def interpretar(texto):
    """A API devolve uma string JSON que contém um array JSON."""
    d = json.loads(texto)
    if isinstance(d, str):
        d = json.loads(d)
    if not isinstance(d, list):
        raise ValueError("resposta não é uma lista")
    return d


def baixar_dia(dia):
    ddmmaaaa = dia.strftime("%d%m%Y")
    ultimo = None
    for i, espera in enumerate((0,) + ESPERAS):
        if espera:
            time.sleep(espera)
        try:
            req = urllib.request.Request(URL.format(ddmmaaaa), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                texto = r.read().decode("utf-8")
            dados = interpretar(texto)  # "Request Rejected" (HTML do WAF) cai aqui
            if len(dados) < MIN_REGISTROS_DIA:
                raise ValueError(f"só {len(dados)} registros")
            return texto
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            ultimo = e
            print(f"  {ddmmaaaa}: tentativa {i + 1} falhou ({e})", file=sys.stderr)
    raise RuntimeError(f"{ddmmaaaa}: sem resposta válida da ANAC ({ultimo})")


def carregar_dia(dia, cache, offline):
    """Devolve a lista de registros do dia, usando o cache em disco quando válido."""
    caminho = os.path.join(cache, dia.strftime("%d%m%Y") + ".json")
    hoje = brasilia_agora().date()
    # dias passados nunca mudam; hoje e futuro são rebaixados a cada execução
    if os.path.exists(caminho) and (offline or dia < hoje):
        return interpretar(open(caminho, encoding="utf-8").read())
    if offline:
        return None
    texto = baixar_dia(dia)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    time.sleep(PAUSA)
    return interpretar(texto)


# ---------------------------------------------------------------- filtro
def pais_do_icao(icao):
    a = AP_ICAO.get(icao)
    if a:
        return a["country"]
    return "BR" if icao.startswith(PREFIXO_BR) else None


def dt(s):
    return datetime.strptime(s, "%d/%m/%Y %H:%M")


def filtrar(registros, inicio, fim, vistos, sem_pais):
    out = []
    for r in registros:
        dest = r["sg_icao_destino"]
        if dest not in ALVOS:
            continue
        org = r["sg_icao_origem"]
        cc = pais_do_icao(org)
        if cc is None:
            sem_pais.add(org)
            continue
        if cc == "BR":
            continue
        servico = r["ds_tipo_servico"] or ""
        assentos = int(r["qt_assentos_previstos"] or 0)
        if "PASSAGEIROS" not in servico or assentos <= 0:
            continue
        chegada = dt(r["dt_chegada_prevista_utc"])
        local = chegada + BRT
        if not (inicio <= local.date() <= fim):
            continue
        chave = (r["sg_empresa_icao"], r["nr_voo"], r["nr_etapa"], r["dt_partida_prevista_utc"], org, dest)
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append({"cia": r["sg_empresa_icao"], "voo": r["nr_voo"], "etapa": int(r["nr_etapa"]),
                    "equip": r["sg_equipamento_icao"], "assentos": assentos, "origem": org,
                    "destino": dest, "pais": cc, "chegada_local": local,
                    "regime": "N" if servico.startswith("NÃO REGULAR") else "R"})
    return out


# ---------------------------------------------------------------- dataset
def montar_dataset(voos, inicio, fim, consultado_de, consultado_ate):
    traducao = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["pt_BR"])

    def nome_pais(cc):
        return PAIS_PT.get(cc) or traducao.gettext(pycountry.countries.get(alpha_2=cc).name)

    voos = sorted(voos, key=lambda r: (r["chegada_local"], r["cia"], r["voo"]))
    paises = {cc: nome_pais(cc) for cc in sorted({r["pais"] for r in voos})}
    aeroportos = {}
    for o in sorted({r["origem"] for r in voos}):
        a = AP_ICAO[o]
        aeroportos[o] = [a["iata"], CIDADE_PT.get(a["city"], a["city"]), a["country"]]
    for icao, iata in ALVOS.items():
        aeroportos[icao] = [iata, CIDADE_DESTINO[icao], "BR"]
    agora = brasilia_agora()
    return {
        "meta": {
            "fonte": "ANAC · SIROS (API /voos, programação prevista)",
            "periodo": [inicio.isoformat(), fim.isoformat()],
            "consultado_de": consultado_de.isoformat(), "consultado_ate": consultado_ate.isoformat(),
            "gerado_em": agora.date().isoformat(), "gerado_em_hora": agora.strftime("%d/%m/%Y %H:%M"),
            "total_intl_pax": len(voos),
            "interesse_padrao": INTERESSE_PADRAO,
            "interesse_sem_voo": {cc: nome_pais(cc) for cc in INTERESSE_PADRAO if cc not in paises},
        },
        "colunas": ["chegada_local", "cia", "voo", "origem", "destino", "equip", "assentos", "etapa", "regime"],
        "aeroportos": aeroportos, "aeroportos_br": NOME_AEROPORTO_BR, "paises": paises,
        "cias": {c: CIAS.get(c, c) for c in sorted({r["cia"] for r in voos})},
        "voos": [[r["chegada_local"].strftime("%Y-%m-%dT%H:%M"), r["cia"], r["voo"], r["origem"], r["destino"],
                  r["equip"], r["assentos"], r["etapa"], r["regime"]] for r in voos],
    }


def gerar_html(ds, destino):
    tpl = open(os.path.join(AQUI, "template.html"), encoding="utf-8").read()
    dados = json.dumps(ds, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    assert "__DATA__" in tpl
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(tpl.replace("__DATA__", dados))


# ---------------------------------------------------------------- main
def brasilia_agora():
    return datetime.now(timezone.utc).replace(tzinfo=None) + BRT


def fim_padrao(hoje):
    return date(hoje.year, 12, 31)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inicio", type=date.fromisoformat, help="AAAA-MM-DD (padrão: hoje em Brasília)")
    ap.add_argument("--fim", type=date.fromisoformat, help="AAAA-MM-DD (padrão: 31/12 do ano corrente)")
    ap.add_argument("--cache", default=os.path.join(AQUI, "dados_brutos"))
    ap.add_argument("--saida", default=os.path.join(AQUI, "site", "index.html"))
    ap.add_argument("--offline", action="store_true", help="não acessa a ANAC; usa só o cache")
    a = ap.parse_args()

    hoje = brasilia_agora().date()
    inicio, fim = a.inicio or hoje, a.fim or fim_padrao(hoje)
    if fim < inicio:
        ap.error("--fim anterior a --inicio")
    os.makedirs(a.cache, exist_ok=True)

    # chegada local (UTC−3) pode vir de voo que parte no dia anterior ou chega após 00:00 UTC do dia seguinte
    consultado_de, consultado_ate = inicio - timedelta(days=1), fim + timedelta(days=1)
    vistos, sem_pais, voos, faltando = set(), set(), [], []
    dia, n = consultado_de, (consultado_ate - consultado_de).days + 1
    while dia <= consultado_ate:
        regs = carregar_dia(dia, a.cache, a.offline)
        if regs is None:
            faltando.append(dia)
        else:
            voos += filtrar(regs, inicio, fim, vistos, sem_pais)
        dia += timedelta(days=1)
    if faltando:
        print(f"AVISO: {len(faltando)} dia(s) sem cache no modo offline: "
              f"{faltando[0]}..{faltando[-1]}", file=sys.stderr)
    if sem_pais:
        print("AVISO: ICAO sem país (ignorados):", ", ".join(sorted(sem_pais)), file=sys.stderr)
    if not voos:
        sys.exit("ERRO: nenhum voo encontrado; o HTML não foi gerado.")

    ds = montar_dataset(voos, inicio, fim, consultado_de, consultado_ate)
    gerar_html(ds, a.saida)
    kb = os.path.getsize(a.saida) // 1024
    print(f"{len(voos)} chegadas | {inicio} a {fim} ({n} dias consultados) | {a.saida} ({kb} KB)")


if __name__ == "__main__":
    main()
