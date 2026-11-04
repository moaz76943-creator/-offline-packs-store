import 'dart:convert';
import 'dart:io';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/analysis/features.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    print('BLOCKED: Missing parser capability');
    exit(1);
  }

  final String filePath = args[0];

  try {
    final file = File(filePath);
    if (!file.existsSync()) {
       print(jsonEncode([]));
       return;
    }
    final content = file.readAsStringSync();

    // Test if parsing capabilities are available. If something fundamental fails, we catch it.
    final result = parseString(
      content: content,
      featureSet: FeatureSet.latestLanguageVersion(),
      throwIfDiagnostics: false,
    );

    final imports = <String>[];
    for (final directive in result.unit.directives) {
      if (directive is UriBasedDirective) {
        final uri = directive.uri.stringValue;
        if (uri != null) {
          String resolvedUri = uri;
          if (uri.startsWith('package:')) {
             // Resolve package:foo/bar.dart -> lib/bar.dart
             final parts = uri.substring('package:'.length).split('/');
             if (parts.length > 1) {
               final packagePath = parts.sublist(1).join('/');
               resolvedUri = 'lib/$packagePath';
             }
          }
          imports.add(resolvedUri);
        }
      }
    }

    print(jsonEncode(imports));
  } catch (e) {
    print('BLOCKED: Missing parser capability');
    exit(1);
  }
}
