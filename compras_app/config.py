import os
import sys
import json
import logging
from datetime import datetime

def _resource_base():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _resource_base()
_FROZEN = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

if _FROZEN:
    _USER_BASE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Emissor documentos")
    DATA_DIR = os.path.join(_USER_BASE, "data")
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
if _FROZEN:
    TEMPLATE_DIR = os.path.join(BASE_DIR, "compras_app", "template_word")
    TEMPLATES_DIR = os.path.join(BASE_DIR, "compras_app", "templates")
    STATIC_DIR = os.path.join(BASE_DIR, "compras_app", "static")
else:
    TEMPLATE_DIR = os.path.join(BASE_DIR, "template_word")
    TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
    STATIC_DIR = os.path.join(BASE_DIR, "static")
DEFAULT_PEDIDOS_DIR = r"C:\Users\PRODUCAO-2.0\J I MONTADORA DE VEICULOS ESPECIAIS LTDA\JI Montadora - 03 Compras\01 Pedidos de Compra"
DEFAULT_OS_DIR = r"C:\Users\PRODUCAO-2.0\J I MONTADORA DE VEICULOS ESPECIAIS LTDA\JI Montadora - 02 Produção\01 Controle de Produção"
DEFAULT_BOM_DIR = r"C:\Users\PRODUCAO-2.0\J I MONTADORA DE VEICULOS ESPECIAIS LTDA\JI Montadora - 02 Produção\01 Controle de Produção\01 - Projeto Cadastro\02 - B.O.M"

