"use client";

import { useControllableState } from "@radix-ui/react-use-controllable-state";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { BrainIcon, ChevronDownIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { createContext, memo, useContext, useEffect, useState } from "react";
import { reasoningPlugins } from "@/core/streamdown/plugins";
import { Shimmer } from "./shimmer";
import { ClipboardSafeStreamdown } from "./streamdown";

type ReasoningContextValue = {
  isStreaming: boolean;
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  duration: number | undefined;
  startTime: number | null;
};

const ReasoningContext = createContext<ReasoningContextValue | null>(null);

/** useReasoning Hook：封装相关状态与交互逻辑。 */
export const useReasoning = () => {
  const context = useContext(ReasoningContext);
  if (!context) {
    throw new Error("Reasoning components must be used within Reasoning");
  }
  return context;
};

/** ReasoningProps 的公开类型定义。 */
export type ReasoningProps = ComponentProps<typeof Collapsible> & {
  isStreaming?: boolean;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  duration?: number;
  startTimeProp?: number | null;
  onTurnDurationChange?: (duration: number | undefined) => void;
};

const AUTO_CLOSE_DELAY = 1000;
const MS_IN_S = 1000;

/** Reasoning 组件：提供对应的界面结构与交互语义。 */
export const Reasoning = memo(
  ({
    className,
    isStreaming = false,
    open,
    defaultOpen = true,
    onOpenChange,
    duration: durationProp,
    startTimeProp,
    onTurnDurationChange,
    children,
    ...props
  }: ReasoningProps) => {
    const [isOpen, setIsOpen] = useControllableState({
      prop: open,
      defaultProp: defaultOpen,
      onChange: onOpenChange,
    });
    const [duration, setDuration] = useControllableState<number | undefined>({
      prop: durationProp,
      defaultProp: undefined,
      onChange: onTurnDurationChange,
    });

    const [hasAutoClosed, setHasAutoClosed] = useState(false);
    const [startTime, setStartTime] = useState<number | null>(
      () => startTimeProp ?? (isStreaming ? Date.now() : null),
    );

    // 在流式输出开始与结束时记录持续时间。
    useEffect(() => {
      if (isStreaming) {
        // 若提供轮次开始时间，则强制与其对齐。
        if (startTimeProp != null && startTime !== startTimeProp) {
          setStartTime(startTimeProp);
        } else if (startTimeProp == null && startTime === null) {
          setStartTime(Date.now());
        }
      } else if (startTime !== null) {
        setDuration(Math.floor((Date.now() - startTime) / MS_IN_S));
        setStartTime(null);
      }
    }, [isStreaming, startTimeProp, startTime, setDuration]);

    // 流式输出开始时自动展开，结束时仅自动收起一次。
    useEffect(() => {
      if (defaultOpen && !isStreaming && isOpen && !hasAutoClosed) {
        // 收起前短暂延迟，让用户能看到刚完成的内容。
        const timer = setTimeout(() => {
          setIsOpen(false);
          setHasAutoClosed(true);
        }, AUTO_CLOSE_DELAY);

        return () => clearTimeout(timer);
      }
    }, [isStreaming, isOpen, defaultOpen, setIsOpen, hasAutoClosed]);

    const handleOpenChange = (newOpen: boolean) => {
      setIsOpen(newOpen);
    };

    return (
      <ReasoningContext.Provider
        value={{ isStreaming, isOpen, setIsOpen, duration, startTime }}
      >
        <Collapsible
          className={cn("not-prose mb-4", className)}
          onOpenChange={handleOpenChange}
          open={isOpen}
          {...props}
        >
          {children}
        </Collapsible>
      </ReasoningContext.Provider>
    );
  },
);

/** ReasoningTriggerProps 的公开类型定义。 */
export type ReasoningTriggerProps = ComponentProps<
  typeof CollapsibleTrigger
> & {
  getThinkingMessage?: (
    isStreaming: boolean,
    duration?: number,
    startTime?: number | null,
  ) => ReactNode;
  hasContent?: boolean;
};

/** LiveTimer 内部组件：组织对应的界面结构与交互语义。 */
const LiveTimer = ({ startTime }: { startTime: number }) => {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const calculateElapsed = () => Math.floor((Date.now() - startTime) / 1000);
    setElapsed(calculateElapsed());

    const interval = setInterval(() => {
      setElapsed(calculateElapsed());
    }, 1000);

    return () => clearInterval(interval);
  }, [startTime]);

  return (
    <span className="flex items-center gap-2">
      <Shimmer duration={1}>Thinking...</Shimmer>
      <span className="text-muted-foreground/80">({elapsed}s)</span>
    </span>
  );
};

const defaultGetThinkingMessage = (
  isStreaming: boolean,
  duration?: number,
  startTime?: number | null,
) => {
  if (isStreaming && startTime != null && startTime !== undefined) {
    return <LiveTimer startTime={startTime} />;
  }
  if (isStreaming || duration === 0) {
    return <Shimmer duration={1}>Thinking...</Shimmer>;
  }
  if (duration === undefined) {
    return <span>Thought for a few seconds</span>;
  }
  return <span>Thought for {duration} seconds</span>;
};

/** ReasoningTrigger 组件：提供对应的界面结构与交互语义。 */
export const ReasoningTrigger = memo(
  ({
    className,
    children,
    getThinkingMessage = defaultGetThinkingMessage,
    hasContent = true,
    ...props
  }: ReasoningTriggerProps) => {
    const { isStreaming, isOpen, duration, startTime } = useReasoning();

    return (
      <CollapsibleTrigger
        className={cn(
          "text-muted-foreground hover:text-foreground flex w-full items-center gap-2 text-sm transition-colors",
          !hasContent && "cursor-default",
          className,
        )}
        {...props}
      >
        {children ?? (
          <>
            <BrainIcon className="size-4" />
            {getThinkingMessage(isStreaming, duration, startTime)}
            {hasContent && (
              <ChevronDownIcon
                className={cn(
                  "size-4 transition-transform",
                  isOpen ? "rotate-180" : "rotate-0",
                )}
              />
            )}
          </>
        )}
      </CollapsibleTrigger>
    );
  },
);

/** ReasoningContentProps 的公开类型定义。 */
export type ReasoningContentProps = ComponentProps<
  typeof CollapsibleContent
> & {
  children: string;
};

/** ReasoningContent 组件：提供对应的界面结构与交互语义。 */
export const ReasoningContent = memo(
  ({ className, children, ...props }: ReasoningContentProps) => (
    <CollapsibleContent
      className={cn(
        "mt-4 text-sm",
        "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 text-muted-foreground data-[state=closed]:animate-out data-[state=open]:animate-in outline-none",
        className,
      )}
      {...props}
    >
      <ClipboardSafeStreamdown {...reasoningPlugins}>
        {children}
      </ClipboardSafeStreamdown>
    </CollapsibleContent>
  ),
);

Reasoning.displayName = "Reasoning";
ReasoningTrigger.displayName = "ReasoningTrigger";
ReasoningContent.displayName = "ReasoningContent";
