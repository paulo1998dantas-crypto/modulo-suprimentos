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

_cache = {}


class SupabaseDataError(RuntimeError):
    pass


def _clean(value):
    return "" if value is None else str(value).strip()


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
        ],
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
                "unidade": _clean(row.get("unidade")),
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
    row = dict(documento or {})
    row["tipo"] = _clean(row.get("tipo")).lower()
    row["numero"] = _clean(row.get("numero"))
    row["data_criacao"] = _date_or_none(row.get("data_criacao")) or datetime.now().date().isoformat()
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
        "tipo": _clean(row.get("tipo")),
        "numero": _clean(row.get("numero")),
        "data_criacao": _clean(row.get("data_criacao")),
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
    _request("POST", DOCUMENTOS_TABLE, payload=row, prefer="return=minimal")
    clear_cache()
    return True


def carregar_documentos(force=False, limit=1000):
    rows = _all_rows(
        DOCUMENTOS_TABLE,
        select="tipo,numero,data_criacao,dados,itens,processos,componentes,composicao",
        order="data_criacao.desc,created_at.desc",
        cache_key="documentos",
        force=force,
    )
    return [documento_to_legacy(row) for row in rows[:limit]]


def verify_user(username, password):
    username = _clean(username)
    if not username or not password:
        return None
    rows = _request(
        "GET",
        USERS_TABLE,
        query=[
            ("select", "id,username,password_hash,role,active"),
            ("username", f"eq.{username}"),
            ("limit", "1"),
        ],
    ) or []
    if not rows:
        return None
    user = rows[0]
    if not bool(user.get("active", True)):
        return None
    password_hash = _clean(user.get("password_hash"))
    if not password_hash or not check_password_hash(password_hash, password):
        return None
    return {
        "id": user.get("id"),
        "username": _clean(user.get("username")),
        "role": _clean(user.get("role")),
    }
