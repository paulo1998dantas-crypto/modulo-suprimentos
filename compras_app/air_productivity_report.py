"""Live export for daily/monthly air-conditioning supplier productivity."""

from collections import Counter
from datetime import date, datetime, timedelta
import unicodedata
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


SUPPLIERS = {
    "CLIM": "CLIM — Climaut",
    "GE": "GE — Grupo Euro",
}
WEEKDAYS_PT = ("SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM")
MONTHS_PT = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)
OPERATIONAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _token(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.upper().replace("_", " ").split())


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(OPERATIONAL_TIMEZONE)
        return parsed.date()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def _months_between(first, last):
    cursor = date(first.year, first.month, 1)
    end = date(last.year, last.month, 1)
    while cursor <= end:
        yield cursor
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)


def prepare_air_productivity_data(orders, target_per_supplier=2):
    """Filter current completed transformation O.S. and count each vehicle once.

    The current completion timestamp is ``termino_producao`` from MES.  For
    duplicate chassis, the earliest completion is the one credited to a
    supplier; all source rows remain visible in the audit/detail sheet.
    """
    eligible = []
    for order in orders or []:
        situation = _token(order.get("situacao") or order.get("status"))
        supplier = _token(order.get("ar_condicionado"))
        finished = _as_date(order.get("termino_producao"))
        if situation not in {"ENTREGUE", "FINALIZADA"}:
            continue
        if supplier not in SUPPLIERS or finished is None:
            continue

        item = str(order.get("item_number") or "").strip()
        chassis = str(order.get("chassi") or "").strip().upper()
        os_number = str(order.get("numero_os") or "").strip()
        unique_key = chassis or (f"ITEM:{item}" if item else f"OS:{os_number or order.get('work_order_id', '')}")
        eligible.append({
            "numero_os": os_number,
            "item": item,
            "fornecedor": supplier,
            "fornecedor_label": SUPPLIERS[supplier],
            "data_termino": finished,
            "situacao": str(order.get("situacao") or order.get("status") or "").strip(),
            "chassi": chassis,
            "modelo": str(order.get("modelo_veicular") or order.get("modelo") or "").strip(),
            "transformacao": str(order.get("transformacao") or "").strip(),
            "unique_key": unique_key,
        })

    eligible.sort(key=lambda row: (
        row["data_termino"], row["item"], row["numero_os"], row["unique_key"],
    ))
    seen = set()
    for row in eligible:
        row["conta"] = row["unique_key"] not in seen
        row["regra"] = "Primeiro término vigente do chassi" if row["conta"] else "Chassi já contado"
        seen.add(row["unique_key"])

    counted = [row for row in eligible if row["conta"]]
    if not counted:
        return {
            "rows": eligible,
            "daily": [],
            "monthly": [],
            "target": target_per_supplier,
            "business_days": 0,
            "unique_count": 0,
            "duplicate_count": len(eligible),
            "period_start": None,
            "period_end": None,
        }

    period_start = min(row["data_termino"] for row in counted)
    period_end = max(row["data_termino"] for row in counted)
    counts_by_day = Counter((row["data_termino"], row["fornecedor"]) for row in counted)
    daily = []
    current = period_start
    while current <= period_end:
        business_day = current.weekday() < 5
        clim = counts_by_day[(current, "CLIM")]
        ge = counts_by_day[(current, "GE")]
        daily.append({
            "date": current,
            "weekday": WEEKDAYS_PT[current.weekday()],
            "business_day": business_day,
            "clim": clim,
            "ge": ge,
            "total": clim + ge,
            "target_clim": target_per_supplier if business_day else 0,
            "target_ge": target_per_supplier if business_day else 0,
            "gap_clim": clim - target_per_supplier if business_day else 0,
            "gap_ge": ge - target_per_supplier if business_day else 0,
        })
        current += timedelta(days=1)

    daily_lookup = {row["date"]: row for row in daily}
    monthly = []
    for month_start in _months_between(period_start, period_end):
        month_end = date(
            month_start.year + (month_start.month == 12), month_start.month % 12 + 1, 1
        )
        month_days = [
            row for day, row in daily_lookup.items()
            if month_start <= day < month_end
        ]
        business_days = sum(row["business_day"] for row in month_days)
        clim = sum(row["clim"] for row in month_days)
        ge = sum(row["ge"] for row in month_days)
        monthly.append({
            "month_start": month_start,
            "month_label": f"{MONTHS_PT[month_start.month - 1]}/{month_start.year}",
            "business_days": business_days,
            "clim": clim,
            "clim_average": clim / business_days if business_days else 0,
            "clim_attainment": clim / (business_days * target_per_supplier) if business_days and target_per_supplier else 0,
            "clim_gap": clim - business_days * target_per_supplier,
            "ge": ge,
            "ge_average": ge / business_days if business_days else 0,
            "ge_attainment": ge / (business_days * target_per_supplier) if business_days and target_per_supplier else 0,
            "ge_gap": ge - business_days * target_per_supplier,
            "target": target_per_supplier,
            "total": clim + ge,
        })

    return {
        "rows": eligible,
        "daily": daily,
        "monthly": monthly,
        "target": target_per_supplier,
        "business_days": sum(row["business_day"] for row in daily),
        "unique_count": len(counted),
        "duplicate_count": len(eligible) - len(counted),
        "period_start": period_start,
        "period_end": period_end,
    }


