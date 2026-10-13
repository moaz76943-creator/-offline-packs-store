import ast

class ImportVisitor(ast.NodeVisitor):
    def __init__(self):
        self.imports = set()
        self.dynamic_imports = False

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module if node.module else ""
        level = node.level if node.level else 0
        prefix = "." * level

        # When module is None (e.g., from . import x), it represents a relative import
        if module:
            base_module = f"{prefix}{module}"
        else:
            base_module = prefix

        for alias in node.names:
            if base_module.endswith("."):
                self.imports.add(f"{base_module}{alias.name}")
            else:
                self.imports.add(f"{base_module}.{alias.name}")

        # Also record the base module for from imports since it creates a module dependency
        if module:
            self.imports.add(f"{prefix}{module}")

        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == '__import__':
            self.dynamic_imports = True
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == 'importlib' and node.func.attr == 'import_module':
                self.dynamic_imports = True
        self.generic_visit(node)

def parse_python_file(filepath: str) -> dict:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content, filename=filepath)
        visitor = ImportVisitor()
        visitor.visit(tree)

        return {
            'imports': list(visitor.imports),
            'has_dynamic': visitor.dynamic_imports,
            'error': None
        }
    except Exception as e:
        return {
            'imports': [],
            'has_dynamic': False,
            'error': str(e)
        }
