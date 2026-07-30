/**
 * 文件上传相关的状态钩子。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  deleteUploadedFile,
  getUploadLimits,
  listUploadedFiles,
  uploadFiles,
  type UploadedFileInfo,
  type UploadResponse,
} from "./api";

/**
 * 获取网关强制上传限制的状态钩子。请求失败时，调用方有意降级为仅依赖服务端校验。
 */
export function useUploadLimits(threadId: string) {
  return useQuery({
    queryKey: ["uploads", "limits", threadId],
    queryFn: () => getUploadLimits(threadId),
    enabled: !!threadId,
    retry: false,
    staleTime: 60_000,
  });
}

/**
 * 上传文件的状态钩子。
 */
export function useUploadFiles(threadId: string) {
  const queryClient = useQueryClient();

  return useMutation<UploadResponse, Error, File[]>({
    mutationFn: (files: File[]) => uploadFiles(threadId, files),
    onSuccess: () => {
      // 使已上传文件列表缓存失效。
      void queryClient.invalidateQueries({
        queryKey: ["uploads", "list", threadId],
      });
    },
  });
}

/**
 * 列出已上传文件的状态钩子。
 */
export function useUploadedFiles(threadId: string) {
  return useQuery({
    queryKey: ["uploads", "list", threadId],
    queryFn: () => listUploadedFiles(threadId),
    enabled: !!threadId,
  });
}

/**
 * 删除已上传文件的状态钩子。
 */
export function useDeleteUploadedFile(threadId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (filename: string) => deleteUploadedFile(threadId, filename),
    onSuccess: () => {
      // 使已上传文件列表缓存失效。
      void queryClient.invalidateQueries({
        queryKey: ["uploads", "list", threadId],
      });
    },
  });
}

/**
 * 在提交流程中处理文件上传的状态钩子，返回一个上传文件并返回其信息的函数。
 */
export function useUploadFilesOnSubmit(threadId: string) {
  const uploadMutation = useUploadFiles(threadId);

  return useCallback(
    async (files: File[]): Promise<UploadedFileInfo[]> => {
      if (files.length === 0) {
        return [];
      }

      const result = await uploadMutation.mutateAsync(files);
      return result.files;
    },
    [uploadMutation],
  );
}
