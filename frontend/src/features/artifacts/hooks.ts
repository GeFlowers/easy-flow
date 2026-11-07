import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { useThread } from "@/components/workspace/messages/context";

import { loadArtifactContent, loadArtifactContentFromToolCall } from "./loader";

/** 加载线程制品内容，并在写文件临时制品时直接从消息流中还原草稿。 */
export function useArtifactContent({
  filepath,
  threadId,
  enabled,
}: {
  filepath: string;
  threadId: string;
  enabled?: boolean;
}) {
  const isWriteFile = useMemo(() => {
    return filepath.startsWith("write-file:");
  }, [filepath]);
  const { thread } = useThread();
  const content = useMemo(() => {
    if (isWriteFile) {
      return loadArtifactContentFromToolCall({ url: filepath, thread });
    }
    return null;
  }, [filepath, isWriteFile, thread]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["artifact", filepath, threadId],
    queryFn: () => {
      return loadArtifactContent({ filepath, threadId });
    },
    enabled,
    // 缓存制品内容五分钟，避免重复获取，尤其是 .skill ZIP 解压场景。
    staleTime: 5 * 60 * 1000,
  });
  return {
    content: isWriteFile ? content : data?.content,
    url: isWriteFile ? undefined : data?.url,
    isLoading,
    error,
  };
}
