import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { Handle, Position } from "@xyflow/react";
import type { ComponentProps } from "react";

/** NodeProps 的公开类型定义。 */
export type NodeProps = ComponentProps<typeof Card> & {
  handles: {
    target: boolean;
    source: boolean;
  };
};

/** Node 组件：提供对应的界面结构与交互语义。 */
export const Node = ({ handles, className, ...props }: NodeProps) => (
  <Card
    className={cn(
      "node-container relative size-full h-auto w-sm gap-0 rounded-md p-0",
      className,
    )}
    {...props}
  >
    {handles.target && <Handle position={Position.Left} type="target" />}
    {handles.source && <Handle position={Position.Right} type="source" />}
    {props.children}
  </Card>
);

/** NodeHeaderProps 的公开类型定义。 */
export type NodeHeaderProps = ComponentProps<typeof CardHeader>;

/** NodeHeader 组件：提供对应的界面结构与交互语义。 */
export const NodeHeader = ({ className, ...props }: NodeHeaderProps) => (
  <CardHeader
    className={cn("bg-secondary gap-0.5 rounded-t-md border-b p-3!", className)}
    {...props}
  />
);

/** NodeTitleProps 的公开类型定义。 */
export type NodeTitleProps = ComponentProps<typeof CardTitle>;

/** NodeTitle 组件：提供对应的界面结构与交互语义。 */
export const NodeTitle = (props: NodeTitleProps) => <CardTitle {...props} />;

/** NodeDescriptionProps 的公开类型定义。 */
export type NodeDescriptionProps = ComponentProps<typeof CardDescription>;

/** NodeDescription 组件：提供对应的界面结构与交互语义。 */
export const NodeDescription = (props: NodeDescriptionProps) => (
  <CardDescription {...props} />
);

/** NodeActionProps 的公开类型定义。 */
export type NodeActionProps = ComponentProps<typeof CardAction>;

/** NodeAction 组件：提供对应的界面结构与交互语义。 */
export const NodeAction = (props: NodeActionProps) => <CardAction {...props} />;

/** NodeContentProps 的公开类型定义。 */
export type NodeContentProps = ComponentProps<typeof CardContent>;

/** NodeContent 组件：提供对应的界面结构与交互语义。 */
export const NodeContent = ({ className, ...props }: NodeContentProps) => (
  <CardContent className={cn("p-3", className)} {...props} />
);

/** NodeFooterProps 的公开类型定义。 */
export type NodeFooterProps = ComponentProps<typeof CardFooter>;

/** NodeFooter 组件：提供对应的界面结构与交互语义。 */
export const NodeFooter = ({ className, ...props }: NodeFooterProps) => (
  <CardFooter
    className={cn("bg-secondary rounded-b-md border-t p-3!", className)}
    {...props}
  />
);
