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


if __name__ == "__main__":
    unittest.main()
