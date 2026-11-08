import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/visitor.dart';
import 'dart:convert';

class DepVisitor extends RecursiveAstVisitor<void> {
  final Set<String> deps = {};
  bool uncertain = false;

  @override
  void visitImportDirective(ImportDirective node) {
    deps.add(node.uri.stringValue ?? '');
    super.visitImportDirective(node);
  }

  @override
  void visitExportDirective(ExportDirective node) {
    deps.add(node.uri.stringValue ?? '');
    super.visitExportDirective(node);
  }

  @override
  void visitPartDirective(PartDirective node) {
    deps.add(node.uri.stringValue ?? '');
    super.visitPartDirective(node);
  }

  @override
  void visitMethodInvocation(MethodInvocation node) {
    if (node.methodName.name == 'reflect' || node.methodName.name == 'loadLibrary') {
      uncertain = true;
    }
    super.visitMethodInvocation(node);
  }
}

void main(List<String> args) {
  if (args.isEmpty) {
    print(jsonEncode({'error': 'no_file'}));
    exit(1);
  }

  final path = args[0];
  try {
    final result = parseFile(
      path: path,
      featureSet: FeatureSet.latestLanguageVersion(),
    );

    if (result.errors.isNotEmpty) {
      print(jsonEncode({'error': 'syntax_error', 'uncertain': true}));
      exit(0);
    }

    final visitor = DepVisitor();
    result.unit.accept(visitor);

    if (visitor.deps.contains('dart:mirrors')) {
      visitor.uncertain = true;
    }

    print(jsonEncode({
      'deps': visitor.deps.toList(),
      'uncertain': visitor.uncertain
    }));
  } catch (e) {
    print(jsonEncode({'error': e.toString(), 'uncertain': true}));
  }
}
