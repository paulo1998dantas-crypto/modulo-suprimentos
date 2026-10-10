import json,sys
from pathlib import Path
from copy import deepcopy
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'compras_app'))
from commercial_options import document_lines,choices_for_lines,merge_choices


def forecast():
    return {'itens_planejados':[{'sku_codigo':'40340045','quantidade_por_veiculo':1},
        {'sku_codigo':'30140001','quantidade_por_veiculo':1},{'sku_codigo':'10260092','quantidade_por_veiculo':2}],
        'dados_planejamento':{'comercial_opcoes_os':{'version':1,'extra_skus':['30140001','10260092'],
        'document_lines':[{'sku_codigo':'40340045','quantidade_por_veiculo':'1','fornecedor':'FORNECEDOR',
            'technical_options':{'root_sku':'40340045','luminaria':{'codigo':'10260092','qtd':'2'},
                'selections':[{'chave':'root:40340045|r1','codigo':'30140001','qtd':'1'}]}}]}}}


def test_os_imports_main_roots_and_keeps_components_only_in_choices():
    f=forecast();assert [r['sku_codigo'] for r in document_lines(f)]==['40340045']
    result=choices_for_lines(f,['40340045'],2)[0]
    assert result['luminaria_qtd']=='4' and json.loads(result['popup'])[0]['qtd']=='2'
    assert len(f['itens_planejados'])==3


def test_manual_sku_or_popup_and_supplier_choices_are_not_overwritten():
    f=forecast();assert choices_for_lines(f,['40340055'])==[{}]
    fields=merge_choices(choices_for_lines(f,['40340045']),['MANUAL'],['__NAO_APLICAVEL__'],['0'],['[{"codigo":"MANUAL"}]'])
    assert fields==[['MANUAL'],['__NAO_APLICAVEL__'],['0'],['[{"codigo":"MANUAL"}]']]
    defaults=merge_choices(choices_for_lines(f,['40340045']),[],[],[],[])
    assert defaults[1]==['10260092'] and defaults[2]==['2']


@pytest.mark.parametrize('change',[
    lambda f:f['dados_planejamento']['comercial_opcoes_os'].update(version=True),
    lambda f:f['dados_planejamento']['comercial_opcoes_os']['document_lines'][0].update(quantidade_por_veiculo='2'),
    lambda f:f['dados_planejamento']['comercial_opcoes_os'].update(extra_skus=['40340045']),
])
def test_incoherent_metadata_fails_without_modifying_data(change):
    f=forecast();change(f);before=deepcopy(f)
    with pytest.raises(ValueError):document_lines(f)
    assert f==before


def test_legacy_forecast_keeps_previous_behavior():
    f={'itens_planejados':[{'sku_codigo':'40340045','quantidade_por_veiculo':1}]}
    assert document_lines(f)==f['itens_planejados'] and choices_for_lines(f,['40340045'])==[{}]
