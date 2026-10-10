from unittest.mock import patch
import pytest
from tests.test_commercial_programming import data
import app as app_module


def test_default_needs_excludes_legacy_even_before_commercial_has_first_proposal():
    forecasts=[{'id':'old','status':'ATIVO','quantidade_planejada':1,'quantidade_saldo_documental':1}]
    with patch.object(data,'carregar_forecasts',return_value=forecasts),patch.object(data,'_all_rows') as query:
        assert data.carregar_necessidades_forecasts_ativos(force=True)==[]
        query.assert_not_called()


def test_current_commercial_and_legacy_are_not_summed():
    forecasts=[{'id':'old','status':'ATIVO','quantidade_planejada':2,'quantidade_saldo_documental':2},
        {'id':'new','status':'ATIVO','quantidade_planejada':1,'dados_planejamento':{'comercial_programacao_id':'p'}}]
    req=[{'forecast_id':fid,'sku_codigo':'X','quantidade_planejada':qty} for fid,qty in [('old',100),('new',3)]]
    with patch.object(data,'carregar_forecasts',return_value=forecasts),patch.object(data,'carregar_programacao_comercial',return_value=[{'id':'p','commercial_status':'AG. ACEITE'}]),patch.object(data,'_all_rows',return_value=req):
        result=data.carregar_necessidades_forecasts_ativos()
    assert len(result)==1 and result[0]['quantidade_planejada']==3


def test_link_rpc_requires_explicit_confirm_and_current_versions():
    payload={'program_version':1,'forecast_version':2,'work_order_id':'00000000-0000-0000-0000-000000000001','confirmed':True,'old_proposal':'10','old_chassi':'VIN'}
    with patch.object(data,'_rpc',return_value={'status':'CONVERTIDO'}) as rpc:
        result=data.vincular_os_comercial_pcp('p',payload,'PAULO')
        assert result['status']=='CONVERTIDO'
        assert rpc.call_args.args[0]=='comercial_vincular_os_pcp'
        assert rpc.call_args.args[1]['p_old_proposal']=='10'
        assert rpc.call_args.args[1]['p_old_chassi']=='VIN'
        for invalid in [{'confirmed':False},{'program_version':None},{'forecast_version':True},{'work_order_id':'invalid'}]:
            with pytest.raises(ValueError): data.vincular_os_comercial_pcp('p',{**payload,**invalid},'PAULO')
        assert rpc.call_count==1


def test_link_route_requires_csrf_and_os_list_filters_closed():
    app_module.app.config['TESTING']=True
    client=app_module.app.test_client()
    with patch.object(app_module,'login_enabled',return_value=False),patch.object(app_module,'erp_feature_enabled',return_value=True),patch.object(app_module,'can',return_value=True),patch.object(data,'vincular_os_comercial_pcp',return_value={'status':'CONVERTIDO'}) as save:
        assert client.post('/api/erp/programacao-comercial/p/vincular-os',json={}).status_code==403
        with client.session_transaction() as session: session['purchase_requests_csrf']='token'
        response=client.post('/api/erp/programacao-comercial/p/vincular-os',headers={'X-CSRF-Token':'token'},json={'confirmed':True})
        assert response.status_code==200
        save.assert_called_once_with('p',{'confirmed':True},'local')
    with patch.object(app_module,'login_enabled',return_value=False),patch.object(app_module,'erp_feature_enabled',return_value=True),patch.object(app_module,'can',return_value=True),patch.object(app_module,'_erp_mes_all_work_orders',return_value=[
        {'work_order_id':'a','status':'EM_PRODUÇÃO','proposta_numero':'10','notes':'private'},
        {'work_order_id':'b','status':'ENTREGUE'},
        {'work_order_id':'c','status':'ATIVA','is_current':False},
        {'entry_id':'e','entry_status':'AGUARDANDO_O_S'}]):
        response=client.get('/api/erp/programacao-comercial/os-disponiveis')
    assert [r['work_order_id'] for r in response.json['orders']]==['a']
    assert 'notes' not in response.json['orders'][0]
