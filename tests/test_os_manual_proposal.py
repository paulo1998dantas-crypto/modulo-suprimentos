import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compras_app"))
os.environ["SUPRIMENTOS_FILE_LOG"] = "0"
import app as mod


class ManualProposalTests(unittest.TestCase):
    def setUp(self):
        mod.app.config.update(TESTING=True)
        self.client = mod.app.test_client()
        for name, result in (("login_enabled", False), ("erp_feature_enabled", True), ("can", True)):
            item = patch.object(mod, name, return_value=result)
            item.start()
            self.addCleanup(item.stop)

    def test_create_accepts_proposal_not_registered_in_commercial(self):
        body = {"proposta_numero": "  LEGADO-10060.2 > COMPL-77  ", "tipo_servico": "TRANSFORMAÇÃO"}
        with patch.object(mod, "_erp_mes_request", return_value={"ok": True, "id": "w"}) as mes:
            response = self.client.post("/api/erp/os-management/entries/entry-1/work-orders", json=body)
        self.assertEqual(201, response.status_code, response.json)
        mes.assert_called_once_with("vehicle-entries/entry-1/work-orders", "POST", {
            **body, "proposta_numero": "LEGADO-10060.2 > COMPL-77",
        })

    def test_rendered_screen_has_an_editable_manual_proposal_field(self):
        with patch.object(mod, "_erp_mes_request") as mes:
            response = self.client.get("/erp/gestao-os")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn('name="proposta_numero" type="text" maxlength="80"', html)
        self.assertNotIn('name="proposta_numero" readonly', html)
        self.assertNotIn('allocation-proposal-select', html)
        mes.assert_not_called()

    def test_update_keeps_typed_number_and_discards_stale_commercial_selector(self):
        body = {"proposta_numero": "10060.3", "commercial_program_id": "old-commercial-slot",
                "commercial_program_version": 7, "commercial_link_reason": "old screen",
                "municipio": "CURITIBA"}
        with patch.object(mod, "_erp_mes_request", return_value={"ok": True}) as mes:
            response = self.client.put("/api/erp/os-management/work-orders/work-1", json=body)
        self.assertEqual(200, response.status_code, response.json)
        mes.assert_called_once_with("work-orders/work-1", "PUT", {
            "proposta_numero": "10060.3", "municipio": "CURITIBA",
        })

    def test_create_never_establishes_a_commercial_link_from_stale_metadata(self):
        body = {"proposta_numero": "NOVA-REFERENCIA", "commercial_program_id": "old",
                "commercial_program_version": 1, "commercial_link_reason": "old screen"}
        with patch.object(mod, "_erp_mes_request", return_value={"ok": True}) as mes:
            response = self.client.post("/api/erp/os-management/entries/entry-1/work-orders", json=body)
        self.assertEqual(201, response.status_code, response.json)
        mes.assert_called_once_with("vehicle-entries/entry-1/work-orders", "POST", {
            "proposta_numero": "NOVA-REFERENCIA",
        })

    def test_historical_correction_keeps_reason_and_existing_work_order(self):
        body = {"motivo": "Corrigir referência da proposta entregue", "entry": {},
                "work_order": {"proposta_numero": "  10060.4  ", "commercial_program_id": "old",
                               "commercial_program_version": 1, "commercial_link_reason": "old"}}
        with patch.object(mod, "_erp_mes_request", return_value={"ok": True}) as mes:
            response = self.client.patch(
                "/api/erp/os-management/work-orders/work-1/historical-correction", json=body,
            )
        self.assertEqual(200, response.status_code, response.json)
        mes.assert_called_once_with("work-orders/work-1/historical-correction", "PATCH", {
            "motivo": body["motivo"], "entry": {}, "work_order": {"proposta_numero": "10060.4"},
        })

    def test_partial_update_does_not_clear_existing_proposal(self):
        with patch.object(mod, "_erp_mes_request", return_value={"ok": True}) as mes:
            response = self.client.put(
                "/api/erp/os-management/work-orders/work-1", json={"municipio": "CURITIBA"},
            )
        self.assertEqual(200, response.status_code, response.json)
        self.assertNotIn("proposta_numero", mes.call_args.args[2])

    def test_explicit_empty_reference_is_forwarded_as_null(self):
        for value in ("", "   ", None):
            with self.subTest(value=value), patch.object(mod, "_erp_mes_request", return_value={"ok": True}) as mes:
                response = self.client.put(
                    "/api/erp/os-management/work-orders/work-1", json={"proposta_numero": value},
                )
                self.assertEqual(200, response.status_code, response.json)
                mes.assert_called_once_with("work-orders/work-1", "PUT", {"proposta_numero": None})

    def test_invalid_or_overlong_reference_is_rejected_before_mes(self):
        for value in ("X" * 81, {"id": "p"}, ["p"], True):
            with self.subTest(value=value), patch.object(mod, "_erp_mes_request") as mes:
                response = self.client.put(
                    "/api/erp/os-management/work-orders/work-1", json={"proposta_numero": value},
                )
                self.assertEqual(400, response.status_code)
                mes.assert_not_called()

    def test_historical_correction_still_requires_reason(self):
        with patch.object(mod, "_erp_mes_request") as mes:
            response = self.client.patch(
                "/api/erp/os-management/work-orders/work-1/historical-correction",
                json={"work_order": {"proposta_numero": "10060.5"}},
            )
        self.assertEqual(400, response.status_code)
        mes.assert_not_called()

    def test_management_permission_is_still_required(self):
        with patch.object(mod, "can", return_value=False), patch.object(mod, "_erp_mes_request") as mes:
            response = self.client.put(
                "/api/erp/os-management/work-orders/work-1", json={"proposta_numero": "10060.5"},
            )
        self.assertEqual(403, response.status_code)
        mes.assert_not_called()
