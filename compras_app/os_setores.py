import re
import unicodedata

from composicao import normalizar_codigo, parse_quantidade


SETOR_EXPEDICAO = "EXPEDICAO"
SETOR_PREPARACAO = "PREPARACAO"
SETOR_NULO = "NULO"
SETOR_FATURAMENTO_DIRETO = "F.D"
SETORES_VALIDOS = {SETOR_EXPEDICAO, SETOR_PREPARACAO, SETOR_FATURAMENTO_DIRETO, SETOR_NULO}
CODIGOS_DESTINO_NULO = frozenset({"10240301", "10240299", "10320035", "10240131", "30240102", "30240032"})
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


def eh_faturamento_direto(*valores):
    """Reconhece o conceito por nome completo ou pela sigla operacional F.D."""
    for valor in valores:
        tokens = re.findall(r"[A-Z0-9]+", normalizar_texto(valor))
        for indice, token in enumerate(tokens):
            proximo = tokens[indice + 1] if indice + 1 < len(tokens) else ""
            if (token, proximo) in {("FATURAMENTO", "DIRETO"), ("F", "D")}:
                return True
            if token == "FD":
                return True
    return False


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
    if codigo in CODIGOS_DESTINO_NULO:
        return SETOR_NULO
    if _regra_preparacao_obrigatoria(item_info):
        return SETOR_PREPARACAO
    if classificar_tipo_requisicao(item_info) == TIPO_REQUISICAO_FATURAMENTO_DIRETO:
        return SETOR_FATURAMENTO_DIRETO
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


def _regra_preparacao_obrigatoria(item_info):
    """Padrão para cadastros atuais e futuros, sem impedir escolha manual."""
    info = item_info or {}
    codigo = normalizar_codigo(info.get("codigo", ""))
    grupo = normalizar_texto(info.get("grupo", ""))
    descricao = normalizar_texto(info.get("descricao", ""))
    if (codigo.startswith("20") or re.match(r"^20\b", grupo) or re.search(r"\bPP\b", grupo)
            or re.search(r"\bPRODUTO(?: EM)? PROCESSO\b", grupo)
            or re.search(r"\bPP\b", descricao)):
        return "PP"
    if re.search(r"\bCJ MOVE(?:L|IS)\b", descricao):
        return "CJ_MOVEL"
    if re.match(r"^MP (?:PASSADEIRA\b|CHAPA (?:DE )?COMPENSADO\b)", descricao):
        return "MP_PREPARACAO"
    return ""


def setor_foi_editado(linha):
    valor = (linha or {}).get("setor_manual", False)
    return valor is True or str(valor).strip().lower() in {"1", "true", "sim"}


def filtrar_linhas_documento_os(linhas):
    """NULO é apenas visibilidade documental; nunca filtrar a demanda salva."""
    return [linha for linha in linhas or [] if (
        linha.get("setor") if linha.get("setor") in SETORES_VALIDOS
        else classificar_item(linha)
    ) != SETOR_NULO]


def classificar_tipo_requisicao(item_info, descricao=""):
    item_info = item_info or {}
    if eh_faturamento_direto(
        descricao,
        item_info.get("descricao", ""),
        item_info.get("categoria", ""),
        item_info.get("grupo", ""),
        item_info.get("tipo_requisicao", ""),
        item_info.get("setor", ""),
    ):
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
        manual = setor_foi_editado(comp) and comp.get("setor") in SETORES_VALIDOS
        setor = comp["setor"] if manual else classificar_item(info_classificacao)
        tipo_requisicao = (TIPO_REQUISICAO_FATURAMENTO_DIRETO
                           if setor == SETOR_FATURAMENTO_DIRETO else TIPO_REQUISICAO_MATERIAL)
        unidade_cadastro = item_info.get("unidade", "") or ""
        unidade = unidade_cadastro or comp.get("unidade", "") or ""
        qtd = _converter_qtd_para_unidade_cadastro(comp.get("qtd", ""), comp.get("unidade", ""), unidade_cadastro)
        linha = {
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
                "setor_manual": manual,
                "tipo_requisicao": tipo_requisicao,
            }
        # A linha é reclassificada aqui, mas a decisão explícita de versão
        # precisa atravessar toda a cadeia até o documento/Supabase.
        for campo in (
            "pais_origem",
            "line_id",
            "equivalence_group_id",
            "equivalence_group_code",
            "equivalence_group_name",
            "sku_planejado",
            "sku_selecionado",
            "quantidade_planejada",
            "equivalence_planned_factor",
            "equivalence_selected_factor",
            "equivalence_reason",
            "equivalence_selected_by",
        ):
            if comp.get(campo, "") != "":
                linha[campo] = comp.get(campo, "")
        linhas.append(linha)
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

    obrigatoria = _regra_preparacao_obrigatoria(info)
    if obrigatoria:
        return obrigatoria
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


