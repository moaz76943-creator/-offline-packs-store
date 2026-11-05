# AST-Based Change Impact & Test Selection Engine

This tool performs source-aware dependency analysis for Python and Dart to map file changes to affected modules, tests, and integration contracts.

It supports parsing Python files via the `ast` module and Dart files using `dart run` with the Dart `analyzer` package. It builds an in-memory directed dependency graph and identifies impacted test ownership based on the changes. If it identifies dynamic capabilities (such as dynamic module imports or reflection) whose impact is uncertain, it widens the test scope to run all available tests.

## Features
- Python AST imports analysis (including dynamic capabilities).
- Dart AST imports analysis using `dart run`.
- Incrementally built directed dependency graph.
- Handles cycles, mixed sources, syntax errors, and missing parsers.

## Usage
```bash
python3 tools/change_impact/cli.py <file1> <file2> ... --repo-root .
```
