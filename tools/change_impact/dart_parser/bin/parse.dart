import 'dart:convert';
import 'dart:io';

import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/visitor.dart';

class ImportVisitor extends RecursiveAstVisitor<void> {
  final Set<String> imports = {};
  final Set<String> exports = {};
  bool hasReflection = false;

  @override
  void visitImportDirective(ImportDirective node) {
    var uri = node.uri.stringValue;
    if (uri != null) {
      imports.add(uri);
      if (uri == 'dart:mirrors') {
        hasReflection = true;
      }
    }
    super.visitImportDirective(node);
  }

  @override
  void visitExportDirective(ExportDirective node) {
    var uri = node.uri.stringValue;
    if (uri != null) {
      exports.add(uri);
    }
    super.visitExportDirective(node);
  }
}

void main(List<String> args) {
  if (args.isEmpty) {
    print(jsonEncode({'error': 'No file provided'}));
    exit(1);
  }

  var path = args[0];
  var file = File(path);

  if (!file.existsSync()) {
    print(jsonEncode({'error': 'File does not exist: $path'}));
    exit(1);
  }

  try {
    var result = parseString(content: file.readAsStringSync(), path: path, throwIfDiagnostics: false);
    var visitor = ImportVisitor();
    result.unit.visitChildren(visitor);

    var output = {
      'imports': visitor.imports.toList(),
      'exports': visitor.exports.toList(),
      'has_reflection': visitor.hasReflection,
    };
    print(jsonEncode(output));
  } catch (e) {
    print(jsonEncode({'error': e.toString()}));
    exit(1);
  }
}
