import inspect
import io
import json
import os
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compras_app"))
os.environ["SUPRIMENTOS_FILE_LOG"] = "0"
import app as app_module


NEGATIVE = {"ok": False, "code": "CONFIRM_NEGATIVE_STOCK", "error": "Confirmar negativo",
            "negative_stock": [{"codigo": "MP", "saldo_atual": "1", "quantidade_baixar": "4", "saldo_final": "-3"}],
            "confirmation_token": "test-plan"}


class TechnicalCloseFlowTests(unittest.TestCase):
    def test_backend_preserves_conflict_payload(self):
        failure = urllib.error.HTTPError("https://mes.example.test", 409, "Conflict", {},
                                        io.BytesIO(json.dumps(NEGATIVE).encode()))
        with (patch.dict(os.environ, {"ERP_MES_API_URL": "https://mes.example.test", "ERP_BACKEND_TOKEN": "test"}),
              app_module.app.test_request_context("/"),
              patch.object(app_module.urllib.request, "urlopen", side_effect=failure)):
            with self.assertRaises(app_module.ErpMesRequestError) as error:
                app_module._erp_mes_request("work-orders/id/technical-close", "POST", {})
        self.assertEqual(409, error.exception.status_code)
        self.assertEqual("test-plan", error.exception.payload["confirmation_token"])
        self.assertEqual(NEGATIVE["negative_stock"], error.exception.payload["negative_stock"])

    def test_management_proxy_returns_409_without_losing_confirmation(self):
        with (app_module.app.test_request_context("/", method="POST", json={"motivo": "test"}),
              patch.object(app_module, "_erp_mes_request", side_effect=app_module.ErpMesRequestError(NEGATIVE, 409))):
            response, status = inspect.unwrap(app_module.erp_work_order_technical_close_proxy)("work-id")
        self.assertEqual(409, status)
        self.assertEqual("test-plan", response.json["confirmation_token"])

    def test_legacy_conflict_does_not_close_document(self):
        document = {"id": 1, "tipo": "os", "numero": "3100", "dados": {}, "status": "emitido"}
        with (app_module.app.test_request_context("/", method="POST", json={"status": "concluido"}),
              patch.object(app_module, "obter_historico_documento", return_value=document),
              patch.object(app_module, "erp_feature_enabled", return_value=True),
              patch.object(app_module, "_close_linked_legacy_os_in_mes", side_effect=app_module.ErpMesRequestError(NEGATIVE, 409)),
              patch.object(app_module, "atualizar_status_historico_documento") as write):
            response, status = inspect.unwrap(app_module.api_status_historico)("os", "1")
        self.assertEqual(409, status)
        self.assertEqual("CONFIRM_NEGATIVE_STOCK", response.json["code"])
        write.assert_not_called()

    def test_legacy_forwards_explicit_confirmation(self):
        with (patch.object(app_module, "_resolve_linked_legacy_os_work_id", return_value="work-id"),
              patch.object(app_module, "_erp_mes_request", return_value={"ok": True}) as send):
            app_module._close_linked_legacy_os_in_mes({}, "test", {"confirm_negative_stock": True, "confirmation_token": "test-plan"})
        self.assertTrue(send.call_args.args[2]["confirm_negative_stock"])
        self.assertEqual("test-plan", send.call_args.args[2]["confirmation_token"])

    def test_string_true_does_not_authorize_negative(self):
        with (patch.object(app_module, "_resolve_linked_legacy_os_work_id", return_value="work-id"),
              patch.object(app_module, "_erp_mes_request", return_value={"ok": True}) as send):
            app_module._close_linked_legacy_os_in_mes({}, "test", {"confirm_negative_stock": "true"})
        self.assertFalse(send.call_args.args[2]["confirm_negative_stock"])


if __name__ == "__main__":
    unittest.main()
