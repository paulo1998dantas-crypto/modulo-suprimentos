"""Visibility of current O.S. items; never change the master B.O.M. or history."""

from composicao import normalizar_codigo


def cadastro_inativo(cadastro):
    cadastro = cadastro or {}
    if cadastro.get("ativo") is False or cadastro.get("active") is False:
        return True
    extras = cadastro.get("campos_extras") or {}
    status = cadastro.get("status") or extras.get("status") or ""
    return str(status).strip().upper() in {"INATIVO", "INACTIVE"}


def codigos_inativos_catalogos(*catalogos):
    return {
        normalizar_codigo(str(codigo))
        for catalogo in catalogos
        for codigo, cadastro in (catalogo or {}).items()
        if cadastro_inativo(cadastro)
    }


def filtrar_catalogo_os(catalogo, inativos):
    return {
        codigo: cadastro
        for codigo, cadastro in (catalogo or {}).items()
        if normalizar_codigo(str(codigo)) not in inativos
    }


def filtrar_linhas_ativas_os(linhas, inativos):
    """Hide explicitly inactive physical SKUs, not unknown legacy references.

    An active manually selected alternative remains valid even if its planned
    SKU is now inactive. Active children of an inactive assembly also remain;
    this is a line visibility rule, not a change to B.O.M. explosion.
    """
    return [
        dict(linha)
        for linha in linhas or []
        if normalizar_codigo(str(linha.get("sku_selecionado") or linha.get("codigo") or ""))
        not in inativos
    ]


def linhas_para_exibicao_os(linhas, inativos):
    """Suppress inactive parent labels in outputs, keeping stored links intact."""
    resultado = filtrar_linhas_ativas_os(linhas, inativos)
    for linha in resultado:
        if normalizar_codigo(str(linha.get("item") or "")) in inativos:
            linha["item"] = ""
    return resultado
