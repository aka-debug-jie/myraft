import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import package_windows as package


class WindowsPackageTests(unittest.TestCase):
    def test_reuses_binary_bytes_used_for_receipt_check(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'docs').mkdir()
            (root / 'docs/quick-start-zh.md').write_text('guide')
            (root / 'go.mod').write_text('module probe')
            node, console, receipt = (root / n for n in ['node.exe', 'console.exe', 'receipt.json'])
            node.write_bytes(b'tested-node')
            console.write_bytes(b'tested-console')
            data = {'source_production_sha256': {'go.mod': package.sha((root / 'go.mod').read_bytes())},
                    'binary_sha256': {'raft-node.exe': package.sha(b'tested-node'),
                                      'raft-console.exe': package.sha(b'tested-console')}}
            receipt.write_text(json.dumps(data))
            original_read_bytes = Path.read_bytes
            reads = 0

            def changing_read(path):
                nonlocal reads
                if path == node:
                    reads += 1
                    return b'tested-node' if reads == 1 else b'replaced-node'
                return original_read_bytes(path)

            def git(args, **kwargs):
                return b'go.mod\0docs/quick-start-zh.md\0' if 'ls-files' in args else 'source\n' if 'rev-parse' in args else ''

            with patch.object(package, 'ROOT', root), \
                    patch.object(package.subprocess, 'check_output', side_effect=git), \
                    patch.object(Path, 'read_bytes', changing_read):
                output = root / 'package.zip'
                package.package(node, console, receipt, output)
                with zipfile.ZipFile(output) as z:
                    self.assertEqual(package.sha(z.read('project/raft-node.exe')),
                                     data['binary_sha256']['raft-node.exe'])
                self.assertEqual(reads, 1)

    def test_binds_sources_and_both_tested_binaries(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'docs').mkdir()
            (root / 'docs/quick-start-zh.md').write_text('guide')
            (root / 'go.mod').write_text('module probe')
            node, console, receipt = (root / n for n in ['node.exe', 'console.exe', 'receipt.json'])
            node.write_bytes(b'tested-node'); console.write_bytes(b'tested-console')
            data = {'source_production_sha256': {'go.mod': package.sha((root / 'go.mod').read_bytes())},
                    'binary_sha256': {'raft-node.exe': package.sha(node.read_bytes()),
                                      'raft-console.exe': package.sha(console.read_bytes())}}
            receipt.write_text(json.dumps(data))
            def git(args, **kwargs):
                return b'go.mod\0docs/quick-start-zh.md\0' if 'ls-files' in args else 'source\n' if 'rev-parse' in args else ''
            with patch.object(package, 'ROOT', root), patch.object(package.subprocess, 'check_output', side_effect=git):
                for binary in [node, console]:
                    saved = binary.read_bytes(); binary.write_bytes(b'unrelated-old-binary')
                    with self.assertRaisesRegex(ValueError, 'untested executable'):
                        package.package(node, console, receipt, root / 'bad.zip')
                    self.assertFalse((root / 'bad.zip').exists())
                    binary.write_bytes(saved)
                (root / 'go.mod').write_text('different-source')
                with self.assertRaisesRegex(ValueError, 'source set/digests'):
                    package.package(node, console, receipt, root / 'bad.zip')
                (root / 'go.mod').write_text('module probe')
                package.package(node, console, receipt, root / 'good.zip')
                with zipfile.ZipFile(root / 'good.zip') as z:
                    for line in z.read('SHA256SUMS.txt').decode().splitlines():
                        digest, name = line.split('  ', 1)
                        self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest)
                with self.assertRaises(FileExistsError):
                    package.package(node, console, receipt, root / 'good.zip')


if __name__ == '__main__':
    unittest.main()
