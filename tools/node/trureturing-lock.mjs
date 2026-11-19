import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const tbook = fileURLToPath(new URL('../../tbook', import.meta.url));
const resolved = new Map();

export function readTrureturingLock(root) {
  const file = join(root, 'trureturing.lock.json');
  if (!existsSync(file)) return null;
  const text = readFileSync(file, 'utf8');
  const lock = JSON.parse(text);
  if (lock.schema !== 'trureturing-books.lock.v1' || Object.hasOwn(lock, 'commit')) return lock;
  const snapshot = process.env.TBOOK_LOCK_SNAPSHOT;
  if (snapshot) {
    const effective = JSON.parse(readFileSync(snapshot, 'utf8'));
    if (!/^[0-9a-f]{40}$/.test(effective.commit) || effective.repo !== lock.repo || effective.branch !== lock.branch) {
      throw new Error('trureturing snapshot does not match the branch lock');
    }
    return effective;
  }
  const key = JSON.stringify([root, text, process.env.TBOOK_TRURETURING_SHA]);
  if (!resolved.has(key)) {
    const output = execFileSync(tbook, ['resolve-lock'], {
      encoding: 'utf8',
      env: { ...process.env, TBOOK_ROOT: root },
      maxBuffer: 16 * 1024 * 1024,
    });
    resolved.set(key, JSON.parse(output));
  }
  return resolved.get(key);
}
