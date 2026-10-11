from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ProposalSelectionTests(unittest.TestCase):
    def test_opening_sends_explicit_id_version_not_chassis_lookup(self):
        source=(ROOT/'compras_app/templates/erp_gestao_os.html').read_text(encoding='utf-8')
        for token in ('data.commercial_program_id=row.id','data.commercial_program_version=row.version',
                      'allocationProposals.entry!==form.elements.entry_id.value',
                      'ticket!==allocationProposals.ticket','name="proposta_numero" readonly'):
            self.assertIn(token,source)
        self.assertNotIn("r.linked?'selected':''",source)

    def test_proxy_requires_manage_permission_and_uses_mes_entry(self):
        source=(ROOT/'compras_app/app.py').read_text(encoding='utf-8')
        start=source.index('@app.route("/api/erp/os-management/entries/<entry_id>/commercial-proposals")')
        route=source[start:source.index('@app.route("/api/erp/os-management/documents")',start)]
        self.assertIn('@login_required',route)
        self.assertIn('@permission_required("suprimentos.work_order.manage")',route)
        self.assertIn('vehicle-entries/{entry_id}/commercial-proposals',route)
        self.assertIn('urllib.parse.urlencode',route)
