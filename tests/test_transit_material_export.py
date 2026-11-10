import copy
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'compras_app'))
from purchase_transit_export import project_transit_rows, export_transit_rows, load_current_graph


class TransitMaterialExportTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(numero_oc='2810', numero_linha=11, fornecedor_nome='SALTON VIDROS',
                        sku_codigo='30120029', descricao_original='CJ VIDROS', unidade='cj',
                        quantidade_pedida=10, quantidade_recebida=2, quantidade_pendente=8,
                        data_necessidade='2026-11-23', destino='O.S. 3246', status='PARCIALMENTE_RECEBIDA')
        self.catalog = {
            '30120029': dict(descricao='CJ VIDROS', unidade='cj', grupo='30'),
            'PP': dict(descricao='PP teste', unidade='pc', grupo='20'),
            'GLASS': dict(descricao='VIDRO SALT', unidade='pc', grupo='10'),
            'BANK': dict(descricao='BANCO RECLINAVEL', unidade='pc', grupo='30'),
        }
        self.edges = [dict(parent_sku='30120029', component_sku='PP', quantidade=2),
                      dict(parent_sku='PP', component_sku='GLASS', quantidade='0.5')]

    def test_partial_receipts_scale_all_three_quantities_and_keep_order_metadata(self):
        before = copy.deepcopy(self.row)
        result = project_transit_rows([self.row], self.catalog, self.edges)
        self.assertEqual(1, len(result))
        row = result[0]
        self.assertEqual(('GLASS', 'VIDRO SALT', 'pc'), (row['sku_codigo'], row['descricao_original'], row['unidade']))
        self.assertEqual((Decimal(10), Decimal(2), Decimal(8)),
                         (row['quantidade_pedida'], row['quantidade_recebida'], row['quantidade_pendente']))
        for key in ('numero_oc', 'numero_linha', 'fornecedor_nome', 'data_necessidade', 'destino', 'status'):
            self.assertEqual(self.row[key], row[key])
        self.assertEqual(before, self.row)

    def test_bank_is_retained_and_different_orders_are_not_merged(self):
        bank = dict(self.row, sku_codigo='BANK', descricao_original='BANCO RECLINAVEL', unidade='pc')
        second = dict(bank, numero_oc='2811', data_necessidade='2026-12-01')
        rows = project_transit_rows([bank, second], self.catalog,
            [dict(parent_sku='BANK', component_sku='10220272', quantidade=2)])
        self.assertEqual(['BANK', 'BANK'], [row['sku_codigo'] for row in rows])
        self.assertEqual(['2810', '2811'], [row['numero_oc'] for row in rows])

    def test_inconsistent_or_invalid_pending_balance_blocks_export(self):
        for pending in (9, -1, 0, 'NaN'):
            with self.subTest(pending=pending), self.assertRaises(ValueError):
                project_transit_rows([dict(self.row, quantidade_pendente=pending)], self.catalog, self.edges)

    def test_fresh_cadastro_is_used_for_every_export(self):
        with patch('purchase_transit_export.load_current_graph', return_value=(self.catalog, self.edges)) as source:
            self.assertEqual('GLASS', export_transit_rows([self.row])[0]['sku_codigo'])
            export_transit_rows([self.row])
        self.assertEqual(2, source.call_count)

    def test_cadastro_failure_does_not_return_original_phantom(self):
        with patch('purchase_transit_export.load_current_graph', side_effect=ValueError('Cadastro indisponível')):
            with self.assertRaisesRegex(ValueError, 'Cadastro indisponível'):
                export_transit_rows([self.row])

    def test_loader_bypasses_bom_cache_and_preserves_inactive_root_registration(self):
        import supabase_catalog
        import supabase_data
        record = dict(sku='BANK', descricao_primaria='BANCO RECLINAVEL', unidade='pc', ativo=False)
        with patch.object(supabase_catalog, 'enabled', return_value=True), \
             patch.object(supabase_data, 'enabled', return_value=True), \
             patch.object(supabase_catalog, '_all_rows', return_value=[record]) as catalog_source, \
             patch.object(supabase_data, '_all_rows', return_value=[]) as bom_source:
            catalog, edges = load_current_graph()
        self.assertFalse(catalog['BANK']['active'])
        self.assertEqual([], edges)
        catalog_source.assert_called_once_with()
        self.assertTrue(bom_source.call_args.kwargs['force'])


if __name__ == '__main__':
    unittest.main()
