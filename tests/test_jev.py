import unittest
from orpheus.jev import JevClient
from orpheus.resolver import SelectionError


class JevTests(unittest.TestCase):
    def answer(self): return {'answers':{'selection':{'type':'choice','choice':'a','probabilities':{'a':.8,'b':.2},'confidence':.8}}}
    def test_valid(self): self.assertEqual(JevClient.validate(self.answer(),{'a':'a','b':'b'})['choice'],'a')
    def test_out_of_set(self):
        answer=self.answer(); answer['answers']['selection']['choice']='c'
        with self.assertRaises(SelectionError): JevClient.validate(answer,{'a':'a','b':'b'})
    def test_low_confidence(self):
        with self.assertRaises(SelectionError) as error: JevClient.validate(self.answer(),{'a':'a','b':'b'},.9)
        self.assertEqual(error.exception.code,'low_confidence')
    def test_invalid_distribution(self):
        answer=self.answer(); answer['answers']['selection']['probabilities']['a']=float('nan')
        with self.assertRaises(SelectionError): JevClient.validate(answer,{'a':'a','b':'b'})
