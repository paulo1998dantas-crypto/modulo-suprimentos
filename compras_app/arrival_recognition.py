"""Read-only arrival recognition. Never chooses an O.S. or consumes Forecast."""
import re
from collections import defaultdict


def vin_key(value):
    return str(value or '').strip().upper()


def arrival_candidates(programs, entries, orders):
    """Full VIN + one visit + one active proposal; explicit links take priority.

    Callers supply ALL competing active slots, not only the displayed/filter page.
    All visits (including past visits) count against uniqueness. No DB writes.
    """
    slots = defaultdict(list)
    visits = defaultdict(list)
    current = defaultdict(list)
    claims = defaultdict(set)
    for p in programs:
        if not p.get('included', True) or p.get('status') == 'CANCELADO':
            continue
        if p.get('proposal_status') in {'CANCELADA', 'SUBSTITUÍDA'} or p.get('proposal_kind') == 'COMPLEMENTAR':
            continue
        slots[vin_key(p.get('chassi'))].append(p)
        for field in ('vehicle_entry_id', 'forecast_entry_id'):
            if p.get(field):
                claims[str(p[field])].add(str(p['id']))
    for e in entries:
        visits[vin_key(e.get('entry_chassi'))].append(e)
    for o in orders:
        if o.get('is_current', True):
            current[str(o['vehicle_entry_id'])].append(o)
    result = {}
    for vin, group in slots.items():
        for p in group:
            if p.get('vehicle_entry_id') or p.get('forecast_entry_id') or p.get('work_order_id') or not p.get('programmed_at'):
                continue
            if not re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', vin):
                continue
            matches = visits.get(vin, [])
            if len(group) > 1 or len(matches) > 1:
                result[str(p['id'])] = {'arrival_warning': 'CHEGADA AMBÍGUA: CONFIRMAR ENTRADA / PROPOSTA'}
                continue
            if not matches:
                continue
            e = matches[0]
            state = vin_key(e.get('status')).replace('_', ' ')
            if e.get('deleted_at') or e.get('chassi_completo') is False or state in {
                'CANCELADO', 'EXCLUIDO', 'EXCLUÍDO', 'RETIRADA', 'RETIRADO', 'ENTREGUE'}:
                continue
            entry_id = str(e['id'])
            if claims.get(entry_id, set()) - {str(p['id'])} or current.get(entry_id):
                result[str(p['id'])] = {'arrival_warning': 'ENTRADA COM VÍNCULO: CONFIRMAR PROPOSTA NO MES'}
                continue
            result[str(p['id'])] = {'entry_id': entry_id, 'arrival_inferred': True}
    return result
