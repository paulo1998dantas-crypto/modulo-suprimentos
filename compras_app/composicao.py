def normalizar_codigo(valor):
    texto = (valor or "").strip()
    if not texto:
        return ""
    return texto.split(" - ", 1)[0].strip()


def parse_quantidade(valor):
    if valor in ("", None):
        return 0.0
    texto = str(valor).strip().replace(",", ".")
    try:
        return float(texto)
    except Exception:
        return 0.0


def consolidar_componentes_por_codigo(linhas, estrategia="max"):
    """Mantém uma única linha por SKU sem perder a necessidade calculada.

    ``somar`` é usado na explosão normal de raízes independentes. ``max`` é
    usado ao mesclar uma composição já existente com inclusões manuais: nesse
    caso a mesma subárvore pode estar presente duas vezes e não deve ser
    contabilizada novamente.
    """
    resultado = []
    indice_por_codigo = {}
    for original in linhas or []:
        linha = dict(original or {})
        codigo = normalizar_codigo(linha.get("codigo", ""))
        linha["codigo"] = codigo
        if not codigo or codigo not in indice_por_codigo:
            if codigo:
                indice_por_codigo[codigo] = len(resultado)
            resultado.append(linha)
            continue

        atual = resultado[indice_por_codigo[codigo]]
        qtd_atual = parse_quantidade(atual.get("qtd", atual.get("quantidade", 0)))
        qtd_nova = parse_quantidade(linha.get("qtd", linha.get("quantidade", 0)))
        qtd_final = qtd_atual + qtd_nova if estrategia == "somar" else max(qtd_atual, qtd_nova)
        if qtd_final or atual.get("qtd", atual.get("quantidade", "")) not in ("", None):
            atual["qtd"] = qtd_final

        for campo in ("descricao", "unidade", "grupo", "categoria", "fornecedor", "tipo_requisicao"):
            if atual.get(campo, "") in ("", None) and linha.get(campo, "") not in ("", None):
                atual[campo] = linha.get(campo)
        try:
            atual["level"] = min(int(atual.get("level", 0) or 0), int(linha.get("level", 0) or 0))
        except (TypeError, ValueError):
            pass
        if linha.get("setor_manual") and linha.get("setor"):
            atual["setor"] = linha.get("setor")
            atual["setor_manual"] = True
    return resultado


def _codigo_alcancavel_por_bom(codigo_raiz, codigo_alvo, componentes, visitados=None):
    raiz = normalizar_codigo(codigo_raiz)
    alvo = normalizar_codigo(codigo_alvo)
    if not raiz or not alvo or raiz == alvo:
        return False
    visitados = set(visitados or ())
    if raiz in visitados:
        return False
    visitados.add(raiz)
    for comp in componentes.get(raiz, []) or []:
        codigo = normalizar_codigo(comp.get("codigo", ""))
        if codigo == alvo:
            return True
        if codigo and _codigo_alcancavel_por_bom(codigo, alvo, componentes, visitados):
            return True
    return False


def normalizar_componentes(componentes):
    normalizados = {}
    for item_codigo, comps in (componentes or {}).items():
        item_norm = normalizar_codigo(item_codigo)
        if not item_norm:
            continue
        destino = normalizados.setdefault(item_norm, [])
        for comp in comps or []:
            linha = dict(comp or {})
            linha["codigo"] = normalizar_codigo(linha.get("codigo", ""))
            destino.append(linha)
    return normalizados


def normalizar_linha_composicao(comp, item="", level=0):
    linha = {
        "item": normalizar_codigo(item),
        "codigo": normalizar_codigo(comp.get("codigo", "")),
        "descricao": comp.get("descricao", "") or "",
        "unidade": comp.get("unidade", "") or "",
        "qtd": comp.get("qtd", comp.get("quantidade", "")),
        "level": level or 0,
    }
    for campo in ("grupo", "categoria", "fornecedor", "setor", "tipo_requisicao", "setor_manual"):
        if comp.get(campo, "") != "":
            linha[campo] = comp.get(campo, "")
    return linha


def _linha_item_sem_bom(item):
    codigo = normalizar_codigo(item.get("codigo", ""))
    return {
        "item": codigo,
        "codigo": codigo,
        "descricao": item.get("descricao", "") or "",
        "unidade": item.get("unidade", "") or "",
        "qtd": item.get("qtd", item.get("quantidade", "")),
        "level": 0,
        "grupo": item.get("grupo", "") or "",
        "categoria": item.get("categoria", "") or "",
        "fornecedor": item.get("fornecedor", "") or "",
    }


def _descricao_contem_cj_trilho(item):
    return "CJ TRILHO" in str((item or {}).get("descricao", "") or "").upper()


