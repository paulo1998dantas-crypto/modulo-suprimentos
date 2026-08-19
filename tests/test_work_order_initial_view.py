import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "compras_app" / "app.py"
TEMPLATE = ROOT / "compras_app" / "templates" / "erp_gestao_os.html"


class WorkOrderInitialViewContractTest(unittest.TestCase):
    def test_route_accepts_only_known_initial_views(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn('request.args.get("view")', source)
        self.assertIn('"ACTIVE"', source)
        self.assertIn("initial_view=initial_view", source)

    def test_template_selects_and_preserves_initial_view(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("initial_view == 'ACTIVE'", template)
        self.assertIn("value='{{ initial_view }}'", template)

    def test_main_save_persists_entry_before_work_order_without_reopening_dialog(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("async function persistEntry()", template)
        self.assertIn("await persistEntry();const result=workId?await api", template)
        save_entry = template.split("async function saveEntryData(){", 1)[1].split(
            "async function saveWork", 1
        )[0]
        self.assertNotIn("await loadOrders()", save_entry)
        self.assertNotIn("openWork(entryId)", save_entry)

    def test_client_is_edited_only_in_vehicle_entry(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(1, template.count('name="entry_cliente_nome"'))
        self.assertNotIn('name="cliente_nome"', template)
        self.assertIn("delete data.cliente_nome", template)
        self.assertIn("O cliente é definido exclusivamente nos dados da entrada", template)


if __name__ == "__main__":
    unittest.main()
