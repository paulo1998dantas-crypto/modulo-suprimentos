"""Proposal choices carried by planning. Never writes Commercial or MES."""
from collections import defaultdict,deque
from copy import deepcopy
from decimal import Decimal,InvalidOperation
import json

NA='__NAO_APLICAVEL__'


def quantity(value):
    try:
        result=Decimal(str(value))
        if not result.is_finite() or result<=0:raise ValueError
        return result
    except (InvalidOperation,TypeError,ValueError):
        raise ValueError('Quantidade inválida nas escolhas técnicas da programação comercial.')


def document_lines(forecast):
    original=forecast.get('itens_planejados') or []
    metadata=(forecast.get('dados_planejamento') or {}).get('comercial_opcoes_os')
    if metadata is None:return original
    if not isinstance(metadata,dict) or type(metadata.get('version')) is not int or metadata['version']!=1:
        raise ValueError('Versão inválida das escolhas técnicas da programação comercial.')
    roots=metadata.get('document_lines');extras=metadata.get('extra_skus')
    if not isinstance(roots,list) or not roots or len(roots)>200 or any(not isinstance(r,dict) for r in roots):
        raise ValueError('Itens principais da proposta ausentes na programação comercial.')
    if not isinstance(extras,list) or len(extras)>400 or any(not isinstance(x,str) for x in extras):
        raise ValueError('Itens técnicos adicionais inválidos na programação comercial.')
    planned=defaultdict(Decimal);main=defaultdict(Decimal)
    for row in original:planned[str(row.get('sku_codigo') or '')]+=quantity(row.get('quantidade_por_veiculo'))
    for row in roots:main[str(row.get('sku_codigo') or '')]+=quantity(row.get('quantidade_por_veiculo'))
    if '' in main or set(main)&set(extras) or set(planned)!=set(main)|set(extras) or any(planned[c]!=q for c,q in main.items()):
        raise ValueError('Composição comercial diverge do planejamento. Sincronize a proposta antes de abrir a O.S.')
    return deepcopy(roots)


def choices_for_lines(forecast,codes,vehicles=1):
    roots=document_lines(forecast);by_code=defaultdict(deque)
    if not (forecast.get('dados_planejamento') or {}).get('comercial_opcoes_os'):return [{} for c in codes]
    multiplier=quantity(vehicles)
    for root in roots:by_code[str(root['sku_codigo'])].append(root)
    result=[]
    for code in codes:
        root=by_code[str(code)].popleft() if by_code[str(code)] else None
        if root is None:result.append({});continue  # A manually changed SKU wins.
        raw=root.get('technical_options') or {}
        if not isinstance(raw,dict) or raw.get('root_sku')!=code:
            result.append({});continue
        selections=deepcopy(raw.get('selections') or []);lamp=deepcopy(raw.get('luminaria') or {})
        if not isinstance(selections,list) or any(not isinstance(s,dict) for s in selections) or not isinstance(lamp,dict):
            raise ValueError('Escolhas técnicas inválidas na programação comercial.')
        for selection in [*selections,*([lamp] if lamp else [])]:
            selection['qtd']='0' if selection.get('codigo')==NA else str(quantity(selection.get('qtd'))*multiplier)
        result.append({'fornecedor':str(root.get('fornecedor') or ''),'luminaria':lamp.get('codigo',''),
            'luminaria_qtd':lamp.get('qtd',''),'popup':json.dumps(selections,ensure_ascii=False)})
    return result


def merge_choices(defaults,suppliers,lamps,counts,popups):
    """Only fill omitted choices. An explicit N/A or edited value stays final."""
    fields=[suppliers,lamps,counts,popups]
    for i,default in enumerate(defaults):
        for values,key in zip(fields,['fornecedor','luminaria','luminaria_qtd','popup']):
            while len(values)<=i:values.append('[]' if key=='popup' else '')
            if values[i] in ('',None) or key=='popup' and values[i]=='[]':
                values[i]=default.get(key,values[i])
    return fields
