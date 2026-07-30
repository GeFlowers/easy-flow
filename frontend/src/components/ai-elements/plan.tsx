"use client";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronsUpDownIcon } from "lucide-react";
import type { ComponentProps } from "react";
import { createContext, useContext } from "react";
import { Shimmer } from "./shimmer";

type PlanContextValue = {
  isStreaming: boolean;
};

const PlanContext = createContext<PlanContextValue | null>(null);

/** usePlan Hook：封装本模块所需的状态或上下文访问。 */
const usePlan = () => {
  const context = useContext(PlanContext);
  if (!context) {
    throw new Error("Plan components must be used within Plan");
  }
  return context;
};

/** PlanProps 的公开类型定义。 */
export type PlanProps = ComponentProps<typeof Collapsible> & {
  isStreaming?: boolean;
};

/** Plan 组件：提供对应的界面结构与交互语义。 */
export const Plan = ({
  className,
  isStreaming = false,
  children,
  ...props
}: PlanProps) => (
  <PlanContext.Provider value={{ isStreaming }}>
    <Collapsible asChild data-slot="plan" {...props}>
      <Card className={cn("shadow-none", className)}>{children}</Card>
    </Collapsible>
  </PlanContext.Provider>
);

/** PlanHeaderProps 的公开类型定义。 */
export type PlanHeaderProps = ComponentProps<typeof CardHeader>;

/** PlanHeader 组件：提供对应的界面结构与交互语义。 */
export const PlanHeader = ({ className, ...props }: PlanHeaderProps) => (
  <CardHeader
    className={cn("flex items-start justify-between", className)}
    data-slot="plan-header"
    {...props}
  />
);

/** PlanTitleProps 的公开类型定义。 */
export type PlanTitleProps = Omit<
  ComponentProps<typeof CardTitle>,
  "children"
> & {
  children: string;
};

/** PlanTitle 组件：提供对应的界面结构与交互语义。 */
export const PlanTitle = ({ children, ...props }: PlanTitleProps) => {
  const { isStreaming } = usePlan();

  return (
    <CardTitle data-slot="plan-title" {...props}>
      {isStreaming ? <Shimmer>{children}</Shimmer> : children}
    </CardTitle>
  );
};

/** PlanDescriptionProps 的公开类型定义。 */
export type PlanDescriptionProps = Omit<
  ComponentProps<typeof CardDescription>,
  "children"
> & {
  children: string;
};

/** PlanDescription 组件：提供对应的界面结构与交互语义。 */
export const PlanDescription = ({
  className,
  children,
  ...props
}: PlanDescriptionProps) => {
  const { isStreaming } = usePlan();

  return (
    <CardDescription
      className={cn("text-balance", className)}
      data-slot="plan-description"
      {...props}
    >
      {isStreaming ? <Shimmer>{children}</Shimmer> : children}
    </CardDescription>
  );
};

/** PlanActionProps 的公开类型定义。 */
export type PlanActionProps = ComponentProps<typeof CardAction>;

/** PlanAction 组件：提供对应的界面结构与交互语义。 */
export const PlanAction = (props: PlanActionProps) => (
  <CardAction data-slot="plan-action" {...props} />
);

/** PlanContentProps 的公开类型定义。 */
export type PlanContentProps = ComponentProps<typeof CardContent>;

/** PlanContent 组件：提供对应的界面结构与交互语义。 */
export const PlanContent = (props: PlanContentProps) => (
  <CollapsibleContent asChild>
    <CardContent data-slot="plan-content" {...props} />
  </CollapsibleContent>
);

/** PlanFooterProps 的公开类型定义。 */
export type PlanFooterProps = ComponentProps<"div">;

/** PlanFooter 组件：提供对应的界面结构与交互语义。 */
export const PlanFooter = (props: PlanFooterProps) => (
  <CardFooter data-slot="plan-footer" {...props} />
);

/** PlanTriggerProps 的公开类型定义。 */
export type PlanTriggerProps = ComponentProps<typeof CollapsibleTrigger>;

/** PlanTrigger 组件：提供对应的界面结构与交互语义。 */
export const PlanTrigger = ({ className, ...props }: PlanTriggerProps) => (
  <CollapsibleTrigger asChild>
    <Button
      className={cn("size-8", className)}
      data-slot="plan-trigger"
      size="icon"
      variant="ghost"
      {...props}
    >
      <ChevronsUpDownIcon className="size-4" />
      <span className="sr-only">Toggle plan</span>
    </Button>
  </CollapsibleTrigger>
);
