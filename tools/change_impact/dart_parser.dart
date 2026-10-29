import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/analysis/features.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print("BLOCKED: Missing file argument");
    exit(1);
  }

  final path = args[0];

  try {
    final result = parseFile(
      path: path,
      featureSet: FeatureSet.latestLanguageVersion(),
    );

    final unit = result.unit;

    final deps = <String>[];

    // In Dart, imports are mostly static, but we'll flag reflection using dart:mirrors as dynamic uncertainty.
    bool hasDynamic = false;

    for (final directive in unit.directives) {
      if (directive is UriBasedDirective) {
        final uri = directive.uri.stringValue;
        if (uri != null) {
          if (uri == 'dart:mirrors') {
             hasDynamic = true;
          } else if (!uri.startsWith('dart:')) {
             deps.add(uri);
          }
        }
      }
    }

    print(jsonEncode({
      "dependencies": deps,
      "dynamic_imports": hasDynamic
    }));
  } catch (e) {
    // A syntax error could mean uncertain scope, return dynamic_imports: true.
    print(jsonEncode({
      "dependencies": [],
      "dynamic_imports": true
    }));
  }
}
