import 'dart:io';
import 'dart:convert';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print(jsonEncode({"deps": [], "dynamic": false}));
    return;
  }

  var filePath = args[0];
  try {
    var result = parseFile(path: filePath, featureSet: null);
    var unit = result.unit;

    var deps = <String>[];
    var isDynamic = false;

    for (var directive in unit.directives) {
      if (directive is ImportDirective) {
        var uri = directive.uri.stringValue;
        if (uri != null) {
          deps.add(uri);
        }
      } else if (directive is ExportDirective) {
        var uri = directive.uri.stringValue;
        if (uri != null) {
          deps.add(uri);
        }
      } else if (directive is PartDirective) {
        var uri = directive.uri.stringValue;
        if (uri != null) {
          deps.add(uri);
        }
      }
    }

    // Simple dynamic check: eval, etc. usually not in Dart, but let's check for dart:mirrors usage
    for (var directive in unit.directives) {
      if (directive is ImportDirective) {
        if (directive.uri.stringValue == 'dart:mirrors') {
          isDynamic = true;
        }
      }
    }

    print(jsonEncode({"deps": deps, "dynamic": isDynamic}));
  } catch (e) {
    print(jsonEncode({"deps": [], "dynamic": true}));
  }
}
