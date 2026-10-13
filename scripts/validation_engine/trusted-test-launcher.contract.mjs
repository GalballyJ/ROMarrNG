// Copyright (c) snapetech and SeerrNG contributors.
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import {
  HOST_PATHS_TO_HIDE,
  hostPathsToHide,
} from './trusted-test-sandbox-policy.mjs';

const launcher = fileURLToPath(
  new URL(
    './trusted-test-launcher.mjs',
    import.meta.url
  )
);
for (const hostPath of ['/etc', '/srv'])
  assert.ok(
    HOST_PATHS_TO_HIDE.includes(hostPath),
    'the sandbox must hide host path ' + hostPath
  );
const bwrap = ['/usr/bin/bwrap', '/bin/bwrap'].find(existsSync);
const sandboxAvailable = (() => {
  if (process.platform !== 'linux' || !bwrap) return false;
  return (
    spawnSync(
      bwrap,
      [
        '--die-with-parent',
        '--unshare-user',
        '--ro-bind',
        '/',
        '/',
        '--',
        '/bin/true',
      ],
      { stdio: 'ignore', timeout: 5_000 }
    ).status === 0
  );
})();
const nestedSandboxAvailable = (() => {
  if (!sandboxAvailable) return false;
  const result = spawnSync(
    bwrap,
    [
      '--die-with-parent',
      '--unshare-user',
      '--ro-bind',
      '/',
      '/',
      '--dev',
      '/dev',
      '--proc',
      '/proc',
      '--tmpfs',
      '/tmp',
      '--',
      bwrap,
      '--die-with-parent',
      '--unshare-user',
      '--ro-bind',
      '/',
      '/',
      '--',
      '/bin/true',
    ],
    { stdio: 'ignore', timeout: 5_000 }
  );
  return result.status === 0;
})();

