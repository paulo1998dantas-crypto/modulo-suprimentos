import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from werkzeug.security import check_password_hash

import supabase_catalog


PAGE_SIZE = 1000
CACHE_TTL_SECONDS = 10

PESSOAS_TABLE = "suprimentos_pessoas"
PROCESSOS_TABLE = "suprimentos_processos"
REGRAS_TABLE = "suprimentos_regras_popup_item"
RELACOES_TABLE = "suprimentos_relacoes_processo_item"
BOM_COMPONENTS_TABLE = "cadastro_bom_componentes"
USERS_TABLE = "users"
DOCUMENTOS_TABLE = "suprimentos_documentos"
ROLES_TABLE = "erp_roles"
PERMISSIONS_TABLE = "erp_permissions"
ROLE_PERMISSIONS_TABLE = "erp_role_permissions"
USER_ROLES_TABLE = "erp_user_roles"
USER_PERMISSION_OVERRIDES_TABLE = "erp_user_permission_overrides"

_cache = {}


class SupabaseDataError(RuntimeError):
    pass


ROLE_PERMISSION_FALLBACKS = {
    "OPERADOR": {
        "estoque.inspection.receive",
        "suprimentos.dashboard.view",
        "suprimentos.purchase.view",
        "suprimentos.work_order.view",
    },
    "COMPRADOR": {
        "suprimentos.dashboard.view",
        "suprimentos.purchase.view",
        "suprimentos.purchase.create",
        "suprimentos.purchase.edit",
        "suprimentos.purchase.cancel",
        "suprimentos.purchase.export",
        "suprimentos.work_order.view",
    },
    "FINANCEIRO": {
        "suprimentos.dashboard.view",
        "suprimentos.purchase.view",
        "suprimentos.purchase.financial_close",
        "suprimentos.purchase.export",
        "suprimentos.work_order.view",
    },
    "PCP": {
        "estoque.inspection.receive",
        "suprimentos.dashboard.view",
        "suprimentos.purchase.view",
        "suprimentos.purchase.create",
        "suprimentos.purchase.edit",
        "suprimentos.purchase.cancel",
        "suprimentos.purchase.technical_close",
        "suprimentos.purchase.financial_close",
        "suprimentos.purchase.export",
        "suprimentos.purchase.bulk_manage",
        "suprimentos.work_order.view",
        "suprimentos.work_order.manage",
        "suprimentos.work_order.schedule",
        "suprimentos.work_order.technical_close",
        "suprimentos.work_order.import",
    },
    "ENGENHARIA": {
        "estoque.inspection.receive",
        "suprimentos.dashboard.view",
        "suprimentos.purchase.view",
        "suprimentos.purchase.create",
        "suprimentos.purchase.edit",
        "suprimentos.purchase.cancel",
        "suprimentos.purchase.technical_close",
        "suprimentos.purchase.financial_close",
        "suprimentos.purchase.export",
        "suprimentos.purchase.bulk_manage",
        "suprimentos.work_order.view",
        "suprimentos.work_order.manage",
        "suprimentos.work_order.schedule",
        "suprimentos.work_order.technical_close",
        "suprimentos.work_order.import",
        "cadastro.access",
    },
    "ADMIN": {"*"},
}


def _clean(value):
    return "" if value is None else str(value).strip()


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return _clean(value).lower() not in {"0", "false", "nao", "não", "no", "n", "off"}


def shared_rbac_enabled():
    return _env_bool("ERP_SHARED_RBAC_ENABLED", default=False)


def _role_codes(value):
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        text = _clean(value).replace(";", ",")
        values = text.split(",") if text else []
    result = []
    for item in values:
        role = _clean(item).upper().replace(" ", "_")
        if not role:
            continue
        if role == "ADM":
            role = "ADMIN"
        if role not in result:
            result.append(role)
    return result


def _supabase_url():
    return (
        _clean(os.environ.get("SUPABASE_URL"))
        or _clean(os.environ.get("SUPRIMENTOS_SUPABASE_URL"))
        or _clean(os.environ.get("CADASTRO_SUPABASE_URL"))
    ).rstrip("/")


