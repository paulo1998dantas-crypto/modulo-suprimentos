import unicodedata

from composicao import normalizar_codigo, parse_quantidade


SETOR_EXPEDICAO = "EXPEDICAO"
SETOR_PREPARACAO = "PREPARACAO"

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


def enriquecer_composicao(composicao, catalogo):
    linhas = []
    for comp in composicao or []:
        codigo = normalizar_codigo(comp.get("codigo", ""))
        item_info = catalogo.get(codigo, {}) if catalogo else {}
        linhas.append(
            {
                "item": normalizar_codigo(comp.get("item", "")),
                "codigo": codigo,
                "descricao": comp.get("descricao", "") or item_info.get("descricao", "") or "",
                "unidade": comp.get("unidade", "") or item_info.get("unidade", "") or "",
                "qtd": comp.get("qtd", ""),
                "level": comp.get("level", 0),
                "grupo": item_info.get("grupo", "") or "",
                "categoria": item_info.get("categoria", "") or "",
                "setor": classificar_item(item_info),
            }
        )
    return linhas


def filtrar_linhas_setor(linhas, setor):
    return [linha for linha in (linhas or []) if linha.get("setor") == setor]


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
                "setor": linha.get("setor", "") or "",
                "qtd": 0.0,
            }
            ordem.append(chave)
        agrupado[chave]["qtd"] += parse_quantidade(linha.get("qtd", 0))

    return [agrupado[chave] for chave in ordem]


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
                "setor": linha.get("setor", "") or "",
            }
        )
    return itens
