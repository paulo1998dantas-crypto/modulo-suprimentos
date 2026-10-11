import os,sys
from pathlib import Path
from unittest.mock import patch
APP_DIR=Path(__file__).resolve().parents[1]/'compras_app'
sys.path.insert(0,str(APP_DIR))
os.environ['SUPRIMENTOS_FILE_LOG']='0'
import supabase_data as data


def test_board_is_readonly_and_uses_selected_entry():
    sources={
      'comercial_programacao':[{'id':'p1','proposal_id':'q1','sequence':1,'chassi':'VIN','vehicle_entry_id':'e1','work_order_id':'w1','status':'AG. CHEGADA','programmed_at':'today','released_at':'today'}],
      'comercial_propostas':[{'id':'q1','number':'1','status':'ACEITA','accepted_at':'today','accepted_date':'today'}],
      'erp_vehicles':[{'id':'v1','chassi':'VIN'}],
      'erp_vehicle_entries':[{'id':'e1','vehicle_id':'v1','item_number':3185,'status':'EM PRODUÇÃO'}],
      'erp_work_orders':[{'id':'w1','vehicle_entry_id':'e1','numero_os':'3185','proposta_numero':'1','status':'EM PRODUÇÃO','is_current':True}],
    }
    calls=[]
    def read(table,**kw):
        calls.append((table,kw))
        assert 'pricing' not in kw.get('select','') and 'notes_internal' not in kw.get('select','')
        return sources.get(table,[])
    with patch.object(data,'_all_rows',side_effect=read),patch.object(data,'carregar_forecasts',return_value=[]),patch.object(data,'_request') as request:
        board=data.carregar_programacao_comercial(force=True)
    assert board[0]['commercial_status']=='FINALIZADO COMERCIAL'
    assert board[0]['current_work_order_id']=='w1' and board[0]['item_number']==3185
    request.assert_not_called()


def test_board_repeated_vin_does_not_infer_a_visit():
    sources={
      'comercial_programacao':[{'id':'p','proposal_id':'q','chassi':'VIN','status':'AG. CHEGADA','released_at':'today'}],
      'comercial_propostas':[{'id':'q','number':'2','accepted_at':'today','accepted_date':'today'}],
      'erp_vehicles':[{'id':'v','chassi':'VIN'}],
      'erp_vehicle_entries':[{'id':'e1','vehicle_id':'v','item_number':1},{'id':'e2','vehicle_id':'v','item_number':2}],
      'erp_work_orders':[{'id':'w1','vehicle_entry_id':'e1','numero_os':'1','proposta_numero':'1'},
                         {'id':'w2','vehicle_entry_id':'e2','numero_os':'2','proposta_numero':'2'}],
    }
    with patch.object(data,'_all_rows',side_effect=lambda table,**kw:sources.get(table,[])),patch.object(data,'carregar_forecasts',return_value=[]):
        board=data.carregar_programacao_comercial()
        assert board[0]['item_number'] is None and board[0]['commercial_status']=='AG. CHEGADA'
        sources['comercial_programacao'][0].update(vehicle_entry_id='e2',work_order_id='w2')
        board=data.carregar_programacao_comercial()
        assert board[0]['item_number']==2 and board[0]['current_work_order_id']=='w2'
        assert board[0]['commercial_status']=='FINALIZADO COMERCIAL'


def test_report_avoids_double_count_and_uses_current_commercial_status():
    forecasts=[{'id':'f1','status':'ATIVO','quantidade_planejada':1,'quantidade_saldo_documental':1,'dados_planejamento':{'comercial_programacao_id':'p1','status_comercial':'AG. ACEITE'}},
               {'id':'f2','status':'ATIVO','quantidade_planejada':1,'quantidade_saldo_documental':1,'dados_planejamento':{'comercial_programacao_id':'p2'}}]
    board=[{'id':'p1','commercial_status':'AG. CHEGADA','current_work_order_id':None},
           {'id':'p2','commercial_status':'FINALIZADO COMERCIAL','current_work_order_id':'w2'}]
    req=[{'forecast_id':f,'sku_codigo':'10240089','quantidade_planejada':4} for f in ['f1','f2']]
    with patch.object(data,'carregar_forecasts',return_value=forecasts),patch.object(data,'carregar_programacao_comercial',return_value=board),patch.object(data,'_all_rows',return_value=req):
        rows=data.carregar_necessidades_forecasts_ativos()
    assert len(rows)==1 and rows[0]['forecast']['dados_planejamento']['status_comercial']=='AG. CHEGADA'
    assert rows[0]['quantidade_planejada']==4
