import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import app as app_module
import supabase_data


class DocumentManagementTests(unittest.TestCase):
    def test_quantity_parser_preserves_decimal_points_from_os_documents(self):
        self.assertEqual("1", app_module._normalizar_qtd("1.0"))
        self.assertEqual("2", app_module._normalizar_qtd("2.0"))
        self.assertEqual("0.025", app_module._normalizar_qtd("0.025"))
        self.assertEqual("1.064", app_module._normalizar_qtd("1.064"))
        self.assertEqual("1.5", app_module._normalizar_qtd("1,5"))
        self.assertEqual("1234.5", app_module._normalizar_qtd("1.234,5"))
        self.assertEqual(
            app_module._assinatura_os_recalculada({"numero": "1", "itens": [{"qtd": 1}]}),
            app_module._assinatura_os_recalculada({"numero": "1", "itens": [{"qtd": 1.0}]}),
        )

    def test_historical_luminaire_fallback_requires_one_consistent_relation(self):
        documents = [
            {
                "tipo": "os",
                "composicao": [
                    {"item": "40340010", "codigo": "10260092", "qtd": 2},
                    {"item": "40340020", "codigo": "10260092", "qtd": 2},
                ],
            },
            {
                "tipo": "os",
                "composicao": [
                    {"item": "40340010", "codigo": "10260092", "qtd": 2.0},
                    {"item": "40340020", "codigo": "10260095", "qtd": 2},
                    {
                        "item": "40340030",
                        "codigo": "10260095",
                        "qtd": 3,
                        "line_status": "cancelado",
                    },
                ],
            },
        ]

        result = app_module._luminarias_historicas_por_item(documents)

        self.assertEqual({"codigo": "10260092", "qtd": 2.0}, result["40340010"])
        self.assertNotIn("40340020", result)
        self.assertNotIn("40340030", result)

    def test_reconciled_os_uses_historical_luminaire_when_source_has_none(self):
        source = {
            "nome": "OS-3102.docx",
            "data_arquivo": datetime(2026, 7, 24, 16, 26),
            "dados": {
                "os_numero": "3102",
                "cliente": "BELISA",
                "chassis": "VE277925",
                "itens": [{"codigo": "40340010", "qtd": 1}],
                "composicao": [],
            },
        }
        context = {
            "os_produtos": {
                "40340010": {"descricao": "ITEM RAIZ", "unidade": "un"},
                "10260092": {"descricao": "ELETRICA LUMINARIA ALURE 30", "unidade": "un"},
            },
            "produtos_catalogo": {},
            "componentes": {},
            "processos": {},
            "processo_por_item": {},
            "regras_por_gatilho": {},
            "luminarias_por_item": {
                "40340010": {"codigo": "10260092", "qtd": 2},
            },
        }

        with patch.object(app_module, "current_username", return_value="codex"):
            result = app_module._montar_os_reconciliada(source, None, context)

        luminaires = [
            line for line in result["composicao"]
            if line.get("codigo") == "10260092"
        ]
        self.assertEqual(1, len(luminaires))
        self.assertEqual("40340010", luminaires[0]["item"])
        self.assertEqual(2.0, luminaires[0]["qtd"])

    def test_dashboard_documents_exposes_compact_filter_data(self):
        rows = app_module._dashboard_documentos([{
            "id": 42,
            "tipo": "OS",
            "numero": 3090,
            "data_criacao": "2026-07-21T14:30:00",
            "status": "concluido",
            "updated_at": "2026-07-21T15:00:00",
            "dados": {
                "cliente": "Cliente A",
                "chassis": "ABC123",
                "mmv": "MODELO X",
                "campo_pesado": "nao deve ser enviado",
            },
            "itens": [{"codigo": "SKU-1"}, {"codigo": "SKU-2"}],
            "processos": {"CORTE": [{"atividade": "Cortar"}]},
        }])

        self.assertEqual([{
            "id": "42",
            "tipo": "os",
            "numero": "3090",
            "data": "2026-07-21",
            "status": "concluido",
            "nome": "Cliente A",
            "chassis": "ABC123",
            "mmv": "MODELO X",
            "total": 0.0,
            "itens": 2,
            "ordem": "2026-07-21T15:00:00",
        }], rows)

    def test_production_upgrade_is_additive_and_transactional(self):
        migration_path = Path(__file__).resolve().parents[1] / "supabase_suprimentos_gestao_documentos_additive.sql"
        sql = migration_path.read_text(encoding="utf-8")
        executable_sql = "\n".join(
            line for line in sql.splitlines()
            if not line.lstrip().startswith("--")
        ).lower()

        self.assertIn("begin;", executable_sql)
        self.assertIn("commit;", executable_sql)
        self.assertNotIn("delete from", executable_sql)
        self.assertNotIn("truncate", executable_sql)
        self.assertNotIn("drop table", executable_sql)
        self.assertNotIn("insert into public.suprimentos_documentos ", executable_sql)
        self.assertNotIn("update public.suprimentos_documentos ", executable_sql)

    def test_local_history_is_idempotent_by_submission_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = str(Path(tmpdir) / "historico.json")
            Path(history_path).write_text("[]", encoding="utf-8")
            with (
                patch.object(app_module, "HISTORICO_FILE", history_path),
                patch.object(app_module.supabase_data, "enabled", return_value=False),
                app_module.app.test_request_context("/"),
            ):
                app_module.session["suprimentos_user"] = {"id": 7, "username": "paulo"}
                first = app_module.registrar_historico(
                    "oc", 10, {"fornecedor": "Fornecedor A"}, itens=[{"codigo": "1"}],
                    status="rascunho", submit_token="token-unico",
                )
                second = app_module.registrar_historico(
                    "oc", 10, {"fornecedor": "Fornecedor B"}, itens=[{"codigo": "2"}],
                    status="emitido", submit_token="token-unico",
                )
                rows = json.loads(Path(history_path).read_text(encoding="utf-8"))

            self.assertEqual(1, len(rows))
            self.assertEqual(first["id"], second["id"])
            self.assertEqual("Fornecedor B", rows[0]["dados"]["fornecedor"])
            self.assertEqual("emitido", rows[0]["status"])
            self.assertEqual("paulo", rows[0]["atualizado_por"])

    def test_document_history_assigns_line_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = str(Path(tmpdir) / "historico.json")
            Path(history_path).write_text("[]", encoding="utf-8")
            with (
                patch.object(app_module, "HISTORICO_FILE", history_path),
                patch.object(app_module.supabase_data, "enabled", return_value=False),
                app_module.app.test_request_context("/"),
            ):
                entry = app_module.registrar_historico(
                    "os",
                    77,
                    {"cliente": "Cliente"},
                    itens=[{"codigo": "SKU-1", "descricao": "Item", "qtd": 1}],
                    processos={"CORTE": [{"atividade": "Cortar", "responsavel": "Ana"}]},
                    composicao=[{"item": "SKU-1", "codigo": "COMP-1", "qtd": 1}],
                    status="emitido",
                    submit_token="token-os",
                )

        self.assertTrue(entry["itens"][0]["line_id"].startswith("os-item-"))
        self.assertTrue(entry["processos"]["CORTE"][0]["line_id"].startswith("os-proc-"))
        self.assertTrue(entry["composicao"][0]["line_id"].startswith("os-comp-"))

    def test_bulk_status_upload_updates_line_or_document_by_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "historico.json"
            history_path.write_text(json.dumps([
                {
                    "id": "local-oc",
                    "tipo": "oc",
                    "numero": "100",
                    "data_criacao": "2026-07-19",
                    "status": "emitido",
                    "dados": {"fornecedor": "Fornecedor"},
                    "itens": [{"line_id": "oc-item-abc", "codigo": "SKU-1"}],
                },
                {
                    "id": "local-os",
                    "tipo": "os",
                    "numero": "200",
                    "data_criacao": "2026-07-19",
                    "status": "emitido",
                    "dados": {"cliente": "Cliente"},
                    "itens": [{"line_id": "os-item-def", "codigo": "SKU-2"}],
                },
            ], ensure_ascii=False), encoding="utf-8")

            wb = Workbook()
            ws = wb.active
            ws.append(["ID", "ID Linha", "ACAO"])
            ws.append(["", "oc-item-abc", "concluir"])
            ws.append(["local-os", "", "excluir"])
            upload = io.BytesIO()
            wb.save(upload)
            upload.seek(0)

            with (
                patch.object(app_module, "HISTORICO_FILE", str(history_path)),
                patch.object(app_module, "login_enabled", return_value=False),
                patch.object(app_module.supabase_data, "enabled", return_value=False),
            ):
                response = app_module.app.test_client().post(
                    "/importar_baixa_documentos",
                    data={"arquivo_baixa_documentos": (upload, "baixas.xlsx")},
                    content_type="multipart/form-data",
                )

            rows = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(302, response.status_code)
            self.assertEqual(["local-oc"], [row["id"] for row in rows])
            self.assertEqual("emitido", rows[0]["status"])
            self.assertEqual("concluido", rows[0]["itens"][0]["line_status"])

    def test_bulk_status_upload_returns_to_selected_management_tab(self):
        upload = io.BytesIO(b"fake spreadsheet")
        with (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "importar_baixas_documentos", return_value={
                "atualizados": 1,
                "excluidos": 0,
                "linhas_atualizadas": 0,
                "linhas_excluidas": 0,
                "ignorados": 0,
                "erros": [],
            }),
        ):
            response = app_module.app.test_client().post(
                "/importar_baixa_documentos",
                data={
                    "tipo_baixa_documentos": "os",
                    "next_tab": "gestao-os",
                    "arquivo_baixa_documentos": (upload, "baixas.xlsx"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(302, response.status_code)
        self.assertIn("tab=gestao-os", response.headers["Location"])

    def test_bulk_status_upload_can_delete_specific_os_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "historico.json"
            history_path.write_text(json.dumps([{
                "id": "local-os",
                "tipo": "os",
                "numero": "200",
                "data_criacao": "2026-07-19",
                "status": "emitido",
                "dados": {"cliente": "Cliente"},
                "itens": [
                    {"line_id": "os-item-keep", "codigo": "SKU-1"},
                    {"line_id": "os-item-drop", "codigo": "SKU-2"},
                ],
            }], ensure_ascii=False), encoding="utf-8")

            wb = Workbook()
            ws = wb.active
            ws.append(["ID", "ID Linha", "ACAO"])
            ws.append(["local-os", "os-item-drop", "excluir"])
            upload = io.BytesIO()
            wb.save(upload)
            upload.seek(0)

            with (
                patch.object(app_module, "HISTORICO_FILE", str(history_path)),
                patch.object(app_module, "login_enabled", return_value=False),
                patch.object(app_module.supabase_data, "enabled", return_value=False),
            ):
                response = app_module.app.test_client().post(
                    "/importar_baixa_documentos",
                    data={"arquivo_baixa_documentos": (upload, "baixas.xlsx")},
                    content_type="multipart/form-data",
                )

            rows = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(302, response.status_code)
            self.assertEqual("emitido", rows[0]["status"])
            self.assertEqual(["os-item-keep"], [item["line_id"] for item in rows[0]["itens"]])

    def test_transient_import_path_is_scoped_by_login(self):
        with app_module.app.test_request_context("/"):
            app_module.session["suprimentos_user"] = {"id": 1, "username": "compras"}
            compras_path = app_module._user_scoped_file(app_module.OS_IMPORT_FILE)
            app_module.session["suprimentos_user"] = {"id": 2, "username": "producao"}
            producao_path = app_module._user_scoped_file(app_module.OS_IMPORT_FILE)

        self.assertNotEqual(compras_path, producao_path)
        self.assertIn("compras", compras_path)
        self.assertIn("producao", producao_path)

    def test_document_normalization_keeps_management_fields(self):
        row = supabase_data.normalizar_documento({
            "tipo": "OS",
            "numero": "42",
            "status": "CONCLUIDO",
            "submit_token": "abc",
            "criado_por": "maria",
            "atualizado_por": "joao",
            "dados": {},
        })
        self.assertEqual("os", row["tipo"])
        self.assertEqual("concluido", row["status"])
        self.assertEqual("abc", row["submit_token"])
        self.assertEqual("maria", row["criado_por"])
        self.assertEqual("joao", row["atualizado_por"])

    def test_reused_submission_token_does_not_overwrite_another_document(self):
        existing = [{
            "id": 10,
            "tipo": "os",
            "numero": "3099",
            "submit_token": "browser-token",
        }]
        saved = [{
            "id": 11,
            "tipo": "os",
            "numero": "3100",
            "submit_token": "browser-token::os::3100",
        }]
        with patch.object(supabase_data, "_request", side_effect=[existing, saved]) as request_mock:
            result = supabase_data.salvar_documento({
                "tipo": "os",
                "numero": "3100",
                "submit_token": "browser-token",
                "dados": {},
            })

        self.assertEqual(11, result["id"])
        self.assertEqual("browser-token::os::3100", result["submit_token"])
        post_call = request_mock.call_args_list[1]
        self.assertEqual("POST", post_call.args[0])
        self.assertEqual("browser-token::os::3100", post_call.kwargs["payload"]["submit_token"])
        self.assertIn(("on_conflict", "submit_token"), post_call.kwargs["query"])

    def test_same_submission_token_and_number_remain_idempotent(self):
        existing = [{
            "id": 10,
            "tipo": "os",
            "numero": "3100",
            "submit_token": "browser-token",
        }]
        saved = [{
            "id": 10,
            "tipo": "os",
            "numero": "3100",
            "submit_token": "browser-token",
        }]
        with patch.object(supabase_data, "_request", side_effect=[existing, saved]) as request_mock:
            result = supabase_data.salvar_documento({
                "tipo": "os",
                "numero": "3100",
                "submit_token": "browser-token",
                "dados": {},
            })

        self.assertEqual(10, result["id"])
        post_call = request_mock.call_args_list[1]
        self.assertEqual("browser-token", post_call.kwargs["payload"]["submit_token"])

    def test_document_history_has_no_default_quantity_limit(self):
        rows = [
            {
                "id": idx,
                "tipo": "os",
                "numero": str(idx),
                "data_criacao": "2026-07-27",
            }
            for idx in range(1005)
        ]
        with patch.object(supabase_data, "_all_rows", return_value=rows):
            documents = supabase_data.carregar_documentos()
            limited = supabase_data.carregar_documentos(limit=25)

        self.assertEqual(1005, len(documents))
        self.assertEqual(25, len(limited))

    def test_filtered_reports_include_status_users_and_details(self):
        history = [{
            "id": 12,
            "tipo": "oc",
            "numero": "100",
            "data_criacao": "2026-07-19",
            "status": "rascunho",
            "criado_por": "ana",
            "atualizado_por": "bia",
            "dados": {"fornecedor": "Fornecedor", "total_pedido": 123.45},
            "itens": [{"codigo": "SKU-1", "descricao": "Item", "qtd": 2, "total": 123.45}],
        }]
        with (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "carregar_historico", return_value=history),
        ):
            response = app_module.app.test_client().get("/exportar_dashboard?tipo=oc")

        self.assertEqual(200, response.status_code)
        workbook = load_workbook(io.BytesIO(response.data), read_only=True)
        self.assertEqual(["Compras", "Compras Itens"], workbook.sheetnames)
        main_rows = list(workbook["Compras"].iter_rows(values_only=True))
        item_rows = list(workbook["Compras Itens"].iter_rows(values_only=True))
        self.assertIn("Status", main_rows[0])
        self.assertIn("Criado Por", main_rows[0])
        self.assertIn("ACAO", main_rows[0])
        self.assertIn("ID Linha", item_rows[0])
        self.assertIn("Status Linha", item_rows[0])
        self.assertIn("ACAO", item_rows[0])
        self.assertEqual("rascunho", main_rows[1][1])
        self.assertEqual("SKU-1", item_rows[1][8])
        workbook.close()
        response.close()

    def test_os_report_includes_action_column_for_bulk_upload(self):
        history = [{
            "id": "os-1",
            "tipo": "os",
            "numero": "200",
            "data_criacao": "2026-07-19",
            "status": "emitido",
            "dados": {"cliente": "Cliente", "chassis": "ABC"},
            "itens": [{"line_id": "os-item-1", "codigo": "SKU-1", "descricao": "Item"}],
        }]
        with (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "carregar_historico", return_value=history),
        ):
            response = app_module.app.test_client().get("/exportar_dashboard?tipo=os")

        workbook = load_workbook(io.BytesIO(response.data), read_only=True)
        self.assertEqual(["Ordens de Servico", "OS Itens", "OS Processos", "OS Componentes"], workbook.sheetnames)
        self.assertIn("ACAO", [cell.value for cell in workbook["Ordens de Servico"][1]])
        self.assertIn("ID Linha", [cell.value for cell in workbook["OS Itens"][1]])
        self.assertIn("Status Linha", [cell.value for cell in workbook["OS Itens"][1]])
        self.assertIn("ACAO", [cell.value for cell in workbook["OS Itens"][1]])
        workbook.close()
        response.close()

    def test_purchase_can_be_saved_without_generating_document(self):
        with (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "atualizar_skus_automatico", return_value={}),
            patch.object(app_module, "carregar_fornecedores", return_value={}),
            patch.object(app_module, "carregar_produtos", return_value={}),
            patch.object(app_module, "carregar_os_componentes", return_value={}),
            patch.object(app_module, "proximo_numero_oc", return_value=51),
            patch.object(app_module, "registrar_historico") as register,
            patch.object(app_module, "gerar_word") as generate,
        ):
            response = app_module.app.test_client().post("/gerar_oc", data={
                "acao": "salvar",
                "oc_submit_token": "oc-token",
                "fornecedor": "Fornecedor",
                "codigo[]": "SKU-1",
                "descricao[]": "Item",
                "unidade[]": "UN",
                "qtd[]": "2",
                "valor[]": "10",
                "desconto[]": "0",
                "frete": "0",
            })

        self.assertEqual(302, response.status_code)
        generate.assert_not_called()
        self.assertEqual("rascunho", register.call_args.kwargs["status"])
        self.assertEqual("oc-token", register.call_args.kwargs["submit_token"])

    def test_service_order_can_be_saved_without_generating_zip(self):
        with (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "atualizar_skus_automatico", return_value={}),
            patch.object(app_module, "carregar_os_produtos", return_value={}),
            patch.object(app_module, "carregar_produtos", return_value={}),
            patch.object(app_module, "carregar_regras_popup_item", return_value=[]),
            patch.object(app_module, "carregar_os_componentes", return_value={}),
            patch.object(app_module, "carregar_os_processos", return_value={}),
            patch.object(app_module, "carregar_relacoes_processo_item", return_value={}),
            patch.object(app_module, "proximo_numero_os", return_value=77),
            patch.object(app_module, "registrar_historico") as register,
            patch.object(app_module, "gerar_os_docx") as generate,
        ):
            response = app_module.app.test_client().post("/gerar_os", data={
                "acao": "salvar",
                "os_submit_token": "os-token",
                "os_composicao_json": "[]",
                "os_composicao_source": "custom",
                "os_cliente": "Cliente",
                "os_codigo[]": "",
            })

        self.assertEqual(302, response.status_code)
        generate.assert_not_called()
        self.assertEqual("rascunho", register.call_args.kwargs["status"])
        self.assertEqual("os-token", register.call_args.kwargs["submit_token"])

    def test_marco_zero_prefers_newest_duplicate_source(self):
        sources = [
            {
                "nome": "OS-antiga.docx",
                "conteudo": b"antiga",
                "data_arquivo": datetime(2026, 7, 20, 10, 0),
                "revisao": 0,
                "ordem": 0,
            },
            {
                "nome": "OS-R01.docx",
                "conteudo": b"nova",
                "data_arquivo": datetime(2026, 7, 21, 10, 0),
                "revisao": 1,
                "ordem": 1,
            },
        ]
        with patch.object(
            app_module,
            "parse_os_docx_atualizado",
            side_effect=[
                {"os_numero": "3090", "itens": [{"codigo": "A"}]},
                {"os_numero": "3090", "itens": [{"codigo": "B"}]},
            ],
        ):
            selected, discarded = app_module._parsear_fontes_os_reconciliacao(sources)

        self.assertEqual(1, discarded)
        self.assertEqual("OS-R01.docx", selected["3090"]["nome"])

    def test_marco_zero_recalculates_bom_and_keeps_required_choices(self):
        source = {
            "nome": "OS-3090.docx",
            "data_arquivo": datetime(2026, 7, 21, 10, 0),
            "dados": {
                "os_numero": "3090",
                "cliente": "Cliente",
                "chassis": "CHASSI",
                "itens": [
                    {"codigo": "40340001", "descricao": "CJ TETO", "qtd": 1, "unidade": "un"},
                    {"codigo": "FD-1", "descricao": "FATURAMENTO DIRETO SERVICO", "qtd": 1, "unidade": "un"},
                ],
                "composicao": [{"codigo": "10260092", "qtd": 2}],
            },
        }
        reference = {
            "tipo": "os",
            "numero": "3090",
            "data_criacao": "2026-07-20",
            "itens": [{"codigo": "FD-1", "fornecedor": "INSTALL TECH"}],
            "composicao": [],
        }
        products = {
            "40340001": {"descricao": "CJ TETO", "unidade": "un"},
            "FD-1": {"descricao": "FATURAMENTO DIRETO SERVICO", "unidade": "un"},
            "10260092": {"descricao": "LUMINARIA", "unidade": "un"},
            "COMP-1": {"descricao": "COMPONENTE", "unidade": "un"},
        }
        context = {
            "os_produtos": products,
            "produtos_catalogo": products,
            "componentes": {
                "40340001": [{"codigo": "COMP-1", "descricao": "COMPONENTE", "unidade": "un", "quantidade": 3}],
            },
            "processos": {},
            "processo_por_item": {},
            "regras_por_gatilho": {},
        }
        with (
            patch.object(app_module, "_resolver_nome_cliente_os", return_value="Cliente"),
            app_module.app.test_request_context("/"),
        ):
            document = app_module._montar_os_reconciliada(source, reference, context)

        composition_codes = {line["codigo"] for line in document["composicao"]}
        direct_item = next(item for item in document["itens"] if item["codigo"] == "FD-1")
        self.assertEqual({"COMP-1", "10260092", "FD-1"}, composition_codes)
        self.assertEqual("INSTALL TECH", direct_item["fornecedor"])
        self.assertTrue(all(line.get("line_id") for line in document["composicao"]))

    def test_selective_recalculation_preserves_new_service_orders(self):
        source = {
            "nome": "OS-3090.docx",
            "data_arquivo": datetime(2026, 7, 21, 10, 0),
            "dados": {"os_numero": "3090", "chassis": "BASE-1", "itens": [{"codigo": "SKU-1"}]},
        }
        baseline = {
            "id": 10,
            "tipo": "os",
            "numero": "3090",
            "data_criacao": "2026-07-21",
            "status": "emitido",
            "submit_token": "baseline-token",
            "criado_por": "paulo",
            "dados": {"chassis": "BASE-1"},
            "itens": [{"codigo": "SKU-1", "qtd": 10}],
            "processos": {},
            "composicao": [],
        }
        new_order = {
            "id": 11,
            "tipo": "os",
            "numero": "4000",
            "data_criacao": "2026-07-22",
            "status": "emitido",
            "dados": {"chassis": "NOVA-1"},
            "itens": [{"codigo": "SKU-NOVA", "qtd": 1}],
            "processos": {},
            "composicao": [],
        }
        corrected = {
            "tipo": "os",
            "numero": "3090",
            "data_criacao": "2026-07-21",
            "status": "emitido",
            "submit_token": "novo-token",
            "criado_por": "codex",
            "atualizado_por": "codex",
            "dados": {"chassis": "BASE-1"},
            "itens": [{"codigo": "SKU-1", "qtd": 1}],
            "processos": {},
            "composicao": [{"codigo": "COMP-1", "qtd": 2}],
        }
        final_baseline = {"id": 10, **corrected}
        final_rows = [final_baseline, new_order]

        with (
            patch.object(app_module.supabase_data, "enabled", return_value=True),
            patch.object(app_module, "_fontes_os_reconciliacao", return_value=[source]),
            patch.object(app_module, "_parsear_fontes_os_reconciliacao", return_value=({"3090": source}, 0)),
            patch.object(app_module, "_carregar_historico_local", return_value=[]),
            patch.object(app_module, "_contexto_reconciliacao_os", return_value={}),
            patch.object(app_module, "_montar_os_reconciliada", return_value=corrected),
            patch.object(app_module, "current_username", return_value="codex"),
            patch.object(
                app_module.supabase_data,
                "carregar_documentos",
                side_effect=[[baseline, new_order], final_rows],
            ),
            patch.object(app_module.supabase_data, "atualizar_documento", return_value=True) as update,
            patch.object(app_module.supabase_data, "excluir_documento") as delete_one,
            patch.object(app_module.supabase_data, "excluir_documentos") as delete_many,
        ):
            result = app_module.recalcular_os_importadas([object()])

        self.assertEqual(1, result["atualizadas"])
        self.assertEqual(1, result["preservadas"])
        self.assertEqual("10", update.call_args.args[0])
        self.assertEqual("3090", update.call_args.args[1]["numero"])
        delete_one.assert_not_called()
        delete_many.assert_not_called()

    def test_add_missing_service_orders_preserves_existing_numbers(self):
        source_existing = {
            "nome": "OS-3088.docx",
            "data_arquivo": datetime(2026, 7, 21, 10, 0),
            "dados": {"os_numero": "3088", "chassis": "BASE-1", "itens": [{"codigo": "SKU-1"}]},
        }
        source_missing = {
            "nome": "OS-3090.docx",
            "data_arquivo": datetime(2026, 7, 21, 11, 0),
            "dados": {"os_numero": "3090", "chassis": "BASE-2", "itens": [{"codigo": "SKU-2"}]},
        }
        existing = {
            "id": 10,
            "tipo": "os",
            "numero": "3088",
            "data_criacao": "2026-07-21",
            "dados": {"chassis": "BASE-1"},
            "itens": [{"codigo": "SKU-1"}],
            "processos": {},
            "composicao": [],
        }
        missing = {
            "tipo": "os",
            "numero": "3090",
            "data_criacao": "2026-07-21",
            "dados": {"chassis": "BASE-2"},
            "itens": [{"codigo": "SKU-2"}],
            "processos": {},
            "composicao": [],
        }
        saved = {"id": 11, **missing}

        with (
            patch.object(app_module.supabase_data, "enabled", return_value=True),
            patch.object(
                app_module,
                "_fontes_os_reconciliacao",
                return_value=[source_existing, source_missing],
            ),
            patch.object(
                app_module,
                "_parsear_fontes_os_reconciliacao",
                return_value=({"3088": source_existing, "3090": source_missing}, 0),
            ),
            patch.object(app_module, "_carregar_historico_local", return_value=[]),
            patch.object(app_module, "_contexto_reconciliacao_os", return_value={}),
            patch.object(app_module, "_montar_os_reconciliada", return_value=missing) as build,
            patch.object(
                app_module.supabase_data,
                "carregar_documentos",
                side_effect=[[existing], [existing, saved]],
            ),
            patch.object(
                app_module.supabase_data,
                "salvar_documentos",
                return_value=[saved],
            ) as insert,
            patch.object(app_module.supabase_data, "excluir_documentos") as delete_many,
        ):
            result = app_module.adicionar_os_ausentes([object()])

        self.assertEqual(1, result["inseridas"])
        self.assertEqual(1, result["ignoradas_existentes"])
        self.assertEqual(["3090"], result["numeros"])
        self.assertEqual(source_missing, build.call_args.args[0])
        self.assertEqual(["3090"], [row["numero"] for row in insert.call_args.args[0]])
        delete_many.assert_not_called()


if __name__ == "__main__":
    unittest.main()
