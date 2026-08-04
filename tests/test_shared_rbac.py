import json
import os
import sys
import unittest
import ast
from pathlib import Path
from unittest.mock import MagicMock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
os.environ["SUPRIMENTOS_FILE_LOG"] = "0"

import app as app_module
import supabase_data


class SharedRbacTests(unittest.TestCase):
    def setUp(self):
        supabase_data.clear_cache()
        app_module.app.config.update(TESTING=True)

    def test_shared_roles_are_combined_and_user_deny_wins(self):
        def fake_request(method, table, query=None, payload=None, prefer=""):
            if table == supabase_data.USER_ROLES_TABLE:
                return [{"role_code": "COMPRADOR"}, {"role_code": "FINANCEIRO"}]
            if table == supabase_data.ROLES_TABLE:
                return [{"code": "COMPRADOR"}, {"code": "FINANCEIRO"}]
            if table == supabase_data.ROLE_PERMISSIONS_TABLE:
                return [
                    {"permission_code": "suprimentos.purchase.create"},
                    {"permission_code": "suprimentos.purchase.financial_close"},
                ]
            if table == supabase_data.USER_PERMISSION_OVERRIDES_TABLE:
                return [
                    {
                        "permission_code": "suprimentos.purchase.create",
                        "allowed": False,
                    },
                    {
                        "permission_code": "suprimentos.work_order.view",
                        "allowed": True,
                    },
                ]
            raise AssertionError(f"Unexpected table: {table}")

        with (
            patch.object(supabase_data, "shared_rbac_enabled", return_value=True),
            patch.object(
                supabase_data,
                "_load_user_record",
                return_value={
                    "id": 9,
                    "username": "maria",
                    "role": "operador",
                    "active": True,
                    "auth_version": 4,
                },
            ),
            patch.object(supabase_data, "_request", side_effect=fake_request),
        ):
            user = supabase_data.load_user_authorization(9, force=True)

        self.assertEqual(["COMPRADOR", "FINANCEIRO"], user["roles"])
        self.assertNotIn("suprimentos.purchase.create", user["permissions"])
        self.assertIn("suprimentos.purchase.financial_close", user["permissions"])
        self.assertIn("suprimentos.work_order.view", user["permissions"])
        self.assertEqual(4, user["auth_version"])
        self.assertEqual("shared", user["rbac_source"])

    def test_missing_shared_schema_fails_closed_without_legacy_fallback(self):
        with (
            patch.object(supabase_data, "shared_rbac_enabled", return_value=True),
            patch.object(
                supabase_data,
                "_load_user_record",
                return_value={
                    "id": 2,
                    "username": "compras",
                    "role": "comprador",
                    "active": True,
                },
            ),
            patch.object(
                supabase_data,
                "_request",
                side_effect=supabase_data.SupabaseDataError("relation does not exist"),
            ),
        ):
            with self.assertRaises(supabase_data.SupabaseDataError):
                supabase_data.load_user_authorization(2, force=True)

    def test_missing_shared_membership_does_not_recover_users_role(self):
        def fake_request(method, table, query=None, payload=None, prefer=""):
            if table in {
                supabase_data.USER_ROLES_TABLE,
                supabase_data.USER_PERMISSION_OVERRIDES_TABLE,
            }:
                return []
            raise AssertionError(f"Unexpected table: {table}")

        with (
            patch.object(supabase_data, "shared_rbac_enabled", return_value=True),
            patch.object(
                supabase_data,
                "_load_user_record",
                return_value={
                    "id": 2,
                    "username": "compras",
                    "role": "comprador",
                    "active": True,
                    "auth_version": 1,
                },
            ),
            patch.object(supabase_data, "_request", side_effect=fake_request),
        ):
            user = supabase_data.load_user_authorization(2, force=True)

        self.assertEqual([], user["roles"])
        self.assertEqual([], user["permissions"])
        self.assertEqual("shared", user["rbac_source"])

    def test_shared_rbac_connection_failure_does_not_fail_open(self):
        with (
            patch.object(supabase_data, "shared_rbac_enabled", return_value=True),
            patch.object(
                supabase_data,
                "_load_user_record",
                return_value={
                    "id": 2,
                    "username": "admin",
                    "role": "admin",
                    "active": True,
                },
            ),
            patch.object(
                supabase_data,
                "_request",
                side_effect=supabase_data.SupabaseDataError(
                    "Nao foi possivel conectar ao Supabase"
                ),
            ),
        ):
            with self.assertRaises(supabase_data.SupabaseDataError):
                supabase_data.load_user_authorization(2, force=True)

    def test_empty_shared_role_does_not_regain_legacy_permissions(self):
        def fake_request(method, table, query=None, payload=None, prefer=""):
            if table == supabase_data.USER_ROLES_TABLE:
                return [{"role_code": "COMPRADOR"}]
            if table == supabase_data.ROLES_TABLE:
                return [{"code": "COMPRADOR"}]
            if table in {
                supabase_data.ROLE_PERMISSIONS_TABLE,
                supabase_data.USER_PERMISSION_OVERRIDES_TABLE,
            }:
                return []
            raise AssertionError(f"Unexpected table: {table}")

        with (
            patch.object(supabase_data, "shared_rbac_enabled", return_value=True),
            patch.object(
                supabase_data,
                "_load_user_record",
                return_value={
                    "id": 2,
                    "username": "compras",
                    "role": "comprador",
                    "active": True,
                    "auth_version": 1,
                },
            ),
            patch.object(supabase_data, "_request", side_effect=fake_request),
        ):
            user = supabase_data.load_user_authorization(2, force=True)

        self.assertEqual([], user["permissions"])
        self.assertEqual("shared", user["rbac_source"])

    def test_inactive_shared_role_grants_no_permissions(self):
        def fake_request(method, table, query=None, payload=None, prefer=""):
            if table == supabase_data.USER_ROLES_TABLE:
                return [{"role_code": "COMPRADOR"}]
            if table == supabase_data.ROLES_TABLE:
                self.assertIn(("active", "eq.true"), query)
                return []
            if table == supabase_data.USER_PERMISSION_OVERRIDES_TABLE:
                return []
            if table == supabase_data.ROLE_PERMISSIONS_TABLE:
                self.fail("Inactive roles must not load mapped permissions.")
            raise AssertionError(f"Unexpected table: {table}")

        with (
            patch.object(supabase_data, "shared_rbac_enabled", return_value=True),
            patch.object(
                supabase_data,
                "_load_user_record",
                return_value={
                    "id": 2,
                    "username": "compras",
                    "role": "comprador",
                    "active": True,
                    "auth_version": 1,
                },
            ),
            patch.object(supabase_data, "_request", side_effect=fake_request),
        ):
            user = supabase_data.load_user_authorization(2, force=True)

        self.assertEqual([], user["roles"])
        self.assertEqual([], user["permissions"])
        self.assertEqual("shared", user["rbac_source"])

    def test_legacy_operator_can_open_receiving_but_not_buy(self):
        permissions = supabase_data.ROLE_PERMISSION_FALLBACKS["OPERADOR"]
        self.assertIn("estoque.inspection.receive", permissions)
        self.assertIn("suprimentos.purchase.view", permissions)
        self.assertNotIn("suprimentos.purchase.create", permissions)
        self.assertNotIn("suprimentos.purchase.financial_close", permissions)

    def test_engineering_fallback_is_exactly_pcp_plus_cadastro_access(self):
        pcp = supabase_data.ROLE_PERMISSION_FALLBACKS["PCP"]
        engineering = supabase_data.ROLE_PERMISSION_FALLBACKS["ENGENHARIA"]
        self.assertEqual(pcp | {"cadastro.access"}, engineering)
        self.assertNotIn("suprimentos.master_data.manage", engineering)

    def test_legacy_adm_is_canonical_admin_and_admin_remains_superprofile(self):
        def fake_request(method, table, query=None, payload=None, prefer=""):
            if table == supabase_data.USER_ROLES_TABLE:
                return [{"role_code": "ADMIN"}]
            if table == supabase_data.ROLES_TABLE:
                return [{"code": "ADMIN"}]
            if table == supabase_data.ROLE_PERMISSIONS_TABLE:
                return [{"permission_code": "suprimentos.dashboard.view"}]
            if table == supabase_data.USER_PERMISSION_OVERRIDES_TABLE:
                return []
            raise AssertionError(f"Unexpected table: {table}")

        with (
            patch.object(supabase_data, "shared_rbac_enabled", return_value=True),
            patch.object(
                supabase_data,
                "_load_user_record",
                return_value={
                    "id": 1,
                    "username": "admin",
                    "role": "ADM",
                    "active": True,
                    "auth_version": 1,
                },
            ),
            patch.object(supabase_data, "_request", side_effect=fake_request),
        ):
            user = supabase_data.load_user_authorization(1, force=True)

        self.assertEqual(["ADMIN"], supabase_data._role_codes("ADM"))
        self.assertIn("*", user["permissions"])

    def test_auth_version_change_invalidates_cached_session(self):
        stale = {
            "id": 12,
            "username": "financeiro",
            "role": "financeiro",
            "auth_version": 1,
            "permissions": ["suprimentos.purchase.financial_close"],
        }
        with (
            patch.object(
                supabase_data,
                "_load_user_record",
                return_value={
                    "id": 12,
                    "username": "financeiro",
                    "role": "financeiro",
                    "active": True,
                    "auth_version": 2,
                },
            ),
            patch.object(supabase_data, "load_user_authorization") as load_auth,
        ):
            self.assertIsNone(supabase_data.revalidate_session_user(stale))
        load_auth.assert_not_called()

    def test_current_session_reuses_short_role_matrix_cache(self):
        session_user = {
            "id": 12,
            "username": "financeiro",
            "role": "financeiro",
            "auth_version": 2,
        }
        current = {
            "id": 12,
            "username": "financeiro",
            "role": "financeiro",
            "active": True,
            "auth_version": 2,
        }
        with (
            patch.object(supabase_data, "_load_user_record", return_value=current),
            patch.object(
                supabase_data,
                "load_user_authorization",
                return_value={**session_user, "permissions": []},
            ) as load_auth,
        ):
            self.assertIsNotNone(supabase_data.revalidate_session_user(session_user))
        load_auth.assert_called_once_with(12, force=False)

    def test_expired_shared_session_is_rejected_before_api_handler(self):
        stale = {
            "id": 12,
            "username": "financeiro",
            "role": "financeiro",
            "auth_version": 1,
            "permissions": ["suprimentos.purchase.financial_close"],
        }
        with (
            patch.object(app_module, "login_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "revalidate_session_user",
                return_value=None,
            ),
            patch.object(app_module, "_erp_stock_request") as stock_request,
        ):
            client = app_module.app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["suprimentos_user"] = stale
            response = client.post(
                "/api/erp/purchase-orders/order-1/financial-close",
                json={"valor_lancado": 10},
            )
            with client.session_transaction() as flask_session:
                self.assertNotIn("suprimentos_user", flask_session)

        self.assertEqual(401, response.status_code)
        stock_request.assert_not_called()

    def test_shared_login_reports_service_unavailable_when_rbac_cannot_load(self):
        with (
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "verify_user",
                side_effect=supabase_data.SupabaseDataError(
                    "schema RBAC indisponivel"
                ),
            ),
        ):
            response = app_module.app.test_client().post(
                "/login",
                data={"username": "compras", "password": "senha"},
            )

        self.assertEqual(503, response.status_code)
        self.assertIn(
            "temporariamente indisponivel",
            response.get_data(as_text=True),
        )

    def test_financial_endpoint_is_blocked_without_permission(self):
        with (
            patch.object(app_module, "login_enabled", return_value=False),
            patch.object(app_module, "erp_feature_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(app_module, "_erp_stock_request") as stock_request,
        ):
            response = app_module.app.test_client().post(
                "/api/erp/purchase-orders/order-1/financial-close",
                json={"valor_lancado": 10},
            )

        self.assertEqual(403, response.status_code)
        stock_request.assert_not_called()

    def test_financial_role_can_proxy_financial_close(self):
        user = {
            "id": 12,
            "username": "financeiro",
            "permissions": [
                "suprimentos.purchase.view",
                "suprimentos.purchase.financial_close",
            ],
            "auth_version": 1,
        }
        with (
            patch.object(app_module, "login_enabled", return_value=True),
            patch.object(app_module, "erp_feature_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "revalidate_session_user",
                return_value=user,
            ),
            patch.object(
                app_module,
                "_erp_stock_request",
                return_value={"ok": True, "financial_status": "CONCLUIDA"},
            ) as stock_request,
        ):
            client = app_module.app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["suprimentos_user"] = user
            response = client.post(
                "/api/erp/purchase-orders/order-1/financial-close",
                json={"valor_lancado": 10},
            )

        self.assertEqual(200, response.status_code)
        stock_request.assert_called_once()

    def test_materials_endpoint_uses_work_order_id(self):
        user = {
            "id": 8,
            "username": "operador",
            "permissions": ["suprimentos.work_order.view"],
            "auth_version": 1,
        }
        work_id = "11111111-1111-1111-1111-111111111111"
        with (
            patch.object(app_module, "login_enabled", return_value=True),
            patch.object(app_module, "erp_feature_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "revalidate_session_user",
                return_value=user,
            ),
            patch.object(
                app_module,
                "_erp_stock_request",
                return_value={"ok": True, "totals": {}, "lines": []},
            ) as stock_request,
        ):
            client = app_module.app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["suprimentos_user"] = user
            response = client.get(
                f"/api/erp/os-management/work-orders/{work_id}/materials"
            )

        self.assertEqual(200, response.status_code)
        stock_request.assert_called_once_with(f"work-orders/{work_id}/materials")

    def test_shared_consumption_is_blocked_without_admin_reconciliation_permission(self):
        user = {
            "id": 8,
            "username": "operador",
            "permissions": ["suprimentos.work_order.view"],
            "auth_version": 1,
        }
        work_id = "11111111-1111-1111-1111-111111111111"
        with (
            patch.object(app_module, "login_enabled", return_value=True),
            patch.object(app_module, "erp_feature_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "revalidate_session_user",
                return_value=user,
            ),
            patch.object(app_module, "_erp_stock_request") as stock_request,
        ):
            client = app_module.app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["suprimentos_user"] = user
            response = client.post(
                f"/api/erp/os-management/work-orders/{work_id}/materials/shared-consumption",
                json={"movement_id": 41, "quantidade": 2, "motivo": "Teste"},
            )

        self.assertEqual(403, response.status_code)
        stock_request.assert_not_called()

    def test_admin_reconciliation_permission_can_proxy_shared_consumption(self):
        user = {
            "id": 1,
            "username": "admin",
            "permissions": [
                "suprimentos.work_order.view",
                "estoque.commitment.reconcile_admin",
            ],
            "auth_version": 1,
        }
        work_id = "11111111-1111-1111-1111-111111111111"
        payload = {
            "movement_id": 41,
            "quantidade": 2,
            "motivo": "Consumo compartilhado confirmado",
            "idempotency_key": "shared-consumption:test",
        }
        with (
            patch.object(app_module, "login_enabled", return_value=True),
            patch.object(app_module, "erp_feature_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "revalidate_session_user",
                return_value=user,
            ),
            patch.object(
                app_module,
                "_erp_stock_request",
                return_value={"ok": True, "movement_id": 99},
            ) as stock_request,
        ):
            client = app_module.app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["suprimentos_user"] = user
            response = client.post(
                f"/api/erp/os-management/work-orders/{work_id}/materials/shared-consumption",
                json=payload,
            )

        self.assertEqual(200, response.status_code)
        stock_request.assert_called_once_with(
            f"work-orders/{work_id}/materials/shared-consumption",
            "POST",
            payload,
        )

    def test_reused_purchase_token_requires_edit_before_any_sync(self):
        user = {
            "id": 14,
            "username": "criador",
            "role": "comprador",
            "permissions": ["suprimentos.purchase.create"],
            "auth_version": 1,
        }
        with (
            patch.object(app_module, "login_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "revalidate_session_user",
                return_value=user,
            ),
            patch.object(
                app_module,
                "obter_historico_por_submit_token",
                return_value={"id": "existing", "tipo": "oc"},
            ),
            patch.object(app_module, "atualizar_skus_automatico") as update_skus,
        ):
            client = app_module.app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["suprimentos_user"] = user
            response = client.post(
                "/gerar_oc",
                data={"oc_submit_token": "known-existing-token", "acao": "salvar"},
            )

        self.assertEqual(403, response.status_code)
        update_skus.assert_not_called()

    def test_new_purchase_token_for_buyer_resolves_create_permission(self):
        with (
            app_module.app.test_request_context(
                "/gerar_oc",
                method="POST",
                data={"oc_submit_token": "new-browser-token"},
            ),
            patch.object(
                app_module,
                "obter_historico_por_submit_token",
                return_value=None,
            ),
        ):
            permission = app_module._purchase_save_required_permission()

        self.assertEqual("suprimentos.purchase.create", permission)

    def test_document_lookup_by_submit_token_uses_document_table(self):
        with patch.object(supabase_data, "_request", return_value=[]) as request_mock:
            result = supabase_data.obter_documento_por_submit_token("new-browser-token")

        self.assertIsNone(result)
        request_mock.assert_called_once_with(
            "GET",
            supabase_data.DOCUMENTOS_TABLE,
            query=[
                ("select", "id,tipo,numero,submit_token"),
                ("submit_token", "eq.new-browser-token"),
                ("limit", "1"),
            ],
        )

    def test_invalid_purchase_edit_id_cannot_fall_through_to_create(self):
        user = {
            "id": 15,
            "username": "editor",
            "role": "comprador",
            "permissions": ["suprimentos.purchase.edit"],
            "auth_version": 1,
        }
        with (
            patch.object(app_module, "login_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "revalidate_session_user",
                return_value=user,
            ),
            patch.object(
                app_module,
                "obter_historico_documento",
                return_value=None,
            ),
            patch.object(app_module, "atualizar_skus_automatico") as update_skus,
            patch.object(app_module, "registrar_historico") as save_history,
        ):
            client = app_module.app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["suprimentos_user"] = user
            response = client.post(
                "/gerar_oc",
                data={"oc_historico_id": "missing", "acao": "salvar"},
            )

        self.assertEqual(404, response.status_code)
        update_skus.assert_not_called()
        save_history.assert_not_called()

    def test_legacy_work_order_reopen_requires_technical_permission(self):
        user = {
            "id": 16,
            "username": "gestor_os",
            "role": "pcp",
            "permissions": ["suprimentos.work_order.manage"],
            "auth_version": 1,
        }
        with (
            patch.object(app_module, "login_enabled", return_value=True),
            patch.object(app_module, "shared_rbac_enabled", return_value=True),
            patch.object(
                app_module.supabase_data,
                "revalidate_session_user",
                return_value=user,
            ),
            patch.object(
                app_module,
                "obter_historico_documento",
                return_value={
                    "id": "os-1",
                    "tipo": "os",
                    "status": "concluido",
                },
            ),
            patch.object(
                app_module,
                "atualizar_status_historico_documento",
            ) as update_status,
        ):
            client = app_module.app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["suprimentos_user"] = user
            response = client.post(
                "/api/historico/os/os-1/status",
                json={"status": "emitido"},
            )

        self.assertEqual(403, response.status_code)
        update_status.assert_not_called()

    def test_every_mutable_application_route_has_permission_decorator(self):
        tree = ast.parse(
            (
                Path(__file__).resolve().parents[1]
                / "compras_app"
                / "app.py"
            ).read_text(encoding="utf-8")
        )
        unguarded = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [ast.unparse(item) for item in node.decorator_list]
            routes = [item for item in decorators if item.startswith("app.route(")]
            mutable = any(
                any(method in route for method in ("POST", "PUT", "PATCH", "DELETE"))
                for route in routes
            )
            if (
                mutable
                and node.name != "login"
                and not any(
                    item.startswith("permission_required(")
                    for item in decorators
                )
            ):
                unguarded.append(node.name)
        self.assertEqual([], unguarded)

    def test_backend_calls_forward_immutable_actor_id(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": True}
        ).encode("utf-8")
        with (
            app_module.app.test_request_context("/"),
            patch.dict(
                os.environ,
                {
                    "ERP_STOCK_API_URL": "https://estoque.example.test",
                    "ERP_BACKEND_TOKEN": "test-token",
                },
                clear=False,
            ),
            patch.object(
                app_module.urllib.request,
                "urlopen",
                return_value=response,
            ) as urlopen,
        ):
            app_module.session["suprimentos_user"] = {
                "id": 77,
                "username": "paulo",
            }
            app_module._erp_stock_request("dashboard")

        sent_request = urlopen.call_args.args[0]
        headers = {key.lower(): value for key, value in sent_request.header_items()}
        self.assertEqual("77", headers["x-erp-actor-id"])
        self.assertEqual("paulo", headers["x-erp-actor"])

    def test_purchase_management_has_no_category_filter(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "compras_app"
            / "templates"
            / "erp_ordens_compra.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn('id="category"', template)
        self.assertNotIn("o.categoria===category", template)

    def test_work_order_template_exposes_read_only_permission_switch(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "compras_app"
            / "templates"
            / "erp_gestao_os.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "manage:{{ can('suprimentos.work_order.manage')|tojson }}",
            template,
        )
        self.assertIn("const editable=permissions.manage", template)
        self.assertIn("/materials`", template)
        self.assertIn(
            "poolAdmin:{{ can('estoque.commitment.reconcile_admin')|tojson }}",
            template,
        )
        self.assertIn("saldo_fluxo_compartilhado", template)
        self.assertIn("Baixar do fluxo", template)
        self.assertIn("materials/shared-consumption", template)
        self.assertIn('name="motivo"', template)
        self.assertIn(
            "{% if can('mes.dashboard.read') %}",
            template,
        )


if __name__ == "__main__":
    unittest.main()
