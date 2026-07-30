import { useQuery } from "@tanstack/react-query";

import { loadSuggestionsConfig } from "./api";

/** 查询并缓存输入建议配置。 */
export function useSuggestionsConfig() {
  return useQuery({
    queryKey: ["suggestionsConfig"],
    queryFn: loadSuggestionsConfig,
    staleTime: Infinity,
  });
}
