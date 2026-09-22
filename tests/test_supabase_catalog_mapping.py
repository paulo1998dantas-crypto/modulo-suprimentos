import sys
from pathlib import Path
import unittest


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import supabase_catalog  # noqa: E402


class SupabaseCatalogMappingTests(unittest.TestCase):
    def test_detailed_cadastro_group_is_used(self):
        sku, product = supabase_catalog.row_to_produto(
            {
                "sku": "10180192",
                "descricao_primaria": "PP ARO JANELA",
                "category_label": "18 - REVESTIMENTO",
                "ativo": True,
                "field_values": {"prefixo": "PP"},
                "form_values": {"grupo_codigo": ["10"]},
            }
        )

        self.assertEqual(sku, "10180192")
        self.assertEqual(product["grupo"], "10 - INSUMO")
        self.assertEqual(product["descricao"], "PP ARO JANELA")

    def test_legacy_group_fallback_is_preserved_when_cadastro_has_no_detail(self):
        _, product = supabase_catalog.row_to_produto(
            {
                "sku": "10200094",
                "descricao_primaria": "BANCO LEGADO",
                "category_label": "20 - BANCOS",
                "ativo": True,
                "field_values": {},
            }
        )

        self.assertEqual(product["grupo"], "10 - INSUMO")


if __name__ == "__main__":
    unittest.main()
