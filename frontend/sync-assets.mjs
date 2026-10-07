import { cpSync, mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const frontend = dirname(fileURLToPath(import.meta.url));
const target = resolve(frontend, '../src/_frontend');
mkdirSync(target, { recursive: true });
for (const path of ['index.html', 'home.html', 'dashboard.html', 'css', 'js', 'img', 'dist']) {
  rmSync(resolve(target, path), { recursive: true, force: true });
  cpSync(resolve(frontend, path), resolve(target, path), { recursive: true });
}
