import { readFileSync } from 'node:fs';

export const plain = value => JSON.parse(JSON.stringify(value));

export function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

export function fixture(name) {
  return freeze(JSON.parse(readFileSync(
    new URL(`../fixtures/results/${name}.json`, import.meta.url), 'utf8')));
}
