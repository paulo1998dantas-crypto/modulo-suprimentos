"""PCP request input and buyer cockpit; Estoque owns canonical persistence."""
import hmac
import secrets
from uuid import UUID
from flask import Blueprint, request, session, jsonify, render_template, current_app

def csrf_token():
    if not session.get("purchase_requests_csrf"):
        session["purchase_requests_csrf"] = secrets.token_urlsafe(32)
    return session["purchase_requests_csrf"]

def check_csrf(value):
    expected = session.get("purchase_requests_csrf", "")
    if not expected or not hmac.compare_digest(str(value or ""), expected):
        raise PermissionError("Sessão de solicitação expirada. Recarregue a página.")

def role_codes(user):
    user = user or {}
    roles = user.get("roles")
    if roles is None: roles = [user.get("role") or ""]
    if isinstance(roles, str): roles = [roles]
    return {"ADMIN" if str(role).strip().upper() == "ADM" else str(role).strip().upper() for role in roles}

def buyer_allowed(user, can):
    return bool(role_codes(user) & {"ADMIN", "COMPRADOR"} and can("suprimentos.purchase.create"))

def parse_ids(value):
    import json
    try:
        values = json.loads(value) if isinstance(value, str) else value
        if not isinstance(values, list) or len(values) > 100: raise ValueError()
        return list(dict.fromkeys(str(UUID(str(i))) for i in values))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Vínculo das solicitações inválido. Volte à tabela de solicitações.")

def prefill(ids, stock_request, user, can):
    if not buyer_allowed(user, can):
        raise PermissionError("Somente o comprador (ou administrador) pode converter solicitações.")
    data = stock_request("purchase-requests/prepare", "POST", {"ids": ids})
    rows = data.get("items") or []
    return {"purchase_request_ids": ids, "allocation_mode": "ESTOQUE",
            "allocation_reference": "ESTOQUE",
            "obs": "Solicitações: "+", ".join("SOL-"+r["id"][:8].upper() for r in rows),
            "itens": [{"codigo":r["sku_codigo"],"descricao":r["descricao"],"unidade":r["unidade"],
                       "qtd":r["quantity"],"data_necessidade":r["needed_at"]} for r in rows]}

def register(app, stock_request, get_user, can, login_required, feature_required):
    bp = Blueprint("purchase_requests", __name__)

    @app.context_processor
    def globals():
        return {"purchase_requests_csrf": csrf_token(),
                "purchase_requests_enabled": __import__("os").environ.get("ERP_FEATURE_FLAG", "").lower() in {"1","true","yes","sim"}}

    @bp.route("/erp/solicitacoes")
    @login_required
    @feature_required
    def screen():
        user = get_user()
        can_submit = bool(role_codes(user) & {"ADMIN", "PCP"} and can("suprimentos.work_order.manage"))
        return render_template("purchase_requests.html", current_user=user, request_config={
            "api":"/api/erp/purchase-requests", "origin":"PCP",
            "can_submit":can_submit, "can_edit_origin":can_submit,
            "can_manage":buyer_allowed(user, can), "user_id":user.get("id"),
            "csrf":csrf_token(), "purchases_url":"/?tab=gestao-oc"})

    @bp.route("/api/erp/purchase-requests", defaults={"suffix":""}, methods=["GET","POST"])
    @bp.route("/api/erp/purchase-requests/<path:suffix>", methods=["GET","POST"])
    @login_required
    @feature_required
    def proxy(suffix):
        user = get_user()
        if not user:
            return jsonify(ok=False,error="Autenticação obrigatória."),401
        try:
            allowed_get = suffix in {"","options","notifications"} or (
                suffix.endswith("/history") and len(suffix.split("/")) == 2)
            allowed_post = suffix == "" or (
                suffix.endswith("/action") and len(suffix.split("/")) == 2)
            if (request.method == "GET" and not allowed_get) or (request.method == "POST" and not allowed_post):
                return jsonify(ok=False,error="Operação inválida."),404
            if request.method == "POST":
                check_csrf(request.headers.get("X-CSRF-Token"))
                if suffix:
                    action = (request.get_json(silent=True) or {}).get("action")
                    if not buyer_allowed(user,can) and action not in {"EDITAR", "EXCLUIR"}:
                        raise PermissionError("Somente o comprador (ou administrador) pode tratar solicitações.")
                elif not role_codes(user) & {"ADMIN","PCP"} or not can("suprimentos.work_order.manage"):
                    raise PermissionError("Seu perfil não pode solicitar pelo PCP.")
            if suffix.endswith(("/history","/action")):
                suffix = str(UUID(suffix.split("/")[0]))+"/"+suffix.split("/")[1]
            path="purchase-requests"+("/"+suffix if suffix else "")
            if request.method == "GET" and request.query_string:
                path+="?"+request.query_string.decode("utf-8")
            result=stock_request(path, request.method, request.get_json(silent=True) or {} if request.method=="POST" else None)
            return jsonify(result)
        except PermissionError as exc:
            return jsonify(ok=False,error=str(exc)),403
        except (ValueError, TypeError) as exc:
            return jsonify(ok=False,error=str(exc)),400
        except Exception:
            current_app.logger.exception("Falha ao integrar solicitações com o Estoque")
            return jsonify(ok=False,error="Workflow indisponível. Tente novamente; a operação não foi confirmada."),503

    app.register_blueprint(bp)

