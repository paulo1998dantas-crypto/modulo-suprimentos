import re
import unicodedata


RELACOES_PROCESSO_TRANSFORMACAO = [
    {
        "transformacao_numero": "23",
        "transformacao_arquivo": "23 - JI CONFORT 417 10 M SELADO PLUS.xlsx",
        "item_codigo": "4-0010",
        "item_descricao": "JI CONFORT 417 10 M SELADO PLUS",
        "processo_numero": "01",
        "processo_arquivo": "01 - PROCESSO TRANSFORMAÇÃO - SPRINTER 417 10 - SELADO-VISTA - PLUS.xlsx",
        "processo_conjunto": "SPRINTER 417 10 - SELADO-VISTA - PLUS",
    },
    {
        "transformacao_numero": "24",
        "transformacao_arquivo": "24 - JI CONFORT 417 10 M VISTA PLUS.xlsx",
        "item_codigo": "4-0012",
        "item_descricao": "JI CONFORT 417 10 M VISTA PLUS",
        "processo_numero": "01",
        "processo_arquivo": "01 - PROCESSO TRANSFORMAÇÃO - SPRINTER 417 10 - SELADO-VISTA - PLUS.xlsx",
        "processo_conjunto": "SPRINTER 417 10 - SELADO-VISTA - PLUS",
    },
    {
        "transformacao_numero": "29",
        "transformacao_arquivo": "29 - JI CONFORT 517 15 M SELADO PLUS.xlsx",
        "item_codigo": "4-0019",
        "item_descricao": "JI CONFORT 517 15 M SELADO PLUS",
        "processo_numero": "02",
        "processo_arquivo": "02 - PROCESSO TRANSFORMAÇÃO - SPRINTER 517 - SELADO-VISTA - PLUS.xlsx",
        "processo_conjunto": "SPRINTER 517 - SELADO-VISTA - PLUS",
    },
    {
        "transformacao_numero": "30",
        "transformacao_arquivo": "30 - JI CONFORT 517 15 M VISTA PLUS.xlsx",
        "item_codigo": "4-0021",
        "item_descricao": "JI CONFORT 517 15 M VISTA PLUS",
        "processo_numero": "02",
        "processo_arquivo": "02 - PROCESSO TRANSFORMAÇÃO - SPRINTER 517 - SELADO-VISTA - PLUS.xlsx",
        "processo_conjunto": "SPRINTER 517 - SELADO-VISTA - PLUS",
    },
    {
        "transformacao_numero": "40",
        "transformacao_arquivo": "40 - JI CONFORT TRANSIT L4H3 VITRE.xlsx",
        "item_codigo": "4-0045",
        "item_descricao": "JI CONFORT TRANSIT L4H3 VITRE",
        "processo_numero": "03",
        "processo_arquivo": "03 - PROCESSO TRANSFORMAÇÃO - TRANSIT L4H3.xlsx",
        "processo_conjunto": "TRANSIT L4H3",
    },
]


def _normalizar_item_codigo(codigo):
    texto = str(codigo or "").strip().upper()
    if not texto:
        return ""
    return texto.split(" - ")[0].strip()


PROCESSO_POR_ITEM = {
    _normalizar_item_codigo(relacao["item_codigo"]): relacao["processo_conjunto"]
    for relacao in RELACOES_PROCESSO_TRANSFORMACAO
}


_PROCESSO_CAMPOS_EXPLICITOS = (
    "processo_conjunto",
    "processo_vinculado",
    "processo",
    "arquivo_processo",
)

_STOPWORDS_RELACAO = {
    "BOM",
    "B",
    "O",
    "M",
    "CJ",
    "CONJUNTO",
    "JI",
    "PROCESSO",
    "PRODUCAO",
    "PRODUTIVO",
    "TRANSFORMACAO",
    "TRANSFORMA",
    "XLSX",
}


def normalizar_relacao(texto):
    texto = str(texto or "").strip().upper()
    if not texto:
        return ""
    texto = texto.replace("B/J/D", "BJD").replace("B J D", "BJD")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    texto = " ".join(texto.split())
    return texto


def _tokens_relacao(texto):
    return {
        token
        for token in normalizar_relacao(texto).split()
        if len(token) >= 2 and token not in _STOPWORDS_RELACAO
    }


def _valor_extra_item(info, campo):
    if not isinstance(info, dict):
        return ""
    valor = info.get(campo, "")
    if valor:
        return valor
    extras = info.get("campos_extras", {}) or {}
    return extras.get(campo, "") or ""


