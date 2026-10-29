"""PCP front end for the canonical external ledger owned by Estoque."""
import hmac
import secrets
from flask import Blueprint, current_app, jsonify, render_template, request, session
from purchase_request_routes import role_codes


def register(app, stock_request, get_user, can, login_required, feature_required):
    bp = Blueprint('external_stock', __name__)

    def access(write=False):
        if not role_codes(get_user()) & {'ADMIN', 'PCP'} or not can('suprimentos.work_order.view'):
            raise PermissionError('Baixa externa disponível somente para PCP e ADMIN.')
        if write and not can('suprimentos.work_order.manage'):
            raise PermissionError('Usuário sem permissão para movimentar estoque externo.')

    def token():
        if not session.get('external_stock_csrf'):
            session['external_stock_csrf'] = secrets.token_urlsafe(32)
        return session['external_stock_csrf']

    @bp.route('/erp/baixa-externa')
    @login_required
    @feature_required
    def screen():
        try:
            access()
            return render_template('external_stock.html', csrf=token(),
                                   can_manage=can('suprimentos.work_order.manage'))
        except PermissionError as exc:
            return str(exc), 403

    @bp.route('/api/erp/external-stock', methods=['GET', 'POST'])
    @login_required
    @feature_required
    def proxy():
        try:
            access(request.method == 'POST')
            if request.method == 'POST':
                if not session.get('external_stock_csrf') or not hmac.compare_digest(
                        request.headers.get('X-CSRF-Token', ''), session['external_stock_csrf']):
                    raise PermissionError('Sessão expirada. Recarregue a página.')
                payload = request.get_json(silent=True) or {}
                return jsonify(stock_request('external-stock', 'POST', payload))
            from urllib.parse import urlencode
            query = urlencode({key: request.args[key] for key in ('sku', 'page') if request.args.get(key)})
            return jsonify(stock_request('external-stock' + ('?' + query if query else ''), 'GET'))
        except PermissionError as exc:
            return jsonify(ok=False, error=str(exc)), 403
        except (ValueError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except Exception:
            current_app.logger.exception('Falha ao consultar estoque externo')
            return jsonify(ok=False, error='Estoque externo indisponível. Tente novamente.'), 503

    app.register_blueprint(bp)
