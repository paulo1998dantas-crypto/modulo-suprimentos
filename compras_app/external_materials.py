"""External foam/fabric stock is technical BOM information, not supplier purchasing.

Keep this classification identical in Suprimentos and Estoque.
"""
EXTERNAL_FOAM_SKUS = frozenset({
    '10220272', '10220273', '10220274', '10220275', '10220276',
})
EXTERNAL_FABRIC_SKUS = frozenset({'10220269', '10220270', '10280062'})
EXTERNAL_MATERIAL_SKUS = EXTERNAL_FOAM_SKUS | EXTERNAL_FABRIC_SKUS


def is_external_material(code):
    return str(code or '').strip().upper() in EXTERNAL_MATERIAL_SKUS


def internal_purchase_bom(components):
    return {code: [dict(row) for row in rows
                   if not is_external_material(row.get('codigo'))]
            for code, rows in components.items()
            if not is_external_material(code)}
