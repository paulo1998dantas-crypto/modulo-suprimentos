import os
import tempfile
import logging
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches
from composicao import expandir_composicao_itens
from config import TEMPLATE_OS, pasta_os
import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

def _resolve_unique_path(path):
    dir_path = os.path.dirname(path)
    try:
        arquivos = os.listdir(dir_path)
    except Exception:
        arquivos = []
    existe_02 = any(
        a.lower().endswith(".docx") and a.strip().startswith("02")
        for a in arquivos
    )
    if not os.path.exists(path) and not existe_02:
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 100):
        candidato = f"{base} - R{i:02d}{ext}"
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


def _set_cell_align_center(cell):
    for p in cell.paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _set_os_numero(cell, numero_os):
    # Mantem alinhamento central e quebra em duas linhas como no template
    while len(cell.paragraphs) < 2:
        cell.add_paragraph()
    for p in cell.paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p.runs:
            run.text = ""
    p0 = cell.paragraphs[0]
    p1 = cell.paragraphs[1]
    run0 = p0.add_run("Nº")
    run0.bold = False
    run1 = p1.add_run(str(numero_os))
    run1.bold = True


def _limpar_linhas_apos(tabela, header_index):
    for i in range(len(tabela.rows) - 1, header_index, -1):
        tabela._tbl.remove(tabela.rows[i]._tr)


def _normalizar_numero(numero):
    return str(numero).strip()


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


def _preencher_tabela_produtos(tabela, itens):
    # Mantem cabecalho de colunas (linha 0)
    _limpar_linhas_apos(tabela, 0)

    for item in itens:
        row = tabela.add_row().cells
        _set_cell_text(row[0], item.get("codigo", ""))
        _set_cell_text(row[1], item.get("descricao", ""))
        _set_cell_text(row[2], item.get("qtd", ""))
        _set_cell_text(row[3], item.get("serie", ""))
        _set_cell_text(row[4], item.get("unidade", ""))
        for cell in row:
            _set_cell_align_center(cell)


def _preencher_tabela_componentes(tabela, itens, componentes):
    # Mantem titulo e cabecalho de colunas (linhas 0 e 1)
    _limpar_linhas_apos(tabela, 1)

    for comp in expandir_composicao_itens(itens, componentes):
        row = tabela.add_row().cells
        _set_cell_text(row[0], comp.get("codigo", ""))
        _set_cell_text(row[1], comp.get("descricao", ""))
        _set_cell_text(row[2], comp.get("qtd", ""))
        _set_cell_text(row[3], comp.get("unidade", ""))
        for cell in row:
            _set_cell_align_center(cell)


def _preencher_tabela_componentes_direto(tabela, composicao):
    # Mantem titulo e cabecalho de colunas (linhas 0 e 1)
    _limpar_linhas_apos(tabela, 1)

    for comp in composicao:
        row = tabela.add_row().cells
        _set_cell_text(row[0], comp.get("codigo", ""))
        _set_cell_text(row[1], comp.get("descricao", ""))
        _set_cell_text(row[2], comp.get("qtd", ""))
        _set_cell_text(row[3], comp.get("unidade", ""))
        for cell in row:
            _set_cell_align_center(cell)


def _preencher_tabela_processo(tabela, linhas):
    # mantem titulo e cabecalho de colunas (linhas 0 e 1)
    _limpar_linhas_apos(tabela, 1)

    for idx, linha in enumerate(linhas, start=1):
        row = tabela.add_row().cells
        _set_cell_text(row[0], idx)
        atividade = linha.get("atividade", "")
        try:
            merged = row[1].merge(row[2])
            _set_cell_text(merged, atividade)
        except Exception:
            _set_cell_text(row[1], atividade)
            _set_cell_text(row[2], "")
        _set_cell_text(row[3], linha.get("responsavel", ""))
        _set_cell_text(row[4], "")
        _set_cell_text(row[5], "")


def _inserir_layout_pdf(doc, file_storage, table_index=13):
    if not file_storage or not file_storage.filename:
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

    if len(doc.tables) > table_index:
        t = doc.tables[table_index]
        cell = t.cell(1, 0)
        cell.text = ""
        p = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
        p.add_run().add_picture(tmp_img.name, width=Inches(6.8))


def _limpar_layout(doc, table_index=13):
    if len(doc.tables) > table_index:
        t = doc.tables[table_index]
        cell = t.cell(1, 0)
        cell.text = ""
        for p in cell.paragraphs:
            for run in p.runs:
                run.text = ""

def _remover_tabela(doc, tabela):
    try:
        tabela._tbl.getparent().remove(tabela._tbl)
    except Exception:
        pass


