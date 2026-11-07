import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  createAgent,
  deleteAgent,
  fetchAgentsApiEnabled,
  getAgent,
  listAgents,
  updateAgent,
} from "./api";
import {
  readCachedAgentsApiEnabled,
  resolveAgentsApiEnabled,
  writeCachedAgentsApiEnabled,
} from "./feature-cache";
import type { CreateAgentRequest, UpdateAgentRequest } from "./types";

/** 查询并以粘滞缓存归并智能体 API 是否可用。 */
export function useAgentsApiEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "agents_api"],
    queryFn: () => fetchAgentsApiEnabled(),
    // 每次挂载重新检查，使修改 config.yaml 后重访智能体区域即可生效，无需重新构建。
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });

  // localStorage 仅存在于浏览器；挂载后再读取可保持首个客户端渲染与服务端一致，
  // 避免未受加载状态控制的侧边栏出现水合不匹配。
  const [cached, setCached] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    setCached(readCachedAgentsApiEnabled());
  }, []);

  // 持久化每个确定结果，使接口故障期间的冷启动可安全回退，避免重现 403 风暴（#3757）。
  useEffect(() => {
    if (data !== undefined) {
      writeCachedAgentsApiEnabled(data);
      setCached(data);
    }
  }, [data]);

  // 实时结果优先；没有实时结果时保持最后已知值，仅在从未观测到值时故障开放。
  return {
    enabled: resolveAgentsApiEnabled(data, cached),
    isLoading: isPending,
  };
}

/** 查询智能体列表，并提供加载与错误状态。 */
export function useAgents() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents"],
    queryFn: () => listAgents(),
  });
  return { agents: data ?? [], isLoading, error };
}

/** 按名称查询智能体；名称为空时保持请求禁用。 */
export function useAgent(name: string | null | undefined) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents", name],
    queryFn: () => getAgent(name!),
    enabled: !!name,
  });
  return { agent: data ?? null, isLoading, error };
}

/** 返回创建智能体的变更操作，成功后刷新智能体列表缓存。 */
export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateAgentRequest) => createAgent(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

/** 返回更新智能体的变更操作，成功后刷新列表和目标详情缓存。 */
export function useUpdateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      request,
    }: {
      name: string;
      request: UpdateAgentRequest;
    }) => updateAgent(name, request),
    onSuccess: (_data, { name }) => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents", name] });
    },
  });
}

/** 返回删除智能体的变更操作，成功后刷新智能体列表缓存。 */
export function useDeleteAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => deleteAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}
