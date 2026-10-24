import ast
from typing import Dict, List, Any

class PythonASTVisitor(ast.NodeVisitor):
    def __init__(self):
        self.dependencies: List[str] = []
        self.has_dynamic = False

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.dependencies.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        base_module = node.module if node.module else ""

        prefix = '.' * node.level if node.level > 0 else ''

        if base_module:
            # We record the base module
            self.dependencies.append(f"{prefix}{base_module}")
            # We also record the specific imported names to resolve submodules
            for alias in node.names:
                self.dependencies.append(f"{prefix}{base_module}.{alias.name}")
        else:
            if node.level > 0:
                self.dependencies.append(prefix)
                for alias in node.names:
                    self.dependencies.append(f"{prefix}{alias.name}")

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id in ('__import__', 'getattr', 'hasattr', 'setattr'):
                self.has_dynamic = True
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr == 'import_module':
                self.has_dynamic = True
        self.generic_visit(node)

def parse_python_file(filepath: str) -> Dict[str, Any]:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content, filename=filepath)
        visitor = PythonASTVisitor()
        visitor.visit(tree)

        return {
            "dependencies": visitor.dependencies,
            "dynamic_imports": visitor.has_dynamic
        }
    except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
        return {
            "dependencies": [],
            "dynamic_imports": True
        }
