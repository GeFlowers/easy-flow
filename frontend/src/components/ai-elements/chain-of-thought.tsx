"use client";

import { useControllableState } from "@radix-ui/react-use-controllable-state";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import {
  BrainIcon,
  ChevronDownIcon,
  DotIcon,
  type LucideIcon,
} from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import {
  createContext,
  isValidElement,
  memo,
  useContext,
  useMemo,
} from "react";

type ChainOfThoughtContextValue = {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
};

const ChainOfThoughtContext = createContext<ChainOfThoughtContextValue | null>(
  null,
);

/** useChainOfThought Hook：封装本模块所需的状态或上下文访问。 */
const useChainOfThought = () => {
  const context = useContext(ChainOfThoughtContext);
  if (!context) {
    throw new Error(
      "ChainOfThought components must be used within ChainOfThought",
    );
  }
  return context;
};

/** ChainOfThoughtProps 的公开类型定义。 */
export type ChainOfThoughtProps = ComponentProps<"div"> & {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

/** ChainOfThought 组件：提供对应的界面结构与交互语义。 */
export const ChainOfThought = memo(
  ({
    className,
    open,
    defaultOpen = false,
    onOpenChange,
    children,
    ...props
  }: ChainOfThoughtProps) => {
    const [isOpen, setIsOpen] = useControllableState({
      prop: open,
      defaultProp: defaultOpen,
      onChange: onOpenChange,
    });

    const chainOfThoughtContext = useMemo(
      () => ({ isOpen, setIsOpen }),
      [isOpen, setIsOpen],
    );

    return (
      <ChainOfThoughtContext.Provider value={chainOfThoughtContext}>
        <div className={cn("not-prose", className)} {...props}>
          {children}
        </div>
      </ChainOfThoughtContext.Provider>
    );
  },
);

/** ChainOfThoughtHeaderProps 的公开类型定义。 */
export type ChainOfThoughtHeaderProps = ComponentProps<
  typeof CollapsibleTrigger
> & {
  icon?: React.ReactElement;
};

/** ChainOfThoughtHeader 组件：提供对应的界面结构与交互语义。 */
export const ChainOfThoughtHeader = memo(
  ({ className, children, icon, ...props }: ChainOfThoughtHeaderProps) => {
    const { isOpen, setIsOpen } = useChainOfThought();

    return (
      <Collapsible onOpenChange={setIsOpen} open={isOpen}>
        <CollapsibleTrigger
          className={cn(
            "text-muted-foreground hover:text-foreground flex w-full items-center gap-2 text-sm transition-colors",
            className,
          )}
          {...props}
        >
          {icon ?? <BrainIcon className="size-4" />}
          <span className="flex-1 text-left">
            {children ?? "Chain of Thought"}
          </span>
          <ChevronDownIcon
            className={cn(
              "size-4 transition-transform",
              isOpen ? "rotate-180" : "rotate-0",
            )}
          />
        </CollapsibleTrigger>
      </Collapsible>
    );
  },
);

/** ChainOfThoughtStepProps 的公开类型定义。 */
export type ChainOfThoughtStepProps = ComponentProps<"div"> & {
  icon?: LucideIcon | React.ReactElement;
  label: ReactNode;
  description?: ReactNode;
  status?: "complete" | "active" | "pending";
};

/** ChainOfThoughtStep 组件：提供对应的界面结构与交互语义。 */
export const ChainOfThoughtStep = memo(
  ({
    className,
    icon: Icon = DotIcon,
    label,
    description,
    status = "complete",
    children,
    ...props
  }: ChainOfThoughtStepProps) => {
    const statusStyles = {
      complete: "text-muted-foreground",
      active: "text-foreground",
      pending: "text-muted-foreground/50",
    };

    return (
      <div
        className={cn(
          "flex gap-2 text-sm",
          statusStyles[status],
          "fade-in-0 slide-in-from-top-2 animate-in",
          className,
        )}
        {...props}
      >
        <div className="relative mt-0.5">
          {isValidElement(Icon) ? Icon : <Icon className="size-4" />}
          <div className="bg-border absolute top-7 bottom-0 left-1/2 -mx-px w-px" />
        </div>
        <div className="flex-1 space-y-2 overflow-hidden">
          <div>{label}</div>
          {description && (
            <div className="text-muted-foreground text-xs">{description}</div>
          )}
          {children}
        </div>
      </div>
    );
  },
);

/** ChainOfThoughtSearchResultsProps 的公开类型定义。 */
export type ChainOfThoughtSearchResultsProps = ComponentProps<"div">;

/** ChainOfThoughtSearchResults 组件：提供对应的界面结构与交互语义。 */
export const ChainOfThoughtSearchResults = memo(
  ({ className, ...props }: ChainOfThoughtSearchResultsProps) => (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 overflow-x-hidden",
        className,
      )}
      {...props}
    />
  ),
);

/** ChainOfThoughtSearchResultProps 的公开类型定义。 */
export type ChainOfThoughtSearchResultProps = ComponentProps<typeof Badge>;

/** ChainOfThoughtSearchResult 组件：提供对应的界面结构与交互语义。 */
export const ChainOfThoughtSearchResult = memo(
  ({ className, children, ...props }: ChainOfThoughtSearchResultProps) => (
    <Badge
      className={cn("gap-1 px-2 py-0.5 text-xs font-normal", className)}
      variant="secondary"
      {...props}
    >
      {children}
    </Badge>
  ),
);

/** ChainOfThoughtContentProps 的公开类型定义。 */
export type ChainOfThoughtContentProps = ComponentProps<
  typeof CollapsibleContent
>;

/** ChainOfThoughtContent 组件：提供对应的界面结构与交互语义。 */
export const ChainOfThoughtContent = memo(
  ({ className, children, ...props }: ChainOfThoughtContentProps) => {
    const { isOpen } = useChainOfThought();

    return (
      <Collapsible open={isOpen}>
        <CollapsibleContent
          className={cn(
            "mt-2 space-y-3",
            "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 text-popover-foreground data-[state=closed]:animate-out data-[state=open]:animate-in outline-none",
            className,
          )}
          {...props}
        >
          {children}
        </CollapsibleContent>
      </Collapsible>
    );
  },
);

/** ChainOfThoughtImageProps 的公开类型定义。 */
export type ChainOfThoughtImageProps = ComponentProps<"div"> & {
  caption?: string;
};

/** ChainOfThoughtImage 组件：提供对应的界面结构与交互语义。 */
export const ChainOfThoughtImage = memo(
  ({ className, children, caption, ...props }: ChainOfThoughtImageProps) => (
    <div className={cn("mt-2 space-y-2", className)} {...props}>
      <div className="bg-muted relative flex max-h-[22rem] items-center justify-center overflow-hidden rounded-lg p-3">
        {children}
      </div>
      {caption && <p className="text-muted-foreground text-xs">{caption}</p>}
    </div>
  ),
);

ChainOfThought.displayName = "ChainOfThought";
ChainOfThoughtHeader.displayName = "ChainOfThoughtHeader";
ChainOfThoughtStep.displayName = "ChainOfThoughtStep";
ChainOfThoughtSearchResults.displayName = "ChainOfThoughtSearchResults";
ChainOfThoughtSearchResult.displayName = "ChainOfThoughtSearchResult";
ChainOfThoughtContent.displayName = "ChainOfThoughtContent";
ChainOfThoughtImage.displayName = "ChainOfThoughtImage";
