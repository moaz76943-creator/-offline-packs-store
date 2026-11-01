import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print(jsonEncode({'error': 'Missing file path'}));
    exit(1);
  }

  final filePath = args[0];
  final file = File(filePath);

  if (!file.existsSync()) {
    print(jsonEncode({'error': 'File not found', 'uncertain': true}));
    exit(0);
  }

  try {
    final content = file.readAsStringSync();
    final result = parseString(content: content, throwIfDiagnostics: false);

    bool uncertain = result.errors.isNotEmpty;

    final deps = <String>[];

    for (final directive in result.unit.directives) {
      if (directive is UriBasedDirective) {
        final uri = directive.uri.stringValue;
        if (uri != null) {
          deps.add(uri);
        }
      }
    }

    // Check for "dart:mirrors" or dynamic-like imports?
    if (deps.any((d) => d == 'dart:mirrors')) {
      uncertain = true;
    }

    print(jsonEncode({
      'dependencies': deps,
      'uncertain': uncertain,
    }));
  } catch (e) {
    print(jsonEncode({
      'dependencies': [],
      'uncertain': true,
      'error': e.toString(),
    }));
  }
}
