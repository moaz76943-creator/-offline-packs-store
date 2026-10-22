import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/visitor.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print("Usage: dart parse.dart <filepath>");
    exit(1);
  }

  final path = args[0];
  final file = File(path);
  if (!file.existsSync()) {
    print(jsonEncode({"error": "File not found: $path"}));
    exit(0);
  }

  final content = file.readAsStringSync();
  try {
    final result = parseString(
      content: content,
      featureSet: FeatureSet.latestLanguageVersion(),
      throwIfDiagnostics: false,
    );

    final unit = result.unit;
    List<String> imports = [];
    bool hasReflection = false;

    for (final directive in unit.directives) {
      if (directive is ImportDirective) {
        imports.add(directive.uri.stringValue ?? "");
        if (directive.uri.stringValue == 'dart:mirrors') {
          hasReflection = true;
        }
      } else if (directive is ExportDirective) {
        imports.add(directive.uri.stringValue ?? "");
      }
    }

    unit.accept(_Visitor(onReflectionFound: () => hasReflection = true));

    print(jsonEncode({
      "imports": imports.where((i) => i.isNotEmpty).toList(),
      "has_reflection": hasReflection,
      "syntax_errors": result.errors.isNotEmpty
    }));
  } catch (e) {
    print(jsonEncode({"error": e.toString(), "syntax_errors": true}));
  }
}

class _Visitor extends RecursiveAstVisitor<void> {
  final Function onReflectionFound;
  _Visitor({required this.onReflectionFound});

  @override
  void visitMethodInvocation(MethodInvocation node) {
    if (node.methodName.name == 'currentMirrorSystem' ||
        node.methodName.name == 'reflect' ||
        node.methodName.name == 'reflectClass') {
      onReflectionFound();
    }
    super.visitMethodInvocation(node);
  }
}
