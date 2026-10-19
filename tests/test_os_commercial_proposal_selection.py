from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ProposalSelectionTests(unittest.TestCase):
    def test_pcp_uses_free_text_without_a_commercial_selection(self):
        source=(ROOT/'compras_app/templates/erp_gestao_os.html').read_text(encoding='utf-8')
        self.assertIn('name="proposta_numero" type="text" maxlength="80"',source)
        self.assertIn('Texto livre. Não exige cadastro ou atualização no Comercial.',source)
        self.assertNotIn('name="proposta_numero" readonly',source)
        for token in ('allocation-proposal-select','loadAllocationProposals',
                      'proposalSelectionPayload','data.commercial_program_id'):
            self.assertNotIn(token,source)

    def test_proxy_requires_manage_permission_and_uses_mes_entry(self):
        source=(ROOT/'compras_app/app.py').read_text(encoding='utf-8')
        start=source.index('@app.route("/api/erp/os-management/entries/<entry_id>/commercial-proposals")')
        route=source[start:source.index('@app.route("/api/erp/os-management/documents")',start)]
        self.assertIn('@login_required',route)
        self.assertIn('@permission_required("suprimentos.work_order.manage")',route)
        self.assertIn('vehicle-entries/{entry_id}/commercial-proposals',route)
        self.assertIn('urllib.parse.urlencode',route)
