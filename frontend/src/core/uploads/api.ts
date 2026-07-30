/**
 * 文件上传接口函数。
 */

import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

/** 网关已保存文件的元数据及其可访问路径。 */
export interface UploadedFileInfo {
  filename: string;
  size: number;
  path: string;
  virtual_path: string;
  artifact_url: string;
  extension?: string;
  modified?: number;
  markdown_file?: string;
  markdown_path?: string;
  markdown_virtual_path?: string;
  markdown_artifact_url?: string;
}

/** 文件上传接口的结果，包括成功保存和跳过的文件。 */
export interface UploadResponse {
  success: boolean;
  files: UploadedFileInfo[];
  message: string;
  skipped_files: string[];
}

/** 查询线程上传文件列表时的响应。 */
export interface ListFilesResponse {
  files: UploadedFileInfo[];
  count: number;
}

/** 网关对单次上传请求强制执行的数量和体积限制。 */
export interface UploadLimits {
  max_files: number;
  max_file_size: number;
  max_total_size: number;
}

/** 从失败的上传响应中提取可展示的错误说明。 */
async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = await response.json().catch(() => ({ detail: fallback }));
  return error.detail ?? fallback;
}

/** 将文件上传到指定线程并返回已保存或跳过文件的信息。 */
export async function uploadFiles(
  threadId: string,
  files: File[],
): Promise<UploadResponse> {
  const formData = new FormData();

  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads`,
    {
      method: "POST",
      body: formData,
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Upload failed"));
  }

  return response.json();
}

/** 获取指定线程适用的网关强制上传限制。 */
export async function getUploadLimits(threadId: string): Promise<UploadLimits> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/limits`,
  );

  if (!response.ok) {
    throw new Error(
      await readErrorDetail(response, "Failed to load upload limits"),
    );
  }

  return response.json();
}

/** 列出指定线程中已上传且仍可用的文件。 */
export async function listUploadedFiles(
  threadId: string,
): Promise<ListFilesResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/list`,
  );

  if (!response.ok) {
    throw new Error(
      await readErrorDetail(response, "Failed to list uploaded files"),
    );
  }

  return response.json();
}

/** 删除指定线程中的一个已上传文件。 */
export async function deleteUploadedFile(
  threadId: string,
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/${filename}`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Failed to delete file"));
  }

  return response.json();
}
