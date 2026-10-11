from copy import deepcopy
import pytest
from tests.test_commercial_programming import data
from arrival_recognition import arrival_candidates

VIN='9V8YET6F4TA009533'


def sources():
    return ([dict(id='p',chassi=VIN,programmed_at='today',status='AG. CHEGADA',proposal_status='ACEITA')],
            [dict(id='e',entry_chassi=VIN,status='AGUARDANDO_O_S')], [])


def test_exact_unique_arrival_is_a_readonly_projection():
    p,e,o=sources()
    before=deepcopy((p,e,o))
    assert arrival_candidates(p,e,o)=={'p':{'entry_id':'e','arrival_inferred':True}}
    assert (p,e,o)==before


@pytest.mark.parametrize('change', [
    'repeat_visit','repeat_proposal','old_visit','order_exists','owned_entry',
    'partial_vin','incomplete_flag','not_programmed','cancelled_proposal',
    'cancelled_slot','complement','withdrawn','delivered','deleted'])
def test_unsafe_arrivals_never_select_an_entry(change):
    p,e,o=sources()
    if change in {'repeat_visit','old_visit'}:
        e.append({**e[0],'id':'past','status':'RETIRADA' if change=='old_visit' else 'AGUARDANDO_O_S'})
    elif change=='repeat_proposal': p.append({**p[0],'id':'p2'})
    elif change=='order_exists': o.append(dict(vehicle_entry_id='e',is_current=True))
    elif change=='owned_entry': p.append(dict(id='owner',chassi='',vehicle_entry_id='e'))
    elif change=='partial_vin': p[0]['chassi']=e[0]['entry_chassi']='TA009533'
    elif change=='incomplete_flag': e[0]['chassi_completo']=False
    elif change=='not_programmed': p[0]['programmed_at']=None
    elif change=='cancelled_proposal': p[0]['proposal_status']='CANCELADA'
    elif change=='cancelled_slot': p[0]['status']='CANCELADO'
    elif change=='complement': p[0]['proposal_kind']='COMPLEMENTAR'
    elif change=='withdrawn': e[0]['status']='RETIRADA'
    elif change=='delivered': e[0]['status']='ENTREGUE'
    elif change=='deleted': e[0]['deleted_at']='today'
    assert not arrival_candidates(p,e,o).get('p',{}).get('entry_id')


def test_case_and_outer_space_only_normalization():
    p,e,o=sources()
    p[0]['chassi']=' '+VIN.lower()+' '
    assert arrival_candidates(p,e,o)['p']['entry_id']=='e'
    p[0]['chassi']=VIN[:-1]+'4'
    assert not arrival_candidates(p,e,o)


def test_explicit_visit_is_never_replaced_even_when_vin_repeats():
    p,e,o=sources()
    p[0]['vehicle_entry_id']='manual'
    e.append({**e[0],'id':'manual'})
    assert arrival_candidates(p,e,o)=={}
