import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/ast/ast.dart';

void main(List<String> args) {
  if (args.isEmpty) return;

  bool isBatch = args[0] == '--batch';
  List<String> filesToParse = isBatch ? args.sublist(1) : args;

  Map<String, dynamic> results = {};

  for (final path in filesToParse) {
    try {
      final result = parseFile(path: path, featureSet: FeatureSet.latestLanguageVersion());
      final unit = result.unit;
      final imports = <String>[];
      for (final directive in unit.directives) {
        if (directive is ImportDirective) {
          imports.add(directive.uri.stringValue ?? "");
        } else if (directive is ExportDirective) {
          imports.add(directive.uri.stringValue ?? "");
        }
      }
      results[path] = {"imports": imports};
    } catch (e) {
      results[path] = {"error": e.toString()};
    }
  }

  if (isBatch) {
    print(jsonEncode(results));
  } else {
    print(jsonEncode(results.values.first));
  }
}
