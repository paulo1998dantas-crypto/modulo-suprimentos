import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


REGISTRATIONS_TABLE = "cadastro_registros"
PAGE_SIZE = 1000
CACHE_TTL_SECONDS = 10

_cache = {
    "loaded_at": 0.0,
    "produtos": None,
    "error": "",
}


class SupabaseCatalogError(RuntimeError):
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
    mode = _clean(os.environ.get("SUPRIMENTOS_CATALOG_MODE")).lower()
    if mode in {"local", "json", "arquivo"}:
        return False
    if mode in {"supabase", "database", "banco"}:
        return True
    return bool(_supabase_url() and _service_key())


def configured():
    return bool(_supabase_url() and _service_key())


def status():
    return {
        "enabled": enabled(),
        "configured": configured(),
        "url": _supabase_url(),
        "table": REGISTRATIONS_TABLE,
        "cached": bool(_cache.get("produtos")),
        "error": _cache.get("error") or "",
    }


def _headers():
    key = _service_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _request_rows(offset):
    if not configured():
        raise SupabaseCatalogError("Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")
    query = urllib.parse.urlencode(
        [
            (
                "select",
                "sku,category_label,descricao_primaria,descricao_secundaria,sufixo,unidade,ativo,field_values,form_values,updated_at",
            ),
            ("order", "sku.asc"),
            ("limit", str(PAGE_SIZE)),
            ("offset", str(offset)),
        ]
    )
    url = f"{_supabase_url()}/rest/v1/{REGISTRATIONS_TABLE}?{query}"
    request = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else []
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SupabaseCatalogError(f"Erro Supabase {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SupabaseCatalogError(f"Nao foi possivel conectar ao Supabase: {exc}") from exc


def registration_by_sku(sku):
    """Return the authoritative Cadastro fields for a specific active SKU."""
    normalized = _clean(sku).upper()
    if not normalized:
        raise SupabaseCatalogError("Informe o SKU.")
    if not configured():
        raise SupabaseCatalogError("Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")
    query = urllib.parse.urlencode(
        [
            ("select", "sku,category_label,descricao_primaria,descricao_secundaria,sufixo,unidade,field_values,form_values,field_codes,updated_at"),
            ("sku", f"eq.{normalized}"),
            ("ativo", "is.true"),
            ("limit", "1"),
        ]
    )
    request = urllib.request.Request(
        f"{_supabase_url()}/rest/v1/{REGISTRATIONS_TABLE}?{query}",
        headers=_headers(),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            rows = json.loads(response.read().decode("utf-8") or "[]")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SupabaseCatalogError(f"Erro Supabase {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SupabaseCatalogError(f"Nao foi possivel conectar ao Supabase: {exc}") from exc
    if not rows:
        raise SupabaseCatalogError("SKU ativo nao encontrado no Cadastro.")
    row = rows[0]
    values = row.get("field_values") if isinstance(row.get("field_values"), dict) else {}
    return {
        "sku": _clean(row.get("sku")),
        "descricao": _clean(row.get("descricao_primaria")),
        "descricao_secundaria": _clean(row.get("descricao_secundaria")),
        "categoria": _clean(row.get("category_label")),
        "unidade": _clean(row.get("unidade")),
        "field_values": values,
        "updated_at": row.get("updated_at"),
    }


def _all_rows():
    rows = []
    offset = 0
    while True:
        page = _request_rows(offset)
        if not page:
            break
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def _group_from_sku(sku):
    prefix = _clean(sku)[:2]
    return {
        "10": "10 - INSUMO",
        "20": "20 - PRODUTO EM PROCESSO",
        "30": "30 - CONJUNTO / KIT",
        "40": "40 - TRANSFORMACAO",
        "50": "50 - MRO",
    }.get(prefix, "")


def _first_value(values, keys):
    if not isinstance(values, dict):
        return ""
    for key in keys:
        value = _clean(values.get(key))
        if value:
            return value
    lowered = {str(k).lower(): _clean(v) for k, v in values.items()}
    for key in keys:
        value = lowered.get(key.lower(), "")
        if value:
            return value
    return ""


def row_to_produto(row):
    if row.get("ativo") is False:
        return "", {}
    sku = _clean(row.get("sku"))
    values = row.get("field_values") if isinstance(row.get("field_values"), dict) else {}
    descricao_primaria = _clean(row.get("descricao_primaria"))
    descricao_secundaria = _clean(row.get("descricao_secundaria"))
    sufixo = _clean(row.get("sufixo"))
    unidade = _clean(row.get("unidade")) or _first_value(
        values,
        [
            "unidade",
            "unidade_comercial",
            "unidade_interna",
            "un_medi_comercial",
            "un_medi_interna",
            "un_medida",
            "un",
        ],
    )
    fornecedor = _first_value(values, ["fornecedor", "cod_fornecedor"])
    status_value = "ATIVO" if row.get("ativo", True) else "INATIVO"
    produto = {
        "descricao": descricao_primaria,
        "unidade": unidade,
        "grupo": _group_from_sku(sku),
        "categoria": _clean(row.get("category_label")),
        "processo_conjunto": _first_value(values, ["processo_conjunto", "processo", "processo_vinculado"]),
        "fornecedor": fornecedor,
        "campos_extras": {
            "descricao_secundaria": descricao_secundaria,
            "sufixo": sufixo,
            "status": status_value or "ATIVO",
            "origem": "supabase",
        },
    }
    if fornecedor:
        produto["campos_extras"]["fornecedor"] = fornecedor
    return sku, produto


def carregar_produtos(force=False):
    if not enabled():
        raise SupabaseCatalogError("Catalogo Supabase desativado.")
    now = time.time()
    cached = _cache.get("produtos")
    if not force and cached is not None and now - float(_cache.get("loaded_at") or 0) < CACHE_TTL_SECONDS:
        return cached
    produtos = {}
    for row in _all_rows():
        sku, produto = row_to_produto(row)
        if sku:
            produtos[sku] = produto
    _cache["produtos"] = produtos
    _cache["loaded_at"] = now
    _cache["error"] = ""
    return produtos


def clear_cache():
    _cache["loaded_at"] = 0.0
    _cache["produtos"] = None
    _cache["error"] = ""
