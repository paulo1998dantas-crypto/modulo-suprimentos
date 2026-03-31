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
    return {
        "item": normalizar_codigo(item),
        "codigo": normalizar_codigo(comp.get("codigo", "")),
        "descricao": comp.get("descricao", "") or "",
        "unidade": comp.get("unidade", "") or "",
        "qtd": comp.get("qtd", comp.get("quantidade", "")),
        "level": level or 0,
    }


def expandir_composicao_item(codigo_item, quantidade, componentes):
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

    visitar(codigo_raiz, parse_quantidade(quantidade), 0, {codigo_raiz})
    return linhas


def expandir_composicao_itens(itens, componentes):
    linhas = []
    for item in itens:
        linhas.extend(
            expandir_composicao_item(
                item.get("codigo", ""),
                item.get("qtd", 0),
                componentes,
            )
        )
    return linhas
