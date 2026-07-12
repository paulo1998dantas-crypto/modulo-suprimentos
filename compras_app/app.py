from flask import Flask, render_template, request, send_file, redirect, url_for, after_this_request
import re
import json
import io
import os
import logging
import tempfile
import sys
import shutil
import zipfile
import subprocess
import unicodedata
from datetime import date, timedelta, datetime
import tempfile
import zipfile
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from werkzeug.datastructures import FileStorage
from openpyxl import load_workbook
from docx import Document

from config import (
    TEMPLATES_DIR,
    STATIC_DIR,
    DATA_DIR,
    PRODUTOS_FILE,
    FORNECEDORES_FILE,
    OS_PRODUTOS_FILE,
    OS_FORNECEDORES_FILE,
    OS_COMPONENTES_FILE,
    OS_PROCESSOS_FILE,
    OS_PROCESSO_RELACOES_FILE,
    OS_ITEM_POPUP_REGRAS_FILE,
    COUNTER_FILE,
    OS_COUNTER_FILE,
    HISTORICO_FILE,
    OC_IMPORT_FILE,
    OS_IMPORT_FILE,
    get_save_paths,
    set_save_paths,
    get_bom_dir,
    set_bom_dir,
    get_skus_file,
    set_skus_file,
    get_processos_dir,
    set_processos_dir,
    pasta_os,
)
from calculos import calcular_total_item
from composicao import (
    expandir_composicao_referenciada,
    normalizar_codigo,
    normalizar_componentes,
    parse_quantidade,
    resolver_composicao_final,
)
from gerar_oc import gerar_word, construir_nome_oc
from gerar_os import gerar_os_docx
from os_template import encontrar_linha_cabecalho, mapear_tabelas_os
from processos_os import PROCESSOS_ORDEM, PROCESSOS_OS, PROCESSOS_POR_KEY, identificar_nome_processo, normalizar_nome_processo
from os_setores import (
    SETOR_EXPEDICAO,
    SETOR_PREPARACAO,
    TIPO_REQUISICAO_FATURAMENTO_DIRETO,
    agrupar_linhas_setor,
    agrupar_linhas_por_fornecedor,
    construir_itens_os_expedicao,
    construir_itens_os_preparacao,
    construir_itens_os_setor,
    enriquecer_composicao,
    filtrar_linhas_faturamento_direto,
    filtrar_linhas_setor,
    propagar_setor_preparacao,
)
from processos_transformacao import (
    PROCESSO_POR_ITEM,
    RELACOES_PROCESSO_TRANSFORMACAO,
    construir_processo_por_item,
    resolver_processo_transformacao,
    resolver_processos_transformacao,
)

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = "emissor_documentos"

RELEASE_BUILD_NAME = "ModuloSuprimentos"
RELEASE_ENVIO_DIR_NAME = "ModuloSuprimentos_envio"
RELEASE_ZIP_NAME = "ModuloSuprimentos_envio.zip"
RELEASE_BUILD_SCRIPT = "gerar_modulo_suprimentos_envio.bat"
ITEM_CAMPOS_BASE = [
    "descricao",
    "unidade",
    "grupo",
    "categoria",
    "processo_conjunto",
]
MODELO_ITENS_HEADERS = [
    "CODIGO",
    "DESCRICAO",
    "UNIDADE",
    "GRUPO",
    "CATEGORIA",
    "PROCESSO CONJUNTO",
]
MODELO_REGRAS_POPUP_HEADERS = [
    "ID_REGRA",
    "ITEM_GATILHO",
    "DESCRICAO_GATILHO",
    "ITENS_OPCOES",
    "DESCRICOES_OPCOES",
    "QUANTIDADE",
    "QUANTIDADE_EDITAVEL",
]
MODELO_RELACOES_PROCESSO_HEADERS = [
    "ITEM_CODIGO",
    "DESCRICAO_ITEM",
    "PROCESSOS",
]
HEADER_ALIASES = {
    "codigo": {
        "codigo",
        "cod",
        "cod_item",
        "codigo_item",
        "codigo_produto",
        "novo_cod",
        "novo_codigo",
        "cod_novo",
        "novo_cod_",
    },
    "descricao": {
        "descricao",
        "descricao_item",
        "descricao_produto",
        "descricao_primaria",
        "descricao_principal",
        "item_descricao",
        "produto",
        "material",
    },
    "descricao_secundaria": {
        "descricao_secundaria",
        "descricao_complementar",
        "complemento_descricao",
    },
    "sufixo": {"sufixo", "sufixo_descricao"},
    "unidade": {
        "unidade",
        "un",
        "um",
        "und",
        "unidade_medida",
        "un_medida",
        "un_medi_interna",
        "unidade_interna",
        "un_medi_comercial",
        "unidade_comercial",
    },
    "grupo": {"grupo", "grupo_produto"},
    "categoria": {"categoria", "categorias", "classificacao", "classificacao_item"},
    "processo_conjunto": {
        "processo_conjunto",
        "processo",
        "processo_vinculado",
        "arquivo_processo",
    },
    "cliente": {"cliente"},
}

CAMPOS_PRODUTO_DESCARTADOS = {
    "unidade_comercial",
    "unidade_interna",
    "tipo",
    "fornecedor",
    "ncm",
    "origem",
    "valor",
    "ipi",
    "icms",
    "cofins",
    "observacao",
}

def _is_in_dir(path, base):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) == os.path.abspath(base)
    except Exception:
        return False


def _sanitize_output_name(texto):
    texto = "" if texto is None else str(texto).strip()
    if not texto:
        return ""
    texto = re.sub(r'[<>:"/\\\\|?*]+', " ", texto)
    return " ".join(texto.split())


def _limpar_valor_busca(texto):
    texto = "" if texto is None else str(texto).strip()
    if not texto:
        return ""
    match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", texto)
    if match:
        texto = match.group(1).strip() or match.group(2).strip()
    return " ".join(texto.split())


def _win_long_path(path):
    if os.name != "nt":
        return path
    if not path:
        return path

    abs_path = os.path.abspath(path)
    if abs_path.startswith("\\\\?\\"):
        return abs_path
    if abs_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abs_path.lstrip("\\")
    return "\\\\?\\" + abs_path


def _open_for_read(path):
    return open(_win_long_path(path), "rb")


def _setup_logging():
    log_dir = DATA_DIR
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "emissor_documentos.log")
        with open(log_path, "a", encoding="utf-8"):
            pass
    except Exception:
        log_dir = tempfile.gettempdir()
        log_path = os.path.join(log_dir, "emissor_documentos.log")

    from logging.handlers import RotatingFileHandler
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info("Log iniciado em %s", log_path)


_setup_logging()


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, PermissionError):
        return str(e), 500
    app.logger.exception("Erro nao tratado")
    return "Internal Server Error", 500


def _ensure_json_file(path, default):
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(default, f, ensure_ascii=False, indent=2)


def _ensure_text_file(path, content):
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(content))


def ensure_data_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    # Para EXE: sempre sobrescreve a base local com a base embutida no build
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        packaged_data = os.path.join(sys._MEIPASS, "compras_app", "data")
        if os.path.isdir(packaged_data):
            for name in os.listdir(packaged_data):
                src = os.path.join(packaged_data, name)
                dst = os.path.join(DATA_DIR, name)
                if os.path.isfile(src):
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass
    _ensure_json_file(PRODUTOS_FILE, {})
    _ensure_json_file(FORNECEDORES_FILE, {})
    _ensure_json_file(OS_PRODUTOS_FILE, {})
    _ensure_json_file(OS_FORNECEDORES_FILE, {})
    _ensure_json_file(OS_COMPONENTES_FILE, {})
    _ensure_json_file(OS_PROCESSOS_FILE, {})
    _ensure_json_file(OS_PROCESSO_RELACOES_FILE, {})
    _ensure_json_file(OS_ITEM_POPUP_REGRAS_FILE, [])
    _ensure_json_file(HISTORICO_FILE, [])
    _ensure_json_file(OC_IMPORT_FILE, {})
    _ensure_json_file(OS_IMPORT_FILE, {})
    _ensure_text_file(COUNTER_FILE, "1")
    _ensure_text_file(OS_COUNTER_FILE, "1")


ensure_data_storage()


def _find_release_source_dir():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.dirname(sys.executable)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    envio_dir = os.path.join(project_root, RELEASE_ENVIO_DIR_NAME)
    if os.path.isdir(envio_dir) and os.path.isdir(os.path.join(envio_dir, "_internal")):
        return envio_dir
    dist_dir = os.path.join(project_root, "dist")
    if os.path.isdir(dist_dir):
        preferred_names = [RELEASE_BUILD_NAME, "Emissor documentos"]
        for preferred_name in preferred_names:
            preferred = os.path.join(dist_dir, preferred_name)
            if os.path.isdir(preferred):
                return preferred
        for name in os.listdir(dist_dir):
            cand = os.path.join(dist_dir, name)
            if os.path.isdir(cand) and os.path.isdir(os.path.join(cand, "_internal")):
                return cand
    return None


