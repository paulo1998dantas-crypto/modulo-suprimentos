import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
        self.assertIn("supabase_catalog.active_bank_sets(code, 100)", source)
        self.assertIn(
            '_erp_mes_request(f"work-orders/{work_id}/bank", "PATCH", payload)',
            source,
        )

    def test_closed_order_ui_edits_only_bank_and_requires_reason(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="correct-bank-button"', template)
        self.assertIn('id="bank-correction-reason"', template)
        self.assertIn("!editable", template)
        self.assertIn("form.elements.codigo_banco.disabled=false", template)
        self.assertIn("form.elements.conjunto_bancos.disabled=false", template)
        self.assertIn("motivo:why", template)
        self.assertIn("O status da O.S. não será alterado", template)


if __name__ == "__main__":
    unittest.main()
