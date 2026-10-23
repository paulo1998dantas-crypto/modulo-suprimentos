import copy
import json
import os
import sys
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'compras_app'))
os.environ['SUPRIMENTOS_FILE_LOG'] = '0'
from os_setores import (enriquecer_composicao, propagar_setor_preparacao,
                       filtrar_linhas_preparacao, filtrar_linhas_documento_os,
                       linhas_layout_preparacao)
from composicao import expandir_composicao_itens, expandir_composicao_manual
from app import _parse_os_composition_form

CASOS = json.loads((Path(__file__).parent / 'fixtures/os_destinos.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('caso', CASOS, ids=[c['nome'] for c in CASOS])
def test_regras_identicas_a_interface(caso):
    original = copy.deepcopy(caso)
    catalogo = caso.get('catalogo', {})
    result = propagar_setor_preparacao(enriquecer_composicao(caso['linhas'], catalogo), catalogo)
    assert [line['setor'] for line in result] == caso['destinos']
    assert [line['setor'] for line in propagar_setor_preparacao(result, catalogo)] == caso['destinos']
    assert caso == original


def test_pacote_pp_recursivo_preserva_quantidades_e_materiais():
    bom = {'TRANSF': [{'codigo':'PP', 'quantidade':2}],
           'PP': [{'codigo':'SUB', 'quantidade':3}, {'codigo':'MP', 'quantidade':0.8}],
           'SUB': [{'codigo':'COLA', 'quantidade':0.5}]}
    catalogo = {'PP': {'grupo':'PP'}}
    linhas = expandir_composicao_itens([{'codigo':'TRANSF', 'qtd':2}], bom)
    original = copy.deepcopy(linhas)
    result = propagar_setor_preparacao(enriquecer_composicao(linhas, catalogo), catalogo, bom)
    assert {line['codigo']:line['qtd'] for line in result} == {'PP':4, 'SUB':12, 'COLA':6, 'MP':3.2}
    assert len(filtrar_linhas_preparacao(result)) == 4
    assert linhas == original


def test_componentes_compartilhados_nao_perdem_origem_preparacao():
    bom = {'TRANSF':[{'codigo':'KIT', 'quantidade':1}, {'codigo':'PP', 'quantidade':1}],
           'KIT':[{'codigo':'COLA','quantidade':2}], 'PP':[{'codigo':'COLA','quantidade':3}]}
    catalogo = {'PP':{'grupo':'PP'}}
    linhas = expandir_composicao_itens([{'codigo':'TRANSF','qtd':1}], bom)
    result = propagar_setor_preparacao(enriquecer_composicao(linhas, catalogo), catalogo)
    cola = next(line for line in result if line['codigo'] == 'COLA')
    assert cola['qtd'] == 5
    assert cola['pais_origem'] == ['KIT', 'PP']
    assert cola['setor'] == 'PREPARACAO'


def test_nulo_manual_persistente_no_form_e_snapshot():
    rows = [{'codigo':'NOVO', 'qtd':3.5, 'setor':'NULO', 'setor_manual':True,
             'pais_origem':['CJ', 'PP'], 'line_id':'linha-existente'}]
    parsed = _parse_os_composition_form(MultiDict({'os_composicao_json':json.dumps(rows)}))
    expanded = expandir_composicao_manual(parsed, {}, preservar_snapshot=True)
    result = propagar_setor_preparacao(enriquecer_composicao(expanded, {}), {})
    assert result[0]['setor'] == 'NULO'
    assert result[0]['line_id'] == 'linha-existente'
    assert float(result[0]['qtd']) == 3.5
    assert result[0]['pais_origem'] == ['CJ', 'PP']
    assert filtrar_linhas_documento_os(result) == []


def test_nulo_no_form_legado_e_layout_respeita_mudanca_manual_do_pai():
    parsed = _parse_os_composition_form(MultiDict({'os_comp_codigo[]':'20140001',
        'os_comp_qtd[]':'2', 'os_comp_setor[]':'NULO', 'os_comp_setor_manual[]':'1'}))
    assert parsed[0]['setor'] == 'NULO'
    assert linhas_layout_preparacao([{'codigo':'20140001','qtd':2}], {}, parsed) == []
