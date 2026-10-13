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

export function sandboxMountOperations({
  workspace,
  runDirectory,
  externalMounts,
  dependencyMounts,
  hiddenDirectories,
  guestWorkspace,
  guestRun,
  markerFile,
  guestMarker,
}) {
  const operations = hiddenDirectories.map((directory) => ({
    type: 'tmpfs',
    path: directory,
    hostMask: true,
  }));
  operations.push(
    { type: 'dir', path: guestWorkspace },
    { type: 'dir', path: guestRun },
    { type: 'bind-fd', source: workspace, target: guestWorkspace },
    { type: 'bind-fd', source: runDirectory, target: guestRun },
  );
  for (const [source, target] of externalMounts)
    operations.push({ type: 'ro-bind-fd', source, target });
  for (const [source, target] of dependencyMounts)
    operations.push({ type: 'ro-bind-fd', source, target });
  operations.push({ type: 'ro-bind-fd', source: markerFile, target: guestMarker });
  return operations;
}

const sensitiveName =
  /^(?:[.]env(?:$|[.](?!example$)[^/]+)|[.]ssh|[.]aws|[.]gnupg|id_(?:rsa|ed25519)|[.]git-credentials|[.]npmrc|[.]pypirc|[.]netrc|[^/]+[.](?:pem|key))$/iu;
const sensitiveCredentialName =
  /^[.]?(?:auth(?:entication)?|tokens?|credentials?|secrets?|private[-_]?keys?|api[-_]?keys?|access[-_]?tokens?|refresh[-_]?tokens?|client[-_]?secrets?)$/iu;
const sensitiveCredentialConfigFile =
  /^[.]?(?:auth(?:entication)?|tokens?|credentials?|secrets?|private[-_]?keys?|api[-_]?keys?|access[-_]?tokens?|refresh[-_]?tokens?|client[-_]?secrets?)[.](?:json|ya?ml|toml|ini|cfg|conf|env(?:[.](?!example$)[^/]+)?|properties|xml|txt)$/iu;
const sensitiveCredentialMaterialFile =
  /^[.]?(?:private[-_]?keys?|api[-_]?keys?|access[-_]?tokens?|refresh[-_]?tokens?|client[-_]?secrets?)[.][^/]+$/iu;
const sourceCodeFile =
  /[.](?:asm|bash|bat|c|cc|cjs|clj|cljs|cljc|cmd|cpp|cs|css|cxx|dart|ex|exs|go|h|hpp|hs|hxx|java|js|jsx|kt|kts|lua|m|mm|mjs|nix|php|pl|ps1|py|r|razor|rb|rs|scala|sh|sol|sql|swift|ts|tsx|vue|zsh)$/iu;

export function isSensitiveCandidatePath(relativePath) {
  const segments = relativePath.replaceAll(String.fromCharCode(92), '/').split('/');
  if (segments.includes('.git') || segments.includes('node_modules'))
    return true;
  if (segments.some((segment) => sensitiveName.test(segment)))
    return true;

  const filename = segments.at(-1) ?? '';
  if (
    sensitiveCredentialName.test(filename) ||
    sensitiveCredentialConfigFile.test(filename) ||
    sensitiveCredentialMaterialFile.test(filename)
  )
    return true;

  const insideCredentialDirectory = segments
    .slice(0, -1)
    .some((segment) => sensitiveCredentialName.test(segment));
  return insideCredentialDirectory && !sourceCodeFile.test(filename);
}
