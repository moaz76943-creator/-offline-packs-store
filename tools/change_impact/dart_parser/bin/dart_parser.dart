import 'dart:convert';
import 'dart:io';

import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/ast/ast.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print(jsonEncode({"error": "No file provided"}));
    exit(1);
  }

  var filePath = args[0];
  var file = File(filePath);
  if (!file.existsSync()) {
    print(jsonEncode({"error": "File not found"}));
    exit(1);
  }

  try {
    var result = parseFile(path: filePath, featureSet: FeatureSet.latestLanguageVersion());
    var unit = result.unit;

    var deps = <String>{};
    bool hasDynamic = false;

    for (var directive in unit.directives) {
      if (directive is UriBasedDirective) {
        var uri = directive.uri.stringValue;
        if (uri != null) {
          deps.add(uri);
        }
      }
    }

    // Check for reflection (dart:mirrors)
    if (deps.contains('dart:mirrors')) {
      hasDynamic = true;
    }

    print(jsonEncode({
      "dependencies": deps.toList(),
      "dynamic": hasDynamic
    }));
  } catch (e) {
    print(jsonEncode({"error": e.toString()}));
    exit(1);
  }
}
