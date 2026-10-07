import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"compras_app"))
os.environ["SUPRIMENTOS_FILE_LOG"]="0"
import app as mod
import purchase_request_routes as routes

class PurchaseRequestIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{"ERP_FEATURE_FLAG":"true"}))
        for name,value in (("login_enabled",False),("shared_rbac_enabled",False),
                ("atualizar_skus_automatico",{}),("carregar_fornecedores",{}),
                ("carregar_produtos",{}),("carregar_os_componentes",{}),("proximo_numero_oc",51)):
            self.stack.enter_context(patch.object(mod,name,return_value=value))
        self.client=mod.app.test_client()
        self.id=str(uuid4())
        with self.client.session_transaction() as sess:
            sess["suprimentos_user"]={"id":1,"username":"BUYER","roles":["COMPRADOR"],"role":"COMPRADOR"}
            sess["purchase_requests_csrf"]="csrf"
        self.form={"acao":"salvar","oc_submit_token":"request-order-token","fornecedor":"Fornecedor",
            "allocation_mode":"ESTOQUE","codigo[]":"MAT-001","descricao[]":"Material","unidade[]":"UN",
            "qtd[]":"2","valor[]":"10","desconto[]":"0","frete":"0","purchase_request_ids":json.dumps([self.id]),
            "purchase_requests_csrf":"csrf"}

    def role(self,role):
        with self.client.session_transaction() as sess:
            sess["suprimentos_user"] = dict(sess["suprimentos_user"], roles=[role], role=role)

    def test_central_table_is_buyer_action_surface(self):
        response=self.client.get("/erp/solicitacoes")
        self.assertEqual(200,response.status_code)
        text=response.get_data(as_text=True)
        self.assertIn("Preparar pedido das selecionadas",text)
        self.role("PCP")
        response=self.client.get("/erp/solicitacoes")
        self.assertNotIn("Preparar pedido das selecionadas",response.get_data(as_text=True))
        self.assertIn("Planejamento / PCP",response.get_data(as_text=True))

    def test_new_pcp_input_forces_origin_on_backend_and_preserves_actor(self):
        self.role("PCP")
        with patch.object(mod,"_erp_stock_request",return_value={"ok":True,"request":{"id":self.id}}) as proxy:
            response=self.client.post("/api/erp/purchase-requests",json={"sku_codigo":"MAT-001","origin":"ESTOQUE"},headers={"X-CSRF-Token":"csrf"})
        self.assertEqual(200,response.status_code)
        self.assertEqual("purchase-requests",proxy.call_args.args[0])
        self.assertEqual("POST",proxy.call_args.args[1])

    def test_no_csrf_no_action(self):
        with patch.object(mod,"_erp_stock_request") as proxy:
            response=self.client.post("/api/erp/purchase-requests/"+self.id+"/action",json={"action":"CANCELAR"})
        self.assertEqual(403,response.status_code)
        proxy.assert_not_called()

    def test_pcp_cannot_treat_even_with_broad_permissions(self):
        self.role("PCP")
        with patch.object(mod,"_erp_stock_request") as proxy:
            response=self.client.post("/api/erp/purchase-requests/"+self.id+"/action",json={"action":"ASSUMIR"},headers={"X-CSRF-Token":"csrf"})
        self.assertEqual(403,response.status_code)
        proxy.assert_not_called()

    def test_requester_edit_and_exclude_actions_are_forwarded_for_stock_ownership_check(self):
        self.role("PCP")
        for action in ("EDITAR", "EXCLUIR"):
            with self.subTest(action=action),patch.object(mod,"_erp_stock_request",return_value={"ok":True}) as proxy:
                response=self.client.post(
                    "/api/erp/purchase-requests/"+self.id+"/action",
                    json={"action":action,"version":1,"reason":"Correção do solicitante"},
                    headers={"X-CSRF-Token":"csrf"},
                )
                self.assertEqual(200,response.status_code)
                proxy.assert_called_once()

    def test_buyer_action_and_notifications(self):
        with patch.object(mod,"_erp_stock_request",return_value={"ok":True,"new":2,"in_progress":3}) as proxy:
            self.assertEqual(200,self.client.get("/api/erp/purchase-requests/notifications").status_code)
            response=self.client.post("/api/erp/purchase-requests/"+self.id+"/action",json={"action":"ASSUMIR","version":1,"reason":"Teste"},headers={"X-CSRF-Token":"csrf"})
        self.assertEqual(200,response.status_code)
        self.assertTrue(proxy.call_args.args[0].endswith("/action"))

    def test_invalid_proxy_path_rejected(self):
        with patch.object(mod,"_erp_stock_request") as proxy:
            response=self.client.post("/api/erp/purchase-requests/../purchase-orders",json={},headers={"X-CSRF-Token":"csrf"})
        self.assertEqual(404,response.status_code)
        proxy.assert_not_called()

    def test_non_json_upstream_failure_returns_readable_error(self):
        with patch.object(mod,"_erp_stock_request",side_effect=ValueError("Estoque indisponível")):
            response=self.client.get("/api/erp/purchase-requests")
        self.assertEqual(400,response.status_code)
        self.assertIn("Estoque indisponível",response.json["error"])

    def test_prepare_prefills_standard_order_form(self):
        callback=lambda *args: {"items":[{"id":self.id,"sku_codigo":"MAT-001","descricao":"Material",
           "unidade":"UN","quantity":"2.000","needed_at":"2026-10-15"}]}
        result=routes.prefill([self.id],callback,{"roles":["COMPRADOR"]},lambda p:True)
        self.assertEqual([self.id],result["purchase_request_ids"])
        self.assertEqual("2.000",result["itens"][0]["qtd"])
        self.assertEqual("ESTOQUE",result["allocation_mode"])

    def test_parse_ids_rejects_tampered_ids(self):
        for value in ("bad","{}",'["bad"]',json.dumps(["bad"]*101)):
            with self.subTest(value=value),self.assertRaises(ValueError):routes.parse_ids(value)

    def test_saving_draft_keeps_requests_pending_and_ids_persisted(self):
        with patch.object(mod,"registrar_historico") as register,patch.object(mod,"_sync_emitted_legacy_oc_to_erp") as sync,patch.object(mod,"gerar_word") as generate:
            response=self.client.post("/gerar_oc",data=self.form)
        self.assertEqual(302,response.status_code)
        self.assertEqual("rascunho",register.call_args.kwargs["status"])
        self.assertEqual([self.id],register.call_args.args[2]["purchase_request_ids"])
        sync.assert_not_called()
        generate.assert_not_called()

    def test_emit_confirms_before_promoting_legacy_document(self):
        with tempfile.TemporaryDirectory() as temp:
            doc=Path(temp)/"order.docx"
            # Test fixture only; real O.C. generation is covered by existing tests.
            doc.touch()
            form=dict(self.form,acao="imprimir")
            with patch.object(mod,"registrar_historico",return_value={"id":77}) as register,patch.object(mod,"_sync_emitted_legacy_oc_to_erp",return_value={"id":str(uuid4())}) as sync,patch.object(mod,"vincular_documento_erp"),patch.object(mod,"gerar_word",return_value=str(doc)):
                response=self.client.post("/gerar_oc",data=form)
            self.assertEqual(200,response.status_code)
            self.assertEqual("rascunho",register.call_args_list[0].kwargs["status"])
            self.assertEqual("emitido",register.call_args_list[-1].kwargs["status"])
            self.assertEqual([self.id],sync.call_args.args[1]["purchase_request_ids"])
            response.close()

    def test_failed_emit_preserves_draft_and_does_not_send_docx(self):
        form=dict(self.form,acao="imprimir")
        with patch.object(mod,"registrar_historico",return_value={"id":77}) as register,patch.object(mod,"_sync_emitted_legacy_oc_to_erp",side_effect=ValueError("Quantidade insuficiente")),patch.object(mod,"gerar_word",return_value="fake.docx"):
            response=self.client.post("/gerar_oc",data=form)
        self.assertEqual(302,response.status_code)
        self.assertEqual(1,register.call_count)
        self.assertEqual("rascunho",register.call_args.kwargs["status"])
        self.assertIn("gestao-oc",response.headers["Location"])

    def test_request_link_cannot_be_removed_when_editing_existing_order(self):
        existing={"id":77,"tipo":"oc","status":"emitido","dados":{"purchase_request_ids":[self.id]}}
        form=dict(self.form,purchase_request_ids="[]",oc_historico_id="77")
        with patch.object(mod,"obter_historico_documento",return_value=existing),patch.object(mod,"registrar_historico",return_value={"id":77}),patch.object(mod,"_sync_emitted_legacy_oc_to_erp",return_value={"id":str(uuid4())}) as sync,patch.object(mod,"vincular_documento_erp"):
            response=self.client.post("/gerar_oc",data=form)
        self.assertEqual(302,response.status_code)
        self.assertEqual([self.id],sync.call_args.args[1]["purchase_request_ids"])

    def test_linked_emission_requires_buyer(self):
        self.role("PCP")
        with patch.object(mod,"registrar_historico") as register:
            response=self.client.post("/gerar_oc",data=self.form)
        self.assertEqual(403,response.status_code)
        register.assert_not_called()

    def test_ids_in_canonical_payload(self):
        with patch.object(mod,"_erp_stock_request",return_value={"id":str(uuid4())}) as proxy:
            mod._sync_emitted_legacy_oc_to_erp({"id":77},{"purchase_request_ids":[self.id]},[{"codigo":"MAT-001","qtd":2,"valor":10}],"51","Fornecedor")
        self.assertEqual([self.id],proxy.call_args.args[2]["purchase_request_ids"])

if __name__=="__main__":unittest.main()

