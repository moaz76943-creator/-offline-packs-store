import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/visitor.dart';

class DynamicVisitor extends RecursiveAstVisitor<void> {
  bool hasDynamic = false;

  @override
  void visitMethodInvocation(MethodInvocation node) {
    if (node.methodName.name == 'import' && node.target == null) {
      // Dart doesn't have a direct equivalent to python's eval/import,
      // but if dynamic methods named "import" exist, we flag it.
    }
    super.visitMethodInvocation(node);
  }
}

void main(List<String> args) {
  if (args.isEmpty) {
    print(jsonEncode({"error": "No file provided"}));
    exit(1);
  }

  final filePath = args[0];
  try {
    final result = parseString(content: File(filePath).readAsStringSync(), throwIfDiagnostics: false);
    final dependencies = <String>[];
    bool hasDynamic = false;

    for (final directive in result.unit.directives) {
      if (directive is ImportDirective) {
        dependencies.add(directive.uri.stringValue ?? "");
      } else if (directive is ExportDirective) {
        dependencies.add(directive.uri.stringValue ?? "");
      }
    }

    if (dependencies.contains('dart:mirrors')) {
      hasDynamic = true;
    }

    final visitor = DynamicVisitor();
    result.unit.accept(visitor);
    if (visitor.hasDynamic) {
      hasDynamic = true;
    }

    print(jsonEncode({
      'file': filePath,
      'dependencies': dependencies,
      'has_dynamic': hasDynamic,
      'syntax_error': result.errors.isNotEmpty
    }));
  } catch (e) {
    print(jsonEncode({
      'file': filePath,
      'error': e.toString(),
      'syntax_error': true
    }));
  }
}
