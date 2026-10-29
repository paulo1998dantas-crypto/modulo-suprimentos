import sys
import unittest
from functools import wraps
from pathlib import Path
from unittest.mock import Mock
from flask import Flask

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'compras_app'))
from external_materials import internal_purchase_bom, EXTERNAL_MATERIAL_SKUS
from composicao import normalizar_componentes, expandir_composicao_itens, resolver_composicao_final
from external_stock_routes import register


class ExternalStockTests(unittest.TestCase):
    def test_technical_bom_is_not_mutated_and_bank_is_preserved_in_os_and_purchase(self):
        graph={'30200001':[{'codigo':'10200001','quantidade':3}],
               '10200001':[{'codigo':'10220272','quantidade':2}]}
        self.assertEqual([],internal_purchase_bom(graph)['10200001'])
        self.assertEqual([],normalizar_componentes(graph)['10200001'])
        lines=expandir_composicao_itens([{'codigo':'30200001','qtd':2}],graph)
        self.assertEqual([('10200001',6)],[(r['codigo'],r['qtd']) for r in lines])
        direct=resolver_composicao_final([{'codigo':'10200001','qtd':4}],graph)
        self.assertEqual([('10200001',4)],[(r['codigo'],r['qtd']) for r in direct])
        self.assertEqual(1,len(graph['10200001']))

    def setUp(self):
        self.app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'compras_app/templates'))
        self.app.secret_key='test-only';self.app.testing=True
        self.user={'id':9,'role':'PCP','roles':['PCP']}
        self.backend=Mock(return_value={'ok':True,'items':[],'movements':[],'total':0,'page':1})
        register(self.app,self.backend,lambda:self.user,lambda p:True,lambda f:f,lambda f:f)
        self.client=self.app.test_client()

    def test_page_opens_and_reads_do_not_write(self):
        # Portal include uses an optional global available in the real app.
        self.app.jinja_env.globals['portal_sso_enabled']=False
        response=self.client.get('/erp/baixa-externa')
        self.assertEqual(200,response.status_code)
        self.assertIn('Baixa externa',response.text)
        self.client.get('/api/erp/external-stock?sku=10220272&page=2')
        self.backend.assert_called_once_with('external-stock?sku=10220272&page=2','GET')

    def test_csrf_required_and_identity_cannot_be_supplied_by_frontend(self):
        self.assertEqual(403,self.client.post('/api/erp/external-stock',json={'quantity':2}).status_code)
        self.backend.assert_not_called()
        with self.client.session_transaction() as session:session['external_stock_csrf']='token'
        self.assertEqual(200,self.client.post('/api/erp/external-stock',json={'sku':'10220272','quantity':2},headers={'X-CSRF-Token':'token'}).status_code)
        self.backend.assert_called_once()

    def test_buyer_and_operator_cannot_access_external_stock(self):
        for role in ('COMPRADOR','OPERADOR','COMERCIAL'):
            self.user={'role':role,'roles':[role]}
            self.assertEqual(403,self.client.get('/api/erp/external-stock').status_code)
            self.assertEqual(403,self.client.get('/erp/baixa-externa').status_code)

    def test_classification_has_only_five_user_supplied_foam_skus(self):
        self.assertEqual({'10220272','10220273','10220274','10220275','10220276'},EXTERNAL_MATERIAL_SKUS)


if __name__=='__main__':unittest.main()
