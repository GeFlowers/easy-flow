import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearMemory,
  createMemoryFact,
  deleteMemoryFact,
  importMemory,
  loadMemory,
  updateMemoryFact,
} from "./api";
import type {
  MemoryFactInput,
  MemoryFactPatchInput,
  UserMemory,
} from "./types";

/** 查询当前用户的记忆数据，并提供加载与错误状态。 */
export function useMemory() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory"],
    queryFn: () => loadMemory(),
  });
  return { memory: data ?? null, isLoading, error };
}

/** 返回清空记忆的变更操作，成功后直接写回记忆缓存。 */
export function useClearMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => clearMemory(),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

/** 返回删除记忆事实的变更操作，成功后直接写回记忆缓存。 */
export function useDeleteMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (factId: string) => deleteMemoryFact(factId),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

/** 返回导入记忆的变更操作，成功后直接写回记忆缓存。 */
export function useImportMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (memory: UserMemory) => importMemory(memory),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

/** 返回创建记忆事实的变更操作，成功后直接写回记忆缓存。 */
export function useCreateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: MemoryFactInput) => createMemoryFact(input),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}

/** 返回更新记忆事实的变更操作，成功后直接写回记忆缓存。 */
export function useUpdateMemoryFact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      factId,
      input,
    }: {
      factId: string;
      input: MemoryFactPatchInput;
    }) => updateMemoryFact(factId, input),
    onSuccess: (memory) => {
      queryClient.setQueryData<UserMemory>(["memory"], memory);
    },
  });
}
