import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const root = path.dirname(new URL(import.meta.url).pathname).replace(/^\//, '').replace(/^([A-Za-z]):/, '$1:');
const files = fs.readdirSync(root)
  .filter((name) => name.endsWith('.test.mjs'))
  .sort();

for (const file of files) {
  const result = spawnSync(process.execPath, ['--test', '--test-concurrency=1', file], {
    cwd: root,
    stdio: 'inherit',
    env: process.env,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
