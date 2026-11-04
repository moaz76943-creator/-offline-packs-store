import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/analysis/features.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print('Usage: dart_parser <file.dart>');
    exit(1);
  }

  final file = File(args[0]);
  if (!file.existsSync()) {
    print('File not found: ${args[0]}');
    exit(1);
  }

  try {
    final result = parseString(content: file.readAsStringSync(), featureSet: FeatureSet.latestLanguageVersion());
    final unit = result.unit;

    final deps = <String>[];

    for (final directive in unit.directives) {
      if (directive is UriBasedDirective) {
        deps.add(directive.uri.stringValue ?? '');
      }
    }

    print('DEPS:${deps.join(",")}');
  } catch (e) {
    print('ERROR:$e');
    exit(1);
  }
}
