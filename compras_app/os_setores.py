import unicodedata

from composicao import normalizar_codigo, parse_quantidade


SETOR_EXPEDICAO = "EXPEDICAO"
SETOR_PREPARACAO = "PREPARACAO"
SETOR_FATURAMENTO_DIRETO = "F.D"
TIPO_REQUISICAO_MATERIAL = "MATERIAL"
TIPO_REQUISICAO_FATURAMENTO_DIRETO = "FATURAMENTO DIRETO"
_MARCADORES_EXPEDICAO_DESCRICAO = (
    "ACESSORIO ACABAMENTO PLASTICO",
)


def normalizar_texto(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return " ".join(texto.replace("_", " ").split())


def _eh_cj_teto(codigo, grupo, descricao):
    descricao = normalizar_texto(descricao)
    grupo = normalizar_texto(grupo)
    codigo = normalizar_codigo(codigo)
    if not descricao.startswith("CJ TETO"):
        return False
    return (
        codigo[:2] in {"20", "30"}
        or "CONJUNTO" in grupo
        or "KIT" in grupo
        or "PRODUTO EM PROCESSO" in grupo
    )


def classificar_item(item_info):
    categoria = normalizar_texto((item_info or {}).get("categoria", ""))
    grupo = normalizar_texto((item_info or {}).get("grupo", ""))
    descricao = normalizar_texto((item_info or {}).get("descricao", ""))
    codigo = normalizar_codigo((item_info or {}).get("codigo", ""))
    referencia = f"{categoria} {grupo} {descricao}"
    if _eh_cj_teto(codigo, grupo, descricao):
        return SETOR_PREPARACAO
    if "TRILHO" in referencia or "REFORCO" in referencia or "ISOLAMENTO" in referencia:
        return SETOR_PREPARACAO
    if any(marcador in descricao for marcador in _MARCADORES_EXPEDICAO_DESCRICAO):
        return SETOR_EXPEDICAO
    if "PISO" in categoria and codigo[:2] in {"20", "30"}:
        return SETOR_PREPARACAO
    if "ACABAMENTO" in categoria and codigo[:2] in {"20", "30"}:
        return SETOR_PREPARACAO
    if codigo.startswith("3020") and "BANCO" in referencia:
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
        info_classificacao["codigo"] = codigo
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
                "setor_origem": setor,
                "setor_manual": bool(comp.get("setor_manual", False)),
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


def _codigo_pp_ou_cj(linha):
    codigo = normalizar_codigo(linha.get("codigo", ""))
    if len(codigo) >= 2 and codigo[:2] in {"20", "30"}:
        return True
    referencia = normalizar_texto(f"{linha.get('grupo', '')} {linha.get('categoria', '')}")
    return "PRODUTO EM PROCESSO" in referencia or "CONJUNTO" in referencia or "KIT" in referencia


def _info_linha(linha, catalogo=None):
    linha = dict(linha or {})
    codigo = normalizar_codigo(linha.get("codigo", ""))
    info = dict((catalogo or {}).get(codigo, {}) if catalogo else {})
    info.update({chave: valor for chave, valor in linha.items() if valor not in (None, "")})
    info["codigo"] = codigo
    return info


def _regra_preparacao(linha, catalogo=None):
    info = _info_linha(linha, catalogo)
    codigo = normalizar_codigo(info.get("codigo", ""))
    categoria = normalizar_texto(info.get("categoria", ""))
    grupo = normalizar_texto(info.get("grupo", ""))
    descricao = normalizar_texto(info.get("descricao", ""))
    referencia = f"{categoria} {grupo} {descricao}"

    if codigo.startswith("3020") and "BANCO" in referencia:
        return "CJ_BANCOS"
    if _eh_cj_teto(codigo, grupo, descricao):
        return "CJ_TETO"
    if "TRILHO" in referencia:
        return "TRILHO"
    if "REFORCO" in referencia:
        return "REFORCO"
    if "ISOLAMENTO" in referencia:
        return "ISOLAMENTO"
    if "PISO" in categoria and _codigo_pp_ou_cj(info):
        return "PISO"
    if "ACABAMENTO" in categoria and _codigo_pp_ou_cj(info):
        return "ACABAMENTO"
    return ""


def _codigo_cj_bancos(codigo):
    return normalizar_codigo(codigo).startswith("3020")


def _descendente_cj_bancos(linha, pai_por_codigo=None):
    codigo = normalizar_codigo(linha.get("codigo", ""))
    pai = normalizar_codigo(linha.get("item", ""))
    visitados = set()
    while pai and pai != codigo and pai not in visitados:
        if _codigo_cj_bancos(pai):
            return True
        visitados.add(pai)
        pai = normalizar_codigo((pai_por_codigo or {}).get(pai, ""))
    return False


def _forcar_linha_layout_preparacao(linha):
    linha = dict(linha or {})
    linha["setor"] = SETOR_PREPARACAO
    linha["tipo_requisicao"] = TIPO_REQUISICAO_MATERIAL
    linha["layout_preparacao"] = True
    return linha


def linhas_layout_preparacao(itens, catalogo=None):
    linhas = []
    vistos = set()
    for item in itens or []:
        codigo = normalizar_codigo(item.get("codigo", ""))
        info = _info_linha(item, catalogo)
        regra = _regra_preparacao(info, catalogo)
        if not codigo or not regra or codigo in vistos:
            continue
        vistos.add(codigo)
        qtd = item.get("qtd", item.get("quantidade", ""))
        linha = _forcar_linha_layout_preparacao(
            {
                "item": codigo,
                "codigo": codigo,
                "descricao": info.get("descricao", "") or "",
                "unidade": info.get("unidade", "") or "",
                "qtd": qtd,
                "level": 0,
                "grupo": info.get("grupo", "") or "",
                "categoria": info.get("categoria", "") or "",
                "fornecedor": info.get("fornecedor", "") or "",
                "setor_origem": SETOR_PREPARACAO,
                "regra_preparacao": regra,
            }
        )
        if regra == "CJ_BANCOS":
            linha["ocultar_composicao_preparacao"] = True
        linhas.append(linha)
    return linhas


def filtrar_linhas_preparacao(linhas):
    resultado = []
    pai_por_codigo = {
        normalizar_codigo(linha.get("codigo", "")): normalizar_codigo(linha.get("item", ""))
        for linha in (linhas or [])
        if normalizar_codigo(linha.get("codigo", ""))
    }
    for linha in linhas or []:
        if linha.get("tipo_requisicao") == TIPO_REQUISICAO_FATURAMENTO_DIRETO:
            continue
        if linha.get("setor_manual"):
            if linha.get("setor") == SETOR_PREPARACAO:
                resultado.append(_forcar_linha_layout_preparacao(linha))
            continue
        if _descendente_cj_bancos(linha, pai_por_codigo):
            continue
        regra = _regra_preparacao(linha)
        if not regra:
            continue
        linha_preparacao = _forcar_linha_layout_preparacao(linha)
        linha_preparacao["regra_preparacao"] = regra
        if regra == "CJ_BANCOS":
            linha_preparacao["ocultar_composicao_preparacao"] = True
        resultado.append(linha_preparacao)
    return resultado


def filtrar_linhas_faturamento_direto(linhas):
    return [
        linha
        for linha in (linhas or [])
        if linha.get("tipo_requisicao") == TIPO_REQUISICAO_FATURAMENTO_DIRETO
    ]


def propagar_setor_preparacao(linhas, catalogo=None, componentes=None):
    linhas = [dict(linha or {}) for linha in (linhas or [])]
    pai_por_codigo = {
        normalizar_codigo(linha.get("codigo", "")): normalizar_codigo(linha.get("item", ""))
        for linha in linhas
        if normalizar_codigo(linha.get("codigo", ""))
    }
    for linha in linhas:
        if linha.get("tipo_requisicao") == TIPO_REQUISICAO_FATURAMENTO_DIRETO:
            continue
        if linha.get("setor_manual"):
            linha["setor_origem"] = linha.get("setor", SETOR_EXPEDICAO)
            continue
        if _descendente_cj_bancos(linha, pai_por_codigo):
            setor = SETOR_EXPEDICAO
        else:
            setor = SETOR_PREPARACAO if _regra_preparacao(linha, catalogo) else SETOR_EXPEDICAO
        linha["setor"] = setor
        linha["setor_origem"] = setor
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


def _nivel_engenharia(linha):
    try:
        level = int(linha.get("level", 0) or 0)
    except Exception:
        level = 0
    return max(1, level + 1)


def construir_itens_os_expedicao(linhas):
    itens = []
    for linha in linhas or []:
        nivel = _nivel_engenharia(linha)
        codigo = normalizar_codigo(linha.get("codigo", ""))
        pai = normalizar_codigo(linha.get("item", ""))
        descricao = linha.get("descricao", "") or ""
        prefixo = ">" * nivel
        if pai and pai != codigo:
            descricao = f"{prefixo} {descricao} (consumido por: {pai})".strip()
        else:
            descricao = f"{prefixo} {descricao}".strip()
        itens.append(
            {
                "codigo": codigo,
                "descricao": descricao,
                "qtd": linha.get("qtd", "") if linha.get("qtd", "") != 0 else "",
                "serie": "",
                "visto": "",
                "unidade": linha.get("unidade", "") or "",
                "grupo": linha.get("grupo", "") or "",
                "categoria": linha.get("categoria", "") or "",
                "fornecedor": linha.get("fornecedor", "") or "",
                "setor": linha.get("setor", "") or "",
                "tipo_requisicao": linha.get("tipo_requisicao", "") or "",
                "item": pai,
                "level": nivel,
            }
        )
    return itens


def construir_itens_os_preparacao(linhas):
    itens = []
    for linha in linhas or []:
        nivel = _nivel_engenharia(linha)
        codigo = normalizar_codigo(linha.get("codigo", ""))
        pai = normalizar_codigo(linha.get("item", ""))
        descricao = linha.get("descricao", "") or ""
        prefixo = ">" * nivel
        if pai and pai != codigo:
            descricao = f"{prefixo} {descricao} (consumido por: {pai})".strip()
        else:
            descricao = f"{prefixo} {descricao}".strip()
        itens.append(
            {
                "codigo": codigo,
                "descricao": descricao,
                "qtd": linha.get("qtd", "") if linha.get("qtd", "") != 0 else "",
                "serie": "",
                "unidade": linha.get("unidade", "") or "",
                "grupo": linha.get("grupo", "") or "",
                "categoria": linha.get("categoria", "") or "",
                "fornecedor": linha.get("fornecedor", "") or "",
                "setor": linha.get("setor", "") or "",
                "tipo_requisicao": linha.get("tipo_requisicao", "") or "",
                "item": pai,
                "level": nivel,
            }
        )
    return itens
