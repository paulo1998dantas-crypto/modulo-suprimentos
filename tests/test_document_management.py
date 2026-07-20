import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import app as app_module
import supabase_data


class DocumentManagementTests(unittest.TestCase):
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
        self.assertIn("ID Linha", item_rows[0])
        self.assertEqual("rascunho", main_rows[1][1])
        self.assertEqual("SKU-1", item_rows[1][8])
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


if __name__ == "__main__":
    unittest.main()
