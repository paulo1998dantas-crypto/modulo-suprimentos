import json
import os
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
os.environ["SUPRIMENTOS_FILE_LOG"] = "0"

import app as app_module


class ErpMesTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "ERP_MES_API_URL": "https://mes.example.test",
            "ERP_BACKEND_TOKEN": "test-token",
        }

    def test_uses_75_seconds_as_default_timeout(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"ok": True}).encode("utf-8")

        with (
            patch.dict(os.environ, self.environment, clear=False),
            patch.dict(os.environ, {"ERP_MES_API_TIMEOUT_SECONDS": ""}, clear=False),
            app_module.app.test_request_context("/"),
            patch.object(app_module.urllib.request, "urlopen", return_value=response) as urlopen,
        ):
            result = app_module._erp_mes_request("work-orders")

        self.assertEqual({"ok": True}, result)
        self.assertEqual(75, urlopen.call_args.kwargs["timeout"])

    def test_uses_configured_timeout(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true}'

        with (
            patch.dict(
                os.environ,
                {**self.environment, "ERP_MES_API_TIMEOUT_SECONDS": "90"},
                clear=False,
            ),
            app_module.app.test_request_context("/"),
            patch.object(app_module.urllib.request, "urlopen", return_value=response) as urlopen,
        ):
            app_module._erp_mes_request("work-orders")

        self.assertEqual(90, urlopen.call_args.kwargs["timeout"])

    def test_direct_timeout_has_actionable_message(self):
        with (
            patch.dict(os.environ, self.environment, clear=False),
            patch.dict(os.environ, {"ERP_MES_API_TIMEOUT_SECONDS": ""}, clear=False),
            app_module.app.test_request_context("/"),
            patch.object(
                app_module.urllib.request,
                "urlopen",
                side_effect=TimeoutError("timed out"),
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                r"MES demorou mais de 75 segundos.*tente novamente",
            ):
                app_module._erp_mes_request("work-orders")

    def test_url_error_wrapping_timeout_has_actionable_message(self):
        timeout_error = urllib.error.URLError(TimeoutError("timed out"))

        with (
            patch.dict(
                os.environ,
                {**self.environment, "ERP_MES_API_TIMEOUT_SECONDS": "80"},
                clear=False,
            ),
            app_module.app.test_request_context("/"),
            patch.object(
                app_module.urllib.request,
                "urlopen",
                side_effect=timeout_error,
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                r"MES demorou mais de 80 segundos.*tente novamente",
            ):
                app_module._erp_mes_request("work-orders")

    def test_non_timeout_url_error_keeps_unavailable_message(self):
        unavailable_error = urllib.error.URLError("connection refused")

        with (
            patch.dict(os.environ, self.environment, clear=False),
            app_module.app.test_request_context("/"),
            patch.object(
                app_module.urllib.request,
                "urlopen",
                side_effect=unavailable_error,
            ),
        ):
            with self.assertRaisesRegex(ValueError, r"MES indisponível: connection refused"):
                app_module._erp_mes_request("work-orders")


if __name__ == "__main__":
    unittest.main()
