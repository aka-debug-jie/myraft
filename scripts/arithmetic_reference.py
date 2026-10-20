"""Read-only, independent WAL v2 and integer reference for stopped experiment nodes.

Never repairs files. This is an experiment oracle, not a second Raft implementation.
"""
import hashlib
import json
from pathlib import Path
import struct
import zlib


def arithmetic(x, command):
    op, value = command['op'], command['value']
    if op == 'noop':
        return x
    if op in ('div', 'mod'):
        if not value:
            raise ValueError('division by zero')
        quotient = abs(x) // abs(value)
        if (x < 0) != (value < 0):
            quotient = -quotient
        result = quotient if op == 'div' else x - quotient * value
    elif op == 'add':
        result = x + value
    elif op == 'sub':
        result = x - value
    elif op == 'mul':
        result = x * value
    else:
        raise ValueError(f'unknown command {op}')
    return (result + (1 << 63)) % (1 << 64) - (1 << 63)


def digest(entries):
    h = hashlib.sha256()
    for e in entries:
        # Same wire JSON bytes as Go's json.Encoder, including trailing newline.
        ordered = {'index': e['index'], 'term': e['term'],
                   'command': {'op': e['command']['op'], 'value': e['command']['value']}}
        h.update((json.dumps(ordered, separators=(',', ':')) + '\n').encode())
    return h.hexdigest()


def read_wal(path, node_id):
    entries = []
    with Path(path).open('rb') as f:
        if f.read(16) != b'RAFTLOG2' + struct.pack('<Q', node_id):
            raise ValueError(f'node {node_id}: invalid WAL header')
        while header := f.read(12):
            if len(header) != 12:
                raise ValueError('incomplete WAL frame header')
            size, checksum, header_checksum = struct.unpack('<III', header)
            if zlib.crc32(header[:8]) != header_checksum or not 0 < size <= 32 << 20:
                raise ValueError('invalid WAL frame header checksum/size')
            payload = f.read(size)
            if len(payload) != size or zlib.crc32(payload) != checksum:
                raise ValueError('incomplete or corrupt WAL payload')
            record = json.loads(payload)
            start, suffix = record['from'], record['entries']
            if not suffix or not 1 <= start <= len(entries) + 1:
                raise ValueError('invalid WAL suffix')
            for i, entry in enumerate(suffix, start):
                if entry['index'] != i:
                    raise ValueError('nonsequential WAL suffix')
            entries[start - 1:] = suffix
    return entries


def verify_entries(entries, state, metadata):
    commit = metadata['commit_index']
    if not 0 <= commit <= len(entries):
        raise AssertionError('commit exceeds WAL')
    x, commands = 0, 0
    for entry in entries[:commit]:
        x = arithmetic(x, entry['command'])
        commands += entry['command']['op'] != 'noop'
    expected = {'last_log_index': len(entries), 'last_log_term': entries[-1]['term'] if entries else 0,
                'commit_index': commit, 'last_applied': commit, 'log_hash': digest(entries),
                'committed_hash': digest(entries[:commit]), 'committed_commands': commands,
                'applied_commands': commands, 'x': x}
    if metadata['commit_hash'] != expected['committed_hash']:
        raise AssertionError('metadata commit hash does not match independent WAL digest')
    for key, value in expected.items():
        if state[key] != value:
            raise AssertionError(f"node {state['id']}: independent {key}={value}, reported={state[key]}")
    target = state.get('target_index', 0)
    if state.get('target_available'):
        tx = 0
        for entry in entries[:target]:
            tx = arithmetic(tx, entry['command'])
        if not 0 <= target <= commit or state['target_hash'] != digest(entries[:target]) or state['target_x'] != tx:
            raise AssertionError('historical reference differs')
    return {'node_id': state['id'], 'result': 'PASS', **expected}


def verify_files(data_dir, states):
    results = []
    for state in states:
        node_id = state['id']
        metadata = json.loads((Path(data_dir) / f'node-{node_id}-state.json').read_text(encoding='utf-8'))
        entries = read_wal(Path(data_dir) / f'node-{node_id}-log.wal', node_id)
        results.append(verify_entries(entries, state, metadata))
    return results
