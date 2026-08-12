import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
os.environ["SUPRIMENTOS_FILE_LOG"] = "0"

import app as app_module  # noqa: E402


class WorkOrderDocumentLinkTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.access = (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "erp_feature_enabled", return_value=True),
            patch.object(app_module, "can", return_value=True),
        )
        for item in self.access:
            item.start()

    def tearDown(self):
        for item in reversed(self.access):
            item.stop()

    @staticmethod
    def document(document_id="101", number="3096", status="emitido", work_id=None):
        return {
            "id": document_id,
            "tipo": "os",
            "numero": number,
            "status": status,
            "data_criacao": "2026-08-04",
            "erp_work_order_id": work_id,
            "dados": {"cliente": "CLIENTE TESTE", "chassis": "9BRTESTE123456789"},
        }

    def test_documents_endpoint_lists_only_active_service_orders(self):
        rows = [
            self.document(),
            self.document("102", "3097", work_id="11111111-1111-1111-1111-111111111111"),
            self.document("103", "3000", status="concluido"),
            self.document(
                "105",
                "3001",
                status="concluido",
                work_id="55555555-5555-5555-5555-555555555555",
            ),
            {**self.document("104", "2723"), "tipo": "oc"},
        ]
        with patch.object(app_module, "_carregar_documentos_os_para_vinculo", return_value=rows):
            response = self.client.get("/api/erp/os-management/documents")

        self.assertEqual(200, response.status_code)
        documents = response.get_json()["documents"]
        self.assertEqual({"101", "102", "105"}, {item["id"] for item in documents})
        by_id = {item["id"]: item for item in documents}
        self.assertTrue(by_id["101"]["available"])
        self.assertFalse(by_id["102"]["available"])
        self.assertFalse(by_id["105"]["available"])

    def test_create_translates_document_id_to_atomic_mes_contract(self):
        rows = [self.document()]
        work_id = "22222222-2222-2222-2222-222222222222"
        with (
            patch.object(app_module, "_carregar_documentos_os_para_vinculo", return_value=rows),
            patch.object(
                app_module,
                "_erp_mes_request",
                return_value={"ok": True, "id": work_id, "numero_os": "3096", "documento_os_id": 101},
            ) as mes_request,
        ):
            response = self.client.post(
                "/api/erp/os-management/entries/entry-1/work-orders",
                json={"document_id": "101", "cliente_nome": "CLIENTE TESTE"},
            )

        self.assertEqual(201, response.status_code)
        self.assertEqual(101, response.get_json()["documento_os_id"])
        self.assertEqual(
            {"cliente_nome": "CLIENTE TESTE", "documento_os_id": 101},
            mes_request.call_args.args[2],
        )

    def test_create_rejects_document_already_linked_to_another_work_order(self):
        rows = [
            self.document(
                work_id="33333333-3333-3333-3333-333333333333",
            )
        ]
        with (
            patch.object(app_module, "_carregar_documentos_os_para_vinculo", return_value=rows),
            patch.object(app_module, "_erp_mes_request") as mes_request,
        ):
            response = self.client.post(
                "/api/erp/os-management/entries/entry-1/work-orders",
                json={"document_id": "101"},
            )

        self.assertEqual(400, response.status_code)
        self.assertIn("ja esta vinculado", response.get_json()["error"])
        mes_request.assert_not_called()

    def test_update_rejects_second_document_for_same_operational_work_order(self):
        work_id = "44444444-4444-4444-4444-444444444444"
        rows = [
            self.document("101", "3096"),
            self.document("102", "3095", work_id=work_id),
        ]
        with (
            patch.object(app_module, "_carregar_documentos_os_para_vinculo", return_value=rows),
            patch.object(app_module, "_erp_mes_request") as mes_request,
        ):
            response = self.client.put(
                f"/api/erp/os-management/work-orders/{work_id}",
                json={"document_id": "101", "cliente_nome": "CLIENTE TESTE"},
            )

        self.assertEqual(400, response.status_code)
        self.assertIn("ja esta vinculada ao documento", response.get_json()["error"])
        mes_request.assert_not_called()

    def test_update_sends_document_link_to_mes_transaction(self):
        work_id = "66666666-6666-6666-6666-666666666666"
        rows = [self.document("101", "3096")]
        with (
            patch.object(app_module, "_carregar_documentos_os_para_vinculo", return_value=rows),
            patch.object(
                app_module,
                "_erp_mes_request",
                return_value={"ok": True, "id": work_id, "documento_os_id": 101},
            ) as mes_request,
        ):
            response = self.client.put(
                f"/api/erp/os-management/work-orders/{work_id}",
                json={"document_id": "101", "linha": "LB"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"linha": "LB", "documento_os_id": 101},
            mes_request.call_args.args[2],
        )

    def test_pending_mes_configuration_is_presented_as_emitted_os(self):
        template = (APP_DIR / "templates" / "erp_gestao_os.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function isMesConfigurationPending(row)", template)
        self.assertIn("if(isMesConfigurationPending(row))return 'EMITIDA'", template)
        self.assertIn("MES: AG. PARAMETRIZAÇÃO", template)
        self.assertIn("Salvar O.S. emitida", template)


if __name__ == "__main__":
    unittest.main()