def _run_release_build():
    if getattr(sys, "frozen", False):
        return True, None
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    script_candidates = [
        RELEASE_BUILD_SCRIPT,
        "gerar_exe.bat",
    ]
    bat_path = None
    for script_name in script_candidates:
        candidate = os.path.join(project_root, script_name)
        if os.path.isfile(candidate):
            bat_path = candidate
            break
    if not bat_path:
        return False, f"Arquivo {RELEASE_BUILD_SCRIPT} nao encontrado no projeto."
    try:
        result = subprocess.run(
            f"\"{bat_path}\"",
            cwd=project_root,
            shell=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return False, f"Falha ao executar gerar_exe.bat: {exc}"
    if result.returncode != 0:
        msg = (result.stdout or "") + "\n" + (result.stderr or "")
        return False, f"Erro ao gerar EXE. Saida:\n{msg.strip()}"
    return True, None


def _build_release_zip():
    source_dir = _find_release_source_dir()
    if not source_dir:
        return None
    temp_root = tempfile.mkdtemp(prefix="emissor_pack_")
    staging = os.path.join(temp_root, RELEASE_ENVIO_DIR_NAME)
    shutil.copytree(source_dir, staging, dirs_exist_ok=True)

    zip_path = os.path.join(temp_root, RELEASE_ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(staging):
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, staging)
                zf.write(full, rel)
    return zip_path, temp_root


def _reset_base_data():
    arquivos = [
        PRODUTOS_FILE,
        FORNECEDORES_FILE,
        OS_PRODUTOS_FILE,
        OS_FORNECEDORES_FILE,
        OS_COMPONENTES_FILE,
        OS_PROCESSOS_FILE,
        OS_PROCESSO_RELACOES_FILE,
        OS_ITEM_POPUP_REGRAS_FILE,
        HISTORICO_FILE,
        OC_IMPORT_FILE,
        OS_IMPORT_FILE,
        COUNTER_FILE,
        OS_COUNTER_FILE,
    ]
    for path in arquivos:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    ensure_data_storage()


def carregar_historico():
    if not os.path.exists(HISTORICO_FILE):
        return []
    try:
        with open(HISTORICO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            merged = []
            for _, items in data.items():
                if isinstance(items, list):
                    merged.extend(items)
            return merged
    except Exception:
        return []
    return []


def salvar_historico(entries):
    try:
        with open(HISTORICO_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def registrar_historico(tipo, numero, dados, itens=None, processos=None, componentes=None, composicao=None):
    entries = carregar_historico()
    entry = {
        "tipo": tipo,
        "numero": str(numero),
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "dados": dados or {},
        "itens": itens or [],
        "processos": processos or {},
        "componentes": componentes or {},
        "composicao": composicao or [],
    }
    entries.append(entry)
    salvar_historico(entries)


def _agrupar_por_data(entries, tipo, campo_soma=None):
    resumo = {}
    for e in entries:
        if e.get("tipo") != tipo:
            continue
        data = (e.get("data_criacao") or "")[:10]
        if not data:
            continue
        if data not in resumo:
            resumo[data] = 0
        if campo_soma:
            valor = e.get("dados", {}).get(campo_soma, 0)
            try:
                resumo[data] += float(valor)
            except Exception:
                pass
        else:
            resumo[data] += 1
    return [{"data": k, "valor": resumo[k]} for k in sorted(resumo.keys())]


def _get_free_port():
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _abrir_navegador(port):
    try:
        import webbrowser
        webbrowser.open_new(f"http://127.0.0.1:{port}")
    except Exception:
        pass




def carregar_produtos():

    if not os.path.exists(PRODUTOS_FILE):
        return {}

    with open(PRODUTOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_fornecedores():

    if not os.path.exists(FORNECEDORES_FILE):
        return {}

    with open(FORNECEDORES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_os_produtos():

    if not os.path.exists(OS_PRODUTOS_FILE):
        return {}

    with open(OS_PRODUTOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_os_fornecedores():

    if not os.path.exists(OS_FORNECEDORES_FILE):
        return {}

    with open(OS_FORNECEDORES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_os_componentes():

    if not os.path.exists(OS_COMPONENTES_FILE):
        return {}

    with open(OS_COMPONENTES_FILE, "r", encoding="utf-8") as f:
        return normalizar_componentes(json.load(f))


def carregar_os_processos():

    if not os.path.exists(OS_PROCESSOS_FILE):
        return {}

    with open(OS_PROCESSOS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # suporta formato antigo: {processo: [linhas]}
    if data and isinstance(next(iter(data.values())), list):
        data = {"PADRAO": data}

    def normalizar_processo(nome):
        if not nome:
            return nome
        n = str(nome).strip().upper()
        mapa = {
            "CORTE": "CORTE",
            "AR CONDICIONADO": "AR CONDICIONADO",
            "PREPARACAO DE PECAS": "PREPARAÇÃO DE PEÇAS",
            "PREPARAÇÃO DE PEÇAS": "PREPARAÇÃO DE PEÇAS",
            "PREPARA??O DE PE?AS": "PREPARAÇÃO DE PEÇAS",
            "PREPARAÃ‡ÃƒO DE PEÃ‡AS": "PREPARAÇÃO DE PEÇAS",
            "ISOLAMENTO": "ISOLAMENTO",
            "DESMONTAGEM E ISOLAMENTO": "ISOLAMENTO",
            "REVESTIMENTO": "REVESTIMENTO",
            "BANCOS": "BANCOS",
            "ELETRICA": "ELÉTRICA 2",
            "ELÉTRICA": "ELÉTRICA 2",
            "ELÉTRICA 2": "ELÉTRICA 2",
            "EL?TRICA 2": "ELÉTRICA 2",
            "ELÃ‰TRICA 2": "ELÉTRICA 2",
            "LIMPEZA/LIBERACAO": "LIMPEZA/LIBERAÇÃO",
            "LIMPEZA/LIBERAÇÃO": "LIMPEZA/LIBERAÇÃO",
            "LIMPEZA/LIBERA??O": "LIMPEZA/LIBERAÇÃO",
            "LIMPEZA/LIBERAÃ‡ÃƒO": "LIMPEZA/LIBERAÇÃO",
        }
        return mapa.get(n, nome)

    normalizado = {}
    for conjunto, processos in data.items():
        normalizado.setdefault(conjunto, {})
        for nome_proc, linhas in processos.items():
            chave = normalizar_processo(nome_proc)
            normalizado[conjunto].setdefault(chave, [])
            normalizado[conjunto][chave].extend(linhas)

    return normalizado


def carregar_relacoes_processo_item():
    if not os.path.exists(OS_PROCESSO_RELACOES_FILE):
        return {}
    try:
        with open(OS_PROCESSO_RELACOES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, dict):
        relacoes = {}
        for chave, valor in data.items():
            codigo = normalizar_codigo(chave)
            processos = valor if isinstance(valor, list) else [valor]
            processos = [
                str(processo or "").strip()
                for processo in processos
                if str(processo or "").strip()
            ]
            if codigo and processos:
                relacoes[codigo] = list(dict.fromkeys(processos))
        return relacoes
    if isinstance(data, list):
        relacoes = {}
        for relacao in data:
            if not isinstance(relacao, dict):
                continue
            codigo = normalizar_codigo(
                relacao.get("codigo")
                or relacao.get("item_codigo")
                or relacao.get("item")
                or ""
            )
            processos = relacao.get("processos") or relacao.get("opcoes") or [
                relacao.get("processo_conjunto") or relacao.get("processo") or ""
            ]
            if not isinstance(processos, list):
                processos = [processos]
            processos = [
                str(processo or "").strip()
                for processo in processos
                if str(processo or "").strip()
            ]
            if codigo and processos:
                relacoes[codigo] = list(dict.fromkeys(processos))
        return relacoes
    return {}


def salvar_relacoes_processo_item(relacoes):
    salvar_json(OS_PROCESSO_RELACOES_FILE, relacoes or {})


def carregar_regras_popup_item():
    if not os.path.exists(OS_ITEM_POPUP_REGRAS_FILE):
        return []
    try:
        with open(OS_ITEM_POPUP_REGRAS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    regras = []
    for idx, regra in enumerate(data):
        if not isinstance(regra, dict):
            continue
        gatilho = normalizar_codigo(regra.get("gatilho") or regra.get("item_gatilho") or "")
        opcoes = [
            normalizar_codigo(codigo)
            for codigo in (regra.get("opcoes") or [])
            if normalizar_codigo(codigo)
        ]
        if not gatilho or not opcoes:
            continue
        try:
            quantidade = float(regra.get("quantidade", 1) or 1)
        except Exception:
            quantidade = 1
        if quantidade <= 0:
            quantidade = 1
        regras.append(
            {
                "id": str(regra.get("id") or f"regra-{idx + 1}"),
                "gatilho": gatilho,
                "opcoes": list(dict.fromkeys(opcoes)),
                "quantidade": quantidade,
                "quantidade_editavel": bool(regra.get("quantidade_editavel", False)),
            }
        )
    return regras


def salvar_regras_popup_item(regras):
    salvar_json(OS_ITEM_POPUP_REGRAS_FILE, regras or [])


def carregar_os_processos():

    if not os.path.exists(OS_PROCESSOS_FILE):
        return {}

    with open(OS_PROCESSOS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data and isinstance(next(iter(data.values())), list):
        data = {"PADRAO": data}

    normalizado = {}
    for conjunto, processos in data.items():
        normalizado.setdefault(conjunto, {})
        for nome_proc, linhas in processos.items():
            chave = normalizar_nome_processo(nome_proc)
            normalizado[conjunto].setdefault(chave, [])
            normalizado[conjunto][chave].extend(linhas)
        for nome in PROCESSOS_ORDEM:
            normalizado[conjunto].setdefault(nome, [])

    return normalizado


def salvar_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise PermissionError(
            f"Falha ao salvar dados em '{path}'. Verifique permissao/OneDrive."
        ) from exc


OS_MODE_CONFIGS = {
    "completa": {
        "titulo": "O.S Completa",
        "doc_mode": "completa",
        "itens_source": "originais",
        "incluir_cliente_nome": False,
    },
    "expedicao": {
        "titulo": "REQUISI\u00c7\u00c3O EXPEDI\u00c7\u00c3O",
        "doc_mode": "expedicao",
        "itens_source": "expedicao",
        "incluir_cliente_nome": False,
    },
    "preparacao": {
        "titulo": "REQUISI\u00c7\u00c3O PREPARA\u00c7\u00c3O",
        "doc_mode": "preparacao",
        "itens_source": "preparacao",
        "incluir_cliente_nome": False,
    },
    "producao": {
        "titulo": "O.S Producao",
        "doc_mode": "producao",
        "itens_source": "originais",
        "incluir_cliente_nome": False,
    },
    "mascara": {
        "titulo": "Mascara",
        "doc_mode": "mascara",
        "itens_source": "originais",
    },
    "resumida": {
        "titulo": "O.S Resumida",
        "doc_mode": "resumida",
        "itens_source": "originais",
    },
}


def _formatar_qtd_saida(valor):
    try:
        numero = float(valor)
    except Exception:
        return valor
    if numero.is_integer():
        return int(numero)
    texto = f"{numero:.4f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def _eh_faturamento_direto(descricao):
    texto = _corrigir_mojibake(descricao)
    texto = unicodedata.normalize("NFKD", str(texto or "").strip().upper())
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return texto.startswith("FATURAMENTO DIRETO")


def _categoria_ar_condicionado(categoria):
    texto = _corrigir_mojibake(categoria)
    texto = unicodedata.normalize("NFKD", str(texto or "").strip().upper())
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return texto.startswith("10") and "AR CONDICIONADO" in texto


def _fornecedor_faturamento_direto(descricao, categoria, fornecedor_informado="", fornecedor_cadastro=""):
    fornecedor_informado = str(fornecedor_informado or "").strip()
    fornecedor_cadastro = str(fornecedor_cadastro or "").strip()
    if _categoria_ar_condicionado(categoria):
        texto = _corrigir_mojibake(descricao)
        texto_norm = unicodedata.normalize("NFKD", str(texto or "").strip().upper())
        texto_norm = "".join(ch for ch in texto_norm if not unicodedata.combining(ch))
        partes = [parte for parte in re.split(r"[^A-Z0-9]+", texto_norm) if parte]
        if partes:
            ultimo = partes[-1]
            if ultimo in {"GE", "CLIM"}:
                return ultimo
            if ultimo in {"EURO", "GRUPOEURO"}:
                return "GE"
            if ultimo in {"CLIMAUTO", "CLIMATIZAR"}:
                return "CLIM"
    return fornecedor_informado or fornecedor_cadastro


def _resolve_output_path(path):
    dir_path = os.path.dirname(path)
    try:
        arquivos = os.listdir(dir_path)
    except Exception:
        arquivos = []
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for idx in range(1, 100):
        candidato = f"{base} - R{idx:02d}{ext}"
        if not os.path.exists(candidato):
            return candidato
    return path


def _save_workbook_safe(wb, path):
    try:
        wb.save(path)
        return path
    except Exception:
        try:
            long_path = _win_long_path(path)
            wb.save(long_path)
            return path
        except Exception:
            fallback_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(fallback_dir, exist_ok=True)
            fallback_path = _resolve_output_path(os.path.join(fallback_dir, os.path.basename(path)))
            wb.save(fallback_path)
            return fallback_path


def _agrupar_linhas_requisicao(linhas):
    agrupado = {}
    ordem = []
    for linha in linhas or []:
        codigo = normalizar_codigo(linha.get("codigo", ""))
        unidade = str(linha.get("unidade", "") or "").strip()
        setor = str(linha.get("setor", "") or "").strip()
        fornecedor = str(linha.get("fornecedor", "") or "").strip()
        tipo_requisicao = str(linha.get("tipo_requisicao", "") or "").strip()
        chave = (codigo, unidade, setor, fornecedor, tipo_requisicao)
        if chave not in agrupado:
            agrupado[chave] = {
                "codigo": codigo,
                "descricao": linha.get("descricao", "") or "",
                "unidade": unidade,
                "grupo": linha.get("grupo", "") or "",
                "categoria": linha.get("categoria", "") or "",
                "fornecedor": fornecedor,
                "setor": setor,
                "tipo_requisicao": tipo_requisicao,
                "qtd": 0.0,
            }
            ordem.append(chave)
        agrupado[chave]["qtd"] += parse_quantidade(linha.get("qtd", 0))
    return [agrupado[chave] for chave in ordem]


def _formatar_titulo_planilha(ws, titulo, total_colunas):
    ultima_coluna = max(total_colunas, 1)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ultima_coluna)
    cell = ws.cell(row=1, column=1)
    cell.value = titulo.upper()
    cell.font = Font(bold=True, size=14)
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _formatar_cabecalho_planilha(ws, row_idx, total_colunas):
    for col_idx in range(1, total_colunas + 1):
        cell = ws.cell(row=row_idx, column=col_idx)
        if cell.value:
            cell.value = str(cell.value).upper()
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _criar_planilha_requisicao_materiais(numero_os, dados, linhas, titulo_arquivo):
    pasta_destino = pasta_os(numero_os, dados)
    chassi = (dados.get("chassis", "") or "").strip()
    partes_nome = [titulo_arquivo]
    if chassi:
        partes_nome.append(chassi)
    nome_arquivo = " - ".join(partes_nome).strip(" -") + ".xlsx"
    caminho = _resolve_output_path(
        os.path.join(pasta_destino, nome_arquivo)
    )

    wb = Workbook()
    ws_detalhe = wb.active
    ws_detalhe.title = "Requisicao"
    _formatar_titulo_planilha(ws_detalhe, "REQUISI\u00c7\u00c3O DE MATERIAIS", 14)
    ws_detalhe.append(
        [
            "numero_os",
            "cliente",
            "chassis",
            "mmv",
            "item_os",
            "codigo",
            "descricao",
            "grupo",
            "categoria",
            "fornecedor",
            "tipo_requisicao",
            "setor",
            "unidade",
            "qtd",
        ]
    )
    _formatar_cabecalho_planilha(ws_detalhe, 2, 14)

    if not linhas:
        ws_detalhe.append(
            [
                numero_os,
                dados.get("cliente", ""),
                dados.get("chassis", ""),
                dados.get("mmv", ""),
                "",
                "",
                "Sem itens classificados para requisicao de materiais.",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
    else:
        for linha in linhas:
            ws_detalhe.append(
                [
                    numero_os,
                    dados.get("cliente", ""),
                    dados.get("chassis", ""),
                    dados.get("mmv", ""),
                    linha.get("item", ""),
                    linha.get("codigo", ""),
                    linha.get("descricao", ""),
                    linha.get("grupo", ""),
                    linha.get("categoria", ""),
                    linha.get("fornecedor", ""),
                    linha.get("tipo_requisicao", ""),
                    linha.get("setor", ""),
                    linha.get("unidade", ""),
                    _formatar_qtd_saida(linha.get("qtd", "")),
                ]
            )

    ws_resumo = wb.create_sheet("Somatorio")
    _formatar_titulo_planilha(ws_resumo, "REQUISI\u00c7\u00c3O DE MATERIAIS", 9)
    ws_resumo.append(["codigo", "descricao", "grupo", "categoria", "fornecedor", "tipo_requisicao", "setor", "unidade", "qtd_total"])
    _formatar_cabecalho_planilha(ws_resumo, 2, 9)
    for linha in _agrupar_linhas_requisicao(linhas):
        ws_resumo.append(
            [
                linha.get("codigo", ""),
                linha.get("descricao", ""),
                linha.get("grupo", ""),
                linha.get("categoria", ""),
                linha.get("fornecedor", ""),
                linha.get("tipo_requisicao", ""),
                linha.get("setor", ""),
                linha.get("unidade", ""),
                _formatar_qtd_saida(linha.get("qtd", "")),
            ]
        )

    for ws in wb.worksheets:
        for col_idx, column_cells in enumerate(ws.columns, start=1):
            valores = [len(str(cell.value or "")) for cell in column_cells]
            letra = get_column_letter(col_idx)
            ws.column_dimensions[letra].width = min(max(max(valores, default=0) + 2, 12), 40)

    return _save_workbook_safe(wb, caminho)


def _criar_zip_temporario(paths, download_name):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            if not path or not os.path.exists(path):
                continue
            zf.write(path, arcname=os.path.basename(path))
    return tmp.name, download_name


def carregar_importacao(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def limpar_importacao(path):
    if os.path.exists(path):
        os.remove(path)


def _limpar_placeholder(texto):
    if texto is None:
        return ""
    texto = str(texto).strip()
    if "{" in texto and "}" in texto:
        return ""
    return texto


def _parse_money(texto):
    if texto is None:
        return ""
    texto = str(texto)
    texto = texto.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return ""


def _normalizar_qtd(texto):
    texto = _limpar_placeholder(texto)
    if texto == "":
        return ""
    texto = str(texto).strip()
    texto = texto.replace(" ", "")
    texto = texto.replace(".", "")
    texto = texto.replace(",", ".")
    try:
        numero = float(texto)
    except ValueError:
        return ""
    if abs(numero - int(numero)) < 1e-9:
        return str(int(numero))
    return f"{numero:.2f}".rstrip("0").rstrip(".")


def _parse_date_ddmmyyyy(texto):
    texto = _limpar_placeholder(texto)
    if not texto:
        return ""
    try:
        dt = datetime.strptime(texto, "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _parse_datetime_ddmmyyyy(texto):
    texto = _limpar_placeholder(texto)
    if not texto:
        return ""
    texto = texto.replace(" - ", " ")
    try:
        dt = datetime.strptime(texto, "%d/%m/%Y %H:%M")
        return dt.strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return ""


def _best_descricao(cells, code_idx, desc_idx, ignore_idx=None):
    desc = _limpar_placeholder(cells[desc_idx]) if len(cells) > desc_idx else ""
    if desc:
        return desc
    parts = []
    for i, c in enumerate(cells):
        if i == code_idx:
            continue
        if ignore_idx and i in ignore_idx:
            continue
        txt = _limpar_placeholder(c)
        if not txt:
            continue
        if re.fullmatch(r"[\\d\\.,]+", txt) or "R$" in txt:
            continue
        parts.append(txt)
    return " ".join(parts).strip()


def _extract_pdf_text(file_storage):
    try:
        from PyPDF2 import PdfReader
    except Exception:
        return ""
    file_storage.stream.seek(0)
    reader = PdfReader(file_storage.stream)
    textos = []
    for page in reader.pages:
        textos.append(page.extract_text() or "")
    return "\n".join(textos)


def _buscar_valor_linha(linhas, label):
    label_upper = label.upper()
    for idx, linha in enumerate(linhas):
        if label_upper in linha.upper():
            partes = linha.split(":", 1)
            if len(partes) > 1 and partes[1].strip():
                return partes[1].strip()
            if idx + 1 < len(linhas):
                return linhas[idx + 1].strip()
    return ""


def parse_oc_docx(file_storage):
    file_storage.stream.seek(0)
    doc = Document(file_storage.stream)
    data = {}

    def cell_text_safe(table, row_idx, col_idx):
        if not table or row_idx < 0 or col_idx < 0:
            return ""
        if row_idx >= len(table.rows):
            return ""
        row = table.rows[row_idx]
        if col_idx >= len(row.cells):
            return ""
        return row.cells[col_idx].text

    if len(doc.tables) < 5:
        return data

    t0 = doc.tables[0]
    data["data_emissao"] = _parse_date_ddmmyyyy(t0.cell(1, 1).text if len(t0.rows) > 1 else "")
    oc_txt = t0.cell(1, 2).text if len(t0.rows) > 1 else ""
    oc_num = re.findall(r"\d+", oc_txt)
    data["oc_numero"] = oc_num[0] if oc_num else ""

    t2 = doc.tables[2]
    data["fornecedor"] = _limpar_placeholder(t2.cell(0, 1).text)
    data["razao_social"] = _limpar_placeholder(t2.cell(0, 4).text)
    data["cnpj"] = _limpar_placeholder(t2.cell(1, 1).text)
    data["endereco"] = _limpar_placeholder(t2.cell(1, 4).text)
    data["bairro"] = _limpar_placeholder(t2.cell(2, 1).text)
    data["cep"] = _limpar_placeholder(t2.cell(2, 4).text)
    data["cidade"] = _limpar_placeholder(t2.cell(3, 1).text)
    data["uf"] = _limpar_placeholder(t2.cell(3, 2).text)
    data["telefone"] = _limpar_placeholder(t2.cell(3, 4).text)
    data["email"] = _limpar_placeholder(t2.cell(4, 1).text)
    data["previsao"] = _parse_date_ddmmyyyy(t2.cell(4, 4).text)

    t3 = doc.tables[3]
    itens = []
    for row in t3.rows[1:]:
        cells = [c.text.strip() for c in row.cells]
        if not any(cells):
            continue
        itens.append({
            "codigo": _limpar_placeholder(cells[0]) if len(cells) > 0 else "",
            "descricao": _best_descricao(cells, 0, 1, ignore_idx={2, 3, 4, 5, 6}),
            "unidade": _limpar_placeholder(cells[2]) if len(cells) > 2 else "",
            "qtd": _normalizar_qtd(cells[3]) if len(cells) > 3 else "",
            "valor": _parse_money(cells[4]) if len(cells) > 4 else "",
            "desconto": _parse_money(cells[5]) if len(cells) > 5 else "",
        })
    data["itens"] = itens

    t4 = doc.tables[4]
    if len(t4.rows) > 1:
        data["tipo_frete"] = _limpar_placeholder(cell_text_safe(t4, 1, 0))
        data["frete"] = _parse_money(cell_text_safe(t4, 1, 1))
        data["total_itens"] = _parse_money(cell_text_safe(t4, 1, 2))
        total_pedido = _parse_money(cell_text_safe(t4, 1, 3))
        if total_pedido == "":
            total_pedido = _parse_money(cell_text_safe(t4, 1, 4))
        data["total_pedido"] = total_pedido
        data["forma_pagamento"] = _limpar_placeholder(cell_text_safe(t4, 1, 6))
        data["prazo"] = _limpar_placeholder(cell_text_safe(t4, 1, 7))
        data["vencimento"] = _limpar_placeholder(cell_text_safe(t4, 1, 8))

    obs = []
    for row in t4.rows[2:]:
        for cell in row.cells:
            texto = cell.text.strip()
            if "Observa" in texto:
                if ":" in texto:
                    obs_txt = texto.split(":", 1)[1].strip()
                    if obs_txt:
                        obs.append(obs_txt)
    data["obs"] = "\n".join(dict.fromkeys(obs))
    return data


def parse_os_docx(file_storage):
    file_storage.stream.seek(0)
    doc = Document(file_storage.stream)
    data = {}

    if len(doc.tables) < 5:
        return data

    t0 = doc.tables[0]
    os_txt = t0.cell(0, 2).text if len(t0.rows) > 0 else ""
    os_num = re.findall(r"\d+", os_txt)
    data["os_numero"] = os_num[0] if os_num else ""

    t1 = doc.tables[1]
    data["chassis"] = _limpar_placeholder(t1.cell(1, 1).text)
    data["municipio"] = _limpar_placeholder(t1.cell(1, 3).text)
    data["cliente"] = _limpar_placeholder(t1.cell(2, 1).text)
    data["mmv"] = _limpar_placeholder(t1.cell(2, 3).text)
    data["previsao_inicio"] = _parse_datetime_ddmmyyyy(t1.cell(3, 1).text)
    data["previsao_termino"] = _parse_datetime_ddmmyyyy(t1.cell(3, 3).text)

    t2 = doc.tables[2]
    itens = []
    for row in t2.rows[2:]:
        cells = [c.text.strip() for c in row.cells]
        if not any(cells):
            continue
        itens.append({
            "codigo": _limpar_placeholder(cells[0]) if len(cells) > 0 else "",
            "descricao": _best_descricao(cells, 0, 1, ignore_idx={2, 3, 4}),
            "qtd": _normalizar_qtd(cells[2]) if len(cells) > 2 else "",
            "serie": _limpar_placeholder(cells[3]) if len(cells) > 3 else "",
            "unidade": _limpar_placeholder(cells[4]) if len(cells) > 4 else "",
        })
    data["itens"] = itens

    t3 = doc.tables[3]
    composicao = []
    for row in t3.rows[2:]:
        cells = [c.text.strip() for c in row.cells]
        if not any(cells):
            continue
        composicao.append({
            "codigo": _limpar_placeholder(cells[0]) if len(cells) > 0 else "",
            "descricao": _limpar_placeholder(cells[1]) if len(cells) > 1 else "",
            "qtd": _normalizar_qtd(cells[2]) if len(cells) > 2 else "",
            "unidade": _limpar_placeholder(cells[3]) if len(cells) > 3 else "",
        })
    data["composicao"] = composicao

    t4 = doc.tables[4]
    if len(t4.rows) > 1:
        data["obs_materiais"] = _limpar_placeholder(t4.cell(1, 0).text)

    processos_map = {
        "CORTE": 5,
        "AR CONDICIONADO": 6,
        "PREPARAÃ‡ÃƒO DE PEÃ‡AS": 7,
        "ISOLAMENTO": 8,
        "REVESTIMENTO": 9,
        "BANCOS": 10,
        "ELÃ‰TRICA 2": 11,
        "LIMPEZA/LIBERAÃ‡ÃƒO": 12,
    }
    processos = {}
    for nome, idx in processos_map.items():
        if len(doc.tables) <= idx:
            continue
        t = doc.tables[idx]
        linhas = []
        for row in t.rows[2:]:
            atividade = row.cells[1].text.strip() if len(row.cells) > 1 else ""
            if not atividade:
                continue
            responsavel_idx = 2 if len(row.cells) > 6 else 3
            data_idx = 3 if len(row.cells) > 6 else None
            inicio_idx = 4 if len(row.cells) > 6 else None
            fim_idx = 5 if len(row.cells) > 6 else None
            feito_idx = 6 if len(row.cells) > 6 else 4 if len(row.cells) > 4 else None
            linha = {
                "atividade": atividade,
                "responsavel": row.cells[responsavel_idx].text.strip() if len(row.cells) > responsavel_idx else "",
            }
            if data_idx is not None:
                linha["data"] = row.cells[data_idx].text.strip() if len(row.cells) > data_idx else ""
                linha["inicio"] = row.cells[inicio_idx].text.strip() if len(row.cells) > inicio_idx else ""
                linha["fim"] = row.cells[fim_idx].text.strip() if len(row.cells) > fim_idx else ""
                linha["feito"] = row.cells[feito_idx].text.strip() if len(row.cells) > feito_idx else ""
            linhas.append(linha)
        processos[nome] = linhas
    data["processos"] = processos

    obs_final = ""
    for p in doc.paragraphs:
        if p.text.strip().upper().startswith("OBS FINAL"):
            obs_final = p.text.split(":", 1)[-1].strip()
            break
    data["obs"] = obs_final
    return data


def parse_os_docx_atualizado(file_storage):
    file_storage.stream.seek(0)
    doc = Document(file_storage.stream)
    refs = mapear_tabelas_os(doc)
    data = {}

    def cell_text_safe(table, row_idx, col_idx):
        if table is None or row_idx < 0 or col_idx < 0:
            return ""
        if row_idx >= len(table.rows):
            return ""
        row = table.rows[row_idx]
        if col_idx >= len(row.cells):
            return ""
        return (row.cells[col_idx].text or "").strip()

    if refs.get("cabecalho") is not None:
        t0 = doc.tables[refs["cabecalho"]]
        os_txt = cell_text_safe(t0, 0, 2)
        os_num = re.findall(r"\d+", os_txt)
        data["os_numero"] = os_num[0] if os_num else ""

    if refs.get("dados") is not None:
        t1 = doc.tables[refs["dados"]]
        data["chassis"] = _limpar_placeholder(cell_text_safe(t1, 1, 1))
        data["municipio"] = _limpar_placeholder(cell_text_safe(t1, 1, 3))
        data["cliente"] = _limpar_placeholder(cell_text_safe(t1, 2, 1))
        data["mmv"] = _limpar_placeholder(cell_text_safe(t1, 2, 3))
        data["previsao_inicio"] = _parse_datetime_ddmmyyyy(cell_text_safe(t1, 3, 1))
        data["previsao_termino"] = _parse_datetime_ddmmyyyy(cell_text_safe(t1, 3, 3))

    itens = []
    if refs.get("itens") is not None:
        tabela_itens = doc.tables[refs["itens"]]
        header_idx = encontrar_linha_cabecalho(tabela_itens, "CODIGO", "QTD")
        inicio = (header_idx or 0) + 1
        for row in tabela_itens.rows[inicio:]:
            cells = [c.text.strip() for c in row.cells]
            if not any(cells):
                continue
            itens.append({
                "codigo": _limpar_placeholder(cells[0]) if len(cells) > 0 else "",
                "descricao": _best_descricao(cells, 0, 1, ignore_idx={2, 3, 4}),
                "qtd": _normalizar_qtd(cells[2]) if len(cells) > 2 else "",
                "serie": _limpar_placeholder(cells[3]) if len(cells) > 3 else "",
                "unidade": _limpar_placeholder(cells[4]) if len(cells) > 4 else "",
            })
    data["itens"] = itens

    composicao = []
    if refs.get("composicao") is not None:
        tabela_comp = doc.tables[refs["composicao"]]
        header_idx = encontrar_linha_cabecalho(tabela_comp, "CODIGO", "QTD")
        inicio = (header_idx or 0) + 1
        for row in tabela_comp.rows[inicio:]:
            cells = [c.text.strip() for c in row.cells]
            if not any(cells):
                continue
            composicao.append({
                "item": "",
                "codigo": _limpar_placeholder(cells[0]) if len(cells) > 0 else "",
                "descricao": _limpar_placeholder(cells[1]) if len(cells) > 1 else "",
                "qtd": _normalizar_qtd(cells[2]) if len(cells) > 2 else "",
                "unidade": _limpar_placeholder(cells[3]) if len(cells) > 3 else "",
                "level": 0,
            })
    data["composicao"] = composicao

    if refs.get("observacoes") is not None:
        tabela_obs = doc.tables[refs["observacoes"]]
        if len(tabela_obs.rows) > 1:
            data["obs_materiais"] = _limpar_placeholder(cell_text_safe(tabela_obs, 1, 0))

    processos = {nome: [] for nome in PROCESSOS_ORDEM}
    for nome, idx in refs.get("processos", {}).items():
        tabela_proc = doc.tables[idx]
        header_idx = encontrar_linha_cabecalho(tabela_proc, "ATIVIDADE", "RESPONS")
        inicio = (header_idx or 0) + 1
        linhas = []
        for row in tabela_proc.rows[inicio:]:
            cells = [c.text.strip() for c in row.cells]
            atividade = cells[1] if len(cells) > 1 else ""
            if not atividade:
                continue
            responsavel_idx = 2 if len(cells) > 6 else 3
            data_idx = 3 if len(cells) > 6 else None
            inicio_idx = 4 if len(cells) > 6 else None
            fim_idx = 5 if len(cells) > 6 else None
            feito_idx = 6 if len(cells) > 6 else 4 if len(cells) > 4 else None
            linha = {
                "atividade": atividade,
                "responsavel": cells[responsavel_idx] if len(cells) > responsavel_idx else "",
            }
            if data_idx is not None:
                linha["data"] = cells[data_idx] if len(cells) > data_idx else ""
                linha["inicio"] = cells[inicio_idx] if len(cells) > inicio_idx else ""
                linha["fim"] = cells[fim_idx] if len(cells) > fim_idx else ""
                linha["feito"] = cells[feito_idx] if len(cells) > feito_idx else ""
            linhas.append(linha)
        processos[nome] = linhas
    data["processos"] = processos

    obs_final = ""
    for p in doc.paragraphs:
        if p.text.strip().upper().startswith("OBS FINAL"):
            obs_final = p.text.split(":", 1)[-1].strip()
            break
    data["obs"] = obs_final
    return data


def parse_oc_pdf(file_storage):
    texto = _extract_pdf_text(file_storage)
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    data = {
        "fornecedor": _buscar_valor_linha(linhas, "NOME FANTASIA"),
        "razao_social": _buscar_valor_linha(linhas, "RAZÃO SOCIAL") or _buscar_valor_linha(linhas, "RAZAO SOCIAL"),
        "cnpj": _buscar_valor_linha(linhas, "CNPJ/CPF"),
        "endereco": _buscar_valor_linha(linhas, "ENDEREÇO") or _buscar_valor_linha(linhas, "ENDERECO"),
        "bairro": _buscar_valor_linha(linhas, "BAIRRO"),
        "cep": _buscar_valor_linha(linhas, "CEP"),
        "cidade": _buscar_valor_linha(linhas, "CIDADE"),
        "uf": _buscar_valor_linha(linhas, "UF"),
        "telefone": _buscar_valor_linha(linhas, "TELEFONE"),
        "email": _buscar_valor_linha(linhas, "E-MAIL"),
        "previsao": _parse_date_ddmmyyyy(_buscar_valor_linha(linhas, "PREVISÃO DE CHEGADA") or _buscar_valor_linha(linhas, "PREVISAO DE CHEGADA")),
        "tipo_frete": _buscar_valor_linha(linhas, "TIPO DO FRETE"),
        "frete": _parse_money(_buscar_valor_linha(linhas, "VALOR DO FRETE")),
        "total_itens": _parse_money(_buscar_valor_linha(linhas, "VALOR DO PEDIDO")),
        "total_pedido": _parse_money(_buscar_valor_linha(linhas, "VALOR TOTAL DO PEDIDO")),
        "forma_pagamento": _buscar_valor_linha(linhas, "FORMA DE PAGAMENTO"),
        "prazo": _buscar_valor_linha(linhas, "PRAZO"),
        "vencimento": _buscar_valor_linha(linhas, "VENCIMENTO"),
        "obs": "",
        "itens": [],
    }

    for linha in linhas:
        if "OBSERVA" in linha.upper() and ":" in linha:
            data["obs"] = linha.split(":", 1)[1].strip()
            break

    itens = []
    for linha in linhas:
        if "R$" not in linha:
            continue
        money = re.findall(r"R\\$\\s*[\\d\\.,]+", linha)
        if len(money) < 2:
            continue
        partes = linha.split()
        if len(partes) < 4:
            continue
        codigo = partes[0]
        pre_money = linha.split("R$")[0].strip()
        numeros = re.findall(r"[\\d\\.,]+", pre_money)
        qtd = _normalizar_qtd(numeros[-1]) if numeros else ""
        desc = pre_money.replace(codigo, "", 1).replace(qtd, "", 1).strip()
        itens.append({
            "codigo": codigo,
            "descricao": desc,
            "unidade": "",
            "qtd": qtd,
            "valor": _parse_money(money[-3]) if len(money) >= 3 else _parse_money(money[-2]),
            "desconto": _parse_money(money[-2]) if len(money) >= 3 else "",
        })
    data["itens"] = itens
    return data


def parse_os_pdf(file_storage):
    texto = _extract_pdf_text(file_storage)
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    data = {
        "os_numero": "",
        "chassis": _buscar_valor_linha(linhas, "CHASSIS"),
        "municipio": _buscar_valor_linha(linhas, "MUNICÍPIO") or _buscar_valor_linha(linhas, "MUNICIPIO"),
        "cliente": _buscar_valor_linha(linhas, "CLIENTE"),
        "mmv": _buscar_valor_linha(linhas, "MMV"),
        "previsao_inicio": _parse_datetime_ddmmyyyy(_buscar_valor_linha(linhas, "PREVISÃO INICIO") or _buscar_valor_linha(linhas, "PREVISAO INICIO")),
        "previsao_termino": _parse_datetime_ddmmyyyy(_buscar_valor_linha(linhas, "PREVISÃO TÉRMINO") or _buscar_valor_linha(linhas, "PREVISAO TERMINO")),
        "obs_materiais": _buscar_valor_linha(linhas, "OBSERVAÇÕES") or _buscar_valor_linha(linhas, "OBSERVACOES"),
        "obs": "",
        "itens": [],
        "processos": {},
    }

    for linha in linhas:
        if "OBS FINAL" in linha.upper() and ":" in linha:
            data["obs"] = linha.split(":", 1)[1].strip()
            break

    itens = []
    capturar = False
    for linha in linhas:
        if "PRODUTOS:" in linha.upper():
            capturar = True
            continue
        if "COMPOSIÇÃO" in linha.upper() or "COMPOSICAO" in linha.upper():
            capturar = False
        if not capturar:
            continue
        partes = linha.split()
        if len(partes) < 3:
            continue
        codigo = partes[0]
        qtd = _normalizar_qtd(partes[-2]) if len(partes) >= 2 else ""
        un = partes[-1] if len(partes) >= 1 else ""
        descricao = " ".join(partes[1:-2]).strip()
        if codigo and descricao:
            itens.append({
                "codigo": codigo,
                "descricao": descricao,
                "qtd": qtd,
                "serie": "",
                "unidade": un,
            })
    data["itens"] = itens

    composicao = []
    capturar = False
    for linha in linhas:
        up = linha.upper()
        if "COMPOSIÇÃO" in up or "COMPOSICAO" in up:
            capturar = True
            continue
        if "OBSERVA" in up or "PROCESSOS DE PRODU" in up or "PROCESSOS DE PRODU" in up:
            capturar = False
        if not capturar:
            continue
        partes = linha.split()
        if len(partes) < 3:
            continue
        codigo = partes[0]
        qtd = _normalizar_qtd(partes[-2]) if len(partes) >= 2 else ""
        un = partes[-1] if len(partes) >= 1 else ""
        descricao = " ".join(partes[1:-2]).strip()
        if codigo and descricao:
            composicao.append({
                "codigo": codigo,
                "descricao": descricao,
                "qtd": qtd,
                "unidade": un,
            })
    data["composicao"] = composicao

    processos = {}
    current = None
    for linha in linhas:
        up = linha.upper()
        if "PROCESSOS DE PRODUÇÃO" in up or "PROCESSOS DE PRODUCAO" in up:
            if "CORTE" in up:
                current = "CORTE"
            elif "AR CONDICIONADO" in up:
                current = "AR CONDICIONADO"
            elif "PREPARA" in up:
                current = "PREPARAÃ‡ÃƒO DE PEÃ‡AS"
            elif "ISOLAMENTO" in up:
                current = "ISOLAMENTO"
            elif "REVESTIMENTO" in up:
                current = "REVESTIMENTO"
            elif "BANCOS" in up:
                current = "BANCOS"
            elif "ELÉTRICA" in up or "ELETRICA" in up:
                current = "ELÃ‰TRICA 2"
            elif "LIMPEZA" in up:
                current = "LIMPEZA/LIBERAÃ‡ÃƒO"
            processos.setdefault(current, [])
            continue
        if current:
            if up.startswith("#") or up.startswith("ATIVIDADE") or up.startswith("RESPONS"):
                continue
            texto = re.sub(r"^\\d+\\s+", "", linha).strip()
            if texto:
                processos[current].append({"atividade": texto, "responsavel": ""})
    data["processos"] = processos
    return data



def _criar_modelo_xlsx(headers, nome_arquivo, header_row=1):
    wb = Workbook()
    ws = wb.active
    for _ in range(max(header_row - 1, 0)):
        ws.append(["" for _ in headers])
    ws.append(headers)
    _formatar_cabecalho_planilha(ws, header_row, len(headers))

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    temp.close()
    wb.save(temp.name)
    return temp.name, nome_arquivo


def _criar_modelo_os_processos_xlsx():
    wb = Workbook()
    ws = wb.active
    headers = [
        "OPERACAO", "10 - CORTE",
        "OPERACAO", "20 - AR CONDICIONADO",
        "OPERACAO", "30 - PREPARACAO DE PECAS",
        "OPERACAO", "40 - ELETRICA 1",
        "OPERACAO", "50 - ISOLAMENTO",
        "OPERACAO", "60 - REVESTIMENTO 1",
        "OPERACAO", "70 - REVESTIMENTO 2",
        "OPERACAO", "80 - ELETRICA 2",
        "OPERACAO", "90 - LIMPEZA/LIBERACAO",
        "OPERACAO", "95 - ACESSORIOS",
        "OPERACAO", "100 - BANCO",
    ]
    ws.append(headers)

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    temp.close()
    wb.save(temp.name)
    return temp.name, "modelo_os_processos.xlsx"


def _catalogo_itens_regras():
    catalogo = dict(carregar_produtos() or {})
    catalogo.update(carregar_os_produtos() or {})
    return catalogo


def _descricao_item_regras(codigo, catalogo):
    info = (catalogo or {}).get(normalizar_codigo(codigo), {}) or {}
    return str(info.get("descricao", "") or "").strip()


def _formatar_planilha_regras(ws, headers):
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
    ws.sheet_view.showGridLines = False
    fill = PatternFill("solid", fgColor="1F4E78")
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24


def _adicionar_instrucoes_planilha(wb, titulo, instrucoes):
    ws = wb.create_sheet("Instrucoes")
    ws.sheet_view.showGridLines = False
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=14, color="1F4E78")
    for idx, instrucao in enumerate(instrucoes, 3):
        ws.cell(row=idx, column=1, value=f"{idx - 2}.")
        ws.cell(row=idx, column=2, value=instrucao)
        ws.cell(row=idx, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 110


def _salvar_planilha_temporaria(wb, nome_arquivo):
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    temp.close()
    wb.save(temp.name)
    return temp.name, nome_arquivo


def _criar_planilha_regras_popup_item(regras=None, nome_arquivo="modelo_parametros_item_relacionado.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Parametros Item Relacionado"
    _formatar_planilha_regras(ws, MODELO_REGRAS_POPUP_HEADERS)
    catalogo = _catalogo_itens_regras()

    for regra in regras or []:
        gatilho = normalizar_codigo(regra.get("gatilho", ""))
        opcoes = [normalizar_codigo(codigo) for codigo in regra.get("opcoes", []) if normalizar_codigo(codigo)]
        ws.append(
            [
                str(regra.get("id", "") or ""),
                gatilho,
                _descricao_item_regras(gatilho, catalogo),
                "; ".join(opcoes),
                " | ".join(_descricao_item_regras(codigo, catalogo) for codigo in opcoes),
                regra.get("quantidade", 1),
                "SIM" if regra.get("quantidade_editavel") else "NAO",
            ]
        )

    widths = [16, 18, 54, 42, 72, 14, 24]
    for idx, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    for row_idx in range(2, ws.max_row + 1):
        ws.cell(row=row_idx, column=2).number_format = "@"
        ws.cell(row=row_idx, column=4).number_format = "@"
    ws.auto_filter.ref = f"A1:G{max(ws.max_row, 1)}"
    validacao = DataValidation(type="list", formula1='"SIM,NAO"', allow_blank=False)
    ws.add_data_validation(validacao)
    validacao.add("G2:G1000")

    _adicionar_instrucoes_planilha(
        wb,
        "Parametros de Item Relacionado",
        [
            "Use uma linha por regra. Separe varios codigos em ITENS_OPCOES com ponto e virgula (;).",
            "ID_REGRA e opcional para regras novas. No arquivo exportado, mantenha o ID para atualizar a regra existente.",
            "QUANTIDADE deve ser maior que zero. QUANTIDADE_EDITAVEL aceita SIM ou NAO.",
            "A importacao mescla os dados: atualiza IDs existentes e adiciona novas regras sem apagar as demais.",
            "As colunas de descricao servem apenas para conferencia e nao sao usadas na importacao.",
        ],
    )
    return _salvar_planilha_temporaria(wb, nome_arquivo)


def _criar_planilha_relacoes_processo_item(relacoes=None, nome_arquivo="modelo_relacao_processo_item.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Relacao Processo x Item"
    _formatar_planilha_regras(ws, MODELO_RELACOES_PROCESSO_HEADERS)
    catalogo = _catalogo_itens_regras()

    for codigo, processos in (relacoes or {}).items():
        codigo = normalizar_codigo(codigo)
        ws.append(
            [
                codigo,
                _descricao_item_regras(codigo, catalogo),
                "; ".join(str(processo or "").strip() for processo in processos if str(processo or "").strip()),
            ]
        )

    widths = [18, 58, 96]
    for idx, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    for row_idx in range(2, ws.max_row + 1):
        ws.cell(row=row_idx, column=1).number_format = "@"
    ws.auto_filter.ref = f"A1:C{max(ws.max_row, 1)}"

    _adicionar_instrucoes_planilha(
        wb,
        "Relacao Processo x Item",
        [
            "Use uma linha por item. Separe varios processos na coluna PROCESSOS com ponto e virgula (;).",
            "O nome do processo deve ser identico ao nome do arquivo/conjunto importado na base de processos.",
            "A importacao mescla os dados: substitui os processos dos itens informados e preserva os demais itens.",
            "A coluna DESCRICAO_ITEM serve apenas para conferencia e nao e usada na importacao.",
        ],
    )
    return _salvar_planilha_temporaria(wb, nome_arquivo)


def normalizar_header(texto):
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    return (
        texto.replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("ç", "c")
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
    )


def ler_linhas_arquivo(file_storage):
    filename = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(filename)[1].lower()

    if ext in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
        wb = load_workbook(file_storage, data_only=True)
        ws = wb.active
        linhas = []
        for row in ws.iter_rows(values_only=True):
            linha = ["" if cell is None else str(cell).strip() for cell in row]
            if any(linha):
                linhas.append(linha)
        return linhas

    return []


def _corrigir_mojibake(texto):
    texto = "" if texto is None else str(texto).strip()
    if not texto:
        return ""
    if any(token in texto for token in ("Ã", "Â", "�")):
        for encoding in ("latin1", "cp1252"):
            try:
                convertido = texto.encode(encoding).decode("utf-8")
            except Exception:
                continue
            if convertido:
                texto = convertido
                break
    return texto


def normalizar_header(texto):
    if texto is None:
        return ""
    texto = _corrigir_mojibake(texto)
    texto = unicodedata.normalize("NFKD", str(texto).strip().lower())
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return texto.strip("_")


def _canonicalizar_header(texto):
    normalizado = normalizar_header(texto)
    if not normalizado:
        return ""
    for canonico, aliases in HEADER_ALIASES.items():
        if normalizado == canonico or normalizado in aliases:
            return canonico
    return normalizado


def _resolver_header_importacao(linhas, campos_esperados=None):
    campos_esperados = set(campos_esperados or [])
    melhor_idx = 0
    melhor_score = -1
    for idx in range(min(len(linhas), 5)):
        headers_canonicos = [_canonicalizar_header(valor) for valor in linhas[idx]]
        score = 0
        for header in headers_canonicos:
            if not header:
                continue
            if header in campos_esperados:
                score += 3
            elif header in HEADER_ALIASES:
                score += 2
            elif any(header in aliases for aliases in HEADER_ALIASES.values()):
                score += 1
        if score > melhor_score:
            melhor_idx = idx
            melhor_score = score

    header_raw = linhas[melhor_idx]
    header = [_canonicalizar_header(h) for h in header_raw]
    mapa = {}
    for idx, nome in enumerate(header):
        if nome and nome not in mapa:
            mapa[nome] = idx
    return header_raw, header, mapa, linhas[melhor_idx + 1:]


def _valor_coluna(row, mapa, *colunas):
    for coluna in colunas:
        idx = mapa.get(coluna)
        if idx is None or idx >= len(row):
            continue
        valor = _corrigir_mojibake(row[idx])
        if valor != "":
            return valor
    return ""


def _coletar_campos_extras(row, header_raw, header, usados):
    extras = {}
    for idx, _ in enumerate(header_raw):
        nome = header[idx] if idx < len(header) else ""
        if not nome or nome in usados or nome in CAMPOS_PRODUTO_DESCARTADOS or idx >= len(row):
            continue
        valor = _corrigir_mojibake(row[idx])
        if valor == "":
            continue
        extras[nome] = valor
    return extras


def _montar_descricao_importacao(row, mapa):
    partes = [
        _valor_coluna(row, mapa, "descricao"),
        _valor_coluna(row, mapa, "descricao_secundaria"),
        _valor_coluna(row, mapa, "sufixo"),
    ]
    return " ".join(parte for parte in partes if parte).strip()


def _mesclar_dados_item(atual, novos, extras=None):
    item = dict(atual or {})
    for campo in CAMPOS_PRODUTO_DESCARTADOS:
        item.pop(campo, None)
    for campo in ITEM_CAMPOS_BASE:
        valor = novos.get(campo, "")
        if valor != "":
            item[campo] = valor
        else:
            item[campo] = item.get(campo, "")

    extras_existentes = dict(item.get("campos_extras", {}) or {})
    for chave, valor in (extras or {}).items():
        if valor != "":
            extras_existentes[chave] = valor
    if extras_existentes:
        item["campos_extras"] = extras_existentes
    elif "campos_extras" in item:
        item["campos_extras"] = item.get("campos_extras", {})
    return item


def ler_linhas_arquivo(file_storage):
    filename = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(filename)[1].lower()

    if ext in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
        wb = load_workbook(file_storage, data_only=True)
        ws = wb.active
        linhas = []
        for row in ws.iter_rows(values_only=True):
            linha = [_corrigir_mojibake(cell) for cell in row]
            if any(linha):
                linhas.append(linha)
        return linhas

    return []


def importar_produtos(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header_raw, header, mapa, rows = _resolver_header_importacao(
        linhas,
        campos_esperados={"codigo", "descricao", "unidade", "grupo", "categoria"},
    )

    produtos = carregar_produtos()
    count = 0

    for row in rows:
        codigo = normalizar_codigo(_valor_coluna(row, mapa, "codigo"))
        if not codigo:
            continue
        atual = produtos.get(codigo, {})
        usados = {
            "codigo",
            "descricao",
            "descricao_secundaria",
            "sufixo",
            "unidade",
            "grupo",
            "categoria",
            "processo_conjunto",
        }
        novos = {
            "descricao": _montar_descricao_importacao(row, mapa),
            "unidade": _valor_coluna(row, mapa, "unidade"),
            "grupo": _valor_coluna(row, mapa, "grupo"),
            "categoria": _valor_coluna(row, mapa, "categoria"),
            "processo_conjunto": _valor_coluna(row, mapa, "processo_conjunto"),
        }
        extras = _coletar_campos_extras(row, header_raw, header, usados)
        produtos[codigo] = _mesclar_dados_item(atual, novos, extras=extras)
        count += 1

    salvar_json(PRODUTOS_FILE, produtos)
    return count


def atualizar_skus_arquivo(skus_file=None, somente_se_mais_novo=False):
    skus_file = skus_file or get_skus_file()
    resultado = {
        "arquivo": skus_file,
        "linhas": 0,
        "atualizado": False,
        "ignorado": False,
        "erro": "",
    }
    if not skus_file or not os.path.isfile(_win_long_path(skus_file)):
        resultado["erro"] = f"Arquivo de SKUs nao encontrado: {skus_file}"
        return resultado

    if somente_se_mais_novo and os.path.exists(PRODUTOS_FILE):
        try:
            if os.path.getmtime(_win_long_path(skus_file)) <= os.path.getmtime(PRODUTOS_FILE):
                resultado["ignorado"] = True
                return resultado
        except Exception:
            pass

    try:
        with _open_for_read(skus_file) as arquivo:
            storage = FileStorage(stream=arquivo, filename=os.path.basename(skus_file))
            resultado["linhas"] = importar_produtos(storage)
        resultado["atualizado"] = resultado["linhas"] > 0
        app.logger.info("Importado cadastro de SKUs %s (%s linhas)", skus_file, resultado["linhas"])
    except PermissionError:
        app.logger.exception("Falha ao importar cadastro de SKUs (arquivo em uso) %s", skus_file)
        resultado["erro"] = f"Arquivo de SKUs em uso no Excel: {os.path.basename(skus_file)}"
    except Exception as exc:
        app.logger.exception("Falha ao importar cadastro de SKUs %s", skus_file)
        resultado["erro"] = f"Falha ao importar SKUs: {exc}"
    return resultado


def atualizar_skus_automatico():
    return atualizar_skus_arquivo(somente_se_mais_novo=True)


def importar_fornecedores(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    _, _, mapa, rows = _resolver_header_importacao(
        linhas,
        campos_esperados={"fornecedor", "cnpj", "razao_social", "email"},
    )

    fornecedores = carregar_fornecedores()
    count = 0

    for row in rows:
        fornecedor = _valor_coluna(row, mapa, "fornecedor")
        cnpj = _valor_coluna(row, mapa, "cnpj")
        chave = cnpj if cnpj else fornecedor
        if not chave:
            continue

        atual = fornecedores.get(chave, {})
        def _pick(campo, valor):
            return valor if valor != "" else atual.get(campo, "")
        fornecedores[chave] = {
            "fornecedor": _pick("fornecedor", fornecedor),
            "razao_social": _pick("razao_social", _valor_coluna(row, mapa, "razao_social")),
            "cnpj": _pick("cnpj", cnpj),
            "email": _pick("email", _valor_coluna(row, mapa, "email")),
            "telefone": _pick("telefone", _valor_coluna(row, mapa, "telefone")),
            "endereco": _pick("endereco", _valor_coluna(row, mapa, "endereco")),
            "bairro": _pick("bairro", _valor_coluna(row, mapa, "bairro")),
            "cidade": _pick("cidade", _valor_coluna(row, mapa, "cidade")),
            "uf": _pick("uf", _valor_coluna(row, mapa, "uf")),
            "cep": _pick("cep", _valor_coluna(row, mapa, "cep")),
        }
        count += 1

    salvar_json(FORNECEDORES_FILE, fornecedores)
    return count


def importar_os_produtos(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header_raw, header, mapa, rows = _resolver_header_importacao(
        linhas,
        campos_esperados={"codigo", "descricao", "unidade", "grupo", "categoria"},
    )

    produtos = carregar_os_produtos()
    count = 0

    for row in rows:
        codigo = normalizar_codigo(_valor_coluna(row, mapa, "codigo"))
        if not codigo:
            continue
        atual = produtos.get(codigo, {})
        usados = {
            "codigo",
            "descricao",
            "descricao_secundaria",
            "sufixo",
            "unidade",
            "grupo",
            "categoria",
        }
        novos = {
            "descricao": _montar_descricao_importacao(row, mapa),
            "unidade": _valor_coluna(row, mapa, "unidade"),
            "grupo": _valor_coluna(row, mapa, "grupo"),
            "categoria": _valor_coluna(row, mapa, "categoria"),
        }
        extras = _coletar_campos_extras(row, header_raw, header, usados)
        produtos[codigo] = _mesclar_dados_item(atual, novos, extras=extras)
        count += 1

    salvar_json(OS_PRODUTOS_FILE, produtos)
    return count


def importar_os_fornecedores(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    _, _, mapa, rows = _resolver_header_importacao(
        linhas,
        campos_esperados={"cliente", "fornecedor"},
    )

    fornecedores = carregar_os_fornecedores()
    count = 0

    for row in rows:
        fornecedor = _valor_coluna(row, mapa, "fornecedor", "cliente")
        chave = fornecedor
        if not chave:
            continue

        atual = fornecedores.get(chave, {})
        fornecedores[chave] = {
            "cliente": fornecedor if fornecedor != "" else atual.get("cliente", ""),
        }
        count += 1

    salvar_json(OS_FORNECEDORES_FILE, fornecedores)
    return count


def _normalizar_codigo_planilha(valor):
    texto = _corrigir_mojibake(valor)
    if re.fullmatch(r"\d+\.0+", texto):
        texto = texto.split(".", 1)[0]
    return normalizar_codigo(texto)


def _separar_lista_planilha(valor):
    texto = _corrigir_mojibake(valor)
    valores = []
    for parte in re.split(r"[;\r\n]+", texto):
        parte = str(parte or "").strip()
        if parte and parte not in valores:
            valores.append(parte)
    return valores


def _quantidade_regra_planilha(valor):
    texto = _corrigir_mojibake(valor).replace(",", ".")
    if not texto:
        return 1.0
    try:
        quantidade = float(texto)
    except Exception as exc:
        raise ValueError("quantidade invalida") from exc
    if quantidade <= 0:
        raise ValueError("quantidade deve ser maior que zero")
    return quantidade


def _booleano_planilha(valor):
    texto = normalizar_header(_corrigir_mojibake(valor))
    if texto in {"sim", "s", "1", "true", "verdadeiro", "x"}:
        return True
    if texto in {"", "nao", "n", "0", "false", "falso"}:
        return False
    raise ValueError("quantidade_editavel deve ser SIM ou NAO")


def _assinatura_regra_popup(regra):
    return (
        normalizar_codigo(regra.get("gatilho", "")),
        tuple(normalizar_codigo(codigo) for codigo in regra.get("opcoes", []) if normalizar_codigo(codigo)),
        float(regra.get("quantidade", 1) or 1),
        bool(regra.get("quantidade_editavel", False)),
    )


def importar_regras_popup_item_planilha(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        raise ValueError("A planilha esta vazia ou nao esta em formato XLSX.")

    _, _, mapa, rows = _resolver_header_importacao(
        linhas,
        campos_esperados={
            "id_regra",
            "item_gatilho",
            "itens_opcoes",
            "quantidade",
            "quantidade_editavel",
        },
    )
    if "item_gatilho" not in mapa or "itens_opcoes" not in mapa:
        raise ValueError("Cabecalho invalido. Use ITEM_GATILHO e ITENS_OPCOES.")

    regras = carregar_regras_popup_item()
    resultado = [dict(regra) for regra in regras]
    indice_por_id = {
        str(regra.get("id", "") or "").strip(): idx
        for idx, regra in enumerate(resultado)
        if str(regra.get("id", "") or "").strip()
    }
    ids_usados = set(indice_por_id)
    assinaturas = {_assinatura_regra_popup(regra) for regra in resultado}
    proximo_numero = max(
        [int(re.sub(r"\D", "", regra_id) or 0) for regra_id in ids_usados] or [0]
    ) + 1
    novas = 0
    atualizadas = 0
    ignoradas = 0
    erros = []

    for numero_linha, row in enumerate(rows, 2):
        gatilho = _normalizar_codigo_planilha(_valor_coluna(row, mapa, "item_gatilho", "gatilho"))
        opcoes = [
            _normalizar_codigo_planilha(valor)
            for valor in _separar_lista_planilha(_valor_coluna(row, mapa, "itens_opcoes", "opcoes", "item_opcao"))
        ]
        opcoes = list(dict.fromkeys(codigo for codigo in opcoes if codigo))
        regra_id = _valor_coluna(row, mapa, "id_regra", "id").strip()
        if not gatilho and not opcoes and not regra_id:
            continue
        if not gatilho or not opcoes:
            ignoradas += 1
            erros.append(f"linha {numero_linha}: informe gatilho e opcoes")
            continue
        try:
            quantidade = _quantidade_regra_planilha(_valor_coluna(row, mapa, "quantidade"))
            quantidade_editavel = _booleano_planilha(
                _valor_coluna(row, mapa, "quantidade_editavel", "alteravel")
            )
        except ValueError as exc:
            ignoradas += 1
            erros.append(f"linha {numero_linha}: {exc}")
            continue

        registro = {
            "id": regra_id,
            "gatilho": gatilho,
            "opcoes": opcoes,
            "quantidade": quantidade,
            "quantidade_editavel": quantidade_editavel,
        }
        if regra_id and regra_id in indice_por_id:
            resultado[indice_por_id[regra_id]] = registro
            atualizadas += 1
            assinaturas.add(_assinatura_regra_popup(registro))
            continue

        assinatura = _assinatura_regra_popup(registro)
        if not regra_id and assinatura in assinaturas:
            ignoradas += 1
            continue
        if not regra_id:
            while f"regra-{proximo_numero}" in ids_usados:
                proximo_numero += 1
            regra_id = f"regra-{proximo_numero}"
            proximo_numero += 1
            registro["id"] = regra_id

        ids_usados.add(regra_id)
        indice_por_id[regra_id] = len(resultado)
        resultado.append(registro)
        assinaturas.add(assinatura)
        novas += 1

    if novas == 0 and atualizadas == 0 and ignoradas == 0:
        raise ValueError("Nenhuma regra foi encontrada na planilha.")
    if novas or atualizadas:
        salvar_regras_popup_item(resultado)
    return {
        "novas": novas,
        "atualizadas": atualizadas,
        "ignoradas": ignoradas,
        "erros": erros,
    }


def importar_relacoes_processo_item_planilha(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        raise ValueError("A planilha esta vazia ou nao esta em formato XLSX.")

    _, _, mapa, rows = _resolver_header_importacao(
        linhas,
        campos_esperados={"item_codigo", "processos"},
    )
    if "item_codigo" not in mapa or not any(campo in mapa for campo in ("processos", "processo", "processo_conjunto")):
        raise ValueError("Cabecalho invalido. Use ITEM_CODIGO e PROCESSOS.")

    importadas = {}
    ignoradas = 0
    erros = []
    for numero_linha, row in enumerate(rows, 2):
        codigo = _normalizar_codigo_planilha(_valor_coluna(row, mapa, "item_codigo", "codigo", "item"))
        processos = _separar_lista_planilha(
            _valor_coluna(row, mapa, "processos", "processo", "processo_conjunto")
        )
        if not codigo and not processos:
            continue
        if not codigo or not processos:
            ignoradas += 1
            erros.append(f"linha {numero_linha}: informe item e processos")
            continue
        destino = importadas.setdefault(codigo, [])
        for processo in processos:
            if processo not in destino:
                destino.append(processo)

    if not importadas and ignoradas == 0:
        raise ValueError("Nenhuma relacao foi encontrada na planilha.")

    relacoes = carregar_relacoes_processo_item()
    novas = 0
    atualizadas = 0
    sem_alteracao = 0
    for codigo, processos in importadas.items():
        atuais = relacoes.get(codigo)
        if atuais is None:
            novas += 1
        elif atuais == processos:
            sem_alteracao += 1
        else:
            atualizadas += 1
        relacoes[codigo] = processos

    if novas or atualizadas:
        salvar_relacoes_processo_item(relacoes)
    return {
        "novas": novas,
        "atualizadas": atualizadas,
        "ignoradas": ignoradas + sem_alteracao,
        "erros": erros,
    }


def importar_os_componentes(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header = [normalizar_header(h) for h in linhas[0]]
    mapa = {name: idx for idx, name in enumerate(header)}

    componentes = carregar_os_componentes()
    produtos = carregar_os_produtos()
    count = 0
    vistos = set()
    item_codigo_atual = ""

    def normalizar_descricao_item(valor):
        return " ".join(str(valor or "").strip().upper().split())

    descricao_para_codigos = {}
    for codigo_produto, info in (produtos or {}).items():
        descricao_produto = normalizar_descricao_item(info.get("descricao", ""))
        if not descricao_produto:
            continue
        descricao_para_codigos.setdefault(descricao_produto, set()).add(codigo_produto)

    item_bloco_descricao = ""
    idx_item_bloco = mapa.get("item_bloco")
    if idx_item_bloco is not None and (idx_item_bloco + 1) < len(linhas[0]):
        item_bloco_descricao = str(linhas[0][idx_item_bloco + 1]).strip()

    item_codigo_alias = ""
    if item_bloco_descricao:
        codigos_match = sorted(
            descricao_para_codigos.get(normalizar_descricao_item(item_bloco_descricao), set())
        )
        if len(codigos_match) == 1:
            item_codigo_alias = codigos_match[0]

    for row in linhas[1:]:
        def pegar(col):
            idx = mapa.get(col)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        item_codigo_linha = normalizar_codigo(
            pegar("item_codigo")
            or pegar("codigo_item")
            or pegar("codigo_pai")
            or pegar("item")
            or pegar("codigo")
        )
        if item_codigo_linha:
            item_codigo_atual = item_codigo_linha

        item_codigo = item_codigo_atual
        if not item_codigo:
            continue

        comp = {
            "codigo": normalizar_codigo(pegar("componente_codigo") or pegar("codigo_componente")),
            "descricao": pegar("descricao"),
            "unidade": pegar("unidade"),
            "quantidade": pegar("quantidade") or pegar("qtd"),
        }

        if not (comp["codigo"] or comp["descricao"] or comp["unidade"] or comp["quantidade"]):
            continue

        destinos = [item_codigo]
        if item_codigo_alias and item_codigo_alias not in destinos:
            destinos.append(item_codigo_alias)

        for item_destino in destinos:
            if item_destino not in vistos:
                componentes[item_destino] = []
                vistos.add(item_destino)
            componentes.setdefault(item_destino, []).append(dict(comp))
        count += 1

    salvar_json(OS_COMPONENTES_FILE, componentes)
    return count


EXCEL_EXTS_IMPORTACAO = {".xls", ".xlsx", ".xlsm", ".xltx", ".xltm"}


def listar_arquivos_excel_base(pasta):
    arquivos = []
    for root, _, nomes in os.walk(pasta):
        for nome in nomes:
            if nome.startswith("~$"):
                continue
            if os.path.splitext(nome)[1].lower() in EXCEL_EXTS_IMPORTACAO:
                arquivos.append(os.path.join(root, nome))
    arquivos.sort()
    return arquivos


def importar_bom_diretorio(bom_dir, somente_se_mais_novo=False):
    arquivos = listar_arquivos_excel_base(bom_dir)
    if not arquivos:
        return {
            "arquivos": 0,
            "linhas": 0,
            "falhas": 0,
            "em_uso": [],
            "com_erro": [],
            "atualizado": False,
        }

    if somente_se_mais_novo and os.path.exists(OS_COMPONENTES_FILE):
        base_mtime = os.path.getmtime(OS_COMPONENTES_FILE)
        mtimes = []
        for caminho in arquivos:
            try:
                mtimes.append(os.path.getmtime(caminho))
            except FileNotFoundError:
                app.logger.warning("B.O.M. ignorada porque nao esta mais acessivel: %s", caminho)
        if not mtimes:
            return {
                "arquivos": 0,
                "linhas": 0,
                "falhas": 0,
                "em_uso": [],
                "com_erro": [],
                "atualizado": False,
            }
        mais_novo = max(mtimes)
        if mais_novo <= base_mtime:
            return {
                "arquivos": len(arquivos),
                "linhas": 0,
                "falhas": 0,
                "em_uso": [],
                "com_erro": [],
                "atualizado": False,
            }

    arquivos_processados = 0
    linhas_importadas = 0
    falhas = 0
    arquivos_em_uso = []
    arquivos_com_erro = []
    for caminho in arquivos:
        try:
            with _open_for_read(caminho) as arquivo:
                storage = FileStorage(stream=arquivo, filename=os.path.basename(caminho))
                linhas_importadas += importar_os_componentes(storage)
            arquivos_processados += 1
            app.logger.info("Importado B.O.M. %s", caminho)
        except PermissionError:
            app.logger.exception("Falha ao importar B.O.M. (arquivo em uso) %s", caminho)
            arquivos_em_uso.append(os.path.basename(caminho))
            falhas += 1
        except Exception:
            app.logger.exception("Falha ao importar B.O.M. %s", caminho)
            arquivos_com_erro.append(os.path.basename(caminho))
            falhas += 1

    return {
        "arquivos": arquivos_processados,
        "linhas": linhas_importadas,
        "falhas": falhas,
        "em_uso": arquivos_em_uso,
        "com_erro": arquivos_com_erro,
        "atualizado": arquivos_processados > 0,
    }


def importar_os_processos(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header_raw = ["" if h is None else str(h).strip() for h in linhas[0]]
    header_norm = [normalizar_header(h) for h in header_raw]

    processos = {"PADRAO": {}}
    count = 0

    # formato "longo": colunas processo/atividade/responsavel
    if "processo" in header_norm:
        mapa = {name: idx for idx, name in enumerate(header_norm)}
        staged_por_conjunto = {}

        for row in linhas[1:]:
            def pegar(col):
                idx = mapa.get(col)
                if idx is None or idx >= len(row):
                    return ""
                return str(row[idx]).strip()

            conjunto = pegar("conjunto") or pegar("grupo") or "PADRAO"
            processo = pegar("processo")
            atividade = pegar("atividade")
            responsavel = pegar("responsavel")
            if not processo or not atividade:
                continue

            processo_norm = processo.strip().upper()
            mapa_proc = {
                "CORTE": "CORTE",
                "AR CONDICIONADO": "AR CONDICIONADO",
                "PREPARACAO DE PECAS": "PREPARAÇÃO DE PEÇAS",
                "PREPARAÇÃO DE PEÇAS": "PREPARAÇÃO DE PEÇAS",
                "ISOLAMENTO": "ISOLAMENTO",
                "DESMONTAGEM E ISOLAMENTO": "ISOLAMENTO",
                "REVESTIMENTO": "REVESTIMENTO",
                "BANCOS": "BANCOS",
                "ELETRICA": "ELÉTRICA 2",
                "ELÉTRICA": "ELÉTRICA 2",
                "ELÉTRICA 2": "ELÉTRICA 2",
                "LIMPEZA/LIBERACAO": "LIMPEZA/LIBERAÇÃO",
                "LIMPEZA/LIBERAÇÃO": "LIMPEZA/LIBERAÇÃO",
            }
            processo_key = normalizar_nome_processo(mapa_proc.get(processo_norm, processo))

            processos.setdefault(conjunto, {})
            processos[conjunto].setdefault(processo_key, []).append({
                "atividade": atividade,
                "responsavel": responsavel,
            })
            count += 1

        salvar_json(OS_PROCESSOS_FILE, processos)
        return count

    # formato "largo": cada coluna = processo, cada linha = atividade
    conjunto = "PADRAO"
    processos.setdefault(conjunto, {})

    for col_idx, processo in enumerate(header_raw):
        processo = processo.strip()
        if not processo:
            continue
        processo_norm = processo.upper()
        mapa_proc = {
            "CORTE": "CORTE",
            "AR CONDICIONADO": "AR CONDICIONADO",
            "PREPARACAO DE PECAS": "PREPARAÇÃO DE PEÇAS",
            "PREPARAÇÃO DE PEÇAS": "PREPARAÇÃO DE PEÇAS",
            "ISOLAMENTO": "ISOLAMENTO",
            "DESMONTAGEM E ISOLAMENTO": "ISOLAMENTO",
            "REVESTIMENTO": "REVESTIMENTO",
            "BANCOS": "BANCOS",
            "ELETRICA": "ELÉTRICA 2",
            "ELÉTRICA": "ELÉTRICA 2",
            "ELÉTRICA 2": "ELÉTRICA 2",
            "LIMPEZA/LIBERACAO": "LIMPEZA/LIBERAÇÃO",
            "LIMPEZA/LIBERAÇÃO": "LIMPEZA/LIBERAÇÃO",
        }
        processo_key = normalizar_nome_processo(mapa_proc.get(processo_norm, processo))
        processos[conjunto].setdefault(processo_key, [])

        for row in linhas[1:]:
            if col_idx >= len(row):
                continue
            atividade = str(row[col_idx]).strip()
            if not atividade:
                continue
            processos[conjunto][processo_key].append({
                "atividade": atividade,
                "responsavel": "",
            })
            count += 1

    salvar_json(OS_PROCESSOS_FILE, processos)
    return count


def importar_os_processos_atualizado(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    def nome_conjunto_arquivo(filename):
        nome = os.path.splitext(os.path.basename(filename or ""))[0].strip()
        if not nome:
            return "PADRAO"
        partes = [parte.strip() for parte in nome.split(" - ") if parte.strip()]
        if len(partes) >= 3 and normalizar_header(partes[1]).startswith("processo_transformacao"):
            nome = " - ".join(partes[2:])
        if normalizar_header(nome) == "template":
            return "PADRAO"
        return nome or "PADRAO"

    def remover_sufixo_banco(nome):
        partes = [parte.strip() for parte in str(nome or "").split(" - ") if parte.strip()]
        if len(partes) >= 2 and normalizar_nome_processo(partes[-1]) == "BANCO":
            return " - ".join(partes[:-1]).strip() or nome
        return nome

    header_raw = ["" if h is None else str(h).strip() for h in linhas[0]]
    header_norm = [normalizar_header(h) for h in header_raw]

    processos = carregar_os_processos()
    conjunto_arquivo = nome_conjunto_arquivo(getattr(file_storage, "filename", ""))
    count = 0
    conjuntos_tocados = set()

    def preparar_conjunto(conjunto, reset_all=False, preservar_processos=None):
        if conjunto in conjuntos_tocados:
            return
        base = processos.get(conjunto, {})
        processos[conjunto] = {
            nome: list(base.get(nome, [])) if not reset_all else []
            for nome in PROCESSOS_ORDEM
        }
        for nome in preservar_processos or []:
            if nome in processos[conjunto]:
                processos[conjunto][nome] = list(base.get(nome, []))
        conjuntos_tocados.add(conjunto)

    if "processo" in header_norm:
        mapa = {name: idx for idx, name in enumerate(header_norm)}
        staged_por_conjunto = {}

        for row in linhas[1:]:
            def pegar(col):
                idx = mapa.get(col)
                if idx is None or idx >= len(row):
                    return ""
                return str(row[idx]).strip()

            conjunto = pegar("conjunto") or pegar("grupo") or conjunto_arquivo or "PADRAO"
            processo = normalizar_nome_processo(pegar("processo"))
            atividade = pegar("atividade")
            responsavel = pegar("responsavel")
            if processo not in PROCESSOS_ORDEM or not atividade:
                continue

            staged_por_conjunto.setdefault(conjunto, {}).setdefault(processo, []).append({
                "atividade": atividade,
                "responsavel": responsavel,
            })
            count += 1

        if count == 0:
            return 0

        for conjunto, staged in staged_por_conjunto.items():
            preservar = set(PROCESSOS_ORDEM) - set(staged)
            preparar_conjunto(conjunto, reset_all=True, preservar_processos=preservar)
            for processo, linhas_processo in staged.items():
                processos[conjunto][processo] = linhas_processo

        salvar_json(OS_PROCESSOS_FILE, processos)
        return count

    conjunto = conjunto_arquivo or "PADRAO"
    colunas_processo = []
    for col_idx, processo in enumerate(header_raw):
        processo_nome = normalizar_nome_processo(processo)
        if processo_nome not in PROCESSOS_ORDEM:
            continue
        colunas_processo.append((col_idx, processo_nome))

    if not colunas_processo:
        return 0

    staged = {}
    for col_idx, processo_nome in colunas_processo:
        linhas_processo = []
        for row in linhas[1:]:
            if col_idx >= len(row):
                continue
            atividade = str(row[col_idx]).strip()
            if not atividade:
                continue
            linhas_processo.append({
                "atividade": atividade,
                "responsavel": "",
            })
        staged[processo_nome] = linhas_processo
        count += len(linhas_processo)

    # Nao limpamos a base quando o arquivo e apenas um template vazio.
    if count == 0:
        return 0

    nomes_importados = set(staged)
    somente_banco = nomes_importados == {"BANCO"}
    if somente_banco:
        conjunto = remover_sufixo_banco(conjunto)
    preservar = set(PROCESSOS_ORDEM) - nomes_importados
    preparar_conjunto(conjunto, reset_all=True, preservar_processos=preservar)

    for processo_nome, linhas_processo in staged.items():
        processos[conjunto][processo_nome] = linhas_processo

    salvar_json(OS_PROCESSOS_FILE, processos)
    return count


def mesclar_processos_modelo(processos, conjuntos):
    processos_final = {nome: [] for nome in PROCESSOS_ORDEM}
    vistos = {nome: set() for nome in PROCESSOS_ORDEM}
    for conjunto in conjuntos or []:
        modelo = processos.get(conjunto) or {}
        for nome in PROCESSOS_ORDEM:
            for linha in modelo.get(nome) or []:
                atividade = str((linha or {}).get("atividade", "")).strip()
                responsavel = str((linha or {}).get("responsavel", "")).strip()
                if not atividade:
                    continue
                chave = (atividade, responsavel)
                if chave in vistos[nome]:
                    continue
                processos_final[nome].append({
                    "atividade": atividade,
                    "responsavel": responsavel,
                })
                vistos[nome].add(chave)
    return processos_final


def proximo_numero_oc():

    if not os.path.exists(COUNTER_FILE):

        with open(COUNTER_FILE, "w") as f:
            f.write("1")

    with open(COUNTER_FILE, "r") as f:
        numero = int(f.read())

    novo = numero + 1

    with open(COUNTER_FILE, "w") as f:
        f.write(str(novo))

    return novo


def proximo_numero_os():

    if not os.path.exists(OS_COUNTER_FILE):

        with open(OS_COUNTER_FILE, "w") as f:
            f.write("1")

    with open(OS_COUNTER_FILE, "r") as f:
        numero = int(f.read())

    novo = numero + 1

    with open(OS_COUNTER_FILE, "w") as f:
        f.write(str(novo))

    return numero


@app.route("/")
def index():

    resultado_skus_auto = atualizar_skus_automatico()
    produtos = carregar_produtos()
    fornecedores = carregar_fornecedores()
    os_produtos = carregar_os_produtos()
    os_fornecedores = carregar_os_fornecedores()
    os_componentes = carregar_os_componentes()
    os_processos = carregar_os_processos()
    relacoes_processo_item = carregar_relacoes_processo_item()
    regras_popup_item = carregar_regras_popup_item()
    processo_por_item = construir_processo_por_item(
        os_produtos,
        os_processos.keys(),
        relacoes_processo_item,
    )
    oc_prefill = carregar_importacao(OC_IMPORT_FILE)
    os_prefill = carregar_importacao(OS_IMPORT_FILE)
    tab = request.args.get("tab", "oc")
    historico = carregar_historico()
    oc_totais = _agrupar_por_data(historico, "oc", "total_pedido")
    os_quantidades = _agrupar_por_data(historico, "os", None)
    dashboard = {
        "oc_totais": oc_totais,
        "os_quantidades": os_quantidades,
    }
    pedidos_dir, os_dir = get_save_paths()
    bom_dir = get_bom_dir()
    skus_file = get_skus_file()
    processos_dir = get_processos_dir()
    save_paths = {
        "pedidos_dir": pedidos_dir,
        "os_dir": os_dir,
        "bom_dir": bom_dir,
        "skus_file": skus_file,
        "processos_dir": processos_dir,
    }
    bom_status = request.args.get("bom_status")
    skus_status = request.args.get("skus_status")
    if not skus_status and resultado_skus_auto.get("atualizado"):
        skus_status = f"SKUs atualizados automaticamente ({resultado_skus_auto['linhas']} linhas)."
    os_processos_status = request.args.get("os_processos_status")
    regras_popup_status = request.args.get("regras_popup_status")
    relacoes_processo_status = request.args.get("relacoes_processo_status")

    return render_template(
        "index.html",
        produtos=produtos,
        fornecedores=fornecedores,
        os_produtos=os_produtos,
        os_fornecedores=os_fornecedores,
        os_componentes=os_componentes,
        os_processos=os_processos,
        oc_prefill=oc_prefill,
        os_prefill=os_prefill,
        tab=tab,
        dashboard=dashboard,
        save_paths=save_paths,
        bom_dir=bom_dir,
        skus_file=skus_file,
        processos_dir=processos_dir,
        bom_status=bom_status,
        skus_status=skus_status,
        os_processos_status=os_processos_status,
        regras_popup_status=regras_popup_status,
        relacoes_processo_status=relacoes_processo_status,
        processos_os=PROCESSOS_OS,
        processo_transformacao_por_item=processo_por_item,
        relacoes_processo_transformacao=RELACOES_PROCESSO_TRANSFORMACAO,
        relacoes_processo_item=relacoes_processo_item,
        regras_popup_item=regras_popup_item,
    )


@app.route("/gerar_oc", methods=["POST"])
def gerar_oc():

    atualizar_skus_automatico()
    fornecedor = request.form.get("fornecedor", "")
    fornecedores = carregar_fornecedores()
    fornecedor_info = fornecedores.get(fornecedor, {})

    itens = []

    codigos = request.form.getlist("codigo[]")
    descricoes = request.form.getlist("descricao[]")
    unidades = request.form.getlist("unidade[]")
    qtds = request.form.getlist("qtd[]")
    valores = request.form.getlist("valor[]")
    descontos = request.form.getlist("desconto[]")
    ipis = request.form.getlist("ipi[]")
    icmss = request.form.getlist("icms[]")
    cofins_list = request.form.getlist("cofins[]")

    produtos = carregar_produtos()
    for i in range(len(codigos)):
        codigo_item = normalizar_codigo(codigos[i])
        if not codigo_item:
            continue
        ipi = ipis[i] if i < len(ipis) else ""
        icms = icmss[i] if i < len(icmss) else ""
        cofins = cofins_list[i] if i < len(cofins_list) else ""

        qtd = float(qtds[i]) if qtds[i] else 0
        valor = float(valores[i]) if valores[i] else 0
        desconto = float(descontos[i]) if descontos[i] else 0

        produto_info = produtos.get(codigo_item, {})
        desc_form = descricoes[i] if i < len(descricoes) else ""
        unidade_form = unidades[i] if i < len(unidades) else ""
        descricao_final = produto_info.get("descricao") or desc_form
        unidade_final = produto_info.get("unidade") or unidade_form
        ipi_val = ipi if ipi != "" else produto_info.get("ipi")
        icms_val = icms if icms != "" else produto_info.get("icms")
        cofins_val = cofins if cofins != "" else produto_info.get("cofins")

        total = calcular_total_item(qtd, valor, desconto, ipi_val, icms_val, cofins_val)
        itens.append({
            "codigo": codigo_item,
            "descricao": descricao_final,
            "unidade": unidade_final,
            "qtd": qtd,
            "valor": valor,
            "desconto": desconto,
            "ipi": ipi_val,
            "icms": icms_val,
            "cofins": cofins_val,
            "total": total
        })

    total_itens = 0
    for item in itens:
        total_itens += item["total"]

    frete_raw = request.form.get("frete", "")
    frete_val = 0
    if frete_raw != "":
        try:
            frete_val = float(frete_raw)
        except ValueError:
            frete_val = 0

    prazo_raw = request.form.get("prazo", "")
    prazo_int = None
    if prazo_raw != "":
        try:
            prazo_int = int(prazo_raw)
        except ValueError:
            prazo_int = None

    vencimento = ""
    if prazo_int is not None:
        vencimento = (date.today() + timedelta(days=prazo_int)).strftime("%d/%m/%Y")

    dados_pedido = {
        "cnpj": fornecedor_info.get("cnpj", request.form.get("cnpj", "")),
        "bairro": fornecedor_info.get("bairro", request.form.get("bairro", "")),
        "cidade": fornecedor_info.get("cidade", request.form.get("cidade", "")),
        "uf": fornecedor_info.get("uf", request.form.get("uf", "")),
        "email": fornecedor_info.get("email", request.form.get("email", "")),
        "razao_social": fornecedor_info.get("razao_social", request.form.get("razao_social", "")),
        "endereco": fornecedor_info.get("endereco", request.form.get("endereco", "")),
        "cep": fornecedor_info.get("cep", request.form.get("cep", "")),
        "telefone": fornecedor_info.get("telefone", request.form.get("telefone", "")),
        "previsao": request.form.get("previsao", ""),
        "tipo_frete": request.form.get("tipo_frete", ""),
        "frete": frete_val,
        "total_itens": total_itens,
        "total_pedido": total_itens + frete_val,
        "forma_pagamento": request.form.get("forma_pagamento", ""),
        "prazo": prazo_raw,
        "vencimento": vencimento,
        "obs": request.form.get("obs", ""),
    }

    numero_oc = proximo_numero_oc()

    fornecedor_nome = fornecedor_info.get("fornecedor") or fornecedor_info.get("razao_social") or fornecedor
    oc_mode = request.form.get("oc_mode", "completo")
    incluir_composicao = oc_mode != "resumido"
    arquivo = gerar_word(numero_oc, fornecedor_nome, dados_pedido, itens, incluir_composicao=incluir_composicao)
    limpar_importacao(OC_IMPORT_FILE)

    nome_docx = construir_nome_oc(numero_oc, fornecedor_nome, dados_pedido)
    dados_hist = dict(dados_pedido)
    dados_hist["fornecedor"] = fornecedor_nome
    registrar_historico("oc", numero_oc, dados_hist, itens=itens)
    pedidos_dir, _ = get_save_paths()
    salvo_onedrive = _is_in_dir(arquivo, pedidos_dir)
    resp = send_file(arquivo, as_attachment=True, download_name=nome_docx)
    resp.set_cookie("save_status", "onedrive" if salvo_onedrive else "fallback", max_age=20, path="/")
    return resp



@app.route("/gerar_os", methods=["POST"])
def gerar_os():
    atualizar_skus_automatico()
    cliente = _limpar_valor_busca(
        request.form.get("os_cliente", "") or request.form.get("os_cliente_busca", "")
    )
    os_produtos = carregar_os_produtos()
    produtos_catalogo = carregar_produtos()
    bom_dir = get_bom_dir()
    if bom_dir and os.path.isdir(bom_dir):
        resultado_bom = importar_bom_diretorio(bom_dir, somente_se_mais_novo=True)
        if resultado_bom.get("falhas"):
            detalhes = []
            if resultado_bom.get("em_uso"):
                detalhes.append(f"arquivos em uso: {', '.join(resultado_bom['em_uso'][:3])}")
            if resultado_bom.get("com_erro"):
                detalhes.append(f"arquivos com erro: {', '.join(resultado_bom['com_erro'][:3])}")
            resumo = "; ".join(detalhes) or "falha ao ler a base"
            return f"Nao foi possivel atualizar a B.O.M antes de gerar a O.S. ({resumo}).", 400
    itens = []

    codigos = request.form.getlist("os_codigo[]")
    qtds = request.form.getlist("os_qtd[]")
    series = request.form.getlist("os_serie[]")
    unidades = request.form.getlist("os_unidade[]")
    descricoes = request.form.getlist("os_descricao[]")
    fornecedores_linha = request.form.getlist("os_fornecedor_item[]")
    luminarias_linha = request.form.getlist("os_luminaria[]")
    luminarias_qtd_linha = request.form.getlist("os_luminaria_qtd[]")
    popup_itens_linha = request.form.getlist("os_popup_itens[]")
    luminarias_extra = []
    popup_itens_extra = []
    regras_popup_por_gatilho = {}
    for regra in carregar_regras_popup_item():
        regras_popup_por_gatilho.setdefault(regra.get("gatilho", ""), []).append(regra)
    for idx in range(len(codigos)):
        codigo_item = normalizar_codigo(codigos[idx])
        if not codigo_item:
            continue
        qtd_raw = str(qtds[idx]).strip() if idx < len(qtds) else ""
        try:
            qtd = float(qtd_raw) if qtd_raw else 1.0
        except Exception:
            qtd = 1.0
        if qtd <= 0:
            qtd = 1.0

        item_info = os_produtos.get(codigo_item, {})
        descricao_final = item_info.get("descricao") or (descricoes[idx] if idx < len(descricoes) else "")
        unidade_final = unidades[idx] if idx < len(unidades) else item_info.get("unidade", "")
        categoria_final = item_info.get("categoria", "") or ""
        fornecedor_linha = fornecedores_linha[idx].strip() if idx < len(fornecedores_linha) else ""
        fornecedor_final = item_info.get("fornecedor", "") or ""
        if _eh_faturamento_direto(descricao_final):
            fornecedor_final = _fornecedor_faturamento_direto(
                descricao_final,
                categoria_final,
                fornecedor_linha,
                item_info.get("fornecedor", ""),
            )
        itens.append(
            {
                "codigo": codigo_item,
                "descricao": descricao_final,
                "qtd": qtd,
                "serie": series[idx] if idx < len(series) else "",
                "unidade": unidade_final or item_info.get("unidade", ""),
                "grupo": item_info.get("grupo", "") or "",
                "categoria": categoria_final,
                "fornecedor": fornecedor_final,
                "valor": 0,
                "total": calcular_total_item(qtd, 0, 0),
            }
        )

        luminaria_codigo = normalizar_codigo(luminarias_linha[idx]) if idx < len(luminarias_linha) else ""
        if luminaria_codigo:
            luminaria_info = produtos_catalogo.get(luminaria_codigo, {}) or os_produtos.get(luminaria_codigo, {})
            luminaria_qtd_raw = str(luminarias_qtd_linha[idx]).strip() if idx < len(luminarias_qtd_linha) else ""
            try:
                luminaria_qtd = float(luminaria_qtd_raw) if luminaria_qtd_raw else 1.0
            except Exception:
                luminaria_qtd = 1.0
            if luminaria_qtd <= 0:
                luminaria_qtd = 1.0
            luminarias_extra.append(
                {
                    "item": codigo_item,
                    "codigo": luminaria_codigo,
                    "descricao": luminaria_info.get("descricao", "") or luminaria_info.get("nome", "") or "",
                    "qtd": luminaria_qtd,
                    "serie": "",
                    "unidade": luminaria_info.get("unidade", "") or "",
                    "grupo": luminaria_info.get("grupo", "") or "",
                    "categoria": luminaria_info.get("categoria", "") or "",
                    "fornecedor": luminaria_info.get("fornecedor", "") or "",
                    "valor": 0,
                    "total": calcular_total_item(qtd, 0, 0),
                    "level": 0,
                }
            )

        popup_json = popup_itens_linha[idx] if idx < len(popup_itens_linha) else "[]"
        try:
            popup_selecoes = json.loads(popup_json or "[]")
        except Exception:
            popup_selecoes = []
        selecoes_por_regra = {
            str(selecao.get("regra_id", "") or ""): selecao
            for selecao in popup_selecoes
            if isinstance(selecao, dict) and str(selecao.get("regra_id", "") or "")
        } if isinstance(popup_selecoes, list) else {}
        for regra in regras_popup_por_gatilho.get(codigo_item, []):
            regra_id = str(regra.get("id", "") or "")
            selecao = selecoes_por_regra.get(regra_id, {})
            selecionado = normalizar_codigo(selecao.get("codigo", ""))
            if selecionado not in (regra.get("opcoes") or []):
                return f"Selecione o item relacionado obrigatorio para {codigo_item}.", 400
        for selecao in popup_selecoes if isinstance(popup_selecoes, list) else []:
            if not isinstance(selecao, dict):
                continue
            relacionado_codigo = normalizar_codigo(selecao.get("codigo", ""))
            if not relacionado_codigo:
                continue
            try:
                relacionado_qtd = float(selecao.get("qtd", 1) or 1)
            except Exception:
                relacionado_qtd = 1
            if relacionado_qtd <= 0:
                relacionado_qtd = 1
            relacionado_info = produtos_catalogo.get(relacionado_codigo, {}) or os_produtos.get(relacionado_codigo, {})
            popup_itens_extra.append(
                {
                    "item": codigo_item,
                    "codigo": relacionado_codigo,
                    "descricao": relacionado_info.get("descricao", "") or relacionado_info.get("nome", "") or "",
                    "qtd": relacionado_qtd,
                    "serie": "",
                    "unidade": relacionado_info.get("unidade", "") or "",
                    "grupo": relacionado_info.get("grupo", "") or "",
                    "categoria": relacionado_info.get("categoria", "") or "",
                    "fornecedor": relacionado_info.get("fornecedor", "") or "",
                    "valor": 0,
                    "total": calcular_total_item(relacionado_qtd, 0, 0),
                    "level": 0,
                }
            )

    total_itens = sum(item["total"] for item in itens)

    processos = carregar_os_processos()
    relacoes_processo_item = carregar_relacoes_processo_item()
    processo_por_item = construir_processo_por_item(
        os_produtos,
        processos.keys(),
        relacoes_processo_item,
    )
    conjunto_processo_form = (request.form.get("os_processo_conjunto", "") or "").strip()
    codigos_para_processo = [
        item.get("codigo", "")
        for item in [*itens, *luminarias_extra, *popup_itens_extra]
        if item.get("codigo", "")
    ]
    conjuntos_processo_disponiveis = resolver_processos_transformacao(
        codigos_para_processo,
        processo_por_item,
    )
    if conjunto_processo_form and conjunto_processo_form in processos:
        conjuntos_processo_disponiveis.append(conjunto_processo_form)
    conjuntos_processo_disponiveis = list(dict.fromkeys(conjuntos_processo_disponiveis))
    conjunto_processo = " + ".join(conjuntos_processo_disponiveis)
    processos_modelo = mesclar_processos_modelo(processos, conjuntos_processo_disponiveis)

    dados = {
        "cliente": cliente,
        "previsao_inicio": request.form.get("os_previsao_inicio", ""),
        "previsao_termino": request.form.get("os_previsao_termino", ""),
        "chassis": request.form.get("os_chassis", ""),
        "municipio": request.form.get("os_municipio", ""),
        "mmv": request.form.get("os_mmv", ""),
        "descricao_servico": request.form.get("os_descricao_servico", ""),
        "total_itens": total_itens,
        "total_pedido": total_itens,
        "obs_materiais": request.form.get("os_obs_materiais", ""),
        "obs": request.form.get("os_obs", ""),
        "processo_conjunto": conjunto_processo,
    }

    processos_final = {nome: [] for nome in PROCESSOS_ORDEM}
    algum_processo_informado = False
    for processo in PROCESSOS_OS:
        nome = processo["nome"]
        key = processo["key"]
        atividades = request.form.getlist(f"proc_{key}_atividade[]")
        responsaveis = request.form.getlist(f"proc_{key}_responsavel[]")
        linhas = []
        for idx in range(len(atividades)):
            atividade = atividades[idx].strip()
            responsavel = responsaveis[idx].strip() if idx < len(responsaveis) else ""
            if atividade:
                linhas.append({"atividade": atividade, "responsavel": responsavel})
        if linhas:
            algum_processo_informado = True
        processos_final[nome] = linhas

    if not algum_processo_informado and any(processos_modelo.values()):
        processos_final = processos_modelo

    numero_manual = request.form.get("os_numero", "").strip()
    numero_os = numero_manual or proximo_numero_os()

    componentes = carregar_os_componentes()
    layout_pdf = request.files.get("os_layout_pdf")
    comp_itens = request.form.getlist("os_comp_item[]")
    comp_codigos = request.form.getlist("os_comp_codigo[]")
    comp_descricoes = request.form.getlist("os_comp_descricao[]")
    comp_unidades = request.form.getlist("os_comp_unidade[]")
    comp_qtds = request.form.getlist("os_comp_qtd[]")
    comp_levels = request.form.getlist("os_comp_level[]")
    composicao_importada = []
    for idx in range(len(comp_codigos)):
        item_pai = normalizar_codigo(comp_itens[idx]) if idx < len(comp_itens) else ""
        codigo = normalizar_codigo(comp_codigos[idx]) if idx < len(comp_codigos) else ""
        descricao = comp_descricoes[idx].strip() if idx < len(comp_descricoes) else ""
        unidade = comp_unidades[idx].strip() if idx < len(comp_unidades) else ""
        qtd = comp_qtds[idx].strip() if idx < len(comp_qtds) else ""
        try:
            level = int((comp_levels[idx] if idx < len(comp_levels) else "0") or 0)
        except Exception:
            level = 0
        if not (codigo or descricao or qtd or unidade):
            continue
        composicao_importada.append(
            {
                "item": item_pai,
                "codigo": codigo,
                "descricao": descricao,
                "unidade": unidade,
                "qtd": qtd,
                "level": level,
            }
        )

    composicao_final = resolver_composicao_final(itens, componentes, composicao_importada or None)
    extras_composicao = expandir_composicao_referenciada(
        [*luminarias_extra, *popup_itens_extra],
        componentes,
    )
    if extras_composicao:
        existentes = {
            (normalizar_codigo(linha.get("item", "")), normalizar_codigo(linha.get("codigo", "")))
            for linha in composicao_final
        }
        for extra in extras_composicao:
            chave = (normalizar_codigo(extra.get("item", "")), normalizar_codigo(extra.get("codigo", "")))
            if chave in existentes:
                continue
            composicao_final.append(extra)
            existentes.add(chave)
    composicao_enriquecida = propagar_setor_preparacao(
        enriquecer_composicao(composicao_final, os_produtos),
        os_produtos,
        componentes,
    )
    pendencias_faturamento_direto = filtrar_linhas_faturamento_direto(composicao_enriquecida)
    pendencias_expedicao = filtrar_linhas_setor(composicao_enriquecida, SETOR_EXPEDICAO)
    pendencias_preparacao = filtrar_linhas_setor(composicao_enriquecida, SETOR_PREPARACAO)
    requisicao_materiais = [*pendencias_expedicao, *pendencias_preparacao, *pendencias_faturamento_direto]

    itens_expedicao = construir_itens_os_expedicao(pendencias_expedicao)
    itens_preparacao = construir_itens_os_preparacao(pendencias_preparacao)
    for item in itens_expedicao + itens_preparacao:
        item["qtd"] = _formatar_qtd_saida(item.get("qtd", ""))

    itens_por_modo = {
        "originais": itens,
        "expedicao": itens_expedicao,
        "preparacao": itens_preparacao,
    }
    modos_pacote = ["completa", "expedicao", "preparacao", "producao"]
    layout_bytes = b""
    if layout_pdf and layout_pdf.filename:
        try:
            layout_pdf.stream.seek(0)
        except Exception:
            pass
        layout_bytes = layout_pdf.read() or b""

    def _criar_layout_clone():
        if not layout_bytes:
            return None
        return FileStorage(
            stream=io.BytesIO(layout_bytes),
            filename=layout_pdf.filename,
            content_type=layout_pdf.content_type,
        )

    arquivos_docx = []
    for modo_key in modos_pacote:
        config_modo = OS_MODE_CONFIGS[modo_key]
        itens_saida = itens_por_modo.get(config_modo["itens_source"], itens)
        layout_clone = _criar_layout_clone()
        arquivos_docx.append(
            gerar_os_docx(
                numero_os,
                dados,
                itens_saida,
                componentes,
                processos_final,
                layout_clone,
                composicao_final or None,
                modo=config_modo["doc_mode"],
                titulo_arquivo=config_modo["titulo"],
                incluir_cliente_nome=config_modo.get("incluir_cliente_nome", True),
                cliente_nome_limite=config_modo.get("cliente_nome_limite"),
            )
        )

    for fornecedor, linhas_fornecedor in agrupar_linhas_por_fornecedor(pendencias_faturamento_direto):
        itens_fornecedor = construir_itens_os_setor(agrupar_linhas_setor(linhas_fornecedor))
        for item in itens_fornecedor:
            item["qtd"] = _formatar_qtd_saida(item.get("qtd", ""))
        fornecedor_titulo = _sanitize_output_name(fornecedor) or "SEM FORNECEDOR"
        dados_requisicao = dict(dados)
        dados_requisicao["fornecedor_requisicao"] = fornecedor
        arquivos_docx.append(
            gerar_os_docx(
                numero_os,
                dados_requisicao,
                itens_fornecedor,
                componentes,
                processos_final,
                _criar_layout_clone(),
                composicao_resolvida=[],
                modo="expedicao",
                titulo_arquivo=f"FATURAMENTO DIRETO - {fornecedor_titulo}",
                incluir_cliente_nome=False,
            )
        )
    arquivo_requisicao_materiais = _criar_planilha_requisicao_materiais(
        numero_os,
        dados,
        requisicao_materiais,
        "03 - Requisicao de Materiais",
    )

    limpar_importacao(OS_IMPORT_FILE)

    chassi_nome = (dados.get("chassis", "") or "").strip()
    dados_historico = dict(dados)
    dados_historico["modo_os"] = "pacote_os"
    registrar_historico(
        "os",
        numero_os,
        dados_historico,
        itens=itens,
        processos=processos_final,
        componentes=componentes,
        composicao=composicao_enriquecida,
    )

    arquivos_saida = [
        *arquivos_docx,
        arquivo_requisicao_materiais,
    ]
    nome_zip = f"02 - Pacote O.S - {chassi_nome}.zip".strip(" -")
    zip_path, download_name = _criar_zip_temporario(arquivos_saida, nome_zip)

    @after_this_request
    def _cleanup_os_zip(response):
        try:
            os.remove(zip_path)
        except Exception:
            pass
        return response

    _, os_dir = get_save_paths()
    salvo_onedrive = all(_is_in_dir(path, os_dir) for path in arquivos_saida if path)
    resp = send_file(zip_path, as_attachment=True, download_name=download_name)
    resp.set_cookie("save_status", "onedrive" if salvo_onedrive else "fallback", max_age=20, path="/")
    return resp


@app.route("/salvar_caminhos", methods=["POST"])
def salvar_caminhos():
    pedidos_dir = request.form.get("pedidos_dir", "")
    os_dir = request.form.get("os_dir", "")
    bom_dir = request.form.get("bom_dir", "")
    skus_file = request.form.get("skus_file", "")
    processos_dir = request.form.get("processos_dir", "")
    set_save_paths(pedidos_dir, os_dir)
    set_bom_dir(bom_dir)
    set_skus_file(skus_file)
    set_processos_dir(processos_dir)
    return redirect(url_for("index", tab="cadastro"))


@app.route("/cadastrar_fornecedor", methods=["POST"])
def cadastrar_fornecedor():

    fornecedores = carregar_fornecedores()

    fornecedor = request.form.get("fornecedor", "").strip()
    cnpj = request.form.get("cnpj", "").strip()

    chave = cnpj if cnpj else fornecedor
    if chave:
        atual = fornecedores.get(chave, {})
        def _pick(campo, valor):
            return valor if valor != "" else atual.get(campo, "")
        fornecedores[chave] = {
            "fornecedor": _pick("fornecedor", fornecedor),
            "razao_social": _pick("razao_social", request.form.get("razao_social", "").strip()),
            "cnpj": _pick("cnpj", cnpj),
            "email": _pick("email", request.form.get("email", "").strip()),
            "telefone": _pick("telefone", request.form.get("telefone", "").strip()),
            "endereco": _pick("endereco", request.form.get("endereco", "").strip()),
            "bairro": _pick("bairro", request.form.get("bairro", "").strip()),
            "cidade": _pick("cidade", request.form.get("cidade", "").strip()),
            "uf": _pick("uf", request.form.get("uf", "").strip()),
            "cep": _pick("cep", request.form.get("cep", "").strip()),
        }

        salvar_json(FORNECEDORES_FILE, fornecedores)

    return index()


@app.route("/cadastrar_item", methods=["POST"])
def cadastrar_item():

    produtos = carregar_produtos()

    codigo = request.form.get("codigo", "").strip()
    if codigo:
        atual = produtos.get(codigo, {})
        novos = {
            "descricao": request.form.get("descricao", "").strip(),
            "unidade": request.form.get("unidade", "").strip(),
            "grupo": request.form.get("grupo", "").strip(),
            "categoria": request.form.get("categoria", "").strip(),
            "processo_conjunto": request.form.get("processo_conjunto", "").strip(),
        }
        produtos[codigo] = _mesclar_dados_item(atual, novos)

        salvar_json(PRODUTOS_FILE, produtos)

    return index()


@app.route("/cadastrar_os_fornecedor", methods=["POST"])
def cadastrar_os_fornecedor():

    fornecedores = carregar_os_fornecedores()

    cliente = request.form.get("os_fornecedor", "").strip()
    if cliente:
        atual = fornecedores.get(cliente, {})
        fornecedores[cliente] = {"cliente": cliente if cliente != "" else atual.get("cliente", "")}

        salvar_json(OS_FORNECEDORES_FILE, fornecedores)

    return index()


@app.route("/cadastrar_os_item", methods=["POST"])
def cadastrar_os_item():

    produtos = carregar_os_produtos()
    componentes = carregar_os_componentes()

    codigo = normalizar_codigo(request.form.get("os_item_codigo", ""))
    descricao = request.form.get("os_item_descricao", "").strip()
    unidade = request.form.get("os_item_unidade", "").strip()
    grupo = request.form.get("os_item_grupo", "").strip()
    categoria = request.form.get("os_item_categoria", "").strip()
    fornecedor = request.form.get("os_item_fornecedor", "").strip()
    processo_conjunto = request.form.get("os_item_processo_conjunto", "").strip()

    comp_codigos = request.form.getlist("os_comp_codigo[]")
    comp_descricoes = request.form.getlist("os_comp_descricao[]")
    comp_unidades = request.form.getlist("os_comp_unidade[]")
    comp_qtds = request.form.getlist("os_comp_qtd[]")

    comps = []
    for i in range(len(comp_codigos)):
        if not comp_codigos[i] and not comp_descricoes[i]:
            continue
        comps.append({
            "codigo": normalizar_codigo(comp_codigos[i]),
            "descricao": comp_descricoes[i],
            "unidade": comp_unidades[i],
            "quantidade": comp_qtds[i],
        })

    if codigo and descricao:
        atual_prod = produtos.get(codigo, {})
        produtos[codigo] = _mesclar_dados_item(
            atual_prod,
            {
                "descricao": descricao,
                "unidade": (unidade or "").strip() or atual_prod.get("unidade", "UN") or "UN",
                "unidade_comercial": (unidade or "").strip() or atual_prod.get("unidade_comercial", "") or atual_prod.get("unidade", "UN") or "UN",
                "unidade_interna": atual_prod.get("unidade_interna", ""),
                "grupo": grupo,
                "categoria": categoria,
                "tipo": atual_prod.get("tipo", ""),
                "fornecedor": fornecedor,
                "ncm": "",
                "origem": "",
                "valor": "",
                "ipi": "",
                "icms": "",
                "cofins": "",
                "observacao": "",
                "processo_conjunto": processo_conjunto,
            },
        )
        if comps:
            componentes[codigo] = comps
        elif codigo in componentes:
            componentes[codigo] = componentes.get(codigo, [])
        else:
            componentes[codigo] = []

        salvar_json(OS_PRODUTOS_FILE, produtos)
        salvar_json(OS_COMPONENTES_FILE, componentes)

    return index()


@app.route("/cadastrar_relacao_processo_item", methods=["POST"])
def cadastrar_relacao_processo_item():
    relacoes = carregar_relacoes_processo_item()
    codigo = normalizar_codigo(request.form.get("relacao_item", ""))
    processos = [
        processo.strip()
        for processo in request.form.getlist("relacao_processo_conjunto[]")
        if processo.strip()
    ]
    if not processos:
        processo_legado = request.form.get("relacao_processo_conjunto", "").strip()
        processos = [processo_legado] if processo_legado else []
    if codigo and processos:
        relacoes[codigo] = list(dict.fromkeys(processos))
        salvar_relacoes_processo_item(relacoes)
    return redirect(url_for("index", tab="cadastro"))


@app.route("/excluir_relacao_processo_item", methods=["POST"])
def excluir_relacao_processo_item():
    relacoes = carregar_relacoes_processo_item()
    codigo = normalizar_codigo(request.form.get("relacao_item", ""))
    if codigo and codigo in relacoes:
        relacoes.pop(codigo, None)
        salvar_relacoes_processo_item(relacoes)
    return redirect(url_for("index", tab="cadastro"))


@app.route("/cadastrar_regra_popup_item", methods=["POST"])
def cadastrar_regra_popup_item():
    regras = carregar_regras_popup_item()
    gatilho = normalizar_codigo(request.form.get("popup_regra_gatilho", ""))
    opcoes = [
        normalizar_codigo(codigo)
        for codigo in request.form.getlist("popup_regra_opcao[]")
        if normalizar_codigo(codigo)
    ]
    try:
        quantidade = float(request.form.get("popup_regra_quantidade", "1") or 1)
    except Exception:
        quantidade = 1
    if quantidade <= 0:
        quantidade = 1
    if gatilho and opcoes:
        proximo_id = max(
            [
                int(re.sub(r"\D", "", str(regra.get("id", ""))) or 0)
                for regra in regras
            ]
            or [0]
        ) + 1
        regras.append(
            {
                "id": f"regra-{proximo_id}",
                "gatilho": gatilho,
                "opcoes": list(dict.fromkeys(opcoes)),
                "quantidade": quantidade,
                "quantidade_editavel": request.form.get("popup_regra_quantidade_editavel") == "1",
            }
        )
        salvar_regras_popup_item(regras)
    return redirect(url_for("index", tab="cadastro"))


@app.route("/excluir_regra_popup_item", methods=["POST"])
def excluir_regra_popup_item():
    regra_id = str(request.form.get("popup_regra_id", "") or "").strip()
    if regra_id:
        regras = [
            regra
            for regra in carregar_regras_popup_item()
            if str(regra.get("id", "") or "").strip() != regra_id
        ]
        salvar_regras_popup_item(regras)
    return redirect(url_for("index", tab="cadastro"))


def _status_importacao_planilha(resultado, nome):
    status = (
        f"{nome}: {resultado['novas']} nova(s), "
        f"{resultado['atualizadas']} atualizada(s) e "
        f"{resultado['ignoradas']} ignorada(s)."
    )
    erros = resultado.get("erros") or []
    if erros:
        status += " " + "; ".join(erros[:3])
        if len(erros) > 3:
            status += f"; mais {len(erros) - 3} erro(s)."
    return status


@app.route("/importar_regras_popup_item", methods=["POST"])
def importar_regras_popup_item_route():
    arquivo = request.files.get("arquivo_regras_popup_item")
    if not arquivo or not arquivo.filename:
        status = "Selecione uma planilha XLSX de parametros de item relacionado."
    else:
        try:
            resultado = importar_regras_popup_item_planilha(arquivo)
            status = _status_importacao_planilha(resultado, "Parametros importados")
        except ValueError as exc:
            status = f"Falha na importacao: {exc}"
        except Exception:
            app.logger.exception("Falha ao importar parametros de item relacionado")
            status = "Falha inesperada ao importar os parametros. Consulte o log."
    destino = url_for("index", tab="cadastro", regras_popup_status=status)
    return redirect(f"{destino}#parametros-item-relacionado")


@app.route("/importar_relacoes_processo_item", methods=["POST"])
def importar_relacoes_processo_item_route():
    arquivo = request.files.get("arquivo_relacoes_processo_item")
    if not arquivo or not arquivo.filename:
        status = "Selecione uma planilha XLSX de relacao processo x item."
    else:
        try:
            resultado = importar_relacoes_processo_item_planilha(arquivo)
            status = _status_importacao_planilha(resultado, "Relacoes importadas")
        except ValueError as exc:
            status = f"Falha na importacao: {exc}"
        except Exception:
            app.logger.exception("Falha ao importar relacoes processo x item")
            status = "Falha inesperada ao importar as relacoes. Consulte o log."
    destino = url_for("index", tab="cadastro", relacoes_processo_status=status)
    return redirect(f"{destino}#relacao-processo-item")


@app.route("/importar_produtos", methods=["POST"])
def importar_produtos_route():

    arquivo = request.files.get("arquivo_produtos")
    if arquivo and arquivo.filename:
        importar_produtos(arquivo)

    return redirect(url_for("index", tab="oc"))


@app.route("/importar_fornecedores", methods=["POST"])
def importar_fornecedores_route():

    arquivo = request.files.get("arquivo_fornecedores")
    if arquivo and arquivo.filename:
        importar_fornecedores(arquivo)

    return redirect(url_for("index", tab="oc"))


@app.route("/importar_os_produtos", methods=["POST"])
def importar_os_produtos_route():

    arquivo = request.files.get("arquivo_os_produtos")
    if arquivo and arquivo.filename:
        importar_os_produtos(arquivo)

    return redirect(url_for("index", tab="os"))


@app.route("/importar_os_fornecedores", methods=["POST"])
def importar_os_fornecedores_route():

    arquivo = request.files.get("arquivo_os_fornecedores")
    if arquivo and arquivo.filename:
        importar_os_fornecedores(arquivo)

    return redirect(url_for("index", tab="os"))


@app.route("/importar_os_componentes", methods=["POST"])
def importar_os_componentes_route():

    arquivo = request.files.get("arquivo_os_componentes")
    if arquivo and arquivo.filename:
        importar_os_componentes(arquivo)

    return redirect(url_for("index", tab="os"))


@app.route("/atualizar_bom", methods=["POST"])
def atualizar_bom():
    bom_dir = get_bom_dir()
    if not bom_dir:
        status = "Caminho da B.O.M. não foi configurado."
        return redirect(url_for("index", tab="cadastro", bom_status=status))
    if not os.path.isdir(bom_dir):
        status = f"Caminho da B.O.M. inválido: {bom_dir}"
        return redirect(url_for("index", tab="cadastro", bom_status=status))

    arquivos = listar_arquivos_excel_base(bom_dir)

    if not arquivos:
        status = f"Nenhuma planilha Excel (.xls/.xlsx/.xlsm/.xltx/.xltm) encontrada em {bom_dir}"
        return redirect(url_for("index", tab="cadastro", bom_status=status))

    resultado = importar_bom_diretorio(bom_dir)
    arquivos_processados = resultado["arquivos"]
    linhas_importadas = resultado["linhas"]
    falhas = resultado["falhas"]
    arquivos_em_uso = resultado["em_uso"]
    arquivos_com_erro = resultado["com_erro"]

    if arquivos_processados == 0:
        status = f"Nenhum arquivo válido encontrado em {bom_dir}"
    elif falhas:
        detalhes = []
        if arquivos_em_uso:
            detalhes.append(f"{len(arquivos_em_uso)} em uso no Excel")
        if arquivos_com_erro:
            detalhes.append(f"{len(arquivos_com_erro)} com erro de leitura")
        resumo_falhas = ", ".join(detalhes) if detalhes else f"{falhas} falhas"
        status = (
            f"{arquivos_processados} arquivos processados, "
            f"{linhas_importadas} linhas importadas e {resumo_falhas}. Veja o log."
        )
    else:
        status = f"{arquivos_processados} arquivos importados ({linhas_importadas} linhas)."

    return redirect(url_for("index", tab="cadastro", bom_status=status))


@app.route("/atualizar_skus", methods=["POST"])
def atualizar_skus():
    skus_file = get_skus_file()
    resultado = atualizar_skus_arquivo(skus_file, somente_se_mais_novo=False)
    if resultado.get("erro"):
        status = resultado["erro"]
    elif resultado.get("linhas", 0) == 0:
        status = f"Nenhum SKU importado de {skus_file}."
    else:
        status = f"SKUs atualizados: {resultado['linhas']} linha(s) importada(s) de {skus_file}."
    return redirect(url_for("index", tab="cadastro", skus_status=status))


@app.route("/atualizar_processos", methods=["POST"])
def atualizar_processos():
    tab_destino = (request.form.get("next_tab", "") or "").strip() or "cadastro"
    processos_dir = get_processos_dir()
    if not processos_dir:
        status = "Caminho da base de processos não foi configurado."
        return redirect(url_for("index", tab=tab_destino, os_processos_status=status))
    if not os.path.isdir(processos_dir):
        status = f"Caminho da base de processos inválido: {processos_dir}"
        return redirect(url_for("index", tab=tab_destino, os_processos_status=status))

    excel_exts = {".xls", ".xlsx", ".xlsm", ".xltx", ".xltm"}
    arquivos = []
    for root, _, nomes in os.walk(processos_dir):
        for nome in nomes:
            if os.path.splitext(nome)[1].lower() in excel_exts:
                arquivos.append(os.path.join(root, nome))

    if not arquivos:
        status = f"Nenhuma planilha Excel (.xls/.xlsx/.xlsm/.xltx/.xltm) encontrada em {processos_dir}"
        return redirect(url_for("index", tab=tab_destino, os_processos_status=status))

    arquivos_processados = 0
    linhas_importadas = 0
    falhas = 0
    arquivos_em_uso = []
    arquivos_com_erro = []

    for caminho in sorted(arquivos):
        try:
            with _open_for_read(caminho) as f:
                storage = FileStorage(stream=f, filename=os.path.basename(caminho))
                linhas_importadas += importar_os_processos_atualizado(storage)
            arquivos_processados += 1
            app.logger.info("Importada base de processos %s", caminho)
        except PermissionError:
            arquivos_em_uso.append(os.path.basename(caminho))
            falhas += 1
        except Exception:
            app.logger.exception("Falha ao importar base de processos %s", caminho)
            arquivos_com_erro.append(os.path.basename(caminho))
            falhas += 1

    if arquivos_processados == 0:
        status = f"Nenhum arquivo válido encontrado em {processos_dir}"
    elif falhas:
        detalhes = []
        if arquivos_em_uso:
            detalhes.append(f"{len(arquivos_em_uso)} em uso no Excel")
        if arquivos_com_erro:
            detalhes.append(f"{len(arquivos_com_erro)} com erro de leitura")
        resumo_falhas = ", ".join(detalhes) if detalhes else f"{falhas} falhas"
        status = (
            f"{arquivos_processados} arquivos processados, "
            f"{linhas_importadas} linhas importadas e {resumo_falhas}. Veja o log."
        )
    else:
        status = f"{arquivos_processados} arquivos de processos importados ({linhas_importadas} linhas)."

    return redirect(url_for("index", tab=tab_destino, os_processos_status=status))


@app.route("/importar_os_processos", methods=["POST"])
def importar_os_processos_route():

    tab_destino = (request.form.get("next_tab", "") or "").strip() or "os"
    arquivos = [arquivo for arquivo in request.files.getlist("arquivo_os_processos") if arquivo and arquivo.filename]
    if not arquivos:
        status = "Nenhum arquivo de processo foi selecionado."
        return redirect(url_for("index", tab=tab_destino, os_processos_status=status))

    linhas_importadas = 0
    arquivos_importados = 0
    for arquivo in arquivos:
        linhas = importar_os_processos_atualizado(arquivo)
        linhas_importadas += linhas
        arquivos_importados += 1

    status = f"{arquivos_importados} arquivo(s) de processo importado(s) ({linhas_importadas} linhas)."
    return redirect(url_for("index", tab=tab_destino, os_processos_status=status))


@app.route("/importar_oc_documento", methods=["POST"])
def importar_oc_documento():
    arquivo = request.files.get("arquivo_oc_template")
    if arquivo and arquivo.filename:
        ext = os.path.splitext(secure_filename(arquivo.filename))[1].lower()
        if ext == ".docx":
            data = parse_oc_docx(arquivo)
        elif ext == ".pdf":
            data = parse_oc_pdf(arquivo)
        else:
            data = {}
        if data:
            salvar_json(OC_IMPORT_FILE, data)
    return redirect(url_for("index", tab="oc"))


@app.route("/importar_os_documento", methods=["POST"])
def importar_os_documento():
    arquivo = request.files.get("arquivo_os_template")
    if arquivo and arquivo.filename:
        ext = os.path.splitext(secure_filename(arquivo.filename))[1].lower()
        if ext == ".docx":
            data = parse_os_docx_atualizado(arquivo)
        elif ext == ".pdf":
            data = parse_os_pdf(arquivo)
        else:
            data = {}
        if data:
            salvar_json(OS_IMPORT_FILE, data)
    return redirect(url_for("index", tab="os"))


@app.route("/exportar_modelo_produtos")
def exportar_modelo_produtos():
    path, nome = _criar_modelo_xlsx(
        MODELO_ITENS_HEADERS,
        "modelo_produtos.xlsx",
        header_row=2,
    )
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_modelo_fornecedores")
def exportar_modelo_fornecedores():
    path, nome = _criar_modelo_xlsx(
        ["fornecedor", "razao_social", "cnpj", "email", "telefone", "endereco", "bairro", "cidade", "uf", "cep"],
        "modelo_fornecedores.xlsx",
    )
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_modelo_os_clientes")
def exportar_modelo_os_clientes():
    path, nome = _criar_modelo_xlsx(["cliente"], "modelo_os_clientes.xlsx")
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_modelo_os_itens")
def exportar_modelo_os_itens():
    path, nome = _criar_modelo_xlsx(
        MODELO_ITENS_HEADERS,
        "modelo_os_itens.xlsx",
        header_row=2,
    )
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_modelo_os_componentes")
def exportar_modelo_os_componentes():
    path, nome = _criar_modelo_xlsx(
        ["item_codigo", "componente_codigo", "descricao", "unidade", "quantidade"],
        "modelo_os_componentes.xlsx",
    )
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_modelo_os_processos")
def exportar_modelo_os_processos():
    path, nome = _criar_modelo_os_processos_xlsx()
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_modelo_regras_popup_item")
def exportar_modelo_regras_popup_item():
    path, nome = _criar_planilha_regras_popup_item()
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_regras_popup_item")
def exportar_regras_popup_item():
    path, nome = _criar_planilha_regras_popup_item(
        carregar_regras_popup_item(),
        nome_arquivo="parametros_item_relacionado_atuais.xlsx",
    )
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_modelo_relacoes_processo_item")
def exportar_modelo_relacoes_processo_item():
    path, nome = _criar_planilha_relacoes_processo_item()
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/exportar_relacoes_processo_item")
def exportar_relacoes_processo_item():
    path, nome = _criar_planilha_relacoes_processo_item(
        carregar_relacoes_processo_item(),
        nome_arquivo="relacao_processo_item_atual.xlsx",
    )
    return send_file(path, as_attachment=True, download_name=nome)


@app.route("/gerar_zip_release", methods=["POST"])
def gerar_zip_release():
    ok, err = _run_release_build()
    if not ok:
        return err, 400
    result = _build_release_zip()
    if not result:
        return "Nao encontrei build em dist. Gere o EXE antes e tente novamente.", 400
    zip_path, temp_root = result

    @after_this_request
    def _cleanup(response):
        try:
            shutil.rmtree(temp_root, ignore_errors=True)
        except Exception:
            pass
        return response

    return send_file(zip_path, as_attachment=True, download_name=RELEASE_ZIP_NAME)


@app.route("/resetar_base", methods=["POST"])
def resetar_base():
    _reset_base_data()
    return redirect(url_for("index"))


@app.route("/exportar_dashboard", methods=["GET"])
def exportar_dashboard():
    historico = carregar_historico()
    wb = Workbook()
    wb.remove(wb.active)

    ws_oc = wb.create_sheet("OC")
    ws_oc.append([
        "Data Criacao", "Numero", "Fornecedor", "Razao Social", "CNPJ", "Email", "Telefone",
        "Endereco", "Bairro", "Cidade", "UF", "CEP", "Previsao", "Tipo Frete", "Frete",
        "Total Itens", "Total Pedido", "Forma Pagamento", "Prazo", "Vencimento", "Obs"
    ])

    ws_oc_itens = wb.create_sheet("OC Itens")
    ws_oc_itens.append([
        "Data Criacao", "Numero", "Codigo", "Descricao", "Unidade", "Qtd", "Valor",
        "Desconto", "IPI", "ICMS", "COFINS", "Total"
    ])

    ws_os = wb.create_sheet("OS")
    ws_os.append([
        "Data Criacao", "Numero", "Cliente", "Chassis", "Municipio", "MMV",
        "Previsao Inicio", "Previsao Termino", "Descricao Servico",
        "Obs Materiais", "Obs"
    ])

    ws_os_itens = wb.create_sheet("OS Itens")
    ws_os_itens.append([
        "Data Criacao", "Numero", "Codigo", "Descricao", "Qtd", "Serie", "Unidade"
    ])

    ws_os_proc = wb.create_sheet("OS Processos")
    ws_os_proc.append(["Data Criacao", "Numero", "Grupo", "Indice", "Atividade", "Responsavel"])

    ws_os_comp = wb.create_sheet("OS Componentes")
    ws_os_comp.append(["Data Criacao", "Numero", "Item", "Codigo", "Descricao", "Unidade", "Qtd"])

    for entry in historico:
        tipo = entry.get("tipo")
        data = entry.get("data_criacao", "")
        numero = entry.get("numero", "")
        dados = entry.get("dados", {}) or {}
        itens = entry.get("itens", []) or []
        if tipo == "oc":
            ws_oc.append([
                data,
                numero,
                dados.get("fornecedor", ""),
                dados.get("razao_social", ""),
                dados.get("cnpj", ""),
                dados.get("email", ""),
                dados.get("telefone", ""),
                dados.get("endereco", ""),
                dados.get("bairro", ""),
                dados.get("cidade", ""),
                dados.get("uf", ""),
                dados.get("cep", ""),
                dados.get("previsao", ""),
                dados.get("tipo_frete", ""),
                dados.get("frete", ""),
                dados.get("total_itens", ""),
                dados.get("total_pedido", ""),
                dados.get("forma_pagamento", ""),
                dados.get("prazo", ""),
                dados.get("vencimento", ""),
                dados.get("obs", ""),
            ])
            for item in itens:
                ws_oc_itens.append([
                    data,
                    numero,
                    item.get("codigo", ""),
                    item.get("descricao", ""),
                    item.get("unidade", ""),
                    item.get("qtd", ""),
                    item.get("valor", ""),
                    item.get("desconto", ""),
                    item.get("ipi", ""),
                    item.get("icms", ""),
                    item.get("cofins", ""),
                    item.get("total", ""),
                ])
        elif tipo == "os":
            ws_os.append([
                data,
                numero,
                dados.get("cliente", ""),
                dados.get("chassis", ""),
                dados.get("municipio", ""),
                dados.get("mmv", ""),
                dados.get("previsao_inicio", ""),
                dados.get("previsao_termino", ""),
                dados.get("descricao_servico", ""),
                dados.get("obs_materiais", ""),
                dados.get("obs", ""),
            ])
            for item in itens:
                ws_os_itens.append([
                    data,
                    numero,
                    item.get("codigo", ""),
                    item.get("descricao", ""),
                    item.get("qtd", ""),
                    item.get("serie", ""),
                    item.get("unidade", ""),
                ])
            processos = entry.get("processos", {}) or {}
            for grupo, linhas in processos.items():
                for idx, linha in enumerate(linhas, start=1):
                    ws_os_proc.append([
                        data,
                        numero,
                        grupo,
                        idx,
                        linha.get("atividade", ""),
                        linha.get("responsavel", ""),
                    ])
            composicao = entry.get("composicao", []) or []
            for comp in composicao:
                ws_os_comp.append([
                    data,
                    numero,
                    comp.get("item", ""),
                    comp.get("codigo", ""),
                    comp.get("descricao", ""),
                    comp.get("unidade", ""),
                    comp.get("qtd", ""),
                ])

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp.close()
    wb.save(tmp.name)
    return send_file(tmp.name, as_attachment=True, download_name="dashboard_export.xlsx")


if __name__ == "__main__":
    port = _get_free_port()
    _abrir_navegador(port)
    app.run(debug=False, use_reloader=False, port=port)
