// The sandbox policy describes Linux paths even when its contract runs on Windows.
import path from 'node:path/posix';

export const HOST_PATHS_TO_HIDE = Object.freeze([
  '/etc',
  '/home',
  '/root',
  '/run',
  '/var',
  '/tmp',
  '/sys',
  '/media',
  '/mnt',
  '/srv',
  '/workspace',
  '/workspaces',
  '/data',
  '/backup',
  '/backups',
  '/volumes',
  '/secrets',
  '/credentials',
]);

const workspaceDirectoryNames = new Set([
  'workspace',
  'workspaces',
  'work',
  'projects',
  'repositories',
  'repos',
  'code',
]);

const systemRootDirectoryNames = new Set([
  'bin',
  'boot',
  'dev',
  'etc',
  'home',
  'lib',
  'lib32',
  'lib64',
  'media',
  'mnt',
  'opt',
  'proc',
  'root',
  'run',
  'sbin',
  'srv',
  'sys',
  'tmp',
  'usr',
  'var',
]);

function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative === '' ||
    (relative !== '..' &&
      !relative.startsWith(`..${path.sep}`) &&
      !path.isAbsolute(relative))
  );
}

function checkoutMaskRoot(checkout) {
  const filesystemRoot = path.parse(checkout).root;
  const segments = checkout
    .slice(filesystemRoot.length)
    .split(path.sep)
    .filter(Boolean);
  const workspaceIndex = segments.slice(0, -1).findIndex((segment) =>
    workspaceDirectoryNames.has(segment.toLowerCase())
  );
  if (workspaceIndex !== -1)
    return path.join(filesystemRoot, ...segments.slice(0, workspaceIndex + 1));

  const topLevel = segments[0];
  if (topLevel && !systemRootDirectoryNames.has(topLevel.toLowerCase()))
    return path.join(filesystemRoot, topLevel);

  const parent = path.dirname(checkout);
  return parent === filesystemRoot ? checkout : parent;
}

export function hostPathsToHide(sourceRoot) {
  const checkout = path.resolve(sourceRoot);
  const filesystemRoot = path.parse(checkout).root;
  if (checkout === filesystemRoot)
    throw new Error('The candidate checkout cannot be the filesystem root.');

  if (HOST_PATHS_TO_HIDE.some((directory) => isWithin(directory, checkout)))
    return [...HOST_PATHS_TO_HIDE];

  return [
    ...HOST_PATHS_TO_HIDE,
    checkoutMaskRoot(checkout),
  ];
}
