import io
import os
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document


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

    def test_reissue_uses_latest_document_transformation_among_other_items(self):
        document = self.document(work_id="11111111-1111-1111-1111-111111111111")
        with patch.object(
            app_module,
            "_erp_mes_request",
            return_value={"work_order": {
                "numero_os": "3096",
                "status": "EM_PRODUÇÃO",
                "documento_os_id": 101,
                "transformacao_codigo": "40340028",
                "transformacao": "JI CONFORT",
            }},
        ) as mes_request:
            plan = app_module._preparar_transformacao_documento_os(
                document,
                [
                    {"codigo": "10100001", "descricao": "Banco"},
                    {"codigo": "30240077", "descricao": "Conjunto"},
                    {"codigo": "40340050", "descricao": "JI URBAN"},
                ],
            )
        self.assertEqual("40340050", plan["codigo"])
        self.assertEqual("JI URBAN", plan["descricao"])
        self.assertEqual("EM_PRODUÇÃO", plan["status"])
        mes_request.assert_called_once_with("work-orders/11111111-1111-1111-1111-111111111111")

    def test_reissue_keeps_current_transformation_when_document_matches(self):
        document = self.document(work_id="11111111-1111-1111-1111-111111111111")
        with patch.object(
            app_module,
            "_erp_mes_request",
            return_value={"work_order": {
                "numero_os": "3096", "transformacao_codigo": "40340028", "transformacao": "JI CONFORT"
            }},
        ):
            self.assertIsNone(
                app_module._preparar_transformacao_documento_os(
                    document, [{"codigo": "40340028", "descricao": "JI CONFORT"}]
                )
            )

    def test_open_os_sync_updates_only_transformation(self):
        plan = {"work_id": "work-1", "numero_os": "3096", "status": "EM_PRODUÇÃO",
                "codigo": "40340050", "descricao": "JI URBAN"}
        with patch.object(app_module, "_erp_mes_request") as mes_request:
            app_module._aplicar_transformacao_documento_os(plan)
        mes_request.assert_called_once_with(
            "work-orders/work-1", "PUT",
            {"transformacao_codigo": "40340050", "transformacao": "JI URBAN"},
        )

    def test_closed_os_sync_uses_audited_historical_correction(self):
        plan = {"work_id": "work-1", "numero_os": "3096", "status": "ENTREGUE",
                "codigo": "40340050", "descricao": "JI URBAN"}
        with patch.object(app_module, "_erp_mes_request") as mes_request:
            app_module._aplicar_transformacao_documento_os(plan)
        path, method, body = mes_request.call_args.args
        self.assertEqual("work-orders/work-1/historical-correction", path)
        self.assertEqual("PATCH", method)
        self.assertEqual({"transformacao_codigo": "40340050", "transformacao": "JI URBAN"}, body["work_order"])
        self.assertIn("3096", body["motivo"])

    def test_timeout_after_mes_commit_is_confirmed_by_readback(self):
        plan = {"work_id": "work-1", "numero_os": "3096", "status": "EM_PRODUÇÃO",
                "codigo": "40340050", "descricao": "JI URBAN"}
        with patch.object(app_module, "_erp_mes_request", side_effect=[
            ValueError("timeout"),
            {"work_order": {"transformacao_codigo": "40340050", "transformacao": "JI URBAN"}},
        ]) as mes_request:
            app_module._aplicar_transformacao_documento_os(plan)
        self.assertEqual(2, mes_request.call_count)

    def test_timeout_without_mes_readback_does_not_assume_rollback_is_safe(self):
        plan = {"work_id": "work-1", "numero_os": "3096", "status": "EM_PRODUÇÃO",
                "codigo": "40340050", "descricao": "JI URBAN"}
        with patch.object(app_module, "_erp_mes_request", side_effect=[
            ValueError("timeout"), ValueError("MES indisponível"),
        ]):
            with self.assertRaises(app_module.SincronizacaoMesIndeterminada):
                app_module._aplicar_transformacao_documento_os(plan)

    def test_saving_edited_document_syncs_operational_os(self):
        document = self.document(work_id="11111111-1111-1111-1111-111111111111")
        with (
            patch.object(app_module, "atualizar_skus_automatico", return_value={}),
            patch.object(app_module, "obter_historico_documento", return_value=document),
            patch.object(app_module, "carregar_os_fornecedores", return_value={}),
            patch.object(app_module, "carregar_os_produtos", return_value={
                "40340050": {"descricao": "JI URBAN", "unidade": "un"}
            }),
            patch.object(app_module, "carregar_produtos", return_value={}),
            patch.object(app_module, "carregar_regras_popup_item", return_value=[]),
            patch.object(app_module, "carregar_os_componentes", return_value={}),
            patch.object(app_module, "carregar_os_processos", return_value={}),
            patch.object(app_module, "carregar_relacoes_processo_item", return_value={}),
            patch.object(app_module, "get_bom_dir", return_value=""),
            patch.object(app_module, "registrar_historico", return_value={"id": "101"}) as register,
            patch.object(app_module, "_erp_mes_request", side_effect=[
                {"work_order": {
                    "numero_os": "3096", "status": "EM_PRODUÇÃO",
                    "documento_os_id": 101, "transformacao_codigo": "40340028",
                    "transformacao": "JI CONFORT",
                }},
                {"ok": True},
            ]) as mes_request,
        ):
            response = self.client.post("/gerar_os", data={
                "acao": "salvar", "os_historico_id": "101", "os_numero": "3096",
                "os_composicao_source": "custom", "os_composicao_json": "[]",
                "os_codigo[]": "40340050", "os_qtd[]": "1",
            })

        self.assertEqual(302, response.status_code)
        self.assertEqual("40340050", register.call_args.kwargs["itens"][0]["codigo"])
        self.assertEqual("work-orders/11111111-1111-1111-1111-111111111111", mes_request.call_args.args[0])
        self.assertEqual("PUT", mes_request.call_args.args[1])
        self.assertEqual("40340050", mes_request.call_args.args[2]["transformacao_codigo"])

    def test_failed_mes_sync_restores_previous_document(self):
        document = self.document(work_id="11111111-1111-1111-1111-111111111111")
        with (
            patch.object(app_module, "atualizar_skus_automatico", return_value={}),
            patch.object(app_module, "obter_historico_documento", return_value=document),
            patch.object(app_module, "carregar_os_fornecedores", return_value={}),
            patch.object(app_module, "carregar_os_produtos", return_value={
                "40340050": {"descricao": "JI URBAN", "unidade": "un"}
            }),
            patch.object(app_module, "carregar_produtos", return_value={}),
            patch.object(app_module, "carregar_regras_popup_item", return_value=[]),
            patch.object(app_module, "carregar_os_componentes", return_value={}),
            patch.object(app_module, "carregar_os_processos", return_value={}),
            patch.object(app_module, "carregar_relacoes_processo_item", return_value={}),
            patch.object(app_module, "get_bom_dir", return_value=""),
            patch.object(app_module, "registrar_historico", return_value={"id": "101"}),
            patch.object(app_module, "salvar_historico_documento_atualizado") as restore,
            patch.object(app_module, "_erp_mes_request", side_effect=[
                {"work_order": {
                    "numero_os": "3096", "status": "EM_PRODUÇÃO",
                    "documento_os_id": 101, "transformacao_codigo": "40340028",
                    "transformacao": "JI CONFORT",
                }},
                ValueError("aplicabilidade bloqueada"),
                {"work_order": {"transformacao_codigo": "40340028", "transformacao": "JI CONFORT"}},
            ]),
        ):
            response = self.client.post("/gerar_os", data={
                "acao": "salvar", "os_historico_id": "101", "os_numero": "3096",
                "os_composicao_source": "custom", "os_composicao_json": "[]",
                "os_codigo[]": "40340050", "os_qtd[]": "1",
            })

        self.assertEqual(409, response.status_code)
        self.assertIn("aplicabilidade bloqueada", response.get_data(as_text=True))
        restore.assert_called_once_with("101", document)

    def test_uncertain_mes_sync_keeps_latest_document_until_verified(self):
        document = self.document(work_id="11111111-1111-1111-1111-111111111111")
        with (
            patch.object(app_module, "atualizar_skus_automatico", return_value={}),
            patch.object(app_module, "obter_historico_documento", return_value=document),
            patch.object(app_module, "carregar_os_fornecedores", return_value={}),
            patch.object(app_module, "carregar_os_produtos", return_value={
                "40340050": {"descricao": "JI URBAN", "unidade": "un"}
            }),
            patch.object(app_module, "carregar_produtos", return_value={}),
            patch.object(app_module, "carregar_regras_popup_item", return_value=[]),
            patch.object(app_module, "carregar_os_componentes", return_value={}),
            patch.object(app_module, "carregar_os_processos", return_value={}),
            patch.object(app_module, "carregar_relacoes_processo_item", return_value={}),
            patch.object(app_module, "get_bom_dir", return_value=""),
            patch.object(app_module, "registrar_historico", return_value={"id": "101"}) as register,
            patch.object(app_module, "salvar_historico_documento_atualizado") as restore,
            patch.object(app_module, "_erp_mes_request", side_effect=[
                {"work_order": {
                    "numero_os": "3096", "status": "EM_PRODUÇÃO",
                    "documento_os_id": 101, "transformacao_codigo": "40340028",
                    "transformacao": "JI CONFORT",
                }},
                ValueError("timeout"),
                ValueError("MES indisponível"),
            ]),
        ):
            response = self.client.post("/gerar_os", data={
                "acao": "salvar", "os_historico_id": "101", "os_numero": "3096",
                "os_composicao_source": "custom", "os_composicao_json": "[]",
                "os_codigo[]": "40340050", "os_qtd[]": "1",
            })

        self.assertEqual(503, response.status_code)
        self.assertIn("edição foi salva no documento", response.get_data(as_text=True))
        self.assertEqual("40340050", register.call_args.kwargs["itens"][0]["codigo"])
        restore.assert_not_called()

    def test_reissue_zip_contains_latest_edited_transformation(self):
        document = self.document(work_id="11111111-1111-1111-1111-111111111111")
        with (
            patch.object(app_module, "atualizar_skus_automatico", return_value={}),
            patch.object(app_module, "obter_historico_documento", return_value=document),
            patch.object(app_module, "carregar_os_fornecedores", return_value={}),
            patch.object(app_module, "carregar_os_produtos", return_value={
                "40340050": {"descricao": "JI URBAN", "unidade": "un"},
                "10100001": {"descricao": "Banco", "unidade": "pc"},
            }),
            patch.object(app_module, "carregar_produtos", return_value={}),
            patch.object(app_module, "carregar_regras_popup_item", return_value=[]),
            patch.object(app_module, "carregar_os_componentes", return_value={}),
            patch.object(app_module, "carregar_os_processos", return_value={}),
            patch.object(app_module, "carregar_relacoes_processo_item", return_value={}),
            patch.object(app_module, "get_bom_dir", return_value=""),
            patch.object(app_module, "registrar_historico", return_value={"id": "101"}) as register,
            patch.object(app_module, "_erp_mes_request", side_effect=[
                {"work_order": {
                    "numero_os": "3096", "status": "EM_PRODUÇÃO",
                    "documento_os_id": 101, "transformacao_codigo": "40340028",
                    "transformacao": "JI CONFORT",
                }},
                {"ok": True},
            ]) as mes_request,
        ):
            response = self.client.post("/gerar_os", data={
                "acao": "imprimir", "os_historico_id": "101", "os_numero": "3096",
                "os_composicao_source": "custom", "os_composicao_json": '[{"item":"10100001","codigo":"10100001","descricao":"Banco","qtd":1,"level":0}]',
                "os_codigo[]": ["10100001", "40340050"], "os_qtd[]": ["1", "1"],
            })

        self.assertEqual(200, response.status_code)
        self.assertEqual(["10100001", "40340050"], [row["codigo"] for row in register.call_args.kwargs["itens"]])
        self.assertEqual("PUT", mes_request.call_args.args[1])
        with zipfile.ZipFile(io.BytesIO(response.data)) as package:
            complete = next(name for name in package.namelist() if "O.S Completa" in name)
            docx = Document(io.BytesIO(package.read(complete)))
        product_rows = [row.cells[0].text for row in docx.tables[2].rows[1:]]
        self.assertEqual(["10100001", "40340050"], product_rows)

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

    def test_create_never_forwards_forecast_consumption_to_mes(self):
        rows = [self.document()]
        with (
            patch.object(app_module, "_carregar_documentos_os_para_vinculo", return_value=rows),
            patch.object(
                app_module,
                "_erp_mes_request",
                return_value={"ok": True, "id": "work-1", "numero_os": "3096"},
            ) as mes_request,
        ):
            response = self.client.post(
                "/api/erp/os-management/entries/entry-1/work-orders",
                json={"document_id": "101", "forecast_id": "forecast-legacy"},
            )

        self.assertEqual(201, response.status_code)
        self.assertNotIn("forecast_id", mes_request.call_args.args[2])
        self.assertEqual(101, mes_request.call_args.args[2]["documento_os_id"])

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
