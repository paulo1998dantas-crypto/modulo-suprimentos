from flask import Flask, render_template, request, send_file, redirect, url_for, after_this_request
import re
import json
import os
import logging
import tempfile
import sys
import shutil
import zipfile
import subprocess
from datetime import date, timedelta, datetime
import tempfile
import zipfile
from openpyxl import Workbook
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
    COUNTER_FILE,
    OS_COUNTER_FILE,
    HISTORICO_FILE,
    OC_IMPORT_FILE,
    OS_IMPORT_FILE,
    get_save_paths,
    set_save_paths,
    get_bom_dir,
    set_bom_dir,
)
from calculos import calcular_total_item
from composicao import expandir_composicao_itens, normalizar_codigo, normalizar_componentes, normalizar_linha_composicao
from gerar_oc import gerar_word, construir_nome_oc
from gerar_os import gerar_os_docx

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = "emissor_documentos"

def _is_in_dir(path, base):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) == os.path.abspath(base)
    except Exception:
        return False


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
    dist_dir = os.path.join(project_root, "dist")
    if os.path.isdir(dist_dir):
        preferred = os.path.join(dist_dir, "Emissor documentos")
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
    bat_path = os.path.join(project_root, "gerar_exe.bat")
    if not os.path.isfile(bat_path):
        return False, "Arquivo gerar_exe.bat nao encontrado no projeto."
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
    staging = os.path.join(temp_root, "Emissor")
    shutil.copytree(source_dir, staging, dirs_exist_ok=True)

    zip_path = os.path.join(temp_root, "EmissorCurto.zip")
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


def salvar_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise PermissionError(
            f"Falha ao salvar dados em '{path}'. Verifique permissao/OneDrive."
        ) from exc


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
            responsavel = row.cells[3].text.strip() if len(row.cells) > 3 else ""
            linhas.append({"atividade": atividade, "responsavel": responsavel})
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



def _criar_modelo_xlsx(headers, nome_arquivo):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    temp.close()
    wb.save(temp.name)
    return temp.name, nome_arquivo


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


