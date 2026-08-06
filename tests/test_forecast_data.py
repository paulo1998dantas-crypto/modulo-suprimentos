import sys
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import supabase_data  # noqa: E402


class ForecastDataTests(unittest.TestCase):
    def test_simulation_is_accepted_without_proposal(self):
        row = supabase_data.normalizar_forecast({
            "tipo_demanda": "PREVISÃO DE DEMANDA",
            "quantidade_planejada": "2,5",
            "probabilidade": "65",
            "itens_planejados": [{"sku_codigo": "30180004", "quantidade_por_veiculo": "2"}],
        }, "pcp")
        self.assertEqual("PREVISAO_DEMANDA", row["tipo_demanda"])
        self.assertEqual(2.5, row["quantidade_planejada"])
        self.assertEqual(65, row["probabilidade"])
        self.assertEqual("30180004", row["itens_planejados"][0]["sku_codigo"])

    def test_forecast_accepts_and_aggregates_multiple_skus(self):
        items = supabase_data.normalizar_itens_forecast([
            {"sku_codigo": "30180004", "quantidade_por_veiculo": "1"},
            {"sku_codigo": "10200186", "quantidade_por_veiculo": "2,5"},
            {"sku_codigo": "30180004", "quantidade_por_veiculo": "3"},
        ])
        self.assertEqual(2, len(items))
        self.assertEqual(4.0, items[0]["quantidade_por_veiculo"])
        self.assertEqual(2.5, items[1]["quantidade_por_veiculo"])

    def test_confirmed_forecast_requires_proposal(self):
        with self.assertRaisesRegex(ValueError, "proposta"):
            supabase_data.normalizar_forecast({
                "tipo_demanda": "AGUARDANDO_CHEGADA",
                "quantidade_planejada": 1,
                "itens_planejados": [{"sku_codigo": "30180004", "quantidade_por_veiculo": 1}],
            })

    def test_legacy_ag_chegada_is_preserved_without_proposal_or_sku(self):
        row = supabase_data.normalizar_forecast({
            "tipo_demanda": "AGUARDANDO_CHEGADA",
            "origem": supabase_data.LEGACY_AG_CHEGADA_ORIGIN,
            "quantidade_planejada": 1,
            "itens_planejados": [],
        }, "migracao")
        self.assertEqual("AGUARDANDO_CHEGADA", row["tipo_demanda"])
        self.assertEqual([], row["itens_planejados"])
        self.assertEqual("", row["proposta_numero"])

    def test_converted_forecast_requires_real_entry(self):
        with self.assertRaisesRegex(ValueError, "entrada real"):
            supabase_data.normalizar_forecast({
                "tipo_demanda": "PREVISAO_DEMANDA",
                "status": "CONVERTIDO",
                "quantidade_planejada": 1,
                "itens_planejados": [{"sku_codigo": "30180004", "quantidade_por_veiculo": 1}],
            })

    def test_creation_is_idempotent_before_consuming_counter(self):
        existing = {"id": "existing-forecast", "codigo": "FCT-00001"}
        with patch.object(supabase_data, "_request", return_value=[existing]), patch.object(
            supabase_data, "proximo_numero_forecast"
        ) as counter:
            row, replayed = supabase_data.criar_forecast({
                "idempotency_key": "forecast:test",
                "tipo_demanda": "PREVISAO_DEMANDA",
                "quantidade_planejada": 1,
            }, "pcp")
        self.assertTrue(replayed)
        self.assertEqual(existing, row)
        counter.assert_not_called()

    def test_active_forecast_requirements_exclude_converted_and_cancelled_rows(self):
        forecasts = [
            {"id": "active", "codigo": "FCT-ATIVA", "status": "ATIVO"},
            {"id": "converted", "codigo": "FCT-CONVERTIDA", "status": "CONVERTIDO"},
            {"id": "cancelled", "codigo": "FCT-CANCELADA", "status": "CANCELADO"},
        ]
        requirements = [
            {"forecast_id": "active", "sku_codigo": "SKU-1", "quantidade_planejada": 2},
            {"forecast_id": "converted", "sku_codigo": "SKU-1", "quantidade_planejada": 9},
            {"forecast_id": "cancelled", "sku_codigo": "SKU-2", "quantidade_planejada": 5},
        ]
        with (
            patch.object(supabase_data, "carregar_forecasts", return_value=forecasts),
            patch.object(supabase_data, "_all_rows", return_value=requirements),
        ):
            rows = supabase_data.carregar_necessidades_forecasts_ativos(force=True)

        self.assertEqual(1, len(rows))
        self.assertEqual("SKU-1", rows[0]["sku_codigo"])
        self.assertEqual("FCT-ATIVA", rows[0]["forecast"]["codigo"])


if __name__ == "__main__":
    unittest.main()
