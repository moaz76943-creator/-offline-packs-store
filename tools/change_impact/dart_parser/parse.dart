import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/ast/ast.dart';

void main(List<String> args) {
  if (args.isEmpty) exit(1);
  final file = File(args[0]);
  if (!file.existsSync()) exit(1);

  try {
    final result = parseString(
      content: file.readAsStringSync(),
      featureSet: FeatureSet.latestLanguageVersion(),
      throwIfDiagnostics: false,
    );

    final imports = <String>[];
    for (final directive in result.unit.directives) {
      if (directive is ImportDirective) {
        imports.add(directive.uri.stringValue ?? '');
      } else if (directive is ExportDirective) {
        imports.add(directive.uri.stringValue ?? '');
      }
    }
    print(jsonEncode({'imports': imports.where((s) => s.isNotEmpty).toList()}));
  } catch (e) {
    print(jsonEncode({'error': e.toString()}));
  }
}
