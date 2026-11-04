import ast
import os
from typing import Tuple, List, Set

def extract_python_imports(filepath: str) -> Tuple[List[str], bool]:
    """
    Parses a Python file and extracts imported modules.
    Returns a tuple of (imports, is_dynamic_uncertain).
    """
    if not os.path.exists(filepath):
        return [], False

    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        # Syntax error makes impact uncertain
        return [], True

    imports: Set[str] = set()
    is_dynamic = False

    class ImportVisitor(ast.NodeVisitor):
        nonlocal is_dynamic

        def visit_Import(self, node):
            for alias in node.names:
                imports.add(alias.name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            if node.module:
                # Resolve relative imports if needed, but here we just record the module string
                prefix = '.' * node.level if node.level > 0 else ''
                imports.add(prefix + node.module)
            else:
                # e.g., from . import foo
                prefix = '.' * node.level if node.level > 0 else ''
                for alias in node.names:
                    imports.add(prefix + alias.name)
            self.generic_visit(node)

        def visit_Call(self, node):
            nonlocal is_dynamic
            if isinstance(node.func, ast.Name):
                if node.func.id in ('__import__', 'eval', 'exec', 'getattr'):
                    is_dynamic = True
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr == 'import_module':
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == 'importlib':
                        is_dynamic = True
            self.generic_visit(node)

    visitor = ImportVisitor()
    visitor.visit(tree)

    return list(imports), is_dynamic
