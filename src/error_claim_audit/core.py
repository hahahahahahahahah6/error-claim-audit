"""Read documentation and AST evidence without importing target code."""
import ast
import re
from pathlib import Path

RULES = {
    "exit_codes": ("documented-exit-code-unproduced", "HIGH"),
    "exceptions": ("documented-exception-unraised", "HIGH"),
    "messages": ("documented-error-message-unproduced", "MEDIUM"),
}
EXCEPTION = r"(?:[A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning)|Error|Exception|Warning|SystemExit|KeyboardInterrupt|StopIteration)"
EXIT = re.compile(r"\bexits?\s+(?:(?:code|status)\s+)?(\d+)\b", re.I)
EXC = re.compile(r"\b(?i:raises?|throws)\s+(?:[a-zA-Z_]\w*\.)*(" + EXCEPTION + r")\b|\b(" + EXCEPTION + r")\s+(?i:is\s+raised)\b")
QUOTED = re.compile(r"([\"'])(.*?)\1")


def claims(text, filename):
    result = []
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            for match in EXIT.finditer(line):
                value = int(match.group(1))
                if 0 <= value <= 255:
                    result.append(("exit_codes", value, filename, number))
        for match in EXC.finditer(line):
            result.append(("exceptions", match.group(1) or match.group(2), filename, number))
        if re.search(r"\berror\b", line, re.I):
            for match in QUOTED.finditer(line):
                if len(match.group(2)) >= 4:
                    result.append(("messages", match.group(2), filename, number))
    return result


def name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = name(node.value)
        return base + "." + node.attr if base else node.attr
    return ""


def integer(node):
    return isinstance(node, ast.Constant) and type(node.value) is int


def evidence(source):
    result = {key: set() for key in RULES}
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return result
    nodes = list(ast.walk(tree))
    parser = any(isinstance(n, ast.Call) and name(n.func) in ("argparse.ArgumentParser", "ArgumentParser") for n in nodes)
    parse = any(isinstance(n, ast.Call) and name(n.func).split(".")[-1] == "parse_args" for n in nodes)
    if parser and parse:
        result["exit_codes"].add(2)
    main_returns = set()
    def returns(body):
        for child in ast.iter_child_nodes(body):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Return) and integer(child.value):
                main_returns.add(child.value.value)
            returns(child)
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            returns(node)
    for node in nodes:
        if isinstance(node, ast.Call):
            called = name(node.func)
            if called in ("sys.exit", "SystemExit", "exit", "quit") and node.args:
                arg = node.args[0]
                if integer(arg):
                    result["exit_codes"].add(arg.value)
                elif called == "sys.exit" and isinstance(arg, ast.Call) and name(arg.func) == "main":
                    result["exit_codes"].update(main_returns)
            stderr = called == "sys.stderr.write" or (called == "print" and any(k.arg == "file" and name(k.value) == "sys.stderr" for k in node.keywords))
            if stderr:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.search(r"\berror\b", arg.value, re.I):
                        result["messages"].add(arg.value)
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc
            target = exc.func if isinstance(exc, ast.Call) else exc
            raised = name(target)
            if raised:
                result["exceptions"].add(raised.split(".")[-1])
            if isinstance(exc, ast.Call) and exc.args:
                arg = exc.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    result["messages"].add(arg.value)
    return result


def audit(root, fail_on="MEDIUM", ignore=()):
    root = Path(root)
    if not root.is_dir():
        raise ValueError("project directory does not exist: " + str(root))
    documented = []
    docs = [root / "README.md"] + sorted((root / "docs").rglob("*.md"))
    for path in docs:
        if path.is_file() and not path.is_symlink():
            documented.extend(claims(path.read_text(encoding="utf-8", errors="replace"), path.relative_to(root).as_posix()))
    produced = {key: set() for key in RULES}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if path.is_symlink() or any(part in ("tests", "fixtures", "docs") for part in rel.parts[:-1]) or path.name.startswith("test_") or path.name.endswith("_test.py"):
            continue
        found = evidence(path.read_text(encoding="utf-8", errors="replace"))
        for key in produced:
            produced[key].update(found[key])
    findings = []
    verified = {key: set() for key in RULES}
    for kind, value, file, line in set(documented):
        rule, severity = RULES[kind]
        if value in produced[kind]:
            verified[kind].add(value)
        elif rule not in ignore:
            findings.append(dict(rule=rule, severity=severity, file=file, line=line, claim=str(value)))
    findings.sort(key=lambda f: (f["rule"], f["file"], f["line"], f["claim"]))
    failed = any(f["severity"] == "HIGH" or fail_on == "MEDIUM" for f in findings)
    return dict(status="FAIL" if failed else "PASS", findings=findings,
                verified_claims={key: sorted(values) for key, values in verified.items()},
                summary=dict(claims=len(set((k, v) for k, v, _, _ in documented)), findings=len(findings), verified=sum(len(v) for v in verified.values())))
