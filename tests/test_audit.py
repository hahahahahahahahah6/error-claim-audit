import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from error_claim_audit.core import audit, claims, evidence, RULES
from error_claim_audit.cli import main

BASE = Path(__file__).parent / 'fixtures'
ROOT = Path(__file__).resolve().parents[1]
os.environ['TMPDIR'] = str(ROOT / '.tmp')
(ROOT / '.tmp').mkdir(exist_ok=True)
tempfile.tempdir = str(ROOT / '.tmp')


class AuditTests(unittest.TestCase):
    def project(self, docs='', source=None, extra=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'README.md').write_text(docs)
        if source is not None:
            (root / 'app.py').write_text(source)
        for file, value in (extra or {}).items():
            path = root / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        return root

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                code = main(list(map(str, args)))
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), errors.getvalue()

    def test_good(self):
        result = audit(BASE / 'good')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['verified_claims'], dict(exit_codes=[0, 2], exceptions=['ValueError'], messages=['input file not found']))
        self.assertEqual(self.cli(BASE / 'good')[0], 0)

    def test_bad(self):
        result = audit(BASE / 'bad')
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(len(result['findings']), 3)
        self.assertEqual({f['rule'] for f in result['findings']}, {r for r, _ in RULES.values()})
        self.assertEqual(self.cli(BASE / 'bad')[0], 2)

    def test_json_fail(self):
        code, output, _ = self.cli(BASE / 'bad', '--json')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)['status'], 'FAIL')

    def test_determinism(self):
        self.assertEqual(self.cli(BASE / 'bad', '--json'), self.cli(BASE / 'bad', '--json'))

    def test_high_threshold(self):
        root = self.project('error "missing file"')
        code, output, _ = self.cli(root, '--fail-on', 'HIGH')
        self.assertEqual(code, 0)
        self.assertIn('MEDIUM documented-error-message-unproduced', output)

    def test_ignore(self):
        root = self.project('exit 9')
        code, output, _ = self.cli(root, '--ignore', 'documented-exit-code-unproduced')
        self.assertEqual(code, 0)
        self.assertNotIn('HIGH', output)

    def test_unknown_ignore(self):
        self.assertEqual(self.cli(BASE / 'good', '--ignore', 'oops')[0], 1)

    def test_version(self):
        self.assertEqual(self.cli('--version')[:2], (0, '0.1.0\n'))

    def test_invalid_option(self):
        self.assertEqual(self.cli('--oops')[0], 1)

    def test_invalid_threshold(self):
        self.assertEqual(self.cli('--fail-on', 'LOW')[0], 1)

    def test_invalid_path(self):
        self.assertEqual(self.cli(ROOT / 'missing-directory')[0], 1)

    def test_verbose(self):
        self.assertIn('OK exceptions ValueError', self.cli(BASE / 'good', '--verbose')[1])

    def test_no_claims(self):
        self.assertEqual(audit(self.project('hello', 'raise ValueError()'))['status'], 'PASS')

    def test_no_source(self):
        self.assertEqual(len(audit(self.project('exit 2\nraises ValueError\nerror "long message"'))['findings']), 3)

    def test_env_never_opened(self):
        root = self.project('exit 0', 'exit(0)', {'.env': 'marker only'})
        original = io.open
        def checked(file, *args, **kwargs):
            if not isinstance(file, int):
                self.assertNotEqual(Path(file).name, '.env')
            return original(file, *args, **kwargs)
        with patch('io.open', checked):
            self.assertEqual(audit(root)['status'], 'PASS')

    def test_docs_scope(self):
        root = self.project('', 'pass', {'notes.md': 'exit 2', 'docs/deep/a.md': 'exit 3'})
        result = audit(root)
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['file'], 'docs/deep/a.md')

    def test_lines_and_sort(self):
        result = audit(self.project('exit 9\nraises ValueError\nerror "message"'))
        findings = result['findings']
        self.assertEqual(findings, sorted(findings, key=lambda f: (f['rule'], f['file'], f['line'], f['claim'])))
        self.assertEqual({f['line'] for f in findings}, {1, 2, 3})

    def test_malformed(self):
        self.assertEqual(audit(self.project('exit 2', 'def broken('))['status'], 'FAIL')

    def test_nested_main_return_excluded(self):
        source = 'def main():\n def other():\n  return 9\n return 0\nsys.exit(main())'
        self.assertEqual(evidence(source)['exit_codes'], {0})

    def test_duplicate_claims_normalized(self):
        result = audit(self.project('exit 2 exit 2\nexit 2', 'exit(2)'))
        self.assertEqual(result['verified_claims']['exit_codes'], [2])
        self.assertEqual(result['summary']['claims'], 1)


