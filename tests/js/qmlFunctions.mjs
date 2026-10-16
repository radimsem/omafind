import { readFileSync } from 'node:fs';
import vm from 'node:vm';

export function qmlSource(file) {
  return readFileSync(new URL(`../../ui/${file}`, import.meta.url), 'utf8');
}

// Runs the top-level functions of ui/<file> in a context holding `values`. The values are assigned
// again afterwards, so a value replaces a QML function of the same name. `root` is the context.
export function qmlFunctions(file, values = {}) {
  const ctx = vm.createContext({ ...values });
  const source = qmlSource(file);
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  Object.assign(ctx, values);
  ctx.root = ctx;
  return { ctx, source };
}
