import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"


class WorkOrderReplacementTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (APP_DIR / "templates" / "erp_gestao_os.html").read_text(
            encoding="utf-8"
        )

    def test_cancelled_current_order_offers_explicit_replacement(self):
        self.assertIn("can_create_replacement", self.template)
        self.assertIn("+ Nova O.S. no ITEM", self.template)
        self.assertIn("openWork('${row.entry_id}',true)", self.template)

    def test_replacement_payload_identifies_cancelled_revision(self):
        self.assertIn("data.create_replacement=true", self.template)
        self.assertIn(
            "data.supersedes_work_order_id=state.replacementSourceId",
            self.template,
        )

    def test_replacement_starts_without_copying_cancelled_demand_fields(self):
        self.assertIn("const workFields=[", self.template)
        self.assertIn("Object.fromEntries(workFields.map(name=>[name,null]))", self.template)
        self.assertIn("a nova demanda começa sem etapas copiadas", self.template)


if __name__ == "__main__":
    unittest.main()
