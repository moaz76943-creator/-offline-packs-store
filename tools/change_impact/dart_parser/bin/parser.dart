import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/analysis/features.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print(jsonEncode({'error': 'No file path provided'}));
    exit(1);
  }

  final filePath = args[0];
  final file = File(filePath);

  if (!file.existsSync()) {
    print(jsonEncode({'error': 'File not found'}));
    exit(1);
  }

  try {
    final result = parseFile(
      path: filePath,
      featureSet: FeatureSet.latestLanguageVersion(),
    );

    final imports = <String>[];
    final exports = <String>[];
    bool hasDynamic = false;

    // Check for syntax errors
    if (result.errors.isNotEmpty) {
      final errors = result.errors.map((e) => e.message).toList();
      print(jsonEncode({
        'errors': errors,
      }));
      exit(0);
    }

    final unit = result.unit;

    for (final directive in unit.directives) {
      if (directive is ImportDirective) {
        final uri = directive.uri.stringValue;
        if (uri != null) {
          imports.add(uri);
          if (uri == 'dart:mirrors' || uri.contains('dart:isolate')) {
             hasDynamic = true;
          }
        }
      } else if (directive is ExportDirective) {
         final uri = directive.uri.stringValue;
         if (uri != null) {
           exports.add(uri);
         }
      }
    }

    print(jsonEncode({
      'imports': imports,
      'exports': exports,
      'has_dynamic': hasDynamic,
    }));
  } catch (e) {
    print(jsonEncode({'error': e.toString()}));
    exit(1);
  }
}