EXIT_PROSE = ['exit 2', 'exits 2', 'exit code 2', 'exit status 2', 'returns exit code 2', 'with exit code 2', 'EXITS 2', 'exit 0', 'exit 255']
for index, prose in enumerate(EXIT_PROSE):
    def test(self, prose=prose):
        self.assertEqual(claims(prose, 'README.md')[0][1], int(prose.split()[-1]))
    setattr(AuditTests, 'test_exit_prose_%02d' % index, test)

CLAIM_CASES = [
 ('```sh\nexit 2\n```', 'exit_codes', []),
 ('~~~sh\nexit 2\n~~~', 'exit_codes', []),
 ('exit 256', 'exit_codes', []),
 ('exit -1', 'exit_codes', []),
 ('raises ValueError', 'exceptions', ['ValueError']),
 ('raise TypeError', 'exceptions', ['TypeError']),
 ('throws CustomException', 'exceptions', ['CustomException']),
 ('ValueError is raised', 'exceptions', ['ValueError']),
 ('`raises ValueError`', 'exceptions', ['ValueError']),
 ('```python\nraise ValueError()\n```', 'exceptions', ['ValueError']),
 ('raises package.CustomError', 'exceptions', ['CustomError']),
 ('raises Exception', 'exceptions', ['Exception']),
 ('raises Warning', 'exceptions', ['Warning']),
 ('raises UserWarning', 'exceptions', ['UserWarning']),
 ('raises SystemExit', 'exceptions', ['SystemExit']),
 ('raises KeyboardInterrupt', 'exceptions', ['KeyboardInterrupt']),
 ('raises StopIteration', 'exceptions', ['StopIteration']),
 ('"missing file"', 'messages', []),
 ('error "abc"', 'messages', []),
 ('ERROR "abcd"', 'messages', ['abcd']),
 ("error 'missing file'", 'messages', ['missing file']),
 ('```\nerror: "missing file"\n```', 'messages', ['missing file']),
]
for index, (text, kind, expected) in enumerate(CLAIM_CASES):
    def test(self, text=text, kind=kind, expected=expected):
        self.assertEqual([v for k, v, _, _ in claims(text, 'doc') if k == kind], expected)
    setattr(AuditTests, 'test_claim_%02d' % index, test)

EVIDENCE_CASES = [
 ('sys.exit(2)', 'exit_codes', {2}),
 ('raise SystemExit(2)', 'exit_codes', {2}),
 ('SystemExit(2)', 'exit_codes', {2}),
 ('def f():\n return SystemExit(2)', 'exit_codes', {2}),
 ('exit(2)', 'exit_codes', {2}),
 ('quit(2)', 'exit_codes', {2}),
 ('sys.exit(x)', 'exit_codes', set()),
 ('sys.exit(1+1)', 'exit_codes', set()),
 ('sys.exit(True)', 'exit_codes', set()),
 ('argparse.ArgumentParser().parse_args()', 'exit_codes', {2}),
 ('p = ArgumentParser()\np.parse_args()', 'exit_codes', {2}),
 ('p = argparse.ArgumentParser()', 'exit_codes', set()),
 ('p.parse_args()', 'exit_codes', set()),
 ('def main():\n return 2\nsys.exit(main())', 'exit_codes', {2}),
 ('def other():\n return 2\nsys.exit(other())', 'exit_codes', set()),
 ('def main():\n return x\nsys.exit(main())', 'exit_codes', set()),
 ('raise ValueError()', 'exceptions', {'ValueError'}),
 ('raise ValueError', 'exceptions', {'ValueError'}),
 ('raise module.ValueError("x") from cause', 'exceptions', {'ValueError'}),
 ('raise', 'exceptions', set()),
 ('try:\n pass\nexcept ValueError:\n pass', 'exceptions', set()),
 ('ValueError("hello")', 'exceptions', set()),
 ('raise ValueError("missing file")', 'messages', {'missing file'}),
 ('raise ValueError(message)', 'messages', set()),
 ('sys.stderr.write("error: missing file")', 'messages', {'error: missing file'}),
 ('print("ERROR missing file", file=sys.stderr)', 'messages', {'ERROR missing file'}),
 ('print("error: missing file")', 'messages', set()),
 ('sys.stderr.write("missing file")', 'messages', set()),
 ('raise ValueError(f"missing {x}")', 'messages', set()),
 ('def broken(', 'exceptions', set()),
]
for index, (source, kind, expected) in enumerate(EVIDENCE_CASES):
    def test(self, source=source, kind=kind, expected=expected):
        self.assertEqual(evidence(source)[kind], expected)
    setattr(AuditTests, 'test_evidence_%02d' % index, test)

for index, filename in enumerate(['tests/a.py', 'nested/tests/a.py', 'test_a.py', 'a_test.py', 'fixtures/a.py', 'docs/a.py']):
    def test(self, filename=filename):
        root = self.project('raises ValueError', 'pass', {filename: 'raise ValueError()'})
        self.assertEqual(audit(root)['status'], 'FAIL')
    setattr(AuditTests, 'test_exclusion_%02d' % index, test)

if __name__ == '__main__':
    unittest.main()