def _resolver_conjunto_por_texto(texto, processos_disponiveis):
    texto_norm = normalizar_relacao(texto)
    if not texto_norm:
        return ""

    candidatos = []
    tokens_texto = _tokens_relacao(texto_norm)
    for conjunto in processos_disponiveis or []:
        conjunto_norm = normalizar_relacao(conjunto)
        if not conjunto_norm:
            continue
        if texto_norm == conjunto_norm:
            return conjunto
        if conjunto_norm in texto_norm or texto_norm in conjunto_norm:
            candidatos.append((100 + len(conjunto_norm), conjunto))
            continue

        tokens_conjunto = _tokens_relacao(conjunto_norm)
        if not tokens_conjunto:
            continue
        comuns = tokens_texto & tokens_conjunto
        cobertura = len(comuns) / max(len(tokens_conjunto), 1)
        if len(tokens_conjunto) == 1 and cobertura == 1:
            candidatos.append((90, conjunto))
        elif cobertura >= 0.33 and len(comuns) >= 2 and any(token.isdigit() and len(token) >= 3 for token in comuns):
            candidatos.append((int(cobertura * 100) + len(comuns), conjunto))
        elif cobertura >= 0.5 and len(comuns) >= 3:
            candidatos.append((int(cobertura * 100) + len(comuns), conjunto))

    if not candidatos:
        return ""
    candidatos.sort(reverse=True)
    if len(candidatos) > 1 and candidatos[0][0] == candidatos[1][0]:
        return ""
    return candidatos[0][1]


def _normalizar_relacoes_customizadas(relacoes_customizadas):
    normalizadas = {}
    if isinstance(relacoes_customizadas, dict):
        itens = relacoes_customizadas.items()
    elif isinstance(relacoes_customizadas, list):
        itens = []
        for relacao in relacoes_customizadas:
            if not isinstance(relacao, dict):
                continue
            itens.append(
                (
                    relacao.get("item_codigo") or relacao.get("codigo") or relacao.get("item") or "",
                    relacao.get("processo_conjunto") or relacao.get("processo") or "",
                )
            )
    else:
        return normalizadas

    for codigo, conjunto in itens:
        codigo_norm = _normalizar_item_codigo(codigo)
        conjuntos = conjunto if isinstance(conjunto, list) else [conjunto]
        conjuntos = [
            str(opcao or "").strip()
            for opcao in conjuntos
            if str(opcao or "").strip()
        ]
        if codigo_norm and conjuntos:
            normalizadas[codigo_norm] = list(dict.fromkeys(conjuntos))
    return normalizadas


def construir_processo_por_item(produtos=None, processos_disponiveis=None, relacoes_customizadas=None):
    processos_disponiveis = list(processos_disponiveis or [])
    mapa = dict(PROCESSO_POR_ITEM)
    mapa.update(_normalizar_relacoes_customizadas(relacoes_customizadas))

    for codigo, info in (produtos or {}).items():
        codigo_norm = _normalizar_item_codigo(codigo)
        if not codigo_norm:
            continue

        for campo in _PROCESSO_CAMPOS_EXPLICITOS:
            valor = _valor_extra_item(info, campo)
            conjunto = _resolver_conjunto_por_texto(valor, processos_disponiveis)
            if conjunto:
                mapa[codigo_norm] = conjunto
                break
        if codigo_norm in mapa:
            continue

        descricao = (info or {}).get("descricao", "") if isinstance(info, dict) else ""
        conjunto = _resolver_conjunto_por_texto(descricao, processos_disponiveis)
        if conjunto:
            mapa[codigo_norm] = conjunto

    return mapa


def resolver_processos_transformacao(codigos_itens, processos_disponiveis=None):
    mapa = PROCESSO_POR_ITEM
    if isinstance(processos_disponiveis, dict):
        mapa = processos_disponiveis
        processos_disponiveis = {
            conjunto
            for opcoes in mapa.values()
            for conjunto in (opcoes if isinstance(opcoes, list) else [opcoes])
            if conjunto
        }
    conjuntos = []
    for codigo in codigos_itens or []:
        codigo_norm = _normalizar_item_codigo(codigo)
        if not codigo_norm:
            continue
        opcoes = mapa.get(codigo_norm)
        if not opcoes:
            continue
        opcoes = opcoes if isinstance(opcoes, list) else [opcoes]
        for conjunto in opcoes:
            if processos_disponiveis is not None and conjunto not in processos_disponiveis:
                continue
            conjuntos.append(conjunto)
    return sorted(set(conjuntos))


def resolver_processo_transformacao(codigos_itens, processos_disponiveis=None):
    conjuntos = resolver_processos_transformacao(codigos_itens, processos_disponiveis)
    if len(conjuntos) == 1:
        return conjuntos[0]
    return ""
