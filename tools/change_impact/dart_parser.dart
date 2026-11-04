import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/visitor.dart';
import 'package:analyzer/error/error.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print('Usage: dart_parser.dart <files.json>');
    exit(1);
  }

  var filesListFile = File(args[0]);
  List<dynamic> files = jsonDecode(filesListFile.readAsStringSync());

  var results = <String, dynamic>{};
  for (var path in files) {
    results[path] = parseDartFile(path);
  }
  print(jsonEncode(results));
}

Map<String, dynamic> parseDartFile(String path) {
  try {
    var result = parseFile(
        path: path,
        featureSet: FeatureSet.latestLanguageVersion());

    bool hasSyntaxError = result.errors.isNotEmpty;

    var visitor = DependencyVisitor();
    result.unit.visitChildren(visitor);

    bool hasReflection = visitor.imports.any((i) => i == 'dart:mirrors') || visitor.hasDynamic;

    return {
      'imports': visitor.imports.toList(),
      'has_uncertainty': hasReflection || hasSyntaxError,
      'error': hasSyntaxError,
    };
  } catch (e) {
    return {
      'imports': [],
      'has_uncertainty': true,
      'error': true,
    };
  }
}

class DependencyVisitor extends RecursiveAstVisitor<void> {
  final Set<String> imports = {};
  bool hasDynamic = false;

  @override
  void visitImportDirective(ImportDirective node) {
    imports.add(node.uri.stringValue ?? '');
    super.visitImportDirective(node);
  }

  @override
  void visitExportDirective(ExportDirective node) {
    imports.add(node.uri.stringValue ?? '');
    super.visitExportDirective(node);
  }

  @override
  void visitMethodInvocation(MethodInvocation node) {
    if (node.target != null && node.target is SimpleIdentifier) {
      if ((node.target as SimpleIdentifier).name == 'Function' && node.methodName.name == 'apply') {
        hasDynamic = true;
      }
    } else if (node.methodName.name == 'eval') {
        hasDynamic = true;
    }
    super.visitMethodInvocation(node);
  }
}