def build_air_productivity_workbook(report, generated_at=None):
    """Create the formula-based workbook used by the Suprimentos PCP export."""
    wb = Workbook()
    summary = wb.active
    summary.title = "Resumo Mensal"
    daily = wb.create_sheet("Produção Diária")
    detail = wb.create_sheet("Concluídos")
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"

    navy = "123D6A"
    blue = "1769AA"
    pale = "EAF4FF"
    green = "16837A"
    light = "F3F6F9"
    white = "FFFFFF"
    thin_gray = Side(style="thin", color="DCE4ED")
    target = int(report["target"])
    rows = report["rows"]
    daily_rows = report["daily"]
    monthly_rows = report["monthly"]
    generated_at = generated_at or datetime.now()

    summary.merge_cells("A1:L1")
    summary["A1"] = "PRODUTIVIDADE DIÁRIA E MENSAL — FORNECEDOR DE AR"
    summary["A1"].font = Font(bold=True, color=white, size=16)
    summary["A1"].fill = PatternFill("solid", fgColor=navy)
    summary["A1"].alignment = Alignment(horizontal="center", vertical="center")
    summary.row_dimensions[1].height = 30
    summary.merge_cells("A2:L2")
    period_label = (
        f"Período: {report['period_start']:%d/%m/%Y} a {report['period_end']:%d/%m/%Y}"
        if report["period_start"] else "Período: sem veículos concluídos elegíveis"
    )
    summary["A2"] = (
        f"{period_label} | Gerado em {generated_at:%d/%m/%Y %H:%M} (horário de Brasília) | "
        "Fonte: O.S. vigentes do MES; término vigente da produção."
    )
    summary["A2"].font = Font(color="526174", italic=True, size=10)
    summary["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    summary.row_dimensions[2].height = 29

    daily_first = 5
    daily_last = daily_first + max(len(daily_rows), 1) - 1
    detail_first = 5
    detail_last = max(detail_first, detail_first + len(rows) - 1)
    daily_clim = f"'Produção Diária'!$D${daily_first}:$D${daily_last}"
    daily_ge = f"'Produção Diária'!$E${daily_first}:$E${daily_last}"
    daily_business = f"'Produção Diária'!$C${daily_first}:$C${daily_last}"
    detail_supplier = f"'Concluídos'!$C${detail_first}:$C${detail_last}"
    detail_date = f"'Concluídos'!$D${detail_first}:$D${detail_last}"
    detail_counted = f"'Concluídos'!$I${detail_first}:$I${detail_last}"

    cards = [
        ("A4:B4", "A5:B6", "CLIM — carros", f"=SUM({daily_clim})"),
        ("C4:D4", "C5:D6", "CLIM — média/dia útil", f"=IFERROR(SUM({daily_clim})/COUNTIF({daily_business},\"SIM\"),0)"),
        ("E4:F4", "E5:F6", "GE — carros", f"=SUM({daily_ge})"),
        ("G4:H4", "G5:H6", "GE — média/dia útil", f"=IFERROR(SUM({daily_ge})/COUNTIF({daily_business},\"SIM\"),0)"),
        ("I4:J4", "I5:J6", "Meta por fornecedor/dia", target),
        ("K4:L4", "K5:L6", "Dias úteis no período", f"=COUNTIF({daily_business},\"SIM\")"),
    ]
    for label_range, value_range, label, value in cards:
        summary.merge_cells(label_range)
        summary.merge_cells(value_range)
        label_cell = summary[label_range.split(":")[0]]
        value_cell = summary[value_range.split(":")[0]]
        label_cell.value = label
        label_cell.font = Font(bold=True, color=white, size=10)
        label_cell.fill = PatternFill("solid", fgColor=blue)
        label_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        value_cell.value = value
        value_cell.font = Font(bold=True, color=navy, size=17)
        value_cell.fill = PatternFill("solid", fgColor=pale)
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
    summary.row_dimensions[4].height = 27
    summary.row_dimensions[5].height = 23
    summary.row_dimensions[6].height = 16
    for cell in ("C5", "G5"):
        summary[cell].number_format = "0.00"

    headers = [
        "Mês", "Dias úteis considerados", "CLIM carros únicos", "CLIM média/dia útil",
        "CLIM atingimento meta", "CLIM diferença vs meta", "GE carros únicos",
        "GE média/dia útil", "GE atingimento meta", "GE diferença vs meta",
        "Meta diária/fornecedor", "Total de carros",
    ]
    header_row = 9
    for index, value in enumerate(headers, start=1):
        cell = summary.cell(header_row, index, value)
        cell.font = Font(bold=True, color=white)
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=thin_gray)
    summary.row_dimensions[header_row].height = 43

    month_start_col = 13
    for idx, month in enumerate(monthly_rows, start=header_row + 1):
        month_start = month["month_start"]
        summary.cell(idx, 1, month["month_label"])
        summary.cell(idx, month_start_col, month_start)
        summary.cell(idx, month_start_col).number_format = "mm/yyyy"
        summary.cell(idx, 2, f'=COUNTIFS({daily_business},"SIM",\'Produção Diária\'!$A${daily_first}:$A${daily_last},">="&$M{idx},\'Produção Diária\'!$A${daily_first}:$A${daily_last},"<"&EDATE($M{idx},1))')
        summary.cell(idx, 3, f'=SUMIFS({daily_clim},\'Produção Diária\'!$A${daily_first}:$A${daily_last},">="&$M{idx},\'Produção Diária\'!$A${daily_first}:$A${daily_last},"<"&EDATE($M{idx},1))')
        summary.cell(idx, 4, f'=IFERROR(C{idx}/B{idx},0)')
        summary.cell(idx, 5, f'=IFERROR(D{idx}/$I$5,0)')
        summary.cell(idx, 6, f'=C{idx}-(B{idx}*$I$5)')
        summary.cell(idx, 7, f'=SUMIFS({daily_ge},\'Produção Diária\'!$A${daily_first}:$A${daily_last},">="&$M{idx},\'Produção Diária\'!$A${daily_first}:$A${daily_last},"<"&EDATE($M{idx},1))')
        summary.cell(idx, 8, f'=IFERROR(G{idx}/B{idx},0)')
        summary.cell(idx, 9, f'=IFERROR(H{idx}/$I$5,0)')
        summary.cell(idx, 10, f'=G{idx}-(B{idx}*$I$5)')
        summary.cell(idx, 11, "=$I$5")
        summary.cell(idx, 12, f'=C{idx}+G{idx}')
        for col in range(1, 13):
            cell = summary.cell(idx, col)
            cell.border = Border(bottom=thin_gray)
            if idx % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=light)
        for col in (4, 8):
            summary.cell(idx, col).number_format = "0.00"
        for col in (5, 9):
            summary.cell(idx, col).number_format = "0.0%"
        for col in (6, 10):
            summary.cell(idx, col).number_format = "+0;-0;0"
    summary.column_dimensions["M"].hidden = True
    summary.freeze_panes = "A10"
    summary.auto_filter.ref = f"A{header_row}:L{max(header_row, header_row + len(monthly_rows))}"

    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    chart.title = "Média de carros concluídos por dia útil"
    chart.y_axis.title = "Carros por dia útil"
    chart.x_axis.title = "Mês"
    chart.height = 8
    chart.width = 17
    if monthly_rows:
        data_ref = Reference(summary, min_col=4, max_col=4, min_row=header_row, max_row=header_row + len(monthly_rows))
        chart.add_data(data_ref, titles_from_data=True)
        data_ref_ge = Reference(summary, min_col=8, max_col=8, min_row=header_row, max_row=header_row + len(monthly_rows))
        chart.add_data(data_ref_ge, titles_from_data=True)
        data_ref_target = Reference(summary, min_col=11, max_col=11, min_row=header_row, max_row=header_row + len(monthly_rows))
        chart.add_data(data_ref_target, titles_from_data=True)
        categories = Reference(summary, min_col=1, min_row=header_row + 1, max_row=header_row + len(monthly_rows))
        chart.set_categories(categories)
        summary.add_chart(chart, f"A{header_row + len(monthly_rows) + 3}")

    audit_row = header_row + len(monthly_rows) + 22
    audit = [
        ("Registros elegíveis", len(rows)),
        ("Veículos contabilizados (ITEM/chassi únicos)", report["unique_count"]),
        ("Duplicidades não somadas", report["duplicate_count"]),
        ("Meta", f"{target} carros por dia útil, para cada fornecedor"),
        ("Critério", "O.S. vigentes em situação ENTREGUE ou FINALIZADA; fornecedor A/C CLIM ou GE; data de término vigente do MES."),
        ("Dias úteis", "Segunda a sexta, sem calendário de feriados da empresa; períodos inicial e final parciais são considerados."),
        ("Duplicidade", "Cada chassi é contado uma vez, na data de término mais antiga entre as O.S. elegíveis."),
    ]
    for offset, (label, value) in enumerate(audit):
        row = audit_row + offset
        summary.cell(row, 1, label).font = Font(bold=True, color=navy)
        summary.cell(row, 2, value)
        summary.merge_cells(start_row=row, start_column=2, end_row=row, end_column=12)
        summary.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="top")
    summary.column_dimensions["A"].width = 18
    for col in range(2, 13):
        summary.column_dimensions[get_column_letter(col)].width = 19

    daily.merge_cells("A1:J1")
    daily["A1"] = "PRODUÇÃO DIÁRIA — CLIM E GE"
    daily["A1"].font = Font(bold=True, color=white, size=15)
    daily["A1"].fill = PatternFill("solid", fgColor=navy)
    daily["A1"].alignment = Alignment(horizontal="center")
    daily_headers = [
        "Data de término vigente", "Dia", "Dia útil?", "CLIM carros", "GE carros",
        "Total carros", "Meta CLIM", "Meta GE", "Diferença CLIM", "Diferença GE",
    ]
    for index, value in enumerate(daily_headers, start=1):
        cell = daily.cell(4, index, value)
        cell.font = Font(bold=True, color=white)
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for idx, row in enumerate(daily_rows, start=daily_first):
        daily.cell(idx, 1, row["date"])
        daily.cell(idx, 1).number_format = "dd/mm/yyyy"
        daily.cell(idx, 2, row["weekday"])
        daily.cell(idx, 3, "SIM" if row["business_day"] else "NÃO")
        daily.cell(idx, 4, f'=COUNTIFS({detail_date},$A{idx},{detail_supplier},"{SUPPLIERS["CLIM"]}",{detail_counted},"SIM")')
        daily.cell(idx, 5, f'=COUNTIFS({detail_date},$A{idx},{detail_supplier},"{SUPPLIERS["GE"]}",{detail_counted},"SIM")')
        daily.cell(idx, 6, f"=D{idx}+E{idx}")
        daily.cell(idx, 7, f'=IF(C{idx}="SIM",\'Resumo Mensal\'!$I$5,0)')
        daily.cell(idx, 8, f'=IF(C{idx}="SIM",\'Resumo Mensal\'!$I$5,0)')
        daily.cell(idx, 9, f'=IF(C{idx}="SIM",D{idx}-G{idx},0)')
        daily.cell(idx, 10, f'=IF(C{idx}="SIM",E{idx}-H{idx},0)')
        if idx % 2 == 0:
            for col in range(1, 11):
                daily.cell(idx, col).fill = PatternFill("solid", fgColor=light)
    daily.freeze_panes = "A5"
    daily.auto_filter.ref = f"A4:J{max(4, daily_first + len(daily_rows) - 1)}"
    daily.row_dimensions[4].height = 36
    for col, width in enumerate((22, 10, 12, 13, 13, 13, 12, 12, 16, 16), start=1):
        daily.column_dimensions[get_column_letter(col)].width = width

    detail.merge_cells("A1:J1")
    detail["A1"] = "O.S. CONCLUÍDAS — BASE DE AUDITORIA"
    detail["A1"].font = Font(bold=True, color=white, size=15)
    detail["A1"].fill = PatternFill("solid", fgColor=navy)
    detail["A1"].alignment = Alignment(horizontal="center")
    detail_headers = [
        "O.S.", "ITEM", "Fornecedor de ar", "Término vigente", "Situação",
        "Chassi", "Modelo", "Transformação", "Conta para produtividade", "Regra de contagem",
    ]
    for index, value in enumerate(detail_headers, start=1):
        cell = detail.cell(4, index, value)
        cell.font = Font(bold=True, color=white)
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for idx, row in enumerate(rows, start=detail_first):
        detail_values = [
            row["numero_os"], row["item"], row["fornecedor_label"], row["data_termino"],
            row["situacao"], row["chassi"], row["modelo"], row["transformacao"],
            "SIM" if row["conta"] else "NÃO", row["regra"],
        ]
        for col, value in enumerate(detail_values, start=1):
            cell = detail.cell(idx, col, value)
            cell.border = Border(bottom=thin_gray)
            if idx % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=light)
        detail.cell(idx, 4).number_format = "dd/mm/yyyy"
    detail.freeze_panes = "A5"
    detail.auto_filter.ref = f"A4:J{max(4, detail_first + len(rows) - 1)}"
    for col, width in enumerate((13, 13, 24, 17, 19, 24, 30, 36, 25, 34), start=1):
        detail.column_dimensions[get_column_letter(col)].width = width
    for sheet in (summary, daily, detail):
        sheet.sheet_view.showGridLines = False
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.page_setup.orientation = "landscape"
    return wb
