import 'dart:io';
import 'dart:convert';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:path/path.dart' as p;

void main(List<String> args) {
  if (args.length < 1) {
    print("Usage: dart dart_parser.dart <repo_root>");
    exit(1);
  }
  var repoRoot = args[0];
  var results = {};

  var dir = Directory(repoRoot);
  var dartFiles = dir.listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart'));

  for (var file in dartFiles) {
    var relPath = p.relative(file.path, from: repoRoot);
    if (relPath.contains('.dart_tool')) continue;

    List<String> deps = [];
    bool hasUncertainty = false;

    try {
      var result = parseString(content: file.readAsStringSync(), path: file.path);
      if (result.errors.isNotEmpty) {
        hasUncertainty = true;
      }
      var unit = result.unit;

      for (var directive in unit.directives) {
        if (directive is UriBasedDirective) {
          var uri = directive.uri.stringValue;
          if (uri != null) {
            if (uri == 'dart:mirrors') {
              hasUncertainty = true;
            } else if (!uri.startsWith('dart:') && !uri.startsWith('package:')) {
              var targetPath = p.normalize(p.join(p.dirname(file.path), uri));
              if (File(targetPath).existsSync()) {
                var relTarget = p.relative(targetPath, from: repoRoot);
                deps.add(relTarget);
              }
            }
          }
        }
      }
    } catch (e) {
      hasUncertainty = true;
    }

    results[relPath] = {
      'dependencies': deps,
      'has_uncertainty': hasUncertainty,
    };
  }

  print(jsonEncode(results));
}
