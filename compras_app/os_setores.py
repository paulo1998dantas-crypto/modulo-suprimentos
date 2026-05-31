import unicodedata

from composicao import normalizar_codigo, parse_quantidade


SETOR_EXPEDICAO = "EXPEDICAO"
SETOR_PREPARACAO = "PREPARACAO"
SETOR_FATURAMENTO_DIRETO = "F.D"
TIPO_REQUISICAO_MATERIAL = "MATERIAL"
TIPO_REQUISICAO_FATURAMENTO_DIRETO = "FATURAMENTO DIRETO"

_MARCADORES_PREPARACAO = (
    "ISOLAMENTO",
    "PISO",
    "REFORCO",
    "ACABAMENTO",
)


def normalizar_texto(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return " ".join(texto.replace("_", " ").split())


def classificar_item(item_info):
    categoria = normalizar_texto((item_info or {}).get("categoria", ""))
    grupo = normalizar_texto((item_info or {}).get("grupo", ""))
    referencia = categoria or grupo
    for marcador in _MARCADORES_PREPARACAO:
        if marcador and marcador in referencia:
            return SETOR_PREPARACAO
    return SETOR_EXPEDICAO


def classificar_tipo_requisicao(item_info, descricao=""):
    referencia = normalizar_texto(
        descricao
        or (item_info or {}).get("descricao", "")
        or ""
    )
    if "FATURAMENTO DIRETO" in referencia:
        return TIPO_REQUISICAO_FATURAMENTO_DIRETO
    return TIPO_REQUISICAO_MATERIAL


def enriquecer_composicao(composicao, catalogo):
    linhas = []
    for comp in composicao or []:
        codigo = normalizar_codigo(comp.get("codigo", ""))
        item_info = catalogo.get(codigo, {}) if catalogo else {}
        descricao = comp.get("descricao", "") or item_info.get("descricao", "") or ""
        grupo = comp.get("grupo", "") or item_info.get("grupo", "") or ""
        categoria = comp.get("categoria", "") or item_info.get("categoria", "") or ""
        fornecedor = comp.get("fornecedor", "") or item_info.get("fornecedor", "") or ""
        info_classificacao = dict(item_info or {})
        if grupo:
            info_classificacao["grupo"] = grupo
        if categoria:
            info_classificacao["categoria"] = categoria
        if descricao:
            info_classificacao["descricao"] = descricao
        setor = comp.get("setor", "") or classificar_item(info_classificacao)
        tipo_requisicao = comp.get("tipo_requisicao", "") or classificar_tipo_requisicao(info_classificacao, descricao)
        if tipo_requisicao == TIPO_REQUISICAO_FATURAMENTO_DIRETO:
            setor = SETOR_FATURAMENTO_DIRETO
        linhas.append(
            {
                "item": normalizar_codigo(comp.get("item", "")),
                "codigo": codigo,
                "descricao": descricao,
                "unidade": comp.get("unidade", "") or item_info.get("unidade", "") or "",
                "qtd": comp.get("qtd", ""),
                "level": comp.get("level", 0),
                "grupo": grupo,
                "categoria": categoria,
                "fornecedor": fornecedor,
                "setor": setor,
                "tipo_requisicao": tipo_requisicao,
            }
        )
    return linhas


def filtrar_linhas_setor(linhas, setor):
    return [
        linha
        for linha in (linhas or [])
        if linha.get("setor") == setor
        and linha.get("tipo_requisicao") != TIPO_REQUISICAO_FATURAMENTO_DIRETO
    ]


def filtrar_linhas_faturamento_direto(linhas):
    return [
        linha
        for linha in (linhas or [])
        if linha.get("tipo_requisicao") == TIPO_REQUISICAO_FATURAMENTO_DIRETO
    ]


def agrupar_linhas_setor(linhas):
    agrupado = {}
    ordem = []
    for linha in linhas or []:
        codigo = normalizar_codigo(linha.get("codigo", ""))
        unidade = str(linha.get("unidade", "") or "").strip()
        chave = (codigo, unidade)
        if chave not in agrupado:
            agrupado[chave] = {
                "codigo": codigo,
                "descricao": linha.get("descricao", "") or "",
                "unidade": unidade,
                "grupo": linha.get("grupo", "") or "",
                "categoria": linha.get("categoria", "") or "",
                "fornecedor": linha.get("fornecedor", "") or "",
                "setor": linha.get("setor", "") or "",
                "tipo_requisicao": linha.get("tipo_requisicao", "") or "",
                "qtd": 0.0,
            }
            ordem.append(chave)
        agrupado[chave]["qtd"] += parse_quantidade(linha.get("qtd", 0))

    return [agrupado[chave] for chave in ordem]


def agrupar_linhas_por_fornecedor(linhas):
    agrupado = {}
    ordem = []
    for linha in linhas or []:
        fornecedor = str(linha.get("fornecedor", "") or "").strip() or "SEM FORNECEDOR"
        if fornecedor not in agrupado:
            agrupado[fornecedor] = []
            ordem.append(fornecedor)
        agrupado[fornecedor].append(linha)
    return [(fornecedor, agrupado[fornecedor]) for fornecedor in ordem]


def construir_itens_os_setor(linhas_agrupadas):
    itens = []
    for linha in linhas_agrupadas or []:
        itens.append(
            {
                "codigo": linha.get("codigo", "") or "",
                "descricao": linha.get("descricao", "") or "",
                "qtd": linha.get("qtd", "") if linha.get("qtd", "") != 0 else "",
                "serie": "",
                "unidade": linha.get("unidade", "") or "",
                "grupo": linha.get("grupo", "") or "",
                "categoria": linha.get("categoria", "") or "",
                "fornecedor": linha.get("fornecedor", "") or "",
                "setor": linha.get("setor", "") or "",
                "tipo_requisicao": linha.get("tipo_requisicao", "") or "",
            }
        )
    return itens
