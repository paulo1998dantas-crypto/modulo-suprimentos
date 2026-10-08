import copy
import io
import json
import os
import sys
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from docx import Document

APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
sys.path.insert(0, str(APP_DIR))
os.environ["SUPRIMENTOS_FILE_LOG"] = "0"

import app as app_module
import supabase_catalog
from os_item_visibility import codigos_inativos_catalogos, filtrar_catalogo_os, filtrar_linhas_ativas_os, linhas_para_exibicao_os


class OsItemVisibilityTests(unittest.TestCase):
    def test_local_status_and_boolean_are_respected_without_hiding_unknowns(self):
        catalog = {
            "A": {"ativo": False}, "B": {"active": False},
            "C": {"campos_extras": {"status": " inativo "}},
            "D": {"status": "INACTIVE"}, "E": {"ativo": True},
        }
        inactive = codigos_inativos_catalogos(catalog)
        self.assertEqual({"A", "B", "C", "D"}, inactive)
        self.assertEqual({"E"}, set(filtrar_catalogo_os(catalog, inactive)))
        rows = [{"codigo": "A - INATIVO"}, {"codigo": "E"}, {"codigo": "LEGADO"}, {"codigo": ""}]
        self.assertEqual(["E", "LEGADO", ""], [r["codigo"] for r in filtrar_linhas_ativas_os(rows, inactive)])

    def test_selected_active_alternative_keeps_planned_inactive_reference(self):
        rows = [
            {"codigo": "ANTIGO", "sku_planejado": "ANTIGO", "sku_selecionado": "NOVO", "qtd": 2},
            {"codigo": "NOVO", "sku_selecionado": "ANTIGO", "qtd": 4},
        ]
        original = copy.deepcopy(rows)
        result = filtrar_linhas_ativas_os(rows, {"ANTIGO"})
        self.assertEqual([rows[0]], result)
        self.assertEqual(original, rows)
        self.assertIsNot(rows[0], result[0])

    def test_active_children_are_not_lost_when_inactive_parent_is_hidden(self):
        rows = [
            {"codigo": "CJ-INATIVO", "item": "RAIZ", "level": 0},
            {"codigo": "PECA-ATIVA", "item": "CJ-INATIVO", "level": 1, "qtd": 6},
        ]
        result = filtrar_linhas_ativas_os(rows, {"CJ-INATIVO"})
        self.assertEqual([rows[1]], result)
        self.assertEqual(6, result[0]["qtd"])

    def test_inactive_parent_reference_is_hidden_only_in_display_copy(self):
        rows = [{"codigo": "PECA", "item": "CJ-INATIVO", "qtd": 6}]
        result = linhas_para_exibicao_os(rows, {"CJ-INATIVO"})
        self.assertEqual("", result[0]["item"])
        self.assertEqual("CJ-INATIVO", rows[0]["item"])


class InactiveCadastroCacheTests(unittest.TestCase):
    def tearDown(self):
        supabase_catalog.clear_cache()

    def test_active_and_inactive_maps_share_paginated_authoritative_read(self):
        supabase_catalog.clear_cache()
        rows = [{"sku": "ATIVO", "ativo": True}, {"sku": "INATIVO", "ativo": False}]
        with patch.object(supabase_catalog, "enabled", return_value=True), patch.object(supabase_catalog, "_all_rows", return_value=rows) as read:
            self.assertEqual({"ATIVO"}, set(supabase_catalog.carregar_produtos()))
            inactive = supabase_catalog.carregar_codigos_inativos()
            self.assertEqual({"INATIVO"}, inactive)
            inactive.clear()
            self.assertEqual({"INATIVO"}, supabase_catalog.carregar_codigos_inativos())
            read.assert_called_once()

    def test_forced_refresh_detects_activation_and_inactivation(self):
        supabase_catalog.clear_cache()
        with patch.object(supabase_catalog, "enabled", return_value=True), patch.object(supabase_catalog, "_all_rows", side_effect=[
            [{"sku": "A", "ativo": False}, {"sku": "B", "ativo": True}],
            [{"sku": "A", "ativo": True}, {"sku": "B", "ativo": False}],
        ]):
            self.assertEqual({"A"}, supabase_catalog.carregar_codigos_inativos())
            self.assertEqual({"B"}, supabase_catalog.carregar_codigos_inativos(force=True))

    def test_unavailable_cadastro_is_not_treated_as_no_inactive_items(self):
        with patch.object(supabase_catalog, "enabled", return_value=True), patch.object(supabase_catalog, "carregar_produtos", side_effect=supabase_catalog.SupabaseCatalogError("indisponível")):
            with self.assertRaises(supabase_catalog.SupabaseCatalogError):
                supabase_catalog.carregar_codigos_inativos(force=True)


class OsInactiveItemsRouteTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.catalog = {
            "40340028": {"descricao": "TRANSFORMAÇÃO ATIVA", "unidade": "un", "ativo": True},
            "10240088": {"descricao": "MATERIAL INATIVO", "unidade": "pc", "ativo": False},
            "10240141": {"descricao": "MATERIAL ATIVO", "unidade": "pc", "ativo": True},
            "30240096": {"descricao": "CJ INATIVO", "unidade": "pc", "ativo": False},
        }
        self.bom = {
            "40340028": [
                {"codigo": "10240088", "descricao": "MATERIAL INATIVO", "quantidade": 2},
                {"codigo": "30240096", "descricao": "CJ INATIVO", "quantidade": 3},
            ],
            "30240096": [{"codigo": "10240141", "descricao": "MATERIAL ATIVO", "quantidade": 2}],
        }
        for target, name, value in [
            (app_module, "login_enabled", False), (app_module, "can", True),
            (app_module, "shared_rbac_enabled", False),
            (app_module.supabase_data, "enabled", False), (supabase_catalog, "enabled", False),
            (app_module, "atualizar_skus_automatico", {}),
            (app_module, "carregar_os_fornecedores", {}),
            (app_module, "carregar_os_produtos", self.catalog),
            (app_module, "carregar_produtos", self.catalog),
            (app_module, "carregar_os_componentes", self.bom),
            (app_module, "carregar_regras_popup_item", []),
            (app_module, "carregar_os_processos", {}),
            (app_module, "carregar_relacoes_processo_item", {}),
            (app_module, "get_bom_dir", ""),
            (app_module, "limpar_importacao", None),
            (app_module, "_preparar_transformacao_documento_os", None),
        ]:
            self.stack.enter_context(patch.object(target, name, return_value=value))
        self.register = self.stack.enter_context(patch.object(app_module, "registrar_historico", return_value={"id": "TESTE"}))
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def post(self, **changes):
        data = {"acao": "salvar", "os_numero": "TESTE", "os_codigo[]": "40340028", "os_qtd[]": "1"}
        data.update(changes)
        return self.client.post("/gerar_os", data=data)

    def test_bom_composition_saved_without_inactive_lines_or_master_bom_mutation(self):
        original = copy.deepcopy(self.bom)
        response = self.post()
        self.assertEqual(302, response.status_code)
        composition = self.register.call_args.kwargs["composicao"]
        self.assertEqual(["10240141"], [r["codigo"] for r in composition])
        self.assertEqual(6, composition[0]["qtd"])
        self.assertEqual(original, self.bom)

    def test_posted_inactive_root_is_rejected_before_any_save(self):
        response = self.post(**{"os_codigo[]": "10240088"})
        self.assertEqual(409, response.status_code)
        self.assertIn("inativo", response.get_data(as_text=True))
        self.register.assert_not_called()

    def test_reissue_snapshot_filters_inactive_and_preserves_current_active_edits(self):
        previous = {"id": "123", "tipo": "os", "dados": {}, "composicao": [
            {"codigo": "10240088", "item": "40340028", "qtd": 2, "level": 0},
            {"codigo": "10240141", "item": "40340028", "descricao": "EDITADO", "qtd": 7, "level": 0, "setor_manual": True, "setor": "PREPARACAO"},
        ]}
        original = copy.deepcopy(previous)
        with patch.object(app_module, "obter_historico_documento", return_value=previous):
            response = self.post(os_historico_id="123", os_composicao_source="custom", os_composicao_json=json.dumps(previous["composicao"]))
        self.assertEqual(302, response.status_code)
        composition = self.register.call_args.kwargs["composicao"]
        self.assertEqual(["10240141"], [r["codigo"] for r in composition])
        self.assertEqual(7, float(composition[0]["qtd"]))
        self.assertEqual("PREPARACAO", composition[0]["setor"])
        self.assertEqual(original, previous)

    def test_generated_docx_package_has_no_inactive_sku_or_description(self):
        response = self.post(acao="imprimir")
        self.assertEqual(200, response.status_code)
        with zipfile.ZipFile(io.BytesIO(response.data)) as package:
            documents = [name for name in package.namelist() if name.endswith(".docx")]
            self.assertEqual(3, len(documents))
            texts = []
            for name in documents:
                document = Document(io.BytesIO(package.read(name)))
                texts.append("\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells))
        full_text = "\n".join(texts)
        self.assertNotIn("10240088", full_text)
        self.assertNotIn("30240096", full_text)
        self.assertNotIn("MATERIAL INATIVO", full_text)
        self.assertIn("10240141", full_text)

    def test_custom_empty_after_filtering_is_not_reexploded_in_docx(self):
        response = self.post(acao="imprimir", os_composicao_source="custom", os_composicao_json=json.dumps([
            {"codigo": "10240088", "item": "40340028", "qtd": 2}
        ]))
        self.assertEqual(200, response.status_code)
        self.assertEqual([], self.register.call_args.kwargs["composicao"])

    def test_cadastro_failure_blocks_emission_without_save(self):
        with patch.object(app_module, "carregar_os_codigos_inativos", side_effect=supabase_catalog.SupabaseCatalogError("indisponível")) as check:
            response = self.post()
        self.assertEqual(503, response.status_code)
        self.assertTrue(check.call_args.kwargs["force"])
        self.register.assert_not_called()

    def test_index_passes_active_os_catalogue_and_inactive_flags_but_not_filtered_master_bom(self):
        with patch.object(app_module, "render_template", return_value="OK") as render:
            response = self.client.get("/?tab=os")
        self.assertEqual(200, response.status_code)
        context = render.call_args.kwargs
        self.assertEqual({"40340028", "10240141"}, set(context["os_produtos"]))
        self.assertEqual(["10240088", "30240096"], context["os_codigos_inativos"])
        self.assertEqual(self.bom, context["os_componentes"])
        self.assertEqual(self.catalog, context["produtos"])

    def test_allocation_transformation_picker_excludes_inactive_but_keeps_na(self):
        with patch.object(app_module, "erp_feature_enabled", return_value=True), patch.object(app_module, "_erp_mes_request", return_value={
            "ok": True, "transformacoes": [{"codigo": "40340028"}, {"codigo": "10240088"}, {"codigo": "N/A"}],
            "ar_tipos": ["COMPLEMENTO"],
        }):
            response = self.client.get("/api/erp/os-management/catalogs")
        self.assertEqual(200, response.status_code)
        self.assertEqual(["40340028", "N/A"], [r["codigo"] for r in response.json["transformacoes"]])
        self.assertEqual(["COMPLEMENTO"], response.json["ar_tipos"])
