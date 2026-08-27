import sys
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import supabase_data  # noqa: E402


class ForecastDataTests(unittest.TestCase):
    def test_sku_search_uses_full_forecast_catalog_limit(self):
        with patch.object(supabase_data, "_request", return_value=[]) as request:
            supabase_data.buscar_skus_forecast("302000")

        request.assert_called_once_with(
            "GET",
            supabase_data.SKUS_TABLE,
            query=[
                ("select", "id,sku,descricao,unidade"),
                ("active", "is.true"),
                ("order", "sku.asc"),
                ("limit", "100"),
                ("or", "(sku.ilike.*302000*,descricao.ilike.*302000*)"),
            ],
        )

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

    def test_documental_consumption_exposes_remaining_forecast_balance(self):
        forecasts = [{"id": "fct-1", "status": "ATIVO", "quantidade_planejada": 10}]
        consumos = [
            {"forecast_id": "fct-1", "quantidade": 8, "status": "ATIVO"},
            {"forecast_id": "fct-1", "quantidade": 1, "status": "CANCELADO"},
        ]
        with patch.object(supabase_data, "carregar_consumos_forecast_documental", return_value=consumos):
            rows = supabase_data.enriquecer_forecasts_com_consumos(forecasts)

        self.assertEqual(8, rows[0]["quantidade_consumida_documental"])
        self.assertEqual(2, rows[0]["quantidade_saldo_documental"])
        self.assertFalse(rows[0]["esgotado_documentalmente"])
        self.assertEqual("PARCIALMENTE_CONVERTIDO", rows[0]["status_exibicao"])

    def test_fully_consumed_forecast_is_presented_as_converted_with_linked_os(self):
        forecasts = [{"id": "fct-13", "status": "ATIVO", "quantidade_planejada": 1}]
        consumos = [{
            "forecast_id": "fct-13",
            "documento_os_id": 356,
            "quantidade": 1,
            "status": "ATIVO",
        }]
        with (
            patch.object(
                supabase_data,
                "carregar_consumos_forecast_documental",
                return_value=consumos,
            ),
            patch.object(
                supabase_data,
                "_request",
                return_value=[{"id": 356, "numero": "3164", "status": "emitido", "tipo": "os"}],
            ) as request,
        ):
            rows = supabase_data.enriquecer_forecasts_com_consumos(forecasts)

        self.assertEqual(0, rows[0]["quantidade_saldo_documental"])
        self.assertTrue(rows[0]["esgotado_documentalmente"])
        self.assertEqual("CONVERTIDO", rows[0]["status_exibicao"])
        self.assertEqual("3164", rows[0]["documentos_os_consumidos"][0]["numero_os"])
        request.assert_called_once_with(
            "GET",
            supabase_data.DOCUMENTOS_TABLE,
            query=[("select", "id,numero,status,tipo"), ("id", "in.(356)")],
        )

    def test_active_forecast_requirements_scale_by_documental_remaining_balance(self):
        forecasts = [{
            "id": "fct-1",
            "codigo": "FCT-00001",
            "status": "ATIVO",
            "quantidade_planejada": 10,
            "quantidade_saldo_documental": 2,
        }]
        requirements = [{
            "forecast_id": "fct-1",
            "sku_codigo": "SKU-1",
            "quantidade_planejada": 20,
        }]
        with (
            patch.object(supabase_data, "carregar_forecasts", return_value=forecasts),
            patch.object(supabase_data, "_all_rows", return_value=requirements),
        ):
            rows = supabase_data.carregar_necessidades_forecasts_ativos(force=True)

        self.assertEqual(1, len(rows))
        self.assertEqual(4, rows[0]["quantidade_planejada"])
        self.assertEqual(16, rows[0]["quantidade_documental_consumida"])

    def test_fully_consumed_active_forecast_does_not_duplicate_mrp_need(self):
        forecasts = [{
            "id": "fct-13",
            "codigo": "FCT-00013",
            "status": "ATIVO",
            "quantidade_planejada": 1,
            "quantidade_saldo_documental": 0,
        }]
        requirements = [{
            "forecast_id": "fct-13",
            "sku_codigo": "SKU-1",
            "quantidade_planejada": 4,
        }]
        with (
            patch.object(supabase_data, "carregar_forecasts", return_value=forecasts),
            patch.object(supabase_data, "_all_rows", return_value=requirements),
        ):
            rows = supabase_data.carregar_necessidades_forecasts_ativos(force=True)

        self.assertEqual([], rows)

    def test_documental_consumption_uses_idempotent_rpc_contract(self):
        with (
            patch.object(supabase_data, "_rpc", return_value={"id": "c-1"}) as rpc,
            patch.object(supabase_data, "clear_cache") as clear_cache,
        ):
            result = supabase_data.consumir_forecast_em_os_documento(
                "fct-1", 99, "2,5", "forecast-os-documento:99", "pcp"
            )

        self.assertEqual("c-1", result["id"])
        rpc.assert_called_once_with(
            "suprimentos_consumir_forecast_em_os_documento",
            {
                "p_forecast_id": "fct-1",
                "p_documento_os_id": 99,
                "p_quantidade": 2.5,
                "p_idempotency_key": "forecast-os-documento:99",
                "p_actor": "pcp",
            },
        )
        clear_cache.assert_called_once()

    def test_unconverted_forecast_deletion_uses_atomic_rpc_contract(self):
        with (
            patch.object(
                supabase_data,
                "_rpc",
                return_value={"excluido": True, "forecast_id": "fct-1"},
            ) as rpc,
            patch.object(supabase_data, "clear_cache") as clear_cache,
        ):
            result = supabase_data.excluir_forecast_sem_historico(
                "fct-1", "pcp", "4"
            )

        self.assertTrue(result["excluido"])
        rpc.assert_called_once_with(
            "suprimentos_excluir_forecast_sem_historico",
            {
                "p_forecast_id": "fct-1",
                "p_expected_version": 4,
                "p_actor": "pcp",
            },
        )
        clear_cache.assert_called_once()

    def test_unconfirmed_atomic_deletion_keeps_cache(self):
        with (
            patch.object(supabase_data, "_rpc", return_value={"excluido": False}),
            patch.object(supabase_data, "clear_cache") as clear_cache,
        ):
            with self.assertRaisesRegex(supabase_data.SupabaseDataError, "nao confirmou"):
                supabase_data.excluir_forecast_sem_historico("fct-1", "pcp")

        clear_cache.assert_not_called()

    def test_protected_forecast_deletion_returns_business_error(self):
        database_error = supabase_data.SupabaseDataError(
            'Erro Supabase 500: {"code":"55000","message":"Este Forecast ja foi convertido em entrada/O.S. e nao pode ser excluido."}'
        )
        with (
            patch.object(supabase_data, "_rpc", side_effect=database_error),
            patch.object(supabase_data, "clear_cache") as clear_cache,
        ):
            with self.assertRaisesRegex(ValueError, "ja foi convertido"):
                supabase_data.excluir_forecast_sem_historico("fct-1", "pcp")

        clear_cache.assert_not_called()

    def test_forecast_deletion_infrastructure_error_is_not_exposed_as_business_error(self):
        database_error = supabase_data.SupabaseDataError(
            'Erro Supabase 404: {"code":"PGRST202","message":"Could not find the function"}'
        )
        with patch.object(supabase_data, "_rpc", side_effect=database_error):
            with self.assertRaises(supabase_data.SupabaseDataError):
                supabase_data.excluir_forecast_sem_historico("fct-1", "pcp")


if __name__ == "__main__":
    unittest.main()
