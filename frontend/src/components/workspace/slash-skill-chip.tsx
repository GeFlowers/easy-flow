import { XIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** `/skill` 激活的共用视觉组件：编辑器中可移除，聊天记录中只读。集中维护可避免两处 Tailwind 类逐渐偏离。 */
const CHIP_BASE_CLASS =
  "border-primary/20 bg-primary/10 text-primary inline-flex h-6 shrink-0 items-center rounded-md border px-1.5 font-mono text-xs leading-none font-medium shadow-xs";

/** 显示已识别的 `/skill` 激活；传入移除回调时才暴露可操作的关闭按钮。 */
export function SlashSkillChip({
  name,
  className,
  onRemove,
  removeLabel,
}: {
  name: string;
  className?: string;
  /** 提供时将标签渲染为带关闭图标的可移除按钮。 */
  onRemove?: () => void;
  removeLabel?: string;
}) {
  if (onRemove) {
    return (
      <button
        aria-label={removeLabel ?? `Remove /${name}`}
        className={cn(
          CHIP_BASE_CLASS,
          "hover:bg-primary/20 cursor-pointer gap-1 transition-colors",
          className,
        )}
        onClick={onRemove}
        type="button"
      >
        <span className="min-w-0 truncate">/{name}</span>
        <XIcon className="text-primary/70 size-2.5 shrink-0" />
      </button>
    );
  }

  return (
    <span className={cn(CHIP_BASE_CLASS, "max-w-full", className)}>
      /{name}
    </span>
  );
}
