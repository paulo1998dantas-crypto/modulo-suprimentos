import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import supabase_catalog


class BankCatalogTests(unittest.TestCase):
    def test_lists_active_unitary_banks_and_bank_sets_with_narrow_payload(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps([
            {"sku": "10200033", "descricao_primaria": "BCO UNITARIO TESTE", "unidade": "pc"},
            {"sku": "20200001", "descricao_primaria": "PROCESSO FORA DO CATALOGO", "unidade": "pc"},
            {"sku": "30200049", "descricao_primaria": "CJ BANCOS TESTE", "unidade": "cj"},
        ]).encode("utf-8")
        environment = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test-key",
        }

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(supabase_catalog.urllib.request, "urlopen", return_value=response) as urlopen,
        ):
            rows = supabase_catalog.active_bank_sets(limit=200)

        self.assertEqual(
            [
                {"codigo": "10200033", "descricao": "BCO UNITARIO TESTE", "unidade": "pc"},
                {"codigo": "30200049", "descricao": "CJ BANCOS TESTE", "unidade": "cj"},
            ],
            rows,
        )
        url = urlopen.call_args.args[0].full_url
        self.assertIn("category_key=in.%28bancos%2Ccat_20_bco%29", url)
        self.assertNotIn("sku=like.30%2A", url)
        self.assertIn("ativo=is.true", url)
        self.assertIn("select=sku%2Cdescricao_primaria%2Cunidade", url)


if __name__ == "__main__":
    unittest.main()
