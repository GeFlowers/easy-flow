"use client";

import { MessageSquareTextIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

import { Tooltip } from "../tooltip";

import { useMaybeSidecar } from "./context";

/** 打开或关闭侧边对话；打开前先协调缓存线程，避免进入已删除的会话。 */
export function SidecarTrigger() {
  const { t } = useI18n();
  const sidecar = useMaybeSidecar();
  const [isReconciling, setIsReconciling] = useState(false);

  if (!sidecar?.sidecarThreadId) {
    return null;
  }

  const label = sidecar.open ? t.sidecar.close : t.sidecar.open;

  const handleClick = async () => {
    if (sidecar.open) {
      sidecar.close();
      return;
    }
    // 缓存 id 可能指向其他位置已删除的侧边线程。打开前重新查询后端；若已不存在，
    // 强制恢复会清除该 id 并使触发器卸载（自愈），不会打开失效线程（#3555）。
    setIsReconciling(true);
    try {
      const restoredThreadId = await sidecar.restoreSidecarThread({
        force: true,
      });
      if (restoredThreadId) {
        sidecar.openSidecar();
      }
    } finally {
      setIsReconciling(false);
    }
  };

  return (
    <Tooltip content={label}>
      <Button
        aria-label={label}
        className="text-muted-foreground hover:text-foreground"
        data-testid="sidecar-header-trigger"
        disabled={isReconciling}
        size="icon"
        type="button"
        variant={sidecar.open ? "secondary" : "ghost"}
        onClick={() => {
          void handleClick();
        }}
      >
        <MessageSquareTextIcon />
      </Button>
    </Tooltip>
  );
}
