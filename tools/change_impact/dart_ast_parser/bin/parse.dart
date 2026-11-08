import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/ast/ast.dart';

void main() async {
  // Read array of file paths from stdin
  String input = await stdin.transform(utf8.decoder).join();
  if (input.trim().isEmpty) {
    print(jsonEncode({'error': 'No input provided'}));
    exit(1);
  }

  List<dynamic> files = [];
  try {
    files = jsonDecode(input);
  } catch (e) {
    print(jsonEncode({'error': 'Invalid JSON'}));
    exit(1);
  }

  Map<String, dynamic> results = {};

  for (String path in files) {
    try {
      var result = parseFile(path: path, featureSet: FeatureSet.latestLanguageVersion());
      var unit = result.unit;
      var imports = <String>[];
      var exports = <String>[];
      bool hasDynamic = false;

      for (var directive in unit.directives) {
        if (directive is ImportDirective) {
          var uri = directive.uri.stringValue;
          if (uri != null) {
            imports.add(uri);
            if (uri == 'dart:mirrors' || uri == 'dart:isolate') {
              hasDynamic = true;
            }
          }
        } else if (directive is ExportDirective) {
          var uri = directive.uri.stringValue;
          if (uri != null) {
            exports.add(uri);
          }
        }
      }

      results[path] = {
        'imports': imports,
        'exports': exports,
        'has_dynamic': hasDynamic,
        'error': null
      };
    } catch (e) {
      results[path] = {
        'imports': [],
        'exports': [],
        'has_dynamic': false,
        'error': e.toString()
      };
    }
  }

  print(jsonEncode(results));
}
