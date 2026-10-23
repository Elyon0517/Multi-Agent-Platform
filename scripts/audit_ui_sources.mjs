// Compare implementation tokens against supplied, locally checked-out source snapshots.
// This is a regression aid, not a legal originality determination.
import { readFileSync, readdirSync } from 'node:fs';
import { resolve, relative, extname } from 'node:path';
import { createHash } from 'node:crypto';
import ts from '../ui/node_modules/typescript/lib/typescript.js';

const production = resolve('ui/src');
const references = process.argv.slice(2).map(path => resolve(path));
if (!references.length) throw new Error('Supply reference source directories; see docs/UI_REPLACEMENT.md');
const windowSize = 120;
function files(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    const path = resolve(root, entry.name);
    if (entry.isDirectory()) return ['node_modules','.git','__tests__','tests','test'].includes(entry.name) ? [] : files(path);
    return ['.ts','.tsx','.css'].includes(extname(path)) && !/\.(?:test|spec)\./.test(path) && !path.endsWith('.d.ts') ? [path] : [];
  });
}
function implementation(path) {
  let source = readFileSync(path, 'utf8');
  if (extname(path) !== '.css') {
    const ast = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
    // Interoperable type signatures and imports are not implementation bodies.
    const ranges = ast.statements.filter(node => ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) ||
      ts.isImportDeclaration(node) || ts.isExportDeclaration(node)).map(node => [node.pos,node.end]);
    for (const [start,end] of ranges.reverse()) source = source.slice(0,start) + ' '.repeat(end-start) + source.slice(end);
  }
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, ts.LanguageVariant.JSX, source);
  const tokens = [];
  for (let kind = scanner.scan(); kind !== ts.SyntaxKind.EndOfFileToken; kind = scanner.scan()) {
    tokens.push({ value: scanner.getTokenText(), offset: scanner.getTokenPos() });
  }
  return { source: readFileSync(path,'utf8'), tokens };
}
const hash = tokens => createHash('sha256').update(tokens.map(t => t.value).join('\u001f')).digest('hex');
const candidates = new Map();
const localFiles = files(production);
for (const path of localFiles) {
  const { tokens, source } = implementation(path);
  for (let start = 0; start + windowSize <= tokens.length; start++) {
    const key = hash(tokens.slice(start,start+windowSize));
    candidates.set(key, { path: relative(process.cwd(),path), line: source.slice(0,tokens[start].offset).split('\n').length });
  }
}
const findings = new Map();
let referenceCount = 0;
for (const root of references) for (const path of files(root)) {
  referenceCount++;
  const { tokens } = implementation(path);
  for (let start = 0; start + windowSize <= tokens.length; start++) {
    const match = candidates.get(hash(tokens.slice(start,start+windowSize)));
    if (match) findings.set(match.path, { ...match, reference: relative(root,path) });
  }
}
console.log(JSON.stringify({ productionFiles: localFiles.length, referenceFiles: referenceCount,
  minimumConsecutiveTokens: windowSize, findings: [...findings.values()] },null,2));
if (findings.size) process.exitCode = 1;