test(
  'trusted launcher contains import-time candidate code before it runs',
  { skip: !sandboxAvailable && 'bubblewrap user namespaces are unavailable' },
  async (t) => {
    const parent = mkdtempSync(
      path.join(tmpdir(), 'trusted-validation-launcher-')
    );
    const source = path.join(parent, 'candidate');
    const hostFile = path.join(parent, 'host-canary.txt');
    const browserCache = path.join(parent, 'playwright-cache');
    const outsideDependencies = path.join(parent, 'outside-dependencies');
    const hostSocket = path.join('/tmp', `rv-${process.pid}.sock`);
    const candidateWrite = path.join(source, 'launcher-write-canary.txt');
    mkdirSync(path.join(source, 'bin'), { recursive: true });
    mkdirSync(browserCache, { recursive: true });
    mkdirSync(outsideDependencies, { recursive: true });
    const tcpServer = createServer();
    tcpServer.listen(0, '127.0.0.1');
    await once(tcpServer, 'listening');
    const socketServer = createServer();
    socketServer.listen(hostSocket);
    await once(socketServer, 'listening');
    t.after(async () => {
      if (tcpServer.listening)
        await new Promise((resolve) => tcpServer.close(resolve));
      if (socketServer.listening)
        await new Promise((resolve) => socketServer.close(resolve));
      rmSync(hostSocket, { force: true });
      rmSync(parent, { recursive: true, force: true });
    });
    mkdirSync(path.join(source, 'nested/config'), { recursive: true });
    writeFileSync(hostFile, 'host canary stays unchanged');
    writeFileSync(path.join(browserCache, 'browser-canary.txt'), 'read-only browser');
    writeFileSync(path.join(source, '.gitignore'), 'node_modules/\n');
    writeFileSync(path.join(source, '.env'), 'PRIVATE_ENV_CANARY=hidden\n');
    writeFileSync(path.join(source, 'config.json'), '{"private":true}\n');
    writeFileSync(
      path.join(source, 'nested/.env.local'),
      'NESTED_ENV_CANARY=hidden\n'
    );
    writeFileSync(
      path.join(source, 'nested/config/secrets.json'),
      '{"secret":"hidden"}\n'
    );
    writeFileSync(path.join(source, 'auth.json'), '{"token":"private"}\n');
    writeFileSync(path.join(source, 'token.json'), '{"token":"private"}\n');
    writeFileSync(path.join(source, 'auth.py'), 'AUTH_MODULE = True\n');
    writeFileSync(path.join(source, 'credentials.py'), 'CREDENTIALS_MODULE = True\n');
    mkdirSync(path.join(source, 'node_modules'), { recursive: true });
    writeFileSync(
      path.join(source, 'node_modules/marker.txt'),
      'read-only dependency'
    );
    mkdirSync(path.join(source, 'node_modules/fixture-dependency'));
    writeFileSync(
      path.join(source, 'node_modules/fixture-dependency/package.json'),
      '{"name":"fixture-dependency","type":"module","exports":"./index.js"}\n'
    );
    writeFileSync(
      path.join(source, 'node_modules/fixture-dependency/index.js'),
      'export default "sibling dependency resolved";\n'
    );
    writeFileSync(
      path.join(source, 'bin/run-local-validation.mjs'),
      `import assert from 'node:assert/strict';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import fixtureDependency from 'fixture-dependency';
const hostFile = ${JSON.stringify(hostFile)};
const hostSocket = ${JSON.stringify(hostSocket)};
const hostPort = ${tcpServer.address().port};
assert.throws(() => readFileSync(hostFile), { code: 'ENOENT' });
assert.equal(process.env.SECRET_CANARY, undefined);
assert.equal(existsSync('/mnt/workspace/.env'), false);
assert.equal(existsSync('/mnt/workspace/config.json'), true);
assert.equal(existsSync('/mnt/workspace/nested/config/operator.json'), false);
assert.equal(existsSync('/mnt/workspace/auth.json'), false);
assert.equal(existsSync('/mnt/workspace/token.json'), false);
assert.equal(existsSync('/mnt/workspace/auth.py'), true);
assert.equal(existsSync('/mnt/workspace/credentials.py'), true);
assert.equal(existsSync('/etc/os-release'), false);
const originalCheckout = ${JSON.stringify(source)};
assert.throws(() => readFileSync(path.join(originalCheckout, 'auth.json')), { code: 'ENOENT' });
assert.equal(existsSync('/mnt/workspace/nested/.env.local'), false);
assert.equal(existsSync('/mnt/workspace/nested/config/secrets.json'), false);
assert.throws(() => writeFileSync(hostFile, 'escaped'));
assert.equal(readFileSync('/run/validation-engine-sandbox', 'utf8'), process.env.VALIDATION_OUTER_SANDBOX_TOKEN);
assert.equal(fixtureDependency, 'sibling dependency resolved');
const connectionResults = await Promise.all([
  new Promise((resolve) => { const socket = net.connect(hostPort, '127.0.0.1'); socket.once('connect', () => { socket.destroy(); resolve('connected'); }); socket.once('error', () => resolve('blocked')); socket.setTimeout(1000, () => { socket.destroy(); resolve('blocked'); }); }),
  new Promise((resolve) => { const socket = net.createConnection(hostSocket); socket.once('connect', () => { socket.destroy(); resolve('connected'); }); socket.once('error', () => resolve('blocked')); socket.setTimeout(1000, () => { socket.destroy(); resolve('blocked'); }); }),
]);
assert.deepEqual(connectionResults, ['blocked', 'blocked']);
assert.equal(readFileSync(path.join(process.env.PLAYWRIGHT_BROWSERS_PATH, 'browser-canary.txt'), 'utf8'), 'read-only browser');
assert.throws(() => writeFileSync(path.join(process.env.PLAYWRIGHT_BROWSERS_PATH, 'browser-canary.txt'), 'changed'));
writeFileSync('/mnt/workspace/launcher-write-canary.txt', 'candidate only');
assert.equal(readFileSync('/mnt/workspace/node_modules/marker.txt', 'utf8'), 'read-only dependency');
assert.throws(() => writeFileSync('/mnt/workspace/node_modules/marker.txt', 'changed'));
`
    );
    execFileSync('git', ['init', '--quiet', '--initial-branch=main'], {
      cwd: source,
    });
    execFileSync('git', ['config', 'user.name', 'Fixture'], { cwd: source });
    execFileSync('git', ['config', 'user.email', 'fixture@example.invalid'], {
      cwd: source,
    });
    execFileSync('git', ['add', '--all'], { cwd: source });
    execFileSync('git', ['commit', '--quiet', '-m', 'Fixture'], {
      cwd: source,
    });
    mkdirSync(path.join(source, 'nested/config'), { recursive: true });
    writeFileSync(
      path.join(source, 'nested/config/operator.json'),
      '{"private":true}\n'
    );

    const result = spawnSync(
      process.execPath,
      [
        launcher,
        source,
        '--playwright-cache',
        browserCache,
        '--',
        process.execPath,
        'bin/run-local-validation.mjs',
      ],
      {
        encoding: 'utf8',
        env: { ...process.env, SECRET_CANARY: 'must-not-be-inherited' },
        timeout: 30_000,
      }
    );
    assert.equal(result.error, undefined, result.error?.message);
    assert.equal(
      result.status,
      0,
      `${result.stdout ?? ''}${result.stderr ?? ''}`
    );
    assert.equal(readFileSync(hostFile, 'utf8'), 'host canary stays unchanged');
    assert.equal(existsSync(candidateWrite), false);

    rmSync(path.join(source, 'node_modules'), { recursive: true, force: true });
    symlinkSync(outsideDependencies, path.join(source, 'node_modules'), 'dir');
    const linkedDependencyResult = spawnSync(
      process.execPath,
      [launcher, source, '--', process.execPath, '-e', 'process.exit(99)'],
      { encoding: 'utf8', timeout: 30_000 }
    );
    assert.equal(linkedDependencyResult.error, undefined);
    assert.equal(linkedDependencyResult.status, 1);
    assert.match(
      linkedDependencyResult.stderr,
      /Installed dependency path must be a real directory/u
    );
  }
);

