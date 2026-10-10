from unittest.mock import patch
import pytest
from tests.test_commercial_programming import data
import app as app_module


def test_nonconsider_excludes_only_that_vehicle_and_docx_does_not_reduce_it():
    forecasts=[{'id':i,'status':'ATIVO','quantidade_planejada':1,'quantidade_saldo_documental':0,
        'dados_planejamento':{'comercial_programacao_id':'p'+i,'pcp_considerar':i=='a'}} for i in ['a','b']]
    board=[{'id':'pa','commercial_status':'AG. ACEITE'},{'id':'pb','commercial_status':'AG. ACEITE'}]
    req=[{'forecast_id':i,'sku_codigo':'10240089','quantidade_planejada':4} for i in ['a','b']]
    with patch.object(data,'carregar_forecasts',return_value=forecasts),patch.object(data,'carregar_programacao_comercial',return_value=board),patch.object(data,'_all_rows',return_value=req):
        result=data.carregar_necessidades_forecasts_ativos()
    assert len(result)==1 and result[0]['quantidade_planejada']==4


def test_commercial_balance_waits_for_physical_conversion():
    rows=[{'id':'a','status':'ATIVO','quantidade_planejada':1,'dados_planejamento':{'comercial_programacao_id':'pa'}},
          {'id':'b','status':'CONVERTIDO','quantidade_planejada':1,'dados_planejamento':{'comercial_programacao_id':'pb'}}]
    with patch.object(data,'carregar_consumos_forecast_documental',return_value=[{'forecast_id':'a','quantidade':1,'status':'ATIVO'}]),patch.object(data,'_resumos_documentos_consumo_forecast',return_value={}):
        data.enriquecer_forecasts_com_consumos(rows)
    assert rows[0]['quantidade_saldo_documental']==1 and rows[0]['status_exibicao']=='ATIVO'
    assert rows[1]['quantidade_saldo_documental']==0 and rows[1]['status_exibicao']=='CONVERTIDO'


def test_wrong_proposal_does_not_convert_same_vin_forecast():
    sources={'comercial_programacao':[{'id':'p','proposal_id':'q','chassi':'VIN','status':'AG. ACEITE'}],
      'comercial_propostas':[{'id':'q','number':'10','revision':2}],
      'erp_vehicles':[{'id':'v','chassi':'VIN'}],
      'erp_vehicle_entries':[{'id':'e','vehicle_id':'v','item_number':3185}],
      'erp_work_orders':[{'id':'w','vehicle_entry_id':'e','numero_os':'3185','proposta_numero':'10','is_current':True}]}
    with patch.object(data,'_all_rows',side_effect=lambda table,**kw:sources.get(table,[])),patch.object(data,'carregar_forecasts',return_value=[]):
        rows=data.carregar_programacao_comercial()
    assert rows[0]['proposal']['display_number']=='10.1'
    assert rows[0]['current_work_order_id'] is None


def test_consider_route_csrf_version_and_permission():
    app_module.app.config['TESTING']=True
    client=app_module.app.test_client()
    with patch.object(app_module,'login_enabled',return_value=False),patch.object(app_module,'erp_feature_enabled',return_value=True),patch.object(app_module,'can',return_value=True),patch.object(data,'definir_consideracao_comercial_pcp',return_value={'id':'f'}) as save:
        assert client.post('/api/erp/programacao-comercial/f/considerar',json={'considerar':False,'version':1}).status_code==403
        with client.session_transaction() as session: session['purchase_requests_csrf']='test-token'
        response=client.post('/api/erp/programacao-comercial/f/considerar',headers={'X-CSRF-Token':'test-token'},json={'considerar':False,'version':1})
        assert response.status_code==200,response.json
        save.assert_called_once_with('f',False,1,'local')


@pytest.mark.parametrize('consider,version',[('false',1),(False,None),(False,True),(False,0)])
def test_rpc_control_rejects_missing_or_wrong_types(consider,version):
    with patch.object(data,'_rpc') as rpc:
        with pytest.raises(ValueError): data.definir_consideracao_comercial_pcp('f',consider,version,'PCP')
        rpc.assert_not_called()
