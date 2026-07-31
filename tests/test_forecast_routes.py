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


class ForecastRouteTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def test_forecast_screen_renders(self):
        with (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "erp_feature_enabled", return_value=True),
            patch.object(app_module, "can", return_value=True),
        ):
            app_module.app.jinja_env.globals["can"] = lambda _permission: True
            response = self.client.get("/erp/forecast")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"FORECAST", response.data)
        self.assertIn(b"Aguardando chegada", response.data)

    def test_forecast_list_returns_metrics(self):
        rows = [{"status": "ATIVO", "tipo_demanda": "PREVISAO_DEMANDA", "quantidade_planejada": 2}]
        with (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "erp_feature_enabled", return_value=True),
            patch.object(app_module, "can", return_value=True),
            patch.object(app_module.supabase_data, "carregar_forecasts", return_value=rows),
        ):
            response = self.client.get("/api/erp/forecasts")
        self.assertEqual(200, response.status_code)
        self.assertEqual(2, response.get_json()["metrics"]["quantidade_planejada"])


if __name__ == "__main__":
    unittest.main()
