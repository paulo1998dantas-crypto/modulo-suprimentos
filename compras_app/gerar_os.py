import logging
import os
import tempfile
from datetime import datetime, timedelta

import pypdfium2 as pdfium
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches

from composicao import resolver_composicao_final
from config import TEMPLATE_OS, pasta_os
from os_template import mapear_tabelas_os

logger = logging.getLogger(__name__)


def _resolve_unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for idx in range(1, 100):
        candidato = f"{base} - R{idx:02d}{ext}"
        if not os.path.exists(candidato):
            return candidato
    return path


def _safe_save_doc(doc, path):
    try:
        doc.save(path)
        return path
    except Exception as exc:
        try:
            fallback_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(fallback_dir, exist_ok=True)
            fallback_path = _resolve_unique_path(os.path.join(fallback_dir, os.path.basename(path)))
            doc.save(fallback_path)
            logger.warning("Falha ao salvar em %s. Salvo em %s. Erro: %s", path, fallback_path, exc)
            return fallback_path
        except Exception:
            raise


def _set_cell_text(cell, texto):
    cell.text = "" if texto is None else str(texto)


def _set_cell_align(cell, alignment):
    for paragraph in cell.paragraphs:
        paragraph.alignment = alignment


def _set_vertical_merge(cell, mode=None):
    tc_pr = cell._tc.get_or_add_tcPr()
    vmerge = tc_pr.find(qn("w:vMerge"))
    if vmerge is None:
        vmerge = OxmlElement("w:vMerge")
        tc_pr.append(vmerge)
    if mode:
        vmerge.set(qn("w:val"), mode)
    else:
        if qn("w:val") in vmerge.attrib:
            del vmerge.attrib[qn("w:val")]


def _set_os_numero_legacy_unused(cell, numero_os):
    while len(cell.paragraphs) < 2:
        cell.add_paragraph()
    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in paragraph.runs:
            run.text = ""
    p0 = cell.paragraphs[0]
    p1 = cell.paragraphs[1]
    p0.add_run("Nº")
    run_num = p1.add_run(str(numero_os))
    run_num.bold = True


def _set_os_numero(cell, numero_os):
    while len(cell.paragraphs) < 2:
        cell.add_paragraph()
    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in paragraph.runs:
            run.text = ""
    p0 = cell.paragraphs[0]
    p1 = cell.paragraphs[1]
    p0.add_run("N\u00ba Ordem de Servi\u00e7o")
    run_num = p1.add_run(str(numero_os))
    run_num.bold = True


def _limpar_linhas_apos(tabela, header_index):
    for idx in range(len(tabela.rows) - 1, header_index, -1):
        tabela._tbl.remove(tabela.rows[idx]._tr)


def _formatar_datetime_local(texto):
    if not texto:
        return ""
    texto = str(texto).strip()
    if "T" in texto:
        data, hora = texto.split("T", 1)
        partes = data.split("-")
        if len(partes) == 3:
            ano, mes, dia = partes
            return f"{dia}/{mes}/{ano} - {hora}"
    return texto


