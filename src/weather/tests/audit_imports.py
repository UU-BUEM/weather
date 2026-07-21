#!/usr/bin/env python3
"""Audit a Python file for the local-import-scope bug.

Flags any use of np./xr./pd./cfgrib. inside a function where that module
is NOT imported at module level or locally in the function — the exact
pattern that caused the '_ffill_time: name xr is not defined' error.

Usage:  python audit_imports.py path/to/file.py [more.py ...]
"""
import ast
import glob
import os
import sys

WATCH = {"np", "xr", "pd", "cfgrib", "warnings"}


def _expand(args):
    """Expand glob patterns that the shell (e.g. PowerShell) left literal."""
    paths = []
    for a in args:
        if os.path.isfile(a):
            paths.append(a)
            continue
        matches = glob.glob(a)
        if not matches:
            print(f"[WARN] no files matched: {a}", file=sys.stderr)
        paths.extend(matches)
    return paths


def audit(path):
    with open(path) as fh:
        src = fh.read()
    mod = ast.parse(src)
    top = set()
    for n in mod.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                top.add(a.asname or a.name)
    hits = []
    for fn in ast.walk(mod):
        if not isinstance(fn, ast.FunctionDef):
            continue
        local = set()
        for n in ast.walk(fn):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    local.add(a.asname or a.name)
        for stmt in fn.body:  # body only -> skips annotations
            for n in ast.walk(stmt):
                if (isinstance(n, ast.Attribute)
                        and isinstance(n.value, ast.Name)
                        and n.value.id in WATCH
                        and n.value.id not in top
                        and n.value.id not in local):
                    hits.append((fn.name, n.lineno, f"{n.value.id}.{n.attr}"))
    if hits:
        print(f"[FAIL] {path}")
        for fname, lineno, e in hits:
            print(f"    {fname}  line {lineno}:  {e}  <- not imported in scope")
    else:
        print(f"[ OK ] {path}")
    return not hits


if __name__ == "__main__":
    ok = all(audit(p) for p in _expand(sys.argv[1:]))
    sys.exit(0 if ok else 1)