def expandir_composicao_item(codigo_item, quantidade, componentes, start_level=0):
    codigo_raiz = normalizar_codigo(codigo_item)
    if not codigo_raiz or codigo_raiz not in componentes:
        return []

    linhas = []

    def visitar(codigo_pai, multiplicador, level, ancestrais):
        for comp in componentes.get(codigo_pai, []) or []:
            codigo_comp = normalizar_codigo(comp.get("codigo", ""))
            qtd_base = parse_quantidade(comp.get("quantidade", comp.get("qtd", 0)))
            qtd_total = multiplicador * qtd_base
            linhas.append(
                {
                    "item": codigo_pai,
                    "codigo": codigo_comp,
                    "descricao": comp.get("descricao", "") or "",
                    "unidade": comp.get("unidade", "") or "",
                    "qtd": qtd_total if qtd_total else "",
                    "level": level,
                }
            )
            if codigo_comp and qtd_total and codigo_comp not in ancestrais and codigo_comp in componentes:
                proximos = set(ancestrais)
                proximos.add(codigo_comp)
                visitar(codigo_comp, qtd_total, level + 1, proximos)

    visitar(codigo_raiz, parse_quantidade(quantidade), start_level, {codigo_raiz})
    return linhas


def expandir_composicao_itens(itens, componentes, incluir_itens_sem_bom=True):
    itens_consolidados = []
    indice_por_codigo = {}
    for original in itens or []:
        item = dict(original or {})
        codigo = normalizar_codigo(item.get("codigo", ""))
        if not codigo:
            continue
        if codigo not in indice_por_codigo:
            indice_por_codigo[codigo] = len(itens_consolidados)
            item["codigo"] = codigo
            itens_consolidados.append(item)
            continue
        existente = itens_consolidados[indice_por_codigo[codigo]]
        existente["qtd"] = (
            parse_quantidade(existente.get("qtd", existente.get("quantidade", 0)))
            + parse_quantidade(item.get("qtd", item.get("quantidade", 0)))
        )

    codigos_raiz = [normalizar_codigo(item.get("codigo", "")) for item in itens_consolidados]
    redundantes = set()
    for indice, codigo in enumerate(codigos_raiz):
        for outro_indice, outro in enumerate(codigos_raiz):
            if indice == outro_indice:
                continue
            if not _codigo_alcancavel_por_bom(outro, codigo, componentes):
                continue
            # Em um ciclo de B.O.M. preserva a primeira raiz, evitando eliminar
            # todas as árvores por um cadastro de engenharia inconsistente.
            if _codigo_alcancavel_por_bom(codigo, outro, componentes) and indice < outro_indice:
                continue
            redundantes.add(codigo)
            break

    linhas = []
    for item in itens_consolidados:
        codigo_item = normalizar_codigo(item.get("codigo", ""))
        if codigo_item in redundantes:
            continue
        if codigo_item and componentes.get(codigo_item):
            if _descricao_contem_cj_trilho(item):
                linhas.append(
                    normalizar_linha_composicao(
                        item,
                        item=codigo_item,
                        level=0,
                    )
                )
            linhas.extend(
                expandir_composicao_item(
                    codigo_item,
                    item.get("qtd", item.get("quantidade", 0)),
                    componentes,
                    start_level=1 if _descricao_contem_cj_trilho(item) else 0,
                )
            )
        elif codigo_item and incluir_itens_sem_bom:
            linhas.append(_linha_item_sem_bom(item))
    return consolidar_componentes_por_codigo(linhas, estrategia="somar")


def expandir_composicao_referenciada(linhas, componentes):
    componentes = normalizar_componentes(componentes)
    resultado = []

    def visitar(codigo_pai, quantidade_pai, level, ancestrais):
        for comp in componentes.get(codigo_pai, []) or []:
            codigo_comp = normalizar_codigo(comp.get("codigo", ""))
            qtd_base = parse_quantidade(comp.get("quantidade", comp.get("qtd", 0)))
            qtd_total = quantidade_pai * qtd_base
            resultado.append(
                {
                    "item": codigo_pai,
                    "codigo": codigo_comp,
                    "descricao": comp.get("descricao", "") or "",
                    "unidade": comp.get("unidade", "") or "",
                    "qtd": qtd_total if qtd_total else "",
                    "level": level,
                }
            )
            if codigo_comp and qtd_total and codigo_comp not in ancestrais and codigo_comp in componentes:
                proximos = set(ancestrais)
                proximos.add(codigo_comp)
                visitar(codigo_comp, qtd_total, level + 1, proximos)

    for linha in linhas or []:
        item_raiz = normalizar_codigo(linha.get("item", "")) or normalizar_codigo(linha.get("codigo", ""))
        codigo = normalizar_codigo(linha.get("codigo", ""))
        try:
            level = int(linha.get("level", 0) or 0)
        except Exception:
            level = 0

        resultado.append(
            normalizar_linha_composicao(
                linha,
                item=item_raiz,
                level=level,
            )
        )

        qtd = parse_quantidade(linha.get("qtd", linha.get("quantidade", 0)))
        if codigo and qtd and codigo in componentes:
            visitar(codigo, qtd, level + 1, {codigo})

    return consolidar_componentes_por_codigo(resultado, estrategia="somar")


