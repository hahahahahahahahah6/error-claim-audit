# error-claim-audit

An offline static CLI that checks documented Python error behaviour against
production source. Python 3.9 or later; no runtime dependencies.

Install with `pip install .`, then run:

```sh
error-claim-audit path/to/project --json
python -m error_claim_audit path/to/project --verbose
```

The tool exits 0 for PASS, exits 2 for FAIL, and exits 1 for usage or input
errors. The default failure threshold is MEDIUM. `--fail-on HIGH` still
prints MEDIUM findings but lets those findings pass. `--ignore RULE,...`
drops selected findings. `--version` prints `0.1.0`.

Rules:

- `documented-exit-code-unproduced` (HIGH)
- `documented-exception-unraised` (HIGH)
- `documented-error-message-unproduced` (MEDIUM)

Only root README.md and docs/**/*.md supply claims. Exit promises in prose
count; fenced shell exit commands do not. Exception promises count in prose,
inline code, and fences. Message claims require the word error and a quoted
string of at least four characters on the same line. Matching is exact and
case sensitive for messages. Exit claims are integers from 0 through 255.

Production Python files supply AST evidence. Tests, test_*.py, *_test.py,
fixtures and docs trees are excluded. Malformed Python is skipped. The tool
never imports or executes target code, accesses the network, or opens .env.
Symlink files are skipped. An unreadable source or documentation file causes
an input error rather than a partial audit.

Literal sys.exit, SystemExit, exit and quit arguments supply exit evidence.
The one framework implication modeled is creation of an ArgumentParser plus
a parse_args call in the same file: together these supply exit 2. The tool
also follows literal returns in functions named main when sys.exit(main())
appears in the same file. Nested function returns are excluded. Variables,
computed values, dynamic imports, aliases and cross-file data flow are not
resolved. Static evidence does not prove that a path is reachable.

Only raised names count as exception evidence; caught names and bare
re-raises do not. Literal first arguments of raised calls supply message
evidence. Literal arguments of sys.stderr.write or print with file=sys.stderr
supply message evidence when they contain the word error.

JSON includes status, deterministic findings (rule, severity, file, line,
claim), verified_claims grouped into exit_codes, exceptions and messages,
and a summary of unique claims, findings, and verified claims. Repeated
claims are verified once; unmatched occurrences retain documentation locations.
No claims means PASS. With no production source, all claims are findings.
Undocumented behaviour never causes a finding.

This complements pytest/unittest, which observe runtime behaviour;
readme-claim-audit, which checks install names, flags, links and versions;
api-claim-audit, which checks symbols and signatures; config-claim-audit,
which checks default values; and bandit/ruff, which check code issues.
It does not replace these tools.

Run tests from the source tree:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
```

MIT licensed.
