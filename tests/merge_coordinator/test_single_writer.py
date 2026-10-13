import unittest
from tools.merge_coordinator.cli import competing_writer
from tools.merge_coordinator.transport import APIError

class Reader:
    def __init__(self, outcome):
        self.outcome=outcome
    def call(self,path):
        if isinstance(self.outcome,Exception):
            raise self.outcome
        return self.outcome

class WriterSafety(unittest.TestCase):
    def test_existing_writer_blocks(self):
        self.assertTrue(competing_writer(Reader({'name':'public_merge_coordinator.yml'})))
    def test_unknown_permission_blocks(self):
        self.assertTrue(competing_writer(Reader(APIError(403,'forbidden'))))
    def test_confirmed_absence_unblocks_only_this_gate(self):
        self.assertFalse(competing_writer(Reader(APIError(404,'not found'))))
