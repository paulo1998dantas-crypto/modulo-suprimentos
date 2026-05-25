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


def resolver_processos_transformacao(codigos_itens, processos_disponiveis=None):
    conjuntos = []
    for codigo in codigos_itens or []:
        codigo_norm = _normalizar_item_codigo(codigo)
        if not codigo_norm:
            continue
        conjunto = PROCESSO_POR_ITEM.get(codigo_norm)
        if not conjunto:
            continue
        if processos_disponiveis is not None and conjunto not in processos_disponiveis:
            continue
        conjuntos.append(conjunto)
    return sorted(set(conjuntos))


def resolver_processo_transformacao(codigos_itens, processos_disponiveis=None):
    conjuntos = resolver_processos_transformacao(codigos_itens, processos_disponiveis)
    if len(conjuntos) == 1:
        return conjuntos[0]
    return ""
