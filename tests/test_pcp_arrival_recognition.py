from copy import deepcopy
from unittest.mock import patch
from tests.test_commercial_programming import data

VIN='9V8YET6F4TA009533'


def sources():
    return {
        'comercial_programacao':[dict(id='p',proposal_id='q',chassi=VIN,status='AG. CHEGADA',
            programmed_at='today',released_at='today',forecast_id='f')],
        'comercial_propostas':[dict(id='q',number='10920',status='ACEITA',
            accepted_at='today',accepted_date='today')],
        'erp_vehicles':[dict(id='v',chassi=VIN,mmv='FORD TRANSIT L4H3')],
        'erp_vehicle_entries':[dict(id='e',vehicle_id='v',item_number=3185,status='AGUARDANDO_O_S',data_chegada='2026-10-11')],
        'erp_work_orders':[],
    }


def board(src):
    def read(table,**kw):
        assert kw.get('force') is True
        return deepcopy(src.get(table,[]))
    forecasts=[dict(id='f',status='ATIVO',quantidade_planejada=1,
        dados_planejamento={'comercial_programacao_id':'p'})]
    with patch.object(data,'_all_rows',side_effect=read),patch.object(data,'carregar_forecasts',return_value=forecasts),patch.object(data,'_request') as write:
        rows=data.carregar_programacao_comercial(force=True)
        write.assert_not_called()
    return rows[0]


def test_arrival_immediately_updates_pcp_without_consuming_forecast():
    src=sources()
    row=board(src)
    assert row['arrival_inferred'] and row['awaiting_os'] and row['item_number']==3185
    assert row['arrival_date']=='2026-10-11' and row['mmv_mes']=='FORD TRANSIT L4H3'
    assert row['production_status']=='AGUARDANDO O.S.'
    assert row['forecast']['status']=='ATIVO' and row['current_work_order_id'] is None
    assert src['comercial_programacao'][0].get('vehicle_entry_id') is None
    src['erp_vehicle_entries'].append(dict(id='repeat',vehicle_id='v',item_number=9999))
    row=board(src)
    assert not row['awaiting_os'] and not row['arrived'] and row['item_number'] is None
    assert 'AMBÍGUA' in row['integration_warning']


def test_existing_order_requires_manual_proposal_selection():
    src=sources()
    src['erp_work_orders']=[dict(id='w',vehicle_entry_id='e',numero_os='3185',proposta_numero='10920',is_current=True)]
    row=board(src)
    assert row['current_work_order_id'] is None and not row['arrived']
    assert 'CONFIRMAR PROPOSTA NO MES' in row['integration_warning']


def test_explicit_entry_remains_authoritative_with_repeated_chassis():
    src=sources()
    src['comercial_programacao'][0]['vehicle_entry_id']='e'
    src['erp_vehicle_entries'].append(dict(id='repeat',vehicle_id='v',item_number=9999))
    row=board(src)
    assert row['item_number']==3185 and not row['arrival_inferred']
