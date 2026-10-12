import { readFileSync } from 'node:fs';
import vm from 'node:vm';

export function load(name) {
  const source = readFileSync(new URL(`../../lib/${name}`, import.meta.url), 'utf8')
    .split('\n').filter(line => !line.startsWith('.pragma') && !line.startsWith('.import'))
    .join('\n');
  const context = vm.createContext({});
  vm.runInContext(source, context, { filename: name });
  return context;
}
