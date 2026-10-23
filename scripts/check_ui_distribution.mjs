import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
const root = resolve(import.meta.dirname,'../ui/dist');
const notice = readFileSync(resolve(root,'THIRD_PARTY_NOTICES.txt'),'utf8');
const packages = readFileSync(resolve(root,'DEPENDENCY_LICENSES.md'),'utf8');
for (const author of ['Cody','Inter Project Authors','JetBrains']) if (!notice.includes(author))
  throw new Error(`Font attribution missing: ${author}`);
for (const name of ['react','pixi.js']) if (!packages.toLowerCase().includes(name))
  throw new Error(`Dependency license missing: ${name}`);
const retired = /munder-difflin|chaitanyagiri|shahar061|the-office|limezu|brooklyn99|dunder/i;
let checked = 0;
function walk(path) {
  for (const entry of readdirSync(path,{ withFileTypes: true })) {
    const file = resolve(path,entry.name);
    if (entry.isDirectory()) walk(file);
    else if (/\.(?:js|css|html|md|txt|svg|json)$/.test(file)) {
      checked++;
      if (retired.test(readFileSync(file,'utf8'))) throw new Error(`Retired source/asset reference in ${file}`);
    }
  }
}
walk(root);
console.log(`Verified ${checked} distribution files, current font notices and bundled dependency licenses.`);