def _forcar_linha_layout_preparacao(linha):
    linha = dict(linha or {})
    linha["setor"] = SETOR_PREPARACAO
    linha["tipo_requisicao"] = TIPO_REQUISICAO_MATERIAL
    linha["layout_preparacao"] = True
    return linha


def linhas_layout_preparacao(itens, catalogo=None, composicao=None):
    linhas = []
    vistos = set()
    destinos_editados = {normalizar_codigo(linha.get("codigo", "")): linha.get("setor")
                         for linha in composicao or [] if setor_foi_editado(linha)}
    for item in itens or []:
        codigo = normalizar_codigo(item.get("codigo", ""))
        info = _info_linha(item, catalogo)
        regra = _regra_preparacao(info, catalogo)
        destino = item.get("setor") if setor_foi_editado(item) else classificar_item(info)
        destino = destinos_editados.get(codigo, destino)
        if not codigo or destino != SETOR_PREPARACAO or not regra or codigo in vistos:
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
        linhas.append(linha)
    return linhas


def filtrar_linhas_preparacao(linhas):
    # Não reclassificar aqui: o destino herdado também inclui matérias-primas
    # e subníveis sem palavras-chave na descrição.
    return [_forcar_linha_layout_preparacao(linha)
            for linha in filtrar_linhas_setor(linhas, SETOR_PREPARACAO)]


def filtrar_linhas_faturamento_direto(linhas):
    return [
        linha
        for linha in (linhas or [])
        if linha.get("setor") != SETOR_NULO
        and linha.get("tipo_requisicao") == TIPO_REQUISICAO_FATURAMENTO_DIRETO
    ]


def propagar_setor_preparacao(linhas, catalogo=None, componentes=None):
    """Resolve pelo snapshot editado da O.S., nunca reinclui itens da B.O.M.

    Destino manual vence o padrão; filhos acompanham preparação e alterações
    manuais de um pai. NULO esconde só sua linha. F.D. conserva o fluxo próprio.
    """
    linhas = [dict(linha or {}) for linha in (linhas or [])]
    por_codigo = {normalizar_codigo(linha.get("codigo", "")): linha for linha in linhas}
    cache = {}

    def resolver(codigo, visitados, linha_atual=None):
        linha = linha_atual if linha_atual is not None else por_codigo.get(codigo)
        chave = ("linha", id(linha)) if linha is not None else ("catalogo", codigo)
        if chave in cache:
            return cache[chave]
        if linha is None:
            linha = {"codigo": codigo}
        info = _info_linha(linha, catalogo)
        automatico = classificar_item(info)
        if setor_foi_editado(linha) and linha.get("setor") in SETORES_VALIDOS:
            return linha["setor"], True
        if codigo in visitados:
            return automatico, False
        if automatico in {SETOR_NULO, SETOR_FATURAMENTO_DIRETO}:
            return automatico, False
        pais = [linha.get("item", ""), *(linha.get("pais_origem") or [])]
        destinos_pais = []
        for valor in pais:
            pai = normalizar_codigo(valor)
            if pai and pai != codigo:
                destinos_pais.append(resolver(pai, visitados | {codigo}))
        manuais = [destino for destino, manual in destinos_pais
                   if manual and destino in {SETOR_PREPARACAO, SETOR_EXPEDICAO}]
        if manuais:
            resultado = (SETOR_PREPARACAO if SETOR_PREPARACAO in manuais else SETOR_EXPEDICAO), True
        else:
            preparacao = automatico == SETOR_PREPARACAO or any(
                destino == SETOR_PREPARACAO for destino, _ in destinos_pais)
            resultado = (SETOR_PREPARACAO if preparacao else SETOR_EXPEDICAO), False
        cache[chave] = resultado
        return resultado

    for linha in linhas:
        setor, _ = resolver(normalizar_codigo(linha.get("codigo", "")), set(), linha)
        linha["setor"] = setor
        linha["setor_origem"] = setor
        linha["tipo_requisicao"] = (TIPO_REQUISICAO_FATURAMENTO_DIRETO
                                   if setor == SETOR_FATURAMENTO_DIRETO else TIPO_REQUISICAO_MATERIAL)
        regra = _regra_preparacao(linha, catalogo)
        if setor == SETOR_PREPARACAO:
            linha["regra_preparacao"] = regra or "HERDADO"
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