test(
  'trusted launcher hides checkout and sibling data outside common masks',
  {
    skip:
      !nestedSandboxAvailable ||
      !existsSync('/usr/local/share')
        ? 'nested bubblewrap user namespaces or /usr/local/share are unavailable'
        : false,
  },
  (t) => {
    const parent = mkdtempSync(
      path.join(tmpdir(), 'trusted-validation-source-mask-')
    );
    const source = path.join(parent, 'source');
    const sibling = path.join(parent, 'sibling');
    const workspaceRoot = '/usr/local/share/workspaces';
    const virtualRoot = `${workspaceRoot}/romarrng-${path.basename(parent)}`;
    const virtualSibling = `${workspaceRoot}/other-project-${path.basename(parent)}`;
    const sourceAlias = '/tmp/candidate-checkout';
    mkdirSync(source, { recursive: true });
    mkdirSync(sibling, { recursive: true });
    writeFileSync(path.join(source, 'README.md'), 'safe candidate content\n');
    writeFileSync(path.join(source, '.env'), 'PRIVATE_SOURCE_CANARY=hidden\n');
    writeFileSync(path.join(source, 'secrets.json'), '{"secret":"hidden"}\n');
    writeFileSync(path.join(sibling, '.env'), 'PRIVATE_SIBLING_CANARY=hidden\n');
    execFileSync('git', ['init', '--quiet', '--initial-branch=main'], {
      cwd: source,
    });
    execFileSync('git', ['config', 'user.name', 'Fixture'], { cwd: source });
    execFileSync('git', ['config', 'user.email', 'fixture@example.invalid'], {
      cwd: source,
    });
    execFileSync('git', ['add', '--all'], { cwd: source });
    execFileSync('git', ['commit', '--quiet', '-m', 'Source mask fixture'], {
      cwd: source,
    });
    t.after(() => rmSync(parent, { recursive: true, force: true }));

    const candidate = `
      import assert from 'node:assert/strict';
      import { readFileSync } from 'node:fs';
      import path from 'node:path';
      const source = ${JSON.stringify(virtualRoot)};
      for (const file of ['.env', 'secrets.json', '.git/config']) {
        assert.throws(() => readFileSync(path.join(source, file)), {
          code: 'ENOENT',
        });
      }
      assert.throws(
        () => readFileSync(${JSON.stringify(`${virtualSibling}/.env`)}),
        { code: 'ENOENT' }
      );
    `;
    const result = spawnSync(
      bwrap,
      [
        '--die-with-parent',
        '--unshare-user',
        '--ro-bind',
        '/',
        '/',
        '--tmpfs',
        '/usr/local/share',
        '--dir',
        workspaceRoot,
        '--dir',
        virtualRoot,
        '--dir',
        virtualSibling,
        '--bind',
        source,
        virtualRoot,
        '--bind',
        sibling,
        virtualSibling,
        '--dev',
        '/dev',
        '--proc',
        '/proc',
        '--tmpfs',
        '/tmp',
        '--symlink',
        virtualRoot,
        sourceAlias,
        '--setenv',
        'TMPDIR',
        '/tmp',
        '--',
        process.execPath,
        launcher,
        sourceAlias,
        '--',
        process.execPath,
        '-e',
        candidate,
      ],
      { encoding: 'utf8', timeout: 30_000 }
    );
    assert.equal(result.error, undefined, result.error?.message);
    assert.equal(
      result.status,
      0,
      `${result.stdout ?? ''}${result.stderr ?? ''}`
    );
  }
);

test('sandbox masks standard and checkout host roots', () => {
  assert.ok(HOST_PATHS_TO_HIDE.includes('/etc'));
  assert.ok(hostPathsToHide('/projects/ROMarrNG').includes('/projects'));
  const nestedCheckout = hostPathsToHide('/projects/team/work/ROMarrNG');
  assert.ok(nestedCheckout.includes('/projects'));
  assert.ok(!nestedCheckout.includes('/projects/team'));
  const localCheckout = hostPathsToHide(
    '/usr/local/share/workspaces/ROMarrNG'
  );
  assert.ok(localCheckout.includes('/usr/local/share/workspaces'));
  assert.ok(!localCheckout.includes('/usr/local'));
  assert.ok(!localCheckout.includes('/opt'));
  assert.ok(hostPathsToHide('/ROMarrNG').includes('/ROMarrNG'));
  assert.equal(
    hostPathsToHide('/home/keith/ROMarrNG').includes('/home/keith'),
    false
  );
  assert.throws(() => hostPathsToHide('/'), /cannot be the filesystem root/u);
});