def gerar_os_docx(numero_os, dados, itens, componentes, processos, layout_pdf=None, composicao_importada=None, modo="completa"):
    doc = Document(TEMPLATE_OS)

    # Tabela 0 - Cabecalho numero OS
    t0 = doc.tables[0]
    _set_os_numero(t0.cell(0, 2), numero_os)

    # Tabela 1 - Dados da ordem
    t1 = doc.tables[1]
    _set_cell_text(t1.cell(1, 1), dados.get("chassis", ""))
    _set_cell_text(t1.cell(1, 3), dados.get("municipio", ""))
    _set_cell_text(t1.cell(2, 1), dados.get("cliente", ""))
    _set_cell_text(t1.cell(2, 3), dados.get("mmv", ""))
    _set_cell_text(t1.cell(3, 1), _formatar_datetime_local(dados.get("previsao_inicio", "")))
    _set_cell_text(t1.cell(3, 3), _formatar_datetime_local(dados.get("previsao_termino", "")))

    # Tabela 2 - Produtos
    _preencher_tabela_produtos(doc.tables[2], itens)

    # Tabela 3 - Composicao (so quando nao for resumida)
    if modo != "resumida":
        if composicao_importada:
            _preencher_tabela_componentes_direto(doc.tables[3], composicao_importada)
        else:
            _preencher_tabela_componentes(doc.tables[3], itens, componentes)

    if modo == "mascara":
        # remove obs materiais e processos, mas manter layout
        remover_indices = list(range(4, min(len(doc.tables), 13)))
        for idx in sorted(remover_indices, reverse=True):
            _remover_tabela(doc, doc.tables[idx])
        layout_idx = len(doc.tables) - 1 if len(doc.tables) > 0 else 0
        _limpar_layout(doc, layout_idx)
        _inserir_layout_pdf(doc, layout_pdf, layout_idx)
        pasta = pasta_os(numero_os, dados)
        cliente = (dados.get("cliente", "") or "").strip()
        chassi = (dados.get("chassis", "") or "").strip()
        nome = f"02 - O.S. - {cliente} - {chassi}.docx"
        path = os.path.join(pasta, nome)
        path = _resolve_unique_path(path)
        path = _safe_save_doc(doc, path)
        return path

    offset = -1 if modo == "resumida" else 0
    if modo == "resumida":
        _remover_tabela(doc, doc.tables[3])

    # Tabela 4 - Observacoes materiais
    t4 = doc.tables[4 + offset]
    if len(t4.rows) > 1:
        _set_cell_text(t4.cell(1, 0), "")
    _set_cell_text(t4.cell(1, 0), dados.get("obs_materiais", ""))

    # Tabelas de processos (indices 5 a 12)
    processos_map = {
        "CORTE": 5 + offset,
        "AR CONDICIONADO": 6 + offset,
        "PREPARAÇÃO DE PEÇAS": 7 + offset,
        "ISOLAMENTO": 8 + offset,
        "REVESTIMENTO": 9 + offset,
        "BANCOS": 10 + offset,
        "ELÉTRICA 2": 11 + offset,
        "LIMPEZA/LIBERAÇÃO": 12 + offset,
    }

    for nome, idx in processos_map.items():
        linhas = processos.get(nome, [])
        _preencher_tabela_processo(doc.tables[idx], linhas)

    if dados.get("obs"):
        doc.add_paragraph("")
        doc.add_paragraph(f"OBS FINAL: {dados.get('obs')}")

    _limpar_layout(doc, 13 + offset)
    _inserir_layout_pdf(doc, layout_pdf, 13 + offset)

    pasta = pasta_os(numero_os, dados)
    cliente = (dados.get("cliente", "") or "").strip()
    chassi = (dados.get("chassis", "") or "").strip()
    nome = f"02 - O.S. - {cliente} - {chassi}.docx"
    path = os.path.join(pasta, nome)
    path = _resolve_unique_path(path)

    # Centraliza texto dentro de todas as celulas
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Mantem colunas de descricao alinhadas à esquerda
    try:
        if len(doc.tables) > 2:
            for row in doc.tables[2].rows:
                if len(row.cells) > 1:
                    for p in row.cells[1].paragraphs:
                        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if len(doc.tables) > 3:
            for row in doc.tables[3].rows:
                if len(row.cells) > 1:
                    for p in row.cells[1].paragraphs:
                        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            # Titulo "COMPOSIÇÃO – LISTA DE MATERIAIS"
            if len(doc.tables[3].rows) > 0 and len(doc.tables[3].rows[0].cells) > 0:
                for p in doc.tables[3].rows[0].cells[0].paragraphs:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # Campos Chassi, Cliente e Previsao Inicio (tabela 1)
        if len(doc.tables) > 1:
            t1 = doc.tables[1]
            for (r, c) in [(1, 1), (2, 1), (3, 1)]:
                if r < len(t1.rows) and c < len(t1.rows[r].cells):
                    for p in t1.rows[r].cells[c].paragraphs:
                        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        # Conteudo das tabelas de processos alinhado a esquerda (linhas de dados)
        processos_indices = [5 + offset, 6 + offset, 7 + offset, 8 + offset, 9 + offset, 10 + offset, 11 + offset, 12 + offset]
        for idx in processos_indices:
            if idx < len(doc.tables):
                tproc = doc.tables[idx]
                for r_idx in range(len(tproc.rows)):
                    # mantém titulo/cabecalho centralizados
                    if r_idx < 2:
                        continue
                    row = tproc.rows[r_idx]
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    except Exception:
        pass

    path = _safe_save_doc(doc, path)
    return path
