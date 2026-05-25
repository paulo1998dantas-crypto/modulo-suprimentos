from processos_os import identificar_nome_processo, normalizar_texto


def texto_linha(row):
    partes = []
    for cell in row.cells:
        texto = " ".join((cell.text or "").split())
        if texto:
            partes.append(texto)
    return " | ".join(partes)


def encontrar_linha_cabecalho(table, *tokens):
    if len(tokens) == 1 and isinstance(tokens[0], (list, tuple, set)):
        tokens = list(tokens[0])
    tokens_norm = [normalizar_texto(token) for token in tokens if token]
    for idx, row in enumerate(table.rows):
        texto = normalizar_texto(texto_linha(row))
        if texto and all(token in texto for token in tokens_norm):
            return idx
    return None


def mapear_tabelas_os(doc):
    refs = {
        "cabecalho": None,
        "dados": None,
        "itens": None,
        "composicao": None,
        "observacoes": None,
        "layout": None,
        "processos": {},
    }

    for idx, table in enumerate(doc.tables):
        primeira_linha = texto_linha(table.rows[0]) if table.rows else ""
        segunda_linha = texto_linha(table.rows[1]) if len(table.rows) > 1 else ""
        titulo_tabela = normalizar_texto(primeira_linha)
        texto_tabela = normalizar_texto(f"{primeira_linha} {segunda_linha}")

        processo = identificar_nome_processo(primeira_linha or texto_tabela)
        if processo:
            refs["processos"].setdefault(processo, idx)
            continue

        if refs["composicao"] is None and "COMPOSICAO" in titulo_tabela:
            refs["composicao"] = idx
            continue

        if refs["layout"] is None and "LAYOUT DO VEICULO" in titulo_tabela:
            refs["layout"] = idx
            continue

        if refs["observacoes"] is None and "OBSERVACO" in titulo_tabela:
            refs["observacoes"] = idx
            continue

        if refs["dados"] is None and "DADOS DA ORDEM" in titulo_tabela:
            refs["dados"] = idx
            continue

        if refs["cabecalho"] is None and "ORDEM DE SERVICO" in titulo_tabela:
            refs["cabecalho"] = idx
            continue

        if refs["itens"] is None:
            header_idx = encontrar_linha_cabecalho(table, "CODIGO", "QTD")
            if header_idx == 0:
                if ("PRODUTO" in titulo_tabela or "DESCRICAO" in titulo_tabela) and "COMPOSICAO" not in titulo_tabela:
                    refs["itens"] = idx

    return refs