PRODUTOS_FILE = os.path.join(DATA_DIR, "produtos.json")
FORNECEDORES_FILE = os.path.join(DATA_DIR, "fornecedores.json")
OS_PRODUTOS_FILE = PRODUTOS_FILE
OS_FORNECEDORES_FILE = os.path.join(DATA_DIR, "os_fornecedores.json")
OS_COMPONENTES_FILE = os.path.join(DATA_DIR, "os_componentes.json")
OS_PROCESSOS_FILE = os.path.join(DATA_DIR, "os_processos.json")
COUNTER_FILE = os.path.join(DATA_DIR, "oc_counter.txt")
OS_COUNTER_FILE = os.path.join(DATA_DIR, "os_counter.txt")
HISTORICO_FILE = os.path.join(DATA_DIR, "historico_oc.json")
OC_IMPORT_FILE = os.path.join(DATA_DIR, "oc_import.json")
OS_IMPORT_FILE = os.path.join(DATA_DIR, "os_import.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

TEMPLATE_WORD = os.path.join(TEMPLATE_DIR, "modelo_oc.docx")
TEMPLATE_OS = os.path.join(TEMPLATE_DIR, "modelo_os.docx")

EMPRESA_PADRAO = "JI MONTADORA"

ENDERECO_ENTREGA = {
    "cep": "13291072",
    "logradouro": "Rodovia Romildo Prado",
    "numero": "3145",
    "bairro": "Sagrado Coração de Jesus",
    "cidade": "Louveira",
    "uf": "SP",
    "pais": "BR"
}

def pasta_ano():
    ano = str(datetime.now().year)
    pedidos_dir, _ = get_save_paths()
    path = os.path.join(pedidos_dir, ano)
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except PermissionError:
        fallback = os.path.join(os.path.expanduser("~"), "Emissor documentos", "Pedidos de Compra", ano)
        os.makedirs(fallback, exist_ok=True)
        logging.getLogger(__name__).warning("Sem acesso a %s. Usando %s", path, fallback)
        return fallback


def pasta_ano_os():
    ano = str(datetime.now().year)
    _, os_dir = get_save_paths()
    path = os.path.join(os_dir, ano)
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except PermissionError:
        fallback = os.path.join(os.path.expanduser("~"), "Emissor documentos", "OS", ano)
        os.makedirs(fallback, exist_ok=True)
        logging.getLogger(__name__).warning("Sem acesso a %s. Usando %s", path, fallback)
        return fallback


def _mes_nome_pt(mes):
    nomes = [
        "Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ]
    try:
        return nomes[int(mes) - 1]
    except Exception:
        return ""


def _sanitize_pasta(texto):
    if texto is None:
        return ""
    texto = str(texto).strip()
    invalid = '<>:"/\\\\|?*'
    for ch in invalid:
        texto = texto.replace(ch, " ")
    return " ".join(texto.split())


def _carregar_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        return {}
    return {}


def salvar_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_save_paths():
    settings = _carregar_settings()
    pedidos_dir = settings.get("pedidos_dir") or DEFAULT_PEDIDOS_DIR
    os_dir = settings.get("os_dir") or DEFAULT_OS_DIR
    return pedidos_dir, os_dir


def set_save_paths(pedidos_dir=None, os_dir=None):
    settings = _carregar_settings()
    if pedidos_dir is not None and pedidos_dir.strip() != "":
        settings["pedidos_dir"] = pedidos_dir.strip()
    if os_dir is not None and os_dir.strip() != "":
        settings["os_dir"] = os_dir.strip()
    salvar_settings(settings)


def get_bom_dir():
    settings = _carregar_settings()
    return settings.get("bom_dir") or DEFAULT_BOM_DIR


def set_bom_dir(bom_dir):
    settings = _carregar_settings()
    if bom_dir and bom_dir.strip():
        settings["bom_dir"] = bom_dir.strip()
    else:
        settings.pop("bom_dir", None)
    salvar_settings(settings)


def pasta_os(numero_os, dados):
    ano = str(datetime.now().year)
    _, os_dir = get_save_paths()
    base_ano = os.path.join(os_dir, ano)
    try:
        os.makedirs(base_ano, exist_ok=True)
    except PermissionError:
        base_ano = os.path.join(os.path.expanduser("~"), "Emissor documentos", "OS", ano)
        os.makedirs(base_ano, exist_ok=True)
        logging.getLogger(__name__).warning("Sem acesso ao diretorio OS. Usando %s", base_ano)

    mes_num = datetime.now().strftime("%m")
    mes_dir = None
    try:
        for nome in os.listdir(base_ano):
            full = os.path.join(base_ano, nome)
            if os.path.isdir(full) and nome[:2] == mes_num:
                mes_dir = full
                break
    except FileNotFoundError:
        mes_dir = None

    if not mes_dir:
        mes_nome = _mes_nome_pt(mes_num)
        nome_pasta = f"{mes_num} {mes_nome}".strip()
        mes_dir = os.path.join(base_ano, nome_pasta)
        os.makedirs(mes_dir, exist_ok=True)

    numero_str = str(numero_os).strip()
    pasta_os_existente = None
    try:
        for nome in os.listdir(mes_dir):
            full = os.path.join(mes_dir, nome)
            if not os.path.isdir(full):
                continue
            nome_trim = nome.strip()
            if (
                nome_trim == numero_str
                or nome_trim.startswith(f"{numero_str} ")
                or nome_trim.startswith(f"{numero_str}-")
                or nome_trim.startswith(f"{numero_str} -")
            ):
                pasta_os_existente = full
                break
    except FileNotFoundError:
        pasta_os_existente = None

    if pasta_os_existente:
        return pasta_os_existente

    cliente = _sanitize_pasta(dados.get("cliente", ""))
    chassi = _sanitize_pasta(dados.get("chassis", ""))
    mmv = _sanitize_pasta(dados.get("mmv", ""))
    municipio = _sanitize_pasta(dados.get("municipio", ""))
    nome_pasta = f"{numero_str} - {cliente} - {chassi} - {mmv} - {municipio}"
    nome_pasta = nome_pasta.strip(" -")
    path = os.path.join(mes_dir, nome_pasta)
    os.makedirs(path, exist_ok=True)
    return path
