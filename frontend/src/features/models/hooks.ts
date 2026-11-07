import { useQuery } from "@tanstack/react-query";

import { loadModels } from "./api";

/** 查询模型配置，并在会话期间缓存稳定的模型列表。 */
export function useModels({ enabled = true }: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["models"],
    queryFn: () => loadModels(),
    enabled,
    refetchOnWindowFocus: false,
    // 模型配置很少变动，而每张子任务卡都会订阅此查询。将其视为会话内新鲜数据，
    // 可避免默认过期时间为零时新卡片挂载触发重复请求。
    staleTime: Infinity,
  });
  return {
    models: data?.models ?? [],
    tokenUsageEnabled: data?.token_usage.enabled ?? false,
    isLoading,
    error,
  };
}
