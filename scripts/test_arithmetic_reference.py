import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from arithmetic_reference import arithmetic, digest, read_wal, verify_entries


def entry(index, op, value, term=1):
    return {'index': index, 'term': term, 'command': {'op': op, 'value': value}}


class ArithmeticReferenceTests(unittest.TestCase):
    def test_integer_rules_and_noop(self):
        for x, op, value, expected in [(-7, 'div', 3, -2), (-7, 'mod', 3, -1),
                                      (7, 'div', -3, -2), (7, 'mod', -3, 1),
                                      (2**63-1, 'add', 1, -2**63),
                                      (-2**63, 'div', -1, -2**63), (3, 'noop', 0, 3)]:
            self.assertEqual(arithmetic(x, {'op': op, 'value': value}), expected)
        with self.assertRaises(ValueError):
            arithmetic(1, {'op': 'div', 'value': 0})

    def test_equal_but_wrong_states_are_rejected(self):
        entries = [entry(1, 'noop', 0), entry(2, 'add', 7), entry(3, 'mul', -3)]
        h = digest(entries)
        state = dict(id=1, last_log_index=3, last_log_term=1, commit_index=3, last_applied=3,
                     committed_commands=2, applied_commands=2, log_hash=h, committed_hash=h, x=123456789)
        with self.assertRaisesRegex(AssertionError, 'independent x=-21'):
            verify_entries(entries, state, {'commit_index': 3, 'commit_hash': h})
        state['x'] = -21
        self.assertEqual(verify_entries(entries, state, {'commit_index': 3, 'commit_hash': h})['result'], 'PASS')

    def test_wal_replacement_and_corruption(self):
        prefix, old, replacement = entry(1, 'add', 7), entry(2, 'mul', 9), entry(2, 'sub', 2, 2)
        data = bytearray(b'RAFTLOG2' + struct.pack('<Q', 7))
        for start, entries in [(1, [prefix, old]), (2, [replacement])]:
            payload = json.dumps({'from': start, 'entries': entries}).encode()
            header = struct.pack('<II', len(payload), zlib.crc32(payload))
            data += header + struct.pack('<I', zlib.crc32(header)) + payload
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'log.wal'
            path.write_bytes(data)
            self.assertEqual(read_wal(path, 7), [prefix, replacement])
            data[-1] ^= 1
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                read_wal(path, 7)


if __name__ == '__main__':
    unittest.main()
