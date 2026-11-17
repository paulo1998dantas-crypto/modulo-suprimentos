import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compras_app"))

from processos_transformacao import (
    PROCESSO_BANCO_PADRAO,
    PROCESSO_ELETRICA1_PADRAO,
    construir_processo_por_item,
    resolver_processos_transformacao,
)


class ProcessDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.templates = [PROCESSO_BANCO_PADRAO, PROCESSO_ELETRICA1_PADRAO, "PROCESSO ESPECIFICO"]

    def test_new_bank_sku_gets_bank_process_without_an_explicit_link(self):
        mapping = construir_processo_por_item({"30209999": {"descricao": "CJ BANCOS NOVO"}}, self.templates)
        self.assertEqual([PROCESSO_BANCO_PADRAO], mapping["30209999"])

    def test_existing_bank_link_is_kept_and_standard_is_added_once(self):
        mapping = construir_processo_por_item(
            {"30200004": {}}, self.templates,
            {"30200004": ["PROCESSO ESPECIFICO", PROCESSO_BANCO_PADRAO]},
        )
        self.assertEqual(["PROCESSO ESPECIFICO", PROCESSO_BANCO_PADRAO], mapping["30200004"])

    def test_raw_bank_material_does_not_get_bank_process(self):
        mapping = construir_processo_por_item({"10200085": {"descricao": "BCO"}}, self.templates)
        self.assertEqual([PROCESSO_ELETRICA1_PADRAO], mapping["10200085"])

    def test_unlinked_item_gets_electrical_fallback(self):
        mapping = construir_processo_por_item({"40349999": {"descricao": "NOVA TRANSFORMACAO"}}, self.templates)
        self.assertEqual([PROCESSO_ELETRICA1_PADRAO], mapping["40349999"])

    def test_custom_process_excludes_electrical_fallback(self):
        mapping = construir_processo_por_item({"40340056": {}}, self.templates, {"40340056": ["PROCESSO ESPECIFICO"]})
        self.assertEqual(["PROCESSO ESPECIFICO"], mapping["40340056"])

    def test_explicit_product_process_excludes_electrical_fallback(self):
        mapping = construir_processo_por_item({"40349999": {"processo_conjunto": "PROCESSO ESPECIFICO"}}, self.templates)
        self.assertEqual("PROCESSO ESPECIFICO", mapping["40349999"])

    def test_inferred_process_takes_precedence_over_fallback(self):
        mapping = construir_processo_por_item({"40349999": {"descricao": "PROCESSO ESPECIFICO"}}, self.templates)
        self.assertEqual("PROCESSO ESPECIFICO", mapping["40349999"])

    def test_missing_default_templates_do_not_generate_dangling_links(self):
        mapping = construir_processo_por_item({"30209999": {}, "40349999": {}}, [])
        self.assertNotIn("30209999", mapping)
        self.assertNotIn("40349999", mapping)

    def test_order_with_multiple_unlinked_items_has_one_fallback_template(self):
        mapping = construir_processo_por_item({"40349999": {}, "30149999": {}}, self.templates)
        self.assertEqual([PROCESSO_ELETRICA1_PADRAO], resolver_processos_transformacao(["40349999", "30149999"], mapping))

    def test_legacy_mapping_is_preserved(self):
        mapping = construir_processo_por_item({}, self.templates)
        self.assertEqual("SPRINTER 417 10 - SELADO-VISTA - PLUS", mapping["4-0010"])


if __name__ == "__main__":
    unittest.main()