def _parse_datetime_local(texto):
    if not texto:
        return None
    texto = str(texto).strip()
    formatos = (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%d/%m/%Y - %H:%M:%S",
        "%d/%m/%Y - %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    )
    for formato in formatos:
        try:
            return datetime.strptime(texto, formato)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _formatar_data_necessidade(texto):
    dt = _parse_datetime_local(texto)
    if dt is not None:
        return (dt - timedelta(days=1)).strftime("%d/%m/%Y")
    texto_formatado = _formatar_datetime_local(texto)
    if " - " in texto_formatado:
        return texto_formatado.split(" - ", 1)[0]
    return texto_formatado


def _configurar_cabecalho_requisicao(doc, refs, dados):
    if refs.get("cabecalho") is not None and refs["cabecalho"] < len(doc.tables):
        tabela_cabecalho = doc.tables[refs["cabecalho"]]
        if tabela_cabecalho.rows and len(tabela_cabecalho.rows[0].cells) > 1:
            _set_cell_text(tabela_cabecalho.cell(0, 1), "ORDEM DE REQUISI\u00c7\u00c3O")

    if refs.get("dados") is None or refs["dados"] >= len(doc.tables):
        return

    tabela_dados = doc.tables[refs["dados"]]
    if tabela_dados.rows:
        for cell in tabela_dados.rows[0].cells:
            _set_cell_text(cell, "DADOS DA ORDEM DE REQUISI\u00c7\u00c3O")
    if len(tabela_dados.rows) > 3 and len(tabela_dados.rows[3].cells) >= 4:
        _set_cell_text(tabela_dados.cell(3, 0), "DATA DE NECESSIDADE:")
        _set_cell_text(
            tabela_dados.cell(3, 1),
            _formatar_data_necessidade(dados.get("previsao_inicio", "")),
        )
        _set_cell_text(tabela_dados.cell(3, 2), "")
        _set_cell_text(tabela_dados.cell(3, 3), "")


def _preencher_tabela_produtos(tabela, itens):
    _limpar_linhas_apos(tabela, 0)
    for item in itens:
        row = tabela.add_row().cells
        _set_cell_text(row[0], item.get("codigo", ""))
        _set_cell_text(row[1], item.get("descricao", ""))
        _set_cell_text(row[2], item.get("qtd", ""))
        _set_cell_text(row[3], item.get("serie", ""))
        _set_cell_text(row[4], item.get("unidade", ""))
        for cell in row:
            _set_cell_align(cell, WD_ALIGN_PARAGRAPH.CENTER)


def _preencher_tabela_componentes(tabela, composicao):
    _limpar_linhas_apos(tabela, 1)
    for comp in composicao or []:
        row = tabela.add_row().cells
        try:
            level = int(comp.get("level", 0) or 0)
        except Exception:
            level = 0
        prefixo = " >" * level
        descricao = f"{prefixo} {comp.get('descricao', '')}".strip() if level else comp.get("descricao", "")
        _set_cell_text(row[0], comp.get("codigo", ""))
        _set_cell_text(row[1], descricao)
        _set_cell_text(row[2], comp.get("qtd", ""))
        _set_cell_text(row[3], comp.get("unidade", ""))
        for cell in row:
            _set_cell_align(cell, WD_ALIGN_PARAGRAPH.CENTER)


def _preencher_tabela_processo(tabela, linhas):
    _limpar_linhas_apos(tabela, 1)
    linhas = list(linhas or [])
    if not linhas:
        return

    responsavel = next((str(linha.get("responsavel", "") or "").strip() for linha in linhas if str(linha.get("responsavel", "") or "").strip()), "")
    data = next((str(linha.get("data", "") or "").strip() for linha in linhas if str(linha.get("data", "") or "").strip()), "")
    inicio = next((str(linha.get("inicio", "") or "").strip() for linha in linhas if str(linha.get("inicio", "") or "").strip()), "")
    fim = next((str(linha.get("fim", "") or "").strip() for linha in linhas if str(linha.get("fim", "") or "").strip()), "")
    feito = next((str(linha.get("feito", "") or "").strip() for linha in linhas if str(linha.get("feito", "") or "").strip()), "")

    for idx, linha in enumerate(linhas, start=1):
        row = tabela.add_row().cells
        _set_cell_text(row[0], idx)
        if len(row) > 1:
            _set_cell_text(row[1], linha.get("atividade", ""))
        for col_idx in range(2, len(row)):
            _set_cell_text(row[col_idx], "")
        for cell in row:
            _set_cell_align(cell, WD_ALIGN_PARAGRAPH.CENTER)

    first_data_row = 2
    last_data_row = len(tabela.rows) - 1
    for col_idx, valor in (
        (2, responsavel),
        (3, data),
        (4, inicio),
        (5, fim),
        (6, feito),
    ):
        if col_idx >= len(tabela.columns):
            continue
        cell = tabela.rows[first_data_row].cells[col_idx]
        if last_data_row > first_data_row:
            _set_vertical_merge(cell, "restart")
            for row_idx in range(first_data_row + 1, last_data_row + 1):
                cont_cell = tabela.rows[row_idx].cells[col_idx]
                _set_cell_text(cont_cell, "")
                _set_vertical_merge(cont_cell)
        _set_cell_text(cell, valor)
        _set_cell_align(cell, WD_ALIGN_PARAGRAPH.CENTER)


def _limpar_layout(tabela):
    if len(tabela.rows) <= 1 or len(tabela.rows[1].cells) == 0:
        return
    cell = tabela.cell(1, 0)
    cell.text = ""
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.text = ""


def _inserir_layout_pdf(tabela, file_storage):
    if not tabela or not file_storage or not file_storage.filename:
        return

    tmp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp_pdf.close()
    file_storage.save(tmp_pdf.name)

    try:
        from PIL import Image  # noqa: F401
    except Exception:
        logger.warning("Pillow nao encontrado. Ignorando insercao do layout PDF.")
        return

    pdf = pdfium.PdfDocument(tmp_pdf.name)
    if len(pdf) == 0:
        return

    page = pdf[0]
    try:
        pil_image = page.render(scale=2).to_pil()
    except Exception as exc:
        logger.warning("Falha ao renderizar PDF para imagem: %s", exc)
        return

    tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp_img.close()
    pil_image.save(tmp_img.name)

    cell = tabela.cell(1, 0)
    cell.text = ""
    paragraph = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    paragraph.add_run().add_picture(tmp_img.name, width=Inches(6.8))


def _remover_tabela(doc, tabela):
    try:
        tabela._tbl.getparent().remove(tabela._tbl)
    except Exception:
        pass


def _alinhar_descricao_esquerda(tabela, coluna, inicio_linha=0):
    if not tabela:
        return
    for row in tabela.rows[inicio_linha:]:
        if len(row.cells) <= coluna:
            continue
        for paragraph in row.cells[coluna].paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT


def _alinhar_tudo_centro(doc):
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _alinhar_tabelas_processo(refs, doc):
    for idx in refs.get("processos", {}).values():
        if idx >= len(doc.tables):
            continue
        tabela = doc.tables[idx]
        for row in tabela.rows[2:]:
            for cell_idx, cell in enumerate(row.cells):
                alinhamento = WD_ALIGN_PARAGRAPH.LEFT if cell_idx == 1 else WD_ALIGN_PARAGRAPH.CENTER
                for paragraph in cell.paragraphs:
                    paragraph.alignment = alinhamento


def _salvar_documento_os(doc, numero_os, dados, titulo_arquivo="O.S"):
    pasta = pasta_os(numero_os, dados)
    cliente = (dados.get("cliente", "") or "").strip()
    chassi = (dados.get("chassis", "") or "").strip()
    nome = f"02 - {titulo_arquivo} - {cliente} - {chassi}.docx"
    path = os.path.join(pasta, nome)
    path = _resolve_unique_path(path)
    return _safe_save_doc(doc, path)


def gerar_os_docx(
    numero_os,
    dados,
    itens,
    componentes,
    processos,
    layout_pdf=None,
    composicao_resolvida=None,
    modo="completa",
    titulo_arquivo="O.S",
):
    doc = Document(TEMPLATE_OS)
    refs = mapear_tabelas_os(doc)

    if refs.get("cabecalho") is not None:
        _set_os_numero(doc.tables[refs["cabecalho"]].cell(0, 2), numero_os)

    if refs.get("dados") is not None:
        tabela_dados = doc.tables[refs["dados"]]
        _set_cell_text(tabela_dados.cell(1, 1), dados.get("chassis", ""))
        _set_cell_text(tabela_dados.cell(1, 3), dados.get("municipio", ""))
        _set_cell_text(tabela_dados.cell(2, 1), dados.get("cliente", ""))
        _set_cell_text(tabela_dados.cell(2, 3), dados.get("mmv", ""))
        _set_cell_text(tabela_dados.cell(3, 1), _formatar_datetime_local(dados.get("previsao_inicio", "")))
        _set_cell_text(tabela_dados.cell(3, 3), _formatar_datetime_local(dados.get("previsao_termino", "")))

    if modo in {"expedicao", "preparacao"}:
        _configurar_cabecalho_requisicao(doc, refs, dados)

    if refs.get("itens") is not None:
        _preencher_tabela_produtos(doc.tables[refs["itens"]], itens)

    composicao_final = composicao_resolvida or resolver_composicao_final(itens, componentes)
    ocultar_composicao = modo in {"resumida", "producao", "expedicao", "preparacao"}
    ocultar_observacoes = modo in {"mascara", "producao", "expedicao", "preparacao"}
    ocultar_processos = modo in {"mascara", "expedicao", "preparacao"}

    if not ocultar_composicao and refs.get("composicao") is not None:
        _preencher_tabela_componentes(doc.tables[refs["composicao"]], composicao_final)

    if ocultar_composicao and refs.get("composicao") is not None:
        _remover_tabela(doc, doc.tables[refs["composicao"]])
        refs = mapear_tabelas_os(doc)

    if modo == "mascara":
        indices_remover = []
        if refs.get("observacoes") is not None:
            indices_remover.append(refs["observacoes"])
        indices_remover.extend(refs.get("processos", {}).values())
        for idx in sorted(set(indices_remover), reverse=True):
            if idx < len(doc.tables):
                _remover_tabela(doc, doc.tables[idx])
        refs = mapear_tabelas_os(doc)
        if refs.get("layout") is not None:
            tabela_layout = doc.tables[refs["layout"]]
            _limpar_layout(tabela_layout)
            _inserir_layout_pdf(tabela_layout, layout_pdf)
        _alinhar_tudo_centro(doc)
        if refs.get("itens") is not None and refs["itens"] < len(doc.tables):
            _alinhar_descricao_esquerda(doc.tables[refs["itens"]], 1)
        if refs.get("composicao") is not None and refs["composicao"] < len(doc.tables):
            _alinhar_descricao_esquerda(doc.tables[refs["composicao"]], 1, inicio_linha=1)
        return _salvar_documento_os(doc, numero_os, dados, titulo_arquivo=titulo_arquivo)

    if ocultar_observacoes and refs.get("observacoes") is not None:
        _remover_tabela(doc, doc.tables[refs["observacoes"]])
        refs = mapear_tabelas_os(doc)
    elif refs.get("observacoes") is not None:
        tabela_obs = doc.tables[refs["observacoes"]]
        if len(tabela_obs.rows) > 1:
            _set_cell_text(tabela_obs.cell(1, 0), dados.get("obs_materiais", ""))

    if ocultar_processos:
        indices_processos_vazios = list(refs.get("processos", {}).values())
    else:
        indices_processos_vazios = [
            idx
            for nome, idx in refs.get("processos", {}).items()
            if not (processos.get(nome) or [])
        ]
    for idx in sorted(set(indices_processos_vazios), reverse=True):
        if idx < len(doc.tables):
            _remover_tabela(doc, doc.tables[idx])

    refs = mapear_tabelas_os(doc)
    for nome, idx in refs.get("processos", {}).items():
        linhas = processos.get(nome, [])
        if idx < len(doc.tables) and linhas:
            _preencher_tabela_processo(doc.tables[idx], linhas)

    if dados.get("obs"):
        doc.add_paragraph("")
        doc.add_paragraph(f"OBS FINAL: {dados.get('obs')}")

    if refs.get("layout") is not None and refs["layout"] < len(doc.tables):
        tabela_layout = doc.tables[refs["layout"]]
        _limpar_layout(tabela_layout)
        _inserir_layout_pdf(tabela_layout, layout_pdf)

    _alinhar_tudo_centro(doc)
    refs = mapear_tabelas_os(doc)

    if refs.get("itens") is not None and refs["itens"] < len(doc.tables):
        _alinhar_descricao_esquerda(doc.tables[refs["itens"]], 1)

    if refs.get("composicao") is not None and refs["composicao"] < len(doc.tables):
        _alinhar_descricao_esquerda(doc.tables[refs["composicao"]], 1, inicio_linha=1)

    if refs.get("dados") is not None and refs["dados"] < len(doc.tables):
        tabela_dados = doc.tables[refs["dados"]]
        for row_idx, col_idx in [(1, 1), (2, 1), (3, 1)]:
            if row_idx < len(tabela_dados.rows) and col_idx < len(tabela_dados.rows[row_idx].cells):
                _set_cell_align(tabela_dados.rows[row_idx].cells[col_idx], WD_ALIGN_PARAGRAPH.LEFT)

    _alinhar_tabelas_processo(refs, doc)
    return _salvar_documento_os(doc, numero_os, dados, titulo_arquivo=titulo_arquivo)