def mesclar_raizes_adicionais(linhas_base, raizes_adicionais, componentes):
    """Inclui seleções extras sem reexplodir uma raiz já coberta pela B.O.M.

    Uma luminária, conjunto ou item de popup que já aparece na árvore principal
    não cria uma segunda necessidade. Quando a raiz é realmente independente,
    componentes compartilhados são mantidos em uma única linha e têm suas
    quantidades somadas.
    """
    resultado = consolidar_componentes_por_codigo(linhas_base, estrategia="max")
    existentes = {
        normalizar_codigo(linha.get("codigo", ""))
        for linha in resultado
        if normalizar_codigo(linha.get("codigo", ""))
    }
    raizes_por_codigo = {}
    ordem = []
    for original in raizes_adicionais or []:
        raiz = dict(original or {})
        codigo = normalizar_codigo(raiz.get("codigo", ""))
        if not codigo or codigo in existentes:
            continue
        raiz["codigo"] = codigo
        if codigo not in raizes_por_codigo:
            raizes_por_codigo[codigo] = raiz
            ordem.append(codigo)
            continue
        atual = raizes_por_codigo[codigo]
        atual["qtd"] = (
            parse_quantidade(atual.get("qtd", atual.get("quantidade", 0)))
            + parse_quantidade(raiz.get("qtd", raiz.get("quantidade", 0)))
        )

    for codigo in ordem:
        expandidas = expandir_composicao_referenciada([raizes_por_codigo[codigo]], componentes)
        resultado = consolidar_componentes_por_codigo(
            [*resultado, *expandidas],
            estrategia="somar",
        )
    return resultado


def expandir_composicao_manual(linhas, componentes):
    """Normaliza uma composição editada manualmente e expande itens-raiz com B.O.M.

    A tela de O.S. permite adicionar materiais além dos itens originalmente
    selecionados. Quando esse material é um conjunto, ele deve seguir a mesma
    regra de explosão da B.O.M. dos itens principais. Apenas linhas-raiz
    (``item`` vazio ou igual ao próprio ``codigo``) são expandidas aqui: as
    linhas-filhas já gravadas por uma explosão anterior permanecem intactas e
    não são duplicadas.
    """
    componentes_norm = normalizar_componentes(componentes)
    resultado = []

    for linha in linhas or []:
        origem = dict(linha or {})
        codigo = normalizar_codigo(origem.get("codigo", ""))
        item_pai = normalizar_codigo(origem.get("item", ""))
        try:
            level = int(origem.get("level", 0) or 0)
        except (TypeError, ValueError):
            level = 0

        quantidade = parse_quantidade(origem.get("qtd", origem.get("quantidade", "")))
        if not quantidade and origem.get("qtd", origem.get("quantidade", "")) in ("", None):
            quantidade = 1.0

        linha_raiz = not item_pai or item_pai == codigo
        if linha_raiz and codigo and quantidade and codigo in componentes_norm:
            raiz = normalizar_linha_composicao(
                origem,
                item=codigo,
                level=level,
            )
            filhos = expandir_composicao_item(
                codigo,
                quantidade,
                componentes_norm,
                start_level=level + 1,
            )
            if origem.get("setor_manual") and origem.get("setor"):
                for filho in filhos:
                    filho["setor"] = origem["setor"]
                    filho["setor_manual"] = True
            resultado.append(raiz)
            resultado.extend(filhos)
            continue

        # Itens sem B.O.M. continuam sendo linhas normais de composição.
        resultado.append(
            normalizar_linha_composicao(
                origem,
                item=item_pai or codigo,
                level=level,
            )
        )

    return consolidar_componentes_por_codigo(resultado, estrategia="max")


def resolver_composicao_final(itens, componentes, composicao_importada=None):
    componentes_norm = normalizar_componentes(componentes)
    linhas = expandir_composicao_itens(itens, componentes_norm)
    if linhas:
        return linhas
    if composicao_importada:
        return expandir_composicao_referenciada(composicao_importada, componentes_norm)
    return []
