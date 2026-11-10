"""Explode phantom purchase lines for export without changing orders/receipts."""
from decimal import Decimal

from material_export_bom import MaterialBom, number


def load_current_graph():
    import supabase_catalog
    import supabase_data
    if not supabase_catalog.enabled() or not supabase_data.enabled():
        raise ValueError('Cadastro online indisponível; exportação de trânsito interrompida.')
    try:
        catalog = {}
        # Read fresh registrations, including inactive historical order items.
        for record in supabase_catalog._all_rows():
            code, item = supabase_catalog.row_to_produto({**record, 'ativo': True})
            if not code or code in catalog:
                raise ValueError(f'SKU vazio ou duplicado no Cadastro: {code}.')
            item['descricao'] = item.get('descricao') or str(record.get('descricao_secundaria') or '').strip()
            catalog[code] = {**item, 'active': record.get('ativo') is not False}
        bom = supabase_data._all_rows(
            supabase_data.BOM_COMPONENTS_TABLE,
            select='parent_sku,component_sku,component_descricao,unidade,quantidade,ordem',
            order='parent_sku.asc,ordem.asc,id.asc',
            cache_key='transit_export_bom', force=True,
        )
        return catalog, bom
    except (supabase_catalog.SupabaseCatalogError, supabase_data.SupabaseDataError) as exc:
        raise ValueError('Não foi possível consultar a B.O.M. vigente; exportação de trânsito interrompida.') from exc


def project_transit_rows(rows, catalog, bom):
    projection = MaterialBom(catalog, bom)
    output = []
    for original in rows:
        code = str(original.get('sku_codigo') or '').strip()
        ordered = number(original.get('quantidade_pedida'), code + ' / pedida', positive=True)
        received = number(original.get('quantidade_recebida'), code + ' / recebida')
        pending = number(original.get('quantidade_pendente'), code + ' / pendente', positive=True)
        expected = max(ordered - received, Decimal(0))
        if abs(pending - expected) > Decimal('0.00000001'):
            raise ValueError(f'Saldo pendente inconsistente na O.C. {original.get("numero_oc")}, linha {original.get("numero_linha")}.')
        for leaf, factor in projection.factors(code).items():
            item = catalog[leaf]
            row = dict(original)
            row.update(
                sku_codigo=leaf,
                quantidade_pedida=ordered * factor,
                quantidade_recebida=received * factor,
                quantidade_pendente=expected * factor,
            )
            if leaf != code:
                row.update(descricao_original=item['descricao'], unidade=item['unidade'])
            output.append(row)
    return output


def export_transit_rows(rows):
    if not rows:
        return []
    catalog, bom = load_current_graph()
    return project_transit_rows(rows, catalog, bom)
