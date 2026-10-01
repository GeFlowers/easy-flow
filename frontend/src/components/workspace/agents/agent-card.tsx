"use client";

import { BotIcon, MessageSquareIcon, Trash2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { type ComponentProps, type ReactElement, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDeleteAgent } from "@/core/agents";
import type { Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface AgentCardProps {
  agent: Agent;
}

/**
 * 仅当触发元素确实被截断时才显示完整文本提示。指针进入时依据元素自身尺寸
 * 检测单行 `truncate` 的宽度截断和多行 `line-clamp` 的高度截断，避免未截断
 * 内容出现多余提示。
 */
function TruncatedTooltip({
  text,
  children,
}: {
  text: string;
  children: ReactElement;
}) {
  const [truncated, setTruncated] = useState(false);
  return (
    <Tooltip>
      <TooltipTrigger
        asChild
        onPointerEnter={(e) => {
          const el = e.currentTarget;
          setTruncated(
            el.scrollWidth > el.clientWidth ||
              el.scrollHeight > el.clientHeight,
          );
        }}
      >
        {children}
      </TooltipTrigger>
      {truncated && (
        <TooltipContent className="max-w-xs text-wrap break-words">
          {text}
        </TooltipContent>
      )}
    </Tooltip>
  );
}

/**
 * 约束代理模型、技能和工具组等用户可控长标签，避免破坏卡片布局；文本在父级
 * 宽度内以省略号截断，并在悬停时显示完整值。
 */
function TruncatedBadge({
  label,
  variant,
  className,
}: {
  label: string;
  variant: ComponentProps<typeof Badge>["variant"];
  className?: string;
}) {
  return (
    <TruncatedTooltip text={label}>
      <Badge
        variant={variant}
        className={cn("block max-w-full truncate", className)}
      >
        {label}
      </Badge>
    </TruncatedTooltip>
  );
}

/** 展示单个自定义代理，并提供发起对话和删除前确认等受控操作。 */
export function AgentCard({ agent }: AgentCardProps) {
  const { t } = useI18n();
  const router = useRouter();
  const deleteAgent = useDeleteAgent();
  const [deleteOpen, setDeleteOpen] = useState(false);

  /** 跳转到该智能体的新对话路由。 */
  function handleChat() {
    router.push(`/workspace/agents/${agent.name}/chats/new`);
  }

  /** 删除当前智能体，反馈结果并在失败时保留确认弹窗。 */
  async function handleDelete() {
    try {
      await deleteAgent.mutateAsync(agent.name);
      toast.success(t.agents.deleteSuccess);
      setDeleteOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <Card className="group flex flex-col transition-shadow hover:shadow-md">
        <CardHeader className="pb-3">
          <div className="flex min-w-0 items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <div className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <BotIcon className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <TruncatedTooltip text={agent.name}>
                  <CardTitle className="truncate text-base">
                    {agent.name}
                  </CardTitle>
                </TruncatedTooltip>
                {agent.model && (
                  <TruncatedBadge
                    label={agent.model}
                    variant="secondary"
                    className="mt-0.5 text-xs"
                  />
                )}
              </div>
            </div>
          </div>
          {agent.description && (
            <TruncatedTooltip text={agent.description}>
              <CardDescription className="mt-2 line-clamp-2 text-sm">
                {agent.description}
              </CardDescription>
            </TruncatedTooltip>
          )}
        </CardHeader>

        {(agent.tool_groups?.length ?? agent.skills?.length ?? 0) > 0 && (
          <CardContent className="pt-0 pb-3">
            <div className="flex flex-wrap gap-1">
              {agent.tool_groups?.map((group) => (
                <TruncatedBadge
                  key={`tg:${group}`}
                  label={group}
                  variant="outline"
                  className="text-xs"
                />
              ))}
              {agent.skills?.map((skill) => (
                <TruncatedBadge
                  key={`sk:${skill}`}
                  label={skill}
                  variant="secondary"
                  className="text-xs"
                />
              ))}
            </div>
          </CardContent>
        )}

        <CardFooter className="mt-auto flex items-center justify-between gap-2 pt-3">
          <Button size="sm" className="flex-1" onClick={handleChat}>
            <MessageSquareIcon className="mr-1.5 h-3.5 w-3.5" />
            {t.agents.chat}
          </Button>
          <div className="flex gap-1">
            <Button
              size="icon"
              variant="ghost"
              className="text-destructive hover:text-destructive h-8 w-8 shrink-0"
              onClick={() => setDeleteOpen(true)}
              title={t.agents.delete}
            >
              <Trash2Icon className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardFooter>
      </Card>

      {/* 删除确认对话框 */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.agents.delete}</DialogTitle>
            <DialogDescription>{t.agents.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteAgent.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteAgent.isPending}
            >
              {deleteAgent.isPending ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