def _service_key():
    return (
        _clean(os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
        or _clean(os.environ.get("SUPRIMENTOS_SUPABASE_SERVICE_ROLE_KEY"))
        or _clean(os.environ.get("CADASTRO_SUPABASE_SERVICE_ROLE_KEY"))
    )


def enabled():
    mode = _clean(os.environ.get("SUPRIMENTOS_DATA_MODE")).lower()
    if mode in {"local", "json", "arquivo"}:
        return False
    if mode in {"supabase", "database", "banco"}:
        return True
    catalog_mode = _clean(os.environ.get("SUPRIMENTOS_CATALOG_MODE")).lower()
    if catalog_mode in {"supabase", "database", "banco"}:
        return True
    return bool(_supabase_url() and _service_key())


def configured():
    return bool(_supabase_url() and _service_key())


def status():
    return {
        "enabled": enabled(),
        "configured": configured(),
        "url": _supabase_url(),
        "tables": [
            PESSOAS_TABLE,
            PROCESSOS_TABLE,
            REGRAS_TABLE,
            RELACOES_TABLE,
            BOM_COMPONENTS_TABLE,
            DOCUMENTOS_TABLE,
            USERS_TABLE,
            ROLES_TABLE,
            PERMISSIONS_TABLE,
            ROLE_PERMISSIONS_TABLE,
            USER_ROLES_TABLE,
            USER_PERMISSION_OVERRIDES_TABLE,
        ],
        "shared_rbac_enabled": shared_rbac_enabled(),
    }


def clear_cache():
    _cache.clear()


def _headers(prefer=""):
    key = _service_key()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _request(method, table, query=None, payload=None, prefer=""):
    if not configured():
        raise SupabaseDataError("Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")
    query_string = urllib.parse.urlencode(query or [])
    url = f"{_supabase_url()}/rest/v1/{table}"
    if query_string:
        url = f"{url}?{query_string}"
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_headers(prefer), method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SupabaseDataError(f"Erro Supabase {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SupabaseDataError(f"Nao foi possivel conectar ao Supabase: {exc}") from exc


def _all_rows(table, select="*", order=None, extra_query=None, cache_key=None, force=False):
    now = time.time()
    if cache_key and not force:
        cached = _cache.get(cache_key)
        if cached and now - cached["loaded_at"] < CACHE_TTL_SECONDS:
            return cached["rows"]
    rows = []
    offset = 0
    while True:
        query = [("select", select), ("limit", str(PAGE_SIZE)), ("offset", str(offset))]
        if order:
            query.append(("order", order))
        if extra_query:
            query.extend(extra_query)
        page = _request("GET", table, query=query) or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    if cache_key:
        _cache[cache_key] = {"loaded_at": now, "rows": rows}
    return rows


def _bool(value):
    texto = _clean(value).lower()
    return texto in {"1", "sim", "s", "true", "verdadeiro", "x", "yes"}


def _blank_dash(value):
    texto = _clean(value)
    return "" if texto in {"---", "-", "None", "none", "NULL", "null"} else texto


def _numeric(value):
    texto = _blank_dash(value)
    if isinstance(value, str) and "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    if texto == "":
        return 0
    try:
        return float(texto)
    except Exception:
        return 0


def _date_or_none(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    texto = _blank_dash(value)
    return texto or None


def _search_text(*parts):
    return " ".join(_clean(part) for part in parts if _clean(part))


def _key_from_pessoa(pessoa):
    return (
        _clean(pessoa.get("identificador"))
        or _clean(pessoa.get("cnpj_cpf"))
        or _clean(pessoa.get("nome_fantasia"))
        or _clean(pessoa.get("razao_social"))
    )


def normalizar_pessoa(pessoa):
    row = dict(pessoa or {})
    for key, value in list(row.items()):
        if isinstance(value, datetime):
            row[key] = value.isoformat()
        elif isinstance(value, str):
            row[key] = _blank_dash(value)
    row["identificador"] = _key_from_pessoa(row)
    row["pessoa_fisica"] = _bool(row.get("pessoa_fisica"))
    row["cliente"] = _bool(row.get("cliente"))
    row["fornecedor"] = _bool(row.get("fornecedor"))
    row["colaborador"] = _bool(row.get("colaborador"))
    row["transportadora"] = _bool(row.get("transportadora"))
    for key in ("limite_credito", "periodicidade_venda_compra_dias", "valor_minimo_compra"):
        row[key] = _numeric(row.get(key))
    row["data_nascimento_fundacao"] = _date_or_none(row.get("data_nascimento_fundacao"))
    row["search_text"] = _search_text(
        row.get("nome_fantasia"),
        row.get("razao_social"),
        row.get("cnpj_cpf"),
        row.get("email"),
        row.get("telefone"),
        row.get("cidade"),
        row.get("uf"),
        row.get("identificador"),
    )
    row.setdefault("payload", {})
    return row


def pessoa_from_legacy(data, tipo):
    nome = _clean(data.get("fornecedor") or data.get("cliente") or data.get("nome_fantasia"))
    cnpj = _clean(data.get("cnpj") or data.get("cnpj_cpf"))
    endereco = _clean(data.get("endereco") or data.get("logradouro"))
    pessoa = {
        "identificador": cnpj or nome,
        "nome_fantasia": nome,
        "razao_social": _clean(data.get("razao_social")) or nome,
        "cnpj_cpf": cnpj,
        "email": _clean(data.get("email")),
        "telefone": _clean(data.get("telefone")),
        "logradouro": endereco,
        "bairro": _clean(data.get("bairro")),
        "cidade": _clean(data.get("cidade")),
        "uf": _clean(data.get("uf")),
        "cep": _clean(data.get("cep")),
        "cliente": tipo == "cliente" or bool(data.get("cliente_flag")),
        "fornecedor": tipo == "fornecedor" or bool(data.get("fornecedor_flag")),
        "payload": data,
    }
    return normalizar_pessoa(pessoa)


def salvar_pessoas(pessoas):
    rows = [normalizar_pessoa(pessoa) for pessoa in pessoas if _key_from_pessoa(pessoa)]
    if not rows:
        return 0
    _request(
        "POST",
        PESSOAS_TABLE,
        query=[("on_conflict", "identificador")],
        payload=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    clear_cache()
    return len(rows)


def salvar_pessoas_legacy(registros, tipo):
    pessoas = [pessoa_from_legacy(data, tipo) for data in (registros or {}).values()]
    return salvar_pessoas(pessoas)


def _pessoa_to_legacy(row, tipo):
    nome = _clean(row.get("nome_fantasia")) or _clean(row.get("razao_social")) or _clean(row.get("cnpj_cpf"))
    legacy = {
        "razao_social": _clean(row.get("razao_social")),
        "cnpj": _clean(row.get("cnpj_cpf")),
        "email": _clean(row.get("email")),
        "telefone": _clean(row.get("telefone") or row.get("celular") or row.get("whatsapp")),
        "endereco": _search_text(row.get("logradouro"), row.get("logradouro_numero"), row.get("complemento")),
        "bairro": _clean(row.get("bairro")),
        "cidade": _clean(row.get("cidade")),
        "uf": _clean(row.get("uf")),
        "cep": _clean(row.get("cep")),
    }
    if tipo == "cliente":
        legacy["cliente"] = nome
    else:
        legacy["fornecedor"] = nome
    return legacy


def carregar_pessoas(tipo=None, force=False):
    rows = _all_rows(
        PESSOAS_TABLE,
        select="*",
        order="nome_fantasia.asc",
        cache_key=f"pessoas:{tipo or 'todos'}",
        force=force,
    )
    result = {}
    for row in rows:
        if tipo and not bool(row.get(tipo)):
            continue
        key = _clean(row.get("cnpj_cpf")) or _clean(row.get("nome_fantasia")) or _clean(row.get("razao_social")) or _clean(row.get("identificador"))
        if key:
            result[key] = _pessoa_to_legacy(row, tipo or "fornecedor")
    return result


def carregar_bom_componentes(force=False):
    rows = _all_rows(
        BOM_COMPONENTS_TABLE,
        select="parent_sku,component_sku,component_descricao,unidade,quantidade,ordem",
        order="parent_sku.asc,ordem.asc",
        cache_key="bom_componentes",
        force=force,
    )
    try:
        catalogo = supabase_catalog.carregar_produtos(force=force) if supabase_catalog.enabled() else {}
    except Exception:
        catalogo = {}
    componentes = {}
    for row in rows:
        parent = _clean(row.get("parent_sku"))
        component = _clean(row.get("component_sku"))
        if not parent or not component:
            continue
        cadastro_item = catalogo.get(component) or {}
        componentes.setdefault(parent, []).append(
            {
                "codigo": component,
                "descricao": _clean(cadastro_item.get("descricao")) or _clean(row.get("component_descricao")),
                "unidade": _clean(cadastro_item.get("unidade")) or _clean(row.get("unidade")),
                "quantidade": _clean(row.get("quantidade")),
            }
        )
    return componentes


def carregar_processos(force=False):
    rows = _all_rows(
        PROCESSOS_TABLE,
        select="conjunto,processo,ordem,atividade,responsavel",
        order="conjunto.asc,processo.asc,ordem.asc",
        cache_key="processos",
        force=force,
    )
    processos = {}
    for row in rows:
        conjunto = _clean(row.get("conjunto")) or "PADRAO"
        processo = _clean(row.get("processo"))
        atividade = _clean(row.get("atividade"))
        if not processo or not atividade:
            continue
        processos.setdefault(conjunto, {}).setdefault(processo, []).append(
            {"atividade": atividade, "responsavel": _clean(row.get("responsavel"))}
        )
    return processos


def salvar_processos(processos):
    rows = []
    for conjunto, por_processo in (processos or {}).items():
        conjunto = _clean(conjunto) or "PADRAO"
        for processo, linhas in (por_processo or {}).items():
            processo = _clean(processo)
            for ordem, linha in enumerate(linhas or [], 1):
                atividade = _clean((linha or {}).get("atividade"))
                if not processo or not atividade:
                    continue
                rows.append(
                    {
                        "conjunto": conjunto,
                        "processo": processo,
                        "ordem": ordem,
                        "atividade": atividade,
                        "responsavel": _clean((linha or {}).get("responsavel")),
                        "search_text": _search_text(conjunto, processo, atividade, (linha or {}).get("responsavel")),
                    }
                )
    _request("DELETE", PROCESSOS_TABLE, query=[("conjunto", "neq.__never_delete__")])
    if rows:
        _request("POST", PROCESSOS_TABLE, payload=rows, prefer="return=minimal")
    clear_cache()
    return len(rows)


def carregar_relacoes(force=False):
    rows = _all_rows(
        RELACOES_TABLE,
        select="item_codigo,processos",
        order="item_codigo.asc",
        cache_key="relacoes_processo_item",
        force=force,
    )
    relacoes = {}
    for row in rows:
        codigo = _clean(row.get("item_codigo"))
        processos = row.get("processos") or []
        if codigo and isinstance(processos, list):
            relacoes[codigo] = [_clean(processo) for processo in processos if _clean(processo)]
    return relacoes


def salvar_relacoes(relacoes):
    rows = []
    for codigo, processos in (relacoes or {}).items():
        codigo = _clean(codigo)
        processos = [_clean(processo) for processo in (processos or []) if _clean(processo)]
        if codigo and processos:
            rows.append({"item_codigo": codigo, "processos": list(dict.fromkeys(processos))})
    _request("DELETE", RELACOES_TABLE, query=[("item_codigo", "neq.__never_delete__")])
    if rows:
        _request("POST", RELACOES_TABLE, payload=rows, prefer="return=minimal")
    clear_cache()
    return len(rows)


def carregar_regras(force=False):
    rows = _all_rows(
        REGRAS_TABLE,
        select="rule_id,gatilho,opcoes,quantidade,quantidade_editavel",
        order="rule_id.asc",
        cache_key="regras_popup_item",
        force=force,
    )
    regras = []
    for row in rows:
        gatilho = _clean(row.get("gatilho"))
        opcoes = [_clean(codigo) for codigo in (row.get("opcoes") or []) if _clean(codigo)]
        if not gatilho or not opcoes:
            continue
        regras.append(
            {
                "id": _clean(row.get("rule_id")),
                "gatilho": gatilho,
                "opcoes": opcoes,
                "quantidade": float(row.get("quantidade") or 1),
                "quantidade_editavel": bool(row.get("quantidade_editavel")),
            }
        )
    return regras


def salvar_regras(regras):
    rows = []
    for regra in regras or []:
        rule_id = _clean(regra.get("id"))
        gatilho = _clean(regra.get("gatilho"))
        opcoes = [_clean(codigo) for codigo in (regra.get("opcoes") or []) if _clean(codigo)]
        if not rule_id or not gatilho or not opcoes:
            continue
        rows.append(
            {
                "rule_id": rule_id,
                "gatilho": gatilho,
                "opcoes": opcoes,
                "quantidade": regra.get("quantidade") or 1,
                "quantidade_editavel": bool(regra.get("quantidade_editavel")),
            }
        )
    _request("DELETE", REGRAS_TABLE, query=[("rule_id", "neq.__never_delete__")])
    if rows:
        _request("POST", REGRAS_TABLE, payload=rows, prefer="return=minimal")
    clear_cache()
    return len(rows)


def normalizar_documento(documento):
    source = dict(documento or {})
    row = {
        key: source.get(key)
        for key in (
            "tipo",
            "numero",
            "data_criacao",
            "dados",
            "itens",
            "processos",
            "componentes",
            "composicao",
            "status",
            "submit_token",
            "criado_por",
            "atualizado_por",
            "erp_purchase_order_id",
            "erp_work_order_id",
        )
        if key in source
    }
    row["tipo"] = _clean(row.get("tipo")).lower()
    row["numero"] = _clean(row.get("numero"))
    row["data_criacao"] = _date_or_none(row.get("data_criacao")) or datetime.now().date().isoformat()
    row["status"] = _clean(row.get("status")).lower() or "emitido"
    row["submit_token"] = _clean(row.get("submit_token")) or None
    row["criado_por"] = _clean(row.get("criado_por"))
    row["atualizado_por"] = _clean(row.get("atualizado_por"))
    row["erp_purchase_order_id"] = _clean(row.get("erp_purchase_order_id")) or None
    row["erp_work_order_id"] = _clean(row.get("erp_work_order_id")) or None
    for key in ("dados", "itens", "processos", "componentes", "composicao"):
        value = row.get(key)
        if value is None:
            value = {} if key in {"dados", "processos", "componentes"} else []
        row[key] = value
    dados = row.get("dados") if isinstance(row.get("dados"), dict) else {}
    itens = row.get("itens") if isinstance(row.get("itens"), list) else []
    row["valor_total"] = _numeric(dados.get("total_pedido"))
    row["itens_count"] = len(itens)
    row["search_text"] = _search_text(
        row.get("tipo"),
        row.get("numero"),
        dados.get("fornecedor"),
        dados.get("cliente"),
        dados.get("razao_social"),
        dados.get("chassis"),
        dados.get("mmv"),
        dados.get("municipio"),
    )
    return row


def documento_to_legacy(row):
    return {
        "id": row.get("id"),
        "created_at": _clean(row.get("created_at")),
        "tipo": _clean(row.get("tipo")),
        "numero": _clean(row.get("numero")),
        "data_criacao": _clean(row.get("data_criacao")),
        "status": _clean(row.get("status")) or "emitido",
        "submit_token": _clean(row.get("submit_token")),
        "criado_por": _clean(row.get("criado_por")),
        "atualizado_por": _clean(row.get("atualizado_por")),
        "erp_purchase_order_id": _clean(row.get("erp_purchase_order_id")),
        "erp_work_order_id": _clean(row.get("erp_work_order_id")),
        "updated_at": _clean(row.get("updated_at")),
        "dados": row.get("dados") or {},
        "itens": row.get("itens") or [],
        "processos": row.get("processos") or {},
        "componentes": row.get("componentes") or {},
        "composicao": row.get("composicao") or [],
    }


def salvar_documento(documento):
    row = normalizar_documento(documento)
    if not row.get("tipo") or not row.get("numero"):
        return False
    query = []
    prefer = "return=representation"
    if row.get("submit_token"):
        token_original = row["submit_token"]
        existentes = _request(
            "GET",
            DOCUMENTOS_TABLE,
            query=[
                ("select", "id,tipo,numero,submit_token"),
                ("submit_token", f"eq.{token_original}"),
                ("limit", "1"),
            ],
        ) or []
        if existentes:
            existente = existentes[0]
            mesma_identidade = (
                _clean(existente.get("tipo")).lower() == row["tipo"]
                and _clean(existente.get("numero")) == row["numero"]
            )
            if not mesma_identidade:
                row["submit_token"] = (
                    f"{token_original}::{row['tipo']}::{row['numero']}"
                )
        query.append(("on_conflict", "submit_token"))
        prefer = "resolution=merge-duplicates,return=representation"
    rows = _request("POST", DOCUMENTOS_TABLE, query=query, payload=row, prefer=prefer) or []
    clear_cache()
    return documento_to_legacy(rows[0]) if rows else True


def salvar_documentos(documentos):
    rows_payload = [normalizar_documento(documento) for documento in (documentos or [])]
    rows_payload = [row for row in rows_payload if row.get("tipo") and row.get("numero")]
    if not rows_payload:
        return []
    rows = _request(
        "POST",
        DOCUMENTOS_TABLE,
        payload=rows_payload,
        prefer="return=representation",
    ) or []
    clear_cache()
    return [documento_to_legacy(row) for row in rows]


def obter_documento(documento_id):
    rows = _request(
        "GET",
        DOCUMENTOS_TABLE,
        query=[
            ("select", "id,created_at,updated_at,tipo,numero,data_criacao,status,submit_token,criado_por,atualizado_por,erp_purchase_order_id,erp_work_order_id,dados,itens,processos,componentes,composicao"),
            ("id", f"eq.{documento_id}"),
            ("limit", "1"),
        ],
    ) or []
    return documento_to_legacy(rows[0]) if rows else None


def obter_documento_por_submit_token(submit_token):
    token = _clean(submit_token)
    if not token:
        return None
    rows = _request(
        "GET",
        DOCUMENTOS_TABLE,
        query=[
            ("select", "id,tipo,numero,submit_token"),
            ("submit_token", f"eq.{token}"),
            ("limit", "1"),
        ],
    ) or []
    return rows[0] if rows else None


def atualizar_documento(documento_id, documento):
    row = normalizar_documento(documento)
    if not row.get("tipo") or not row.get("numero"):
        return False
    _request(
        "PATCH",
        DOCUMENTOS_TABLE,
        query=[("id", f"eq.{documento_id}")],
        payload=row,
        prefer="return=minimal",
    )
    clear_cache()
    return True


def excluir_documento(documento_id):
    _request(
        "DELETE",
        DOCUMENTOS_TABLE,
        query=[("id", f"eq.{documento_id}")],
        prefer="return=minimal",
    )
    clear_cache()
    return True


def excluir_documentos(documento_ids):
    ids = [str(documento_id).strip() for documento_id in (documento_ids or []) if str(documento_id).strip()]
    if not ids:
        return 0
    filtro = ",".join(ids)
    _request(
        "DELETE",
        DOCUMENTOS_TABLE,
        query=[("id", f"in.({filtro})")],
        prefer="return=minimal",
    )
    clear_cache()
    return len(ids)


def carregar_documentos(force=False, limit=None):
    rows = _all_rows(
        DOCUMENTOS_TABLE,
        select="id,created_at,updated_at,tipo,numero,data_criacao,status,submit_token,criado_por,atualizado_por,erp_purchase_order_id,erp_work_order_id,dados,itens,processos,componentes,composicao",
        order="data_criacao.desc,created_at.desc",
        cache_key="documentos",
        force=force,
    )
    if limit is not None:
        rows = rows[:max(0, int(limit))]
    return [documento_to_legacy(row) for row in rows]


def proximo_numero_documento(tipo):
    tipo = _clean(tipo).lower()
    if tipo not in {"oc", "os"}:
        raise ValueError("Tipo de documento invalido.")
    if not configured():
        raise SupabaseDataError("Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")
    url = f"{_supabase_url()}/rest/v1/rpc/suprimentos_proximo_numero"
    payload = json.dumps({"p_tipo": tipo}, ensure_ascii=False).encode("utf-8")
    rpc_request = urllib.request.Request(url, data=payload, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(rpc_request, timeout=30) as response:
            body = response.read().decode("utf-8")
            value = json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SupabaseDataError(f"Erro Supabase {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SupabaseDataError(f"Nao foi possivel conectar ao Supabase: {exc}") from exc
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SupabaseDataError("O contador do Supabase retornou um valor invalido.") from exc


def _load_user_record(*, user_id=None, username=None, include_password=False):
    fields = ["id", "username", "role", "active", "auth_version"]
    if include_password:
        fields.append("password_hash")
    filters = []
    if user_id is not None:
        filters.append(("id", f"eq.{user_id}"))
    elif username:
        filters.append(("username", f"eq.{_clean(username)}"))
    else:
        return None
    try:
        rows = _request(
            "GET",
            USERS_TABLE,
            query=[("select", ",".join(fields)), *filters, ("limit", "1")],
        ) or []
    except SupabaseDataError as exc:
        # Compatibilidade durante a janela entre o deploy do código e a
        # migration aditiva que cria users.auth_version.
        if shared_rbac_enabled() or "auth_version" not in str(exc):
            raise
        fields.remove("auth_version")
        rows = _request(
            "GET",
            USERS_TABLE,
            query=[("select", ",".join(fields)), *filters, ("limit", "1")],
        ) or []
    return rows[0] if rows else None


def _fallback_permissions(roles):
    permissions = set()
    for role in roles:
        permissions.update(ROLE_PERMISSION_FALLBACKS.get(role, set()))
    return permissions


def _load_active_role_codes(role_codes):
    candidates = _role_codes(role_codes)
    if not candidates:
        return []
    role_filter = ",".join(candidates)
    rows = _request(
        "GET",
        ROLES_TABLE,
        query=[
            ("select", "code"),
            ("code", f"in.({role_filter})"),
            ("active", "eq.true"),
        ],
    ) or []
    active = set(_role_codes([
        row.get("code") for row in rows
        if row.get("code")
    ]))
    return [role for role in candidates if role in active]


def load_user_authorization(user_id, force=False):
    cache_key = f"user_authorization:{user_id}"
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and not force and now - cached["loaded_at"] < CACHE_TTL_SECONDS:
        return dict(cached["user"])

    user = _load_user_record(user_id=user_id)
    if not user or not bool(user.get("active", True)):
        return None

    legacy_roles = _role_codes(user.get("role"))
    roles = list(legacy_roles)
    permissions = set()
    overrides = {}
    rbac_source = "legacy"

    if shared_rbac_enabled():
        try:
            role_rows = _request(
                "GET",
                USER_ROLES_TABLE,
                query=[
                    ("select", "role_code"),
                    ("user_id", f"eq.{user_id}"),
                    ("order", "role_code.asc"),
                ],
            ) or []
            assigned_roles = _role_codes([
                row.get("role_code") for row in role_rows
                if row.get("role_code")
            ])
            # Shared mode never falls back to users.role. A missing or
            # intentionally removed membership must remove access.
            roles = _load_active_role_codes(assigned_roles)
            rbac_source = "shared"

            if roles:
                role_filter = ",".join(roles)
                permission_rows = _request(
                    "GET",
                    ROLE_PERMISSIONS_TABLE,
                    query=[
                        ("select", "permission_code"),
                        ("role_code", f"in.({role_filter})"),
                    ],
                ) or []
                permissions.update(
                    _clean(row.get("permission_code"))
                    for row in permission_rows
                    if _clean(row.get("permission_code"))
                )

            override_rows = _request(
                "GET",
                USER_PERMISSION_OVERRIDES_TABLE,
                query=[
                    ("select", "permission_code,allowed"),
                    ("user_id", f"eq.{user_id}"),
                ],
            ) or []
            overrides = {
                _clean(row.get("permission_code")): bool(row.get("allowed"))
                for row in override_rows
                if _clean(row.get("permission_code"))
            }
        except SupabaseDataError:
            # Shared mode is intentionally fail-closed. Keep the flag disabled
            # until the additive schema has been migrated and reconciled.
            raise

    if not permissions and rbac_source == "legacy":
        permissions.update(_fallback_permissions(roles))
    for permission, allowed in overrides.items():
        if allowed:
            permissions.add(permission)
        else:
            permissions.discard(permission)
    if "ADMIN" in roles:
        # O contrato compartilhado trata ADMIN como superperfil também no
        # backend, independentemente de uma nova permissão ainda não ter sido
        # copiada para erp_role_permissions.
        permissions.add("*")

    result = {
        "id": user.get("id"),
        "username": _clean(user.get("username")),
        "role": _clean(user.get("role")),
        "roles": roles,
        "permissions": sorted(permissions),
        "auth_version": int(user.get("auth_version") or 0),
        "rbac_source": rbac_source,
    }
    _cache[cache_key] = {"loaded_at": now, "user": result}
    return dict(result)


def shared_rbac_schema_status():
    """Probe the REST-visible RBAC contract without reading operational data."""
    if not shared_rbac_enabled():
        return {"enabled": False, "ready": False, "error": ""}
    probes = (
        (USERS_TABLE, "auth_version"),
        (ROLES_TABLE, "code,active"),
        (ROLE_PERMISSIONS_TABLE, "role_code,permission_code"),
        (USER_ROLES_TABLE, "user_id,role_code"),
        (USER_PERMISSION_OVERRIDES_TABLE, "user_id,permission_code,allowed"),
    )
    try:
        for table_name, fields in probes:
            _request(
                "GET",
                table_name,
                query=[("select", fields), ("limit", "1")],
            )
    except SupabaseDataError as exc:
        return {"enabled": True, "ready": False, "error": str(exc)}
    return {"enabled": True, "ready": True, "error": ""}


def revalidate_session_user(session_user):
    """Invalidate signed sessions immediately after any auth_version change."""
    if not isinstance(session_user, dict) or session_user.get("id") is None:
        return None
    user = _load_user_record(user_id=session_user.get("id"))
    if not user or not bool(user.get("active", True)):
        return None
    try:
        session_version = int(session_user.get("auth_version"))
    except (TypeError, ValueError):
        return None
    current_version = int(user.get("auth_version") or 0)
    if session_version != current_version:
        return None
    if (
        _clean(session_user.get("username")) != _clean(user.get("username"))
        or _clean(session_user.get("role")) != _clean(user.get("role"))
    ):
        return None
    # Re-read the role matrix on every authenticated request. Membership and
    # user changes also bump auth_version, while matrix-only changes become
    # effective immediately without waiting for the short cache TTL.
    return load_user_authorization(user.get("id"), force=True)


def verify_user(username, password):
    username = _clean(username)
    if not username or not password:
        return None
    user = _load_user_record(username=username, include_password=True)
    if not user or not bool(user.get("active", True)):
        return None
    password_hash = _clean(user.get("password_hash"))
    if not password_hash or not check_password_hash(password_hash, password):
        return None
    return load_user_authorization(user.get("id"), force=True)
