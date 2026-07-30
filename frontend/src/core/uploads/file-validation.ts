import type { UploadLimits } from "./api";

const MACOS_APP_BUNDLE_CONTENT_TYPES = new Set([
  "",
  "application/octet-stream",
]);

/** 浏览器无法直接上传苹果系统应用包目录时显示的提示文本。 */
export const MACOS_APP_BUNDLE_UPLOAD_MESSAGE =
  "macOS .app bundles can't be uploaded directly from the browser. Compress the app as a .zip or upload the .dmg instead.";

/** 判断文件是否可能是苹果系统应用包目录的占位上传项。 */
export function isLikelyMacOSAppBundle(file: Pick<File, "name" | "type">) {
  return (
    file.name.toLowerCase().endsWith(".app") &&
    MACOS_APP_BUNDLE_CONTENT_TYPES.has(file.type)
  );
}

/** 将待上传文件拆分为可接受与不支持的两组。 */
export function splitUnsupportedUploadFiles(fileList: File[] | FileList) {
  const incoming = Array.from(fileList);
  const accepted: File[] = [];
  const rejected: File[] = [];

  for (const file of incoming) {
    if (isLikelyMacOSAppBundle(file)) {
      rejected.push(file);
      continue;
    }
    accepted.push(file);
  }

  return {
    accepted,
    rejected,
    message: rejected.length > 0 ? MACOS_APP_BUNDLE_UPLOAD_MESSAGE : undefined,
  };
}

/** 上传限制违反的分类编码，与网关限制字段对应。 */
export type UploadLimitViolationCode =
  | "max_file_size"
  | "max_files"
  | "max_total_size";

/** 一类上传限制违反及受影响文件。 */
export interface UploadLimitViolation {
  code: UploadLimitViolationCode;
  files: File[];
  limit: number;
}

/** 客户端预校验后允许上传与拒绝上传的文件集合。 */
export interface UploadLimitValidationResult {
  accepted: File[];
  rejected: File[];
  violations: UploadLimitViolation[];
}

/** 按网关强制执行的单次请求限制校验文件；既有文件优先，待选文件按选择顺序接纳。 */
export function validateUploadLimits(
  existingFiles: File[],
  incomingFiles: File[] | FileList,
  limits?: UploadLimits,
): UploadLimitValidationResult {
  const incoming = Array.from(incomingFiles);
  if (!limits) {
    return { accepted: incoming, rejected: [], violations: [] };
  }

  let fileCount = existingFiles.length;
  let totalSize = existingFiles.reduce((total, file) => total + file.size, 0);
  const accepted: File[] = [];
  const rejectedByCode: Record<UploadLimitViolationCode, File[]> = {
    max_file_size: [],
    max_files: [],
    max_total_size: [],
  };

  for (const file of incoming) {
    if (file.size > limits.max_file_size) {
      rejectedByCode.max_file_size.push(file);
      continue;
    }
    if (fileCount >= limits.max_files) {
      rejectedByCode.max_files.push(file);
      continue;
    }
    if (totalSize + file.size > limits.max_total_size) {
      rejectedByCode.max_total_size.push(file);
      continue;
    }

    accepted.push(file);
    fileCount += 1;
    totalSize += file.size;
  }

  const limitByCode: Record<UploadLimitViolationCode, number> = {
    max_file_size: limits.max_file_size,
    max_files: limits.max_files,
    max_total_size: limits.max_total_size,
  };
  const codes: UploadLimitViolationCode[] = [
    "max_file_size",
    "max_files",
    "max_total_size",
  ];
  const violations = codes.flatMap((code) =>
    rejectedByCode[code].length > 0
      ? [{ code, files: rejectedByCode[code], limit: limitByCode[code] }]
      : [],
  );

  return {
    accepted,
    rejected: violations.flatMap((violation) => violation.files),
    violations,
  };
}

/** 将字节数格式化为适合上传提示展示的容量文本。 */
export function formatUploadSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Number((bytes / 1024).toFixed(1))} KiB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${Number((bytes / (1024 * 1024)).toFixed(1))} MiB`;
  }
  return `${Number((bytes / (1024 * 1024 * 1024)).toFixed(1))} GiB`;
}
