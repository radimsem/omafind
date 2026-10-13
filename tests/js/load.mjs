import { readFileSync } from 'node:fs';
import vm from 'node:vm';

export function load(...names) {
  const context = vm.createContext({});
  for (const name of names) {
    const source = readFileSync(new URL(`../../lib/${name}`, import.meta.url), 'utf8')
      .split('\n').filter(line => !line.startsWith('.pragma') && !line.startsWith('.import'))
      .join('\n');
    vm.runInContext(source, context, { filename: name });
  }
  return context;
}
