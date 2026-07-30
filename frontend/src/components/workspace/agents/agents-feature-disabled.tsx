"use client";

import { BotOffIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";

/** 在自定义代理功能关闭时呈现不可用原因，避免显示无效操作入口。 */
export function AgentsFeatureDisabled() {
  const { t } = useI18n();
  return (
    <div className="flex size-full flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
        <BotOffIcon className="text-muted-foreground h-7 w-7" />
      </div>
      <div>
        <p className="font-medium">{t.agents.featureDisabledTitle}</p>
        <p className="text-muted-foreground mt-1 max-w-md text-sm">
          {t.agents.featureDisabledDescription}
        </p>
      </div>
    </div>
  );
}
