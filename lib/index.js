import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

export const name = 'rtlens-dsh';
export const PACKAGE_NAME = 'rtlens-dsh';

/** DSH profile 下解析本包的 skills 根目录（供 skill provider 使用）。 */
export function resolveRtlensSkillRoot(profileBaseUrl) {
  const pkg = resolvePackageRoot(profileBaseUrl);
  return join(pkg, 'skills');
}

/** DSH profile 下解析本包根目录 —— 即 `python -m rtlens` 的工作目录（rtlens/ Python 包在此）。 */
export function resolveRtlensCliRoot(profileBaseUrl) {
  return resolvePackageRoot(profileBaseUrl);
}

function resolvePackageRoot(profileBaseUrl) {
  if (!profileBaseUrl) {
    throw new Error('rtlens-dsh: missing DSH profile baseUrl for package resolution');
  }
  let manifestPath;
  try {
    manifestPath = createRequire(profileBaseUrl).resolve(`${PACKAGE_NAME}/package.json`);
  } catch (error) {
    throw new Error(
      `rtlens-dsh: cannot resolve ${PACKAGE_NAME}/package.json from the DSH profile`,
      { cause: error },
    );
  }
  return dirname(manifestPath);
}
