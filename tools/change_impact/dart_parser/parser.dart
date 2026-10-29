import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/ast/ast.dart';

void main(List<String> args) {
  var results = <String, dynamic>{};

  for (var path in args) {
    try {
      var result = parseFile(
        path: path,
        featureSet: FeatureSet.latestLanguageVersion(),
      );

      var imports = <String>[];
      bool isDynamic = false;

      for (var directive in result.unit.directives) {
        if (directive is UriBasedDirective) {
          if (directive.uri.stringValue != null) {
            var uri = directive.uri.stringValue!;
            imports.add(uri);
            if (uri == 'dart:mirrors') {
              isDynamic = true;
            }
          }
        }
      }

      results[path] = {
        'imports': imports,
        'dynamic': isDynamic
      };
    } catch (e) {
      // Syntax error or missing file
      results[path] = {
        'imports': [],
        'dynamic': false,
        'error': e.toString()
      };
    }
  }

  print(jsonEncode(results));
}
