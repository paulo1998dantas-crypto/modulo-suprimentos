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


if __name__ == "__main__":
    unittest.main()
