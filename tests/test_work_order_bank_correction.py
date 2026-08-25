import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
os.environ["SUPRIMENTOS_FILE_LOG"] = "0"

import app as app_module  # noqa: E402


APP = ROOT / "compras_app" / "app.py"
TEMPLATE = ROOT / "compras_app" / "templates" / "erp_gestao_os.html"


class WorkOrderBankCorrectionContractTests(unittest.TestCase):
    def test_backend_validates_catalog_and_proxies_a_bank_only_patch(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn(
            '"/api/erp/os-management/work-orders/<work_id>/bank", methods=["PATCH"]',
            source,
        )
        self.assertIn('@permission_required("suprimentos.work_order.manage")', source)
        self.assertIn("supabase_catalog.active_bank_sets(\"\", 1000)", source)
        self.assertIn("_normalize_work_order_banks(payload)", source)
        self.assertIn('" / ".join(', source)
        self.assertIn("N/A não pode ser combinado com códigos de bancos.", source)
        self.assertIn(
            '_erp_mes_request(f"work-orders/{work_id}/bank", "PATCH", payload)',
            source,
        )

    def test_backend_proxies_the_audited_historical_correction(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn(
            '"/api/erp/os-management/work-orders/<work_id>/historical-correction"',
            source,
        )
        self.assertIn('@permission_required("suprimentos.work_order.manage")', source)
        self.assertIn("Informe o motivo da correção histórica da O.S.", source)
        self.assertIn(
            'f"work-orders/{work_id}/historical-correction"',
            source,
        )

    def test_closed_order_ui_enables_historical_fields_and_requires_reason(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="correct-historical-button"', template)
        self.assertIn('id="historical-correction-reason"', template)
        self.assertIn("!editable", template)
        self.assertIn("historicalEntryPayload()", template)
        self.assertIn("status, etapas, apontamentos, finalização, entrega", template.lower())
        self.assertIn("work_order:work,entry,motivo:why", template)
        self.assertIn("/historical-correction", template)

    def test_work_order_ui_supports_multiple_individual_banks(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="bank-add"', template)
        self.assertIn('id="selected-banks"', template)
        self.assertIn("state.selectedBanks", template)
        self.assertIn(".join(' / ')", template)
        self.assertIn("Adicione quantos bancos individuais forem necessários.", template)

    def test_create_and_update_normalize_banks_before_forwarding_to_mes(self):
        source = APP.read_text(encoding="utf-8")
        create = source.index("def erp_work_order_create_proxy(entry_id):")
        update = source.index("def erp_work_order_update_proxy(work_id):")
        bank_patch = source.index("def erp_work_order_bank_correction_proxy(work_id):")
        self.assertIn(
            "_normalize_work_order_banks(payload)",
            source[create:update],
        )
        self.assertIn(
            "original_description=original_description",
            source[update:bank_patch],
        )

    def test_normalizer_consolidates_multiple_banks_in_selection_order(self):
        payload = {"codigo_banco": "10200003 / 10200001"}
        catalog = [
            {"codigo": "10200001", "descricao": "BCO FIXO 3L"},
            {"codigo": "10200003", "descricao": "BCO RECLINÁVEL 3L"},
        ]
        with patch.object(
            app_module.supabase_catalog,
            "active_bank_sets",
            return_value=catalog,
        ):
            app_module._normalize_work_order_banks(payload)

        self.assertEqual(payload["codigo_banco"], "10200003 / 10200001")
        self.assertEqual(
            payload["conjunto_bancos"],
            "BCO RECLINÁVEL 3L / BCO FIXO 3L",
        )

    def test_partial_payload_does_not_clear_an_existing_bank(self):
        payload = {"linha": "LB"}

        app_module._normalize_work_order_banks(payload)

        self.assertEqual(payload, {"linha": "LB"})


if __name__ == "__main__":
    unittest.main()