def importar_produtos(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header = [normalizar_header(h) for h in linhas[0]]
    mapa = {name: idx for idx, name in enumerate(header)}

    produtos = carregar_produtos()
    count = 0

    for row in linhas[1:]:
        codigo = row[mapa.get("codigo", 0)] if mapa else ""
        codigo = str(codigo).strip()
        if not codigo:
            continue

        def pegar(col):
            idx = mapa.get(col)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        atual = produtos.get(codigo, {})
        def _pick(campo, valor):
            return valor if valor != "" else atual.get(campo, "")
        produtos[codigo] = {
            "descricao": _pick("descricao", pegar("descricao")),
            "unidade": _pick("unidade", pegar("unidade")),
            "valor": _pick("valor", pegar("valor")),
            "ipi": _pick("ipi", pegar("ipi")),
            "icms": _pick("icms", pegar("icms")),
            "cofins": _pick("cofins", pegar("cofins")),
        }
        count += 1

    salvar_json(PRODUTOS_FILE, produtos)
    return count


def importar_fornecedores(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header = [normalizar_header(h) for h in linhas[0]]
    mapa = {name: idx for idx, name in enumerate(header)}

    fornecedores = carregar_fornecedores()
    count = 0

    for row in linhas[1:]:
        def pegar(col):
            idx = mapa.get(col)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        fornecedor = pegar("fornecedor")
        cnpj = pegar("cnpj")
        chave = cnpj if cnpj else fornecedor
        if not chave:
            continue

        atual = fornecedores.get(chave, {})
        def _pick(campo, valor):
            return valor if valor != "" else atual.get(campo, "")
        fornecedores[chave] = {
            "fornecedor": _pick("fornecedor", fornecedor),
            "razao_social": _pick("razao_social", pegar("razao_social")),
            "cnpj": _pick("cnpj", cnpj),
            "email": _pick("email", pegar("email")),
            "telefone": _pick("telefone", pegar("telefone")),
            "endereco": _pick("endereco", pegar("endereco")),
            "bairro": _pick("bairro", pegar("bairro")),
            "cidade": _pick("cidade", pegar("cidade")),
            "uf": _pick("uf", pegar("uf")),
            "cep": _pick("cep", pegar("cep")),
        }
        count += 1

    salvar_json(FORNECEDORES_FILE, fornecedores)
    return count


def importar_os_produtos(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header = [normalizar_header(h) for h in linhas[0]]
    mapa = {name: idx for idx, name in enumerate(header)}

    produtos = carregar_os_produtos()
    count = 0

    for row in linhas[1:]:
        codigo = row[mapa.get("codigo", 0)] if mapa else ""
        codigo = str(codigo).strip()
        if not codigo:
            continue

        def pegar(col):
            idx = mapa.get(col)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        atual = produtos.get(codigo, {})
        def _pick(campo, valor):
            return valor if valor != "" else atual.get(campo, "")
        produtos[codigo] = dict(atual)
        produtos[codigo]["descricao"] = _pick("descricao", pegar("descricao"))
        produtos[codigo]["unidade"] = _pick("unidade", pegar("unidade"))
        count += 1

    salvar_json(OS_PRODUTOS_FILE, produtos)
    return count


def importar_os_fornecedores(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header = [normalizar_header(h) for h in linhas[0]]
    mapa = {name: idx for idx, name in enumerate(header)}

    fornecedores = carregar_os_fornecedores()
    count = 0

    for row in linhas[1:]:
        def pegar(col):
            idx = mapa.get(col)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        fornecedor = pegar("fornecedor") or pegar("cliente")
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


def importar_os_componentes(file_storage):
    linhas = ler_linhas_arquivo(file_storage)
    if not linhas:
        return 0

    header = [normalizar_header(h) for h in linhas[0]]
    mapa = {name: idx for idx, name in enumerate(header)}

    componentes = carregar_os_componentes()
    count = 0
    vistos = set()

    for row in linhas[1:]:
        def pegar(col):
            idx = mapa.get(col)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        item_codigo = normalizar_codigo(pegar("item_codigo") or pegar("codigo_item") or pegar("codigo"))
        if not item_codigo:
            continue

        comp = {
            "codigo": normalizar_codigo(pegar("componente_codigo") or pegar("codigo_componente")),
            "descricao": pegar("descricao"),
            "unidade": pegar("unidade"),
            "quantidade": pegar("quantidade") or pegar("qtd"),
        }

        if item_codigo not in vistos:
            componentes[item_codigo] = []
            vistos.add(item_codigo)
        componentes.setdefault(item_codigo, []).append(comp)
        count += 1

    salvar_json(OS_COMPONENTES_FILE, componentes)
    return count


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
            processo_key = mapa_proc.get(processo_norm, processo)

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
        processo_key = mapa_proc.get(processo_norm, processo)
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

    produtos = carregar_produtos()
    fornecedores = carregar_fornecedores()
    os_produtos = carregar_os_produtos()
    os_fornecedores = carregar_os_fornecedores()
    os_componentes = carregar_os_componentes()
    os_processos = carregar_os_processos()
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
    save_paths = {"pedidos_dir": pedidos_dir, "os_dir": os_dir, "bom_dir": bom_dir}
    bom_status = request.args.get("bom_status")

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
        bom_status=bom_status,
    )


@app.route("/gerar_oc", methods=["POST"])
def gerar_oc():

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

    os_fornecedores = carregar_os_fornecedores()
    cliente = request.form.get("os_cliente", "")

    os_produtos = carregar_os_produtos()
    itens = []

    codigos = request.form.getlist("os_codigo[]")
    qtds = request.form.getlist("os_qtd[]")
    series = request.form.getlist("os_serie[]")
    unidades = request.form.getlist("os_unidade[]")
    descricoes = request.form.getlist("os_descricao[]")
    for i in range(len(codigos)):
        codigo_item = normalizar_codigo(codigos[i])
        if not codigo_item:
            continue
        total = calcular_total_item(qtds[i], 0, 0)

        qtd = float(qtds[i]) if qtds[i] else 0
        valor = 0

        item_info = os_produtos.get(codigo_item, {})
        desc_form = descricoes[i] if i < len(descricoes) else ""
        unidade_form = unidades[i] if i < len(unidades) else ""
        descricao_final = item_info.get("descricao") or desc_form
        unidade_final = unidades[i] if i < len(unidades) else item_info.get("unidade", "")
        itens.append({
            "codigo": codigo_item,
            "descricao": descricao_final,
            "qtd": qtd,
            "serie": series[i] if i < len(series) else "",
            "unidade": unidade_final or item_info.get("unidade", ""),
            "valor": valor,
            "total": total
        })

    total_itens = 0
    for item in itens:
        total_itens += item["total"]

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
    }
    processos = carregar_os_processos()

    processos_input = {
        "CORTE": (request.form.getlist("proc_corte_atividade[]"), request.form.getlist("proc_corte_responsavel[]")),
        "AR CONDICIONADO": (request.form.getlist("proc_ar_atividade[]"), request.form.getlist("proc_ar_responsavel[]")),
        "PREPARAÇÃO DE PEÇAS": (request.form.getlist("proc_preparacao_atividade[]"), request.form.getlist("proc_preparacao_responsavel[]")),
        "ISOLAMENTO": (request.form.getlist("proc_isolamento_atividade[]"), request.form.getlist("proc_isolamento_responsavel[]")),
        "REVESTIMENTO": (request.form.getlist("proc_revestimento_atividade[]"), request.form.getlist("proc_revestimento_responsavel[]")),
        "BANCOS": (request.form.getlist("proc_bancos_atividade[]"), request.form.getlist("proc_bancos_responsavel[]")),
        "ELÉTRICA 2": (request.form.getlist("proc_eletrica_atividade[]"), request.form.getlist("proc_eletrica_responsavel[]")),
        "LIMPEZA/LIBERAÇÃO": (request.form.getlist("proc_limpeza_atividade[]"), request.form.getlist("proc_limpeza_responsavel[]")),
    }

    processos_final = {}
    for nome, (atividades, responsaveis) in processos_input.items():
        linhas = []
        for i in range(len(atividades)):
            atv = atividades[i].strip()
            resp = responsaveis[i].strip() if i < len(responsaveis) else ""
            if atv:
                linhas.append({"atividade": atv, "responsavel": resp})
        processos_final[nome] = linhas

    numero_manual = request.form.get("os_numero", "").strip()
    if numero_manual:
        numero_os = numero_manual
    else:
        numero_os = proximo_numero_os()

    componentes = carregar_os_componentes()
    layout_pdf = request.files.get("os_layout_pdf")
    comp_itens = request.form.getlist("os_comp_item[]")
    comp_codigos = request.form.getlist("os_comp_codigo[]")
    comp_descricoes = request.form.getlist("os_comp_descricao[]")
    comp_unidades = request.form.getlist("os_comp_unidade[]")
    comp_qtds = request.form.getlist("os_comp_qtd[]")
    comp_levels = request.form.getlist("os_comp_level[]")
    composicao_importada = []
    for i in range(len(comp_codigos)):
        item_pai = normalizar_codigo(comp_itens[i]) if i < len(comp_itens) else ""
        codigo = normalizar_codigo(comp_codigos[i]) if i < len(comp_codigos) else ""
        desc = comp_descricoes[i].strip() if i < len(comp_descricoes) else ""
        un = comp_unidades[i].strip() if i < len(comp_unidades) else ""
        qtd = comp_qtds[i].strip() if i < len(comp_qtds) else ""
        try:
            level = int((comp_levels[i] if i < len(comp_levels) else "0") or 0)
        except Exception:
            level = 0
        if not (codigo or desc or qtd or un):
            continue
        composicao_importada.append({
            "item": item_pai,
            "codigo": codigo,
            "descricao": desc,
            "unidade": un,
            "qtd": qtd,
            "level": level,
        })

    modo_os = request.form.get("os_mode", "completa")
    arquivo = gerar_os_docx(
        numero_os,
        dados,
        itens,
        componentes,
        processos_final,
        layout_pdf,
        composicao_importada or None,
        modo=modo_os,
    )

    limpar_importacao(OS_IMPORT_FILE)

    composicao_final = []
    if composicao_importada:
        for comp in composicao_importada:
            composicao_final.append(normalizar_linha_composicao(comp, item=comp.get("item", ""), level=comp.get("level", 0)))
    else:
        composicao_final = expandir_composicao_itens(itens, componentes)

    cliente_nome = (dados.get("cliente", "") or "").strip()
    chassi_nome = (dados.get("chassis", "") or "").strip()
    nome_docx = f"02 - O.S. - {cliente_nome} - {chassi_nome}.docx"
    registrar_historico("os", numero_os, dados, itens=itens, processos=processos_final, componentes=componentes, composicao=composicao_final)
    _, os_dir = get_save_paths()
    salvo_onedrive = _is_in_dir(arquivo, os_dir)
    resp = send_file(arquivo, as_attachment=True, download_name=nome_docx)
    resp.set_cookie("save_status", "onedrive" if salvo_onedrive else "fallback", max_age=20, path="/")
    return resp


@app.route("/salvar_caminhos", methods=["POST"])
def salvar_caminhos():
    pedidos_dir = request.form.get("pedidos_dir", "")
    os_dir = request.form.get("os_dir", "")
    bom_dir = request.form.get("bom_dir", "")
    set_save_paths(pedidos_dir, os_dir)
    set_bom_dir(bom_dir)
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
        def _pick(campo, valor):
            return valor if valor != "" else atual.get(campo, "")
        produtos[codigo] = {
            "descricao": _pick("descricao", request.form.get("descricao", "").strip()),
            "unidade": _pick("unidade", request.form.get("unidade", "").strip()),
            "valor": _pick("valor", request.form.get("valor", "").strip()),
            "ipi": _pick("ipi", request.form.get("ipi", "").strip()),
            "icms": _pick("icms", request.form.get("icms", "").strip()),
            "cofins": _pick("cofins", request.form.get("cofins", "").strip()),
        }

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
        produtos[codigo] = dict(atual_prod)
        produtos[codigo]["descricao"] = descricao if descricao != "" else atual_prod.get("descricao", "")
        produtos[codigo]["unidade"] = (unidade or "").strip() or atual_prod.get("unidade", "UN") or "UN"
        if comps:
            componentes[codigo] = comps
        elif codigo in componentes:
            componentes[codigo] = componentes.get(codigo, [])
        else:
            return "Informe ao menos um componente para o item da OS.", 400

        salvar_json(OS_PRODUTOS_FILE, produtos)
        salvar_json(OS_COMPONENTES_FILE, componentes)

    return index()


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

    excel_exts = {".xls", ".xlsx", ".xlsm", ".xltx", ".xltm"}
    arquivos = []
    for root, _, nomes in os.walk(bom_dir):
        for nome in nomes:
            if os.path.splitext(nome)[1].lower() in excel_exts:
                arquivos.append(os.path.join(root, nome))
    arquivos.sort()

    if not arquivos:
        status = f"Nenhuma planilha Excel (.xls/.xlsx/.xlsm/.xltx/.xltm) encontrada em {bom_dir}"
        return redirect(url_for("index", tab="cadastro", bom_status=status))

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


@app.route("/importar_os_processos", methods=["POST"])
def importar_os_processos_route():

    arquivo = request.files.get("arquivo_os_processos")
    if arquivo and arquivo.filename:
        importar_os_processos(arquivo)

    return redirect(url_for("index", tab="os"))


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
            data = parse_os_docx(arquivo)
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
        ["codigo", "descricao", "unidade", "valor", "ipi", "icms", "cofins"],
        "modelo_produtos.xlsx",
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
    path, nome = _criar_modelo_xlsx(["codigo", "descricao", "unidade"], "modelo_os_itens.xlsx")
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
    path, nome = _criar_modelo_xlsx(
        [
            "CORTE",
            "AR CONDICIONADO",
            "PREPARAÇÃO DE PEÇAS",
            "ISOLAMENTO",
            "REVESTIMENTO",
            "BANCOS",
            "ELÉTRICA 2",
            "LIMPEZA/LIBERAÇÃO",
        ],
        "modelo_os_processos.xlsx",
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

    return send_file(zip_path, as_attachment=True, download_name="EmissorCurto.zip")


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
