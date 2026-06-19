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
_MARCADOR_PRODUTO_PROCESSO = "PRODUTO EM PROCESSO"


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


def _formatar_quantidade(numero):
    try:
        numero = float(numero)
    except Exception:
        return numero
    if numero.is_integer():
        return int(numero)
    return f"{numero:.4f}".rstrip("0").rstrip(".")


def _converter_qtd_para_unidade_cadastro(qtd, unidade_origem, unidade_cadastro):
    unidade_origem_norm = normalizar_texto(unidade_origem)
    unidade_cadastro_norm = normalizar_texto(unidade_cadastro)
    numero = parse_quantidade(qtd)
    if not numero:
        return qtd
    if unidade_cadastro_norm == "MM" and unidade_origem_norm != "MM" and abs(numero) < 1000:
        return _formatar_quantidade(numero * 1000)
    return qtd


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
        unidade_cadastro = item_info.get("unidade", "") or ""
        unidade = unidade_cadastro or comp.get("unidade", "") or ""
        qtd = _converter_qtd_para_unidade_cadastro(comp.get("qtd", ""), comp.get("unidade", ""), unidade_cadastro)
        linhas.append(
            {
                "item": normalizar_codigo(comp.get("item", "")),
                "codigo": codigo,
                "descricao": descricao,
                "unidade": unidade,
                "qtd": qtd,
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


def propagar_setor_preparacao(linhas, catalogo=None, componentes=None):
    linhas = [dict(linha or {}) for linha in (linhas or [])]
    codigos_com_bom = {
        normalizar_codigo(codigo)
        for codigo, filhos in (componentes or {}).items()
        if normalizar_codigo(codigo) and filhos
    }
    setor_por_codigo = {
        normalizar_codigo(linha.get("codigo", "")): linha.get("setor", "")
        for linha in linhas
        if normalizar_codigo(linha.get("codigo", ""))
    }
    pai_por_codigo = {
        normalizar_codigo(linha.get("codigo", "")): normalizar_codigo(linha.get("item", ""))
        for linha in linhas
        if normalizar_codigo(linha.get("codigo", ""))
    }

    def produto_processo_com_bom(codigo):
        codigo = normalizar_codigo(codigo)
        if not codigo or codigo not in codigos_com_bom:
            return False
        item_info = (catalogo or {}).get(codigo, {}) if catalogo else {}
        grupo = normalizar_texto((item_info or {}).get("grupo", ""))
        categoria = normalizar_texto((item_info or {}).get("categoria", ""))
        return _MARCADOR_PRODUTO_PROCESSO in grupo or _MARCADOR_PRODUTO_PROCESSO in categoria

    def setor_codigo(codigo):
        codigo = normalizar_codigo(codigo)
        if not codigo:
            return ""
        if produto_processo_com_bom(codigo):
            return SETOR_PREPARACAO
        if setor_por_codigo.get(codigo):
            return setor_por_codigo[codigo]
        item_info = (catalogo or {}).get(codigo, {}) if catalogo else {}
        if item_info:
            return classificar_item(item_info)
        return ""

    def tem_ancestral_preparacao(linha):
        visitados = set()
        pai = normalizar_codigo(linha.get("item", ""))
        codigo = normalizar_codigo(linha.get("codigo", ""))
        while pai and pai != codigo and pai not in visitados:
            visitados.add(pai)
            if setor_codigo(pai) == SETOR_PREPARACAO:
                return True
            pai = pai_por_codigo.get(pai, "")
        return False

    setores_por_level = {}
    for linha in linhas:
        codigo = normalizar_codigo(linha.get("codigo", ""))
        try:
            level = int(linha.get("level", 0) or 0)
        except Exception:
            level = 0
        tem_ancestral_por_nivel = any(
            setor == SETOR_PREPARACAO
            for nivel, setor in setores_por_level.items()
            if nivel < level
        )
        if (
            linha.get("setor") != SETOR_PREPARACAO
            and linha.get("tipo_requisicao") != TIPO_REQUISICAO_FATURAMENTO_DIRETO
            and (
                setor_codigo(codigo) == SETOR_PREPARACAO
                or tem_ancestral_preparacao(linha)
                or tem_ancestral_por_nivel
            )
        ):
            linha["setor"] = SETOR_PREPARACAO
        setores_por_level = {
            nivel: setor
            for nivel, setor in setores_por_level.items()
            if nivel < level
        }
        setores_por_level[level] = linha.get("setor", "")

    codigos_preparacao = {
        normalizar_codigo(linha.get("codigo", ""))
        for linha in linhas
        if linha.get("setor") == SETOR_PREPARACAO
        and normalizar_codigo(linha.get("codigo", ""))
    }
    for linha in linhas:
        codigo = normalizar_codigo(linha.get("codigo", ""))
        if (
            codigo in codigos_preparacao
            and linha.get("tipo_requisicao") != TIPO_REQUISICAO_FATURAMENTO_DIRETO
        ):
            linha["setor"] = SETOR_PREPARACAO
    return linhas


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


def construir_itens_os_preparacao(linhas):
    agrupado = {}
    ordem = []
    for linha in linhas or []:
        codigo = normalizar_codigo(linha.get("codigo", ""))
        unidade = str(linha.get("unidade", "") or "").strip()
        chave = (codigo, unidade)
        try:
            level = int(linha.get("level", 0) or 0)
        except Exception:
            level = 0
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
                "level": level,
            }
            ordem.append(chave)
        agrupado[chave]["qtd"] += parse_quantidade(linha.get("qtd", 0))
        agrupado[chave]["level"] = max(agrupado[chave].get("level", 0), level)

    itens = []
    for chave in ordem:
        linha = agrupado[chave]
        level = max(0, int(linha.get("level", 0) or 0))
        prefixo = ">" * level
        descricao = linha.get("descricao", "") or ""
        if prefixo:
            descricao = f"{prefixo} {descricao}".strip()
        itens.append(
            {
                "codigo": linha.get("codigo", "") or "",
                "descricao": descricao,
                "qtd": linha.get("qtd", "") if linha.get("qtd", "") != 0 else "",
                "serie": "",
                "unidade": linha.get("unidade", "") or "",
                "grupo": linha.get("grupo", "") or "",
                "categoria": linha.get("categoria", "") or "",
                "fornecedor": linha.get("fornecedor", "") or "",
                "setor": linha.get("setor", "") or "",
                "tipo_requisicao": linha.get("tipo_requisicao", "") or "",
                "level": level,
            }
        )
    return itens
