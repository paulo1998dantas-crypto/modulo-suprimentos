import json
import os
from pathlib import Path
import sys
import unittest

from werkzeug.datastructures import MultiDict


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
sys.path.insert(0, str(APP_DIR))
os.environ["SUPRIMENTOS_REQUIRE_LOGIN"] = "0"

from app import (  # noqa: E402
    POPUP_ITEM_NAO_APLICAVEL,
    SuprimentosRequest,
    _parse_os_composition_form,
    _resolver_selecoes_popup_item,
    app,
)
from flask import request  # noqa: E402


class OsRequestPayloadTests(unittest.TestCase):
    def test_large_legacy_multipart_payload_is_accepted(self):
        pairs = []
        for index in range(1_500):
            pairs.extend(
                [
                    ("os_comp_item[]", "40340049"),
                    ("os_comp_codigo[]", str(10_000_000 + index)),
                    ("os_comp_descricao[]", f"COMPONENTE {index}"),
                    ("os_comp_unidade[]", "pc"),
                    ("os_comp_qtd[]", "1"),
                    ("os_comp_level[]", "1"),
                    ("os_comp_setor[]", "EXPEDICAO"),
                    ("os_comp_setor_manual[]", "0"),
                ]
            )

        with app.test_request_context(
            "/gerar_os",
            method="POST",
            data=MultiDict(pairs),
            content_type="multipart/form-data",
        ):
            self.assertEqual(len(request.form.getlist("os_comp_codigo[]")), 1_500)
            request.close()

    def test_json_composition_preserves_custom_rows(self):
        rows = [
            {
                "item": "40340049",
                "codigo": str(10_000_000 + index),
                "descricao": f"COMPONENTE {index}",
                "unidade": "pc",
                "qtd": "1",
                "level": 1,
                "setor": "PREPARACAO",
                "setor_manual": True,
            }
            for index in range(1_500)
        ]
        form = MultiDict({"os_composicao_json": json.dumps(rows)})

        parsed = _parse_os_composition_form(form)

        self.assertEqual(len(parsed), 1_500)
        self.assertEqual(parsed[0]["item"], "40340049")
        self.assertEqual(parsed[-1]["setor"], "PREPARACAO")
        self.assertTrue(parsed[-1]["setor_manual"])

    def test_request_limits_cover_long_orders(self):
        self.assertGreaterEqual(SuprimentosRequest.max_form_parts, 20_000)
        self.assertGreaterEqual(SuprimentosRequest.max_form_memory_size, 32 * 1024 * 1024)
        self.assertGreaterEqual(app.config["MAX_CONTENT_LENGTH"], 64 * 1024 * 1024)


class OsPopupChainTests(unittest.TestCase):
    def setUp(self):
        self.regras = {
            "A": [{"id": "regra-a", "gatilho": "A", "opcoes": ["B"]}],
            "B": [{"id": "regra-b", "gatilho": "B", "opcoes": ["C"]}],
        }

    def test_resolves_complete_nested_popup_chain(self):
        selecoes = [
            {"regra_id": "regra-a", "codigo": "B", "qtd": 1},
            {
                "regra_id": "regra-b",
                "codigo": "C",
                "qtd": 2,
                "chave": "root:A|regra-a>B|regra-b",
            },
        ]

        resolvidas, erro = _resolver_selecoes_popup_item("A", selecoes, self.regras)

        self.assertEqual(erro, "")
        self.assertEqual([item["codigo"] for item in resolvidas], ["B", "C"])
        self.assertEqual(resolvidas[1]["gatilho"], "B")
        self.assertEqual(resolvidas[1]["ancestrais"], ["root:A|regra-a"])

    def test_requires_selection_for_nested_trigger(self):
        resolvidas, erro = _resolver_selecoes_popup_item(
            "A",
            [{"regra_id": "regra-a", "codigo": "B", "qtd": 1}],
            self.regras,
        )

        self.assertEqual([item["codigo"] for item in resolvidas], ["B"])
        self.assertIn("B", erro)

    def test_rejects_popup_cycles(self):
        regras = {
            **self.regras,
            "B": [{"id": "regra-b", "gatilho": "B", "opcoes": ["A"]}],
        }
        selecoes = [
            {"regra_id": "regra-a", "codigo": "B", "qtd": 1},
            {
                "regra_id": "regra-b",
                "codigo": "A",
                "qtd": 1,
                "chave": "root:A|regra-a>B|regra-b",
            },
        ]

        _, erro = _resolver_selecoes_popup_item("A", selecoes, regras)

        self.assertIn("A -> B -> A", erro)

    def test_ignores_stale_selections_outside_active_chain(self):
        selecoes = [
            {"regra_id": "regra-a", "codigo": "B", "qtd": 1},
            {
                "regra_id": "regra-b",
                "codigo": "C",
                "qtd": 1,
                "chave": "root:A|regra-a>B|regra-b",
            },
            {"regra_id": "regra-antiga", "codigo": "X", "qtd": 99},
        ]

        resolvidas, erro = _resolver_selecoes_popup_item("A", selecoes, self.regras)

        self.assertEqual(erro, "")
        self.assertEqual([item["codigo"] for item in resolvidas], ["B", "C"])

    def test_non_applicable_completes_root_popup_without_creating_item(self):
        resolvidas, erro = _resolver_selecoes_popup_item(
            "A",
            [{"regra_id": "regra-a", "codigo": POPUP_ITEM_NAO_APLICAVEL, "qtd": 0}],
            self.regras,
        )

        self.assertEqual(erro, "")
        self.assertEqual(len(resolvidas), 1)
        self.assertEqual(resolvidas[0]["codigo"], POPUP_ITEM_NAO_APLICAVEL)
        self.assertEqual(resolvidas[0]["qtd"], 0)

    def test_non_applicable_stops_only_nested_branch(self):
        selecoes = [
            {"regra_id": "regra-a", "codigo": "B", "qtd": 1},
            {
                "regra_id": "regra-b",
                "codigo": POPUP_ITEM_NAO_APLICAVEL,
                "qtd": 0,
                "chave": "root:A|regra-a>B|regra-b",
            },
        ]

        resolvidas, erro = _resolver_selecoes_popup_item("A", selecoes, self.regras)

        self.assertEqual(erro, "")
        self.assertEqual([item["codigo"] for item in resolvidas], ["B", POPUP_ITEM_NAO_APLICAVEL])


if __name__ == "__main__":
    unittest.main()
