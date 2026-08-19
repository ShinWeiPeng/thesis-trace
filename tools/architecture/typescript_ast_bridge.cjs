"use strict";

const fs = require("fs");
const path = require("path");

function fail(message) {
  process.stderr.write(String(message) + "\n");
  process.exit(2);
}

const compilerPath = process.argv[2];
if (!compilerPath) fail("TypeScript compiler path is required");

let ts;
try {
  ts = require(compilerPath);
} catch (error) {
  fail(`cannot load TypeScript compiler API: ${error.message}`);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(0, "utf8"));
} catch (error) {
  fail(`invalid analyzer request: ${error.message}`);
}

function scriptKind(file) {
  return file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
}

function bindingNames(name, result) {
  if (ts.isIdentifier(name)) {
    result.add(name.text);
    return;
  }
  for (const element of name.elements || []) {
    if (!ts.isOmittedExpression(element)) bindingNames(element.name, result);
  }
}

const output = { version: ts.version, files: [] };
for (const relative of input.files || []) {
  const absolute = path.join(input.project_root, relative);
  let sourceText;
  try {
    sourceText = fs.readFileSync(absolute, "utf8");
  } catch (error) {
    output.files.push({ path: relative, errors: [`cannot read source: ${error.message}`], types: [], symbols: [] });
    continue;
  }
  const source = ts.createSourceFile(relative, sourceText, ts.ScriptTarget.Latest, true, scriptKind(relative));
  const errors = source.parseDiagnostics.map((diagnostic) => {
    const position = source.getLineAndCharacterOfPosition(diagnostic.start || 0);
    const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, " ");
    return `${position.line + 1}:${position.character + 1}: ${message}`;
  });
  const types = [];
  const symbols = new Set();
  for (const statement of source.statements) {
    if (
      ts.isInterfaceDeclaration(statement) ||
      ts.isTypeAliasDeclaration(statement) ||
      ts.isClassDeclaration(statement) ||
      ts.isEnumDeclaration(statement)
    ) {
      if (!statement.name) {
        errors.push("anonymous top-level type declaration cannot be cataloged");
      } else {
        const kind = ts.isInterfaceDeclaration(statement) ? "interface"
          : ts.isTypeAliasDeclaration(statement) ? "alias"
          : ts.isClassDeclaration(statement) ? "class" : "enum";
        types.push({ symbol: statement.name.text, kind });
        symbols.add(statement.name.text);
      }
    } else if (ts.isFunctionDeclaration(statement) && statement.name) {
      symbols.add(statement.name.text);
    } else if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        bindingNames(declaration.name, symbols);
      }
    } else if (ts.isModuleDeclaration(statement) && statement.name) {
      symbols.add(statement.name.text);
    }
  }
  output.files.push({ path: relative, errors, types, symbols: Array.from(symbols).sort() });
}

process.stdout.write(JSON.stringify(output));
