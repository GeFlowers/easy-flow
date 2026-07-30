import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { ComponentProps, ReactNode } from "react";

/** ModelSelectorProps 的公开类型定义。 */
export type ModelSelectorProps = ComponentProps<typeof Dialog>;

/** ModelSelector 组件：提供对应的界面结构与交互语义。 */
export const ModelSelector = (props: ModelSelectorProps) => (
  <Dialog {...props} />
);

/** ModelSelectorTriggerProps 的公开类型定义。 */
export type ModelSelectorTriggerProps = ComponentProps<typeof DialogTrigger>;

/** ModelSelectorTrigger 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorTrigger = (props: ModelSelectorTriggerProps) => (
  <DialogTrigger {...props} />
);

/** ModelSelectorContentProps 的公开类型定义。 */
export type ModelSelectorContentProps = ComponentProps<typeof DialogContent> & {
  title?: ReactNode;
};

/** ModelSelectorContent 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorContent = ({
  className,
  children,
  title = "Model Selector",
  ...props
}: ModelSelectorContentProps) => (
  <DialogContent className={cn("p-0", className)} {...props}>
    <DialogTitle className="sr-only">{title}</DialogTitle>
    <Command className="**:data-[slot=command-input-wrapper]:h-auto">
      {children}
    </Command>
  </DialogContent>
);

/** ModelSelectorDialogProps 的公开类型定义。 */
export type ModelSelectorDialogProps = ComponentProps<typeof CommandDialog>;

/** ModelSelectorDialog 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorDialog = (props: ModelSelectorDialogProps) => (
  <CommandDialog {...props} />
);

/** ModelSelectorInputProps 的公开类型定义。 */
export type ModelSelectorInputProps = ComponentProps<typeof CommandInput>;

/** ModelSelectorInput 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorInput = ({
  className,
  ...props
}: ModelSelectorInputProps) => (
  <CommandInput className={cn("h-auto py-3.5", className)} {...props} />
);

/** ModelSelectorListProps 的公开类型定义。 */
export type ModelSelectorListProps = ComponentProps<typeof CommandList>;

/** ModelSelectorList 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorList = (props: ModelSelectorListProps) => (
  <CommandList {...props} />
);

/** ModelSelectorEmptyProps 的公开类型定义。 */
export type ModelSelectorEmptyProps = ComponentProps<typeof CommandEmpty>;

/** ModelSelectorEmpty 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorEmpty = (props: ModelSelectorEmptyProps) => (
  <CommandEmpty {...props} />
);

/** ModelSelectorGroupProps 的公开类型定义。 */
export type ModelSelectorGroupProps = ComponentProps<typeof CommandGroup>;

/** ModelSelectorGroup 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorGroup = (props: ModelSelectorGroupProps) => (
  <CommandGroup {...props} />
);

/** ModelSelectorItemProps 的公开类型定义。 */
export type ModelSelectorItemProps = ComponentProps<typeof CommandItem>;

/** ModelSelectorItem 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorItem = (props: ModelSelectorItemProps) => (
  <CommandItem {...props} />
);

/** ModelSelectorShortcutProps 的公开类型定义。 */
export type ModelSelectorShortcutProps = ComponentProps<typeof CommandShortcut>;

/** ModelSelectorShortcut 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorShortcut = (props: ModelSelectorShortcutProps) => (
  <CommandShortcut {...props} />
);

/** ModelSelectorSeparatorProps 的公开类型定义。 */
export type ModelSelectorSeparatorProps = ComponentProps<
  typeof CommandSeparator
>;

/** ModelSelectorSeparator 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorSeparator = (props: ModelSelectorSeparatorProps) => (
  <CommandSeparator {...props} />
);

/** ModelSelectorLogoProps 的公开类型定义。 */
export type ModelSelectorLogoProps = Omit<
  ComponentProps<"img">,
  "src" | "alt"
> & {
  provider:
    | "moonshotai-cn"
    | "lucidquery"
    | "moonshotai"
    | "zai-coding-plan"
    | "alibaba"
    | "xai"
    | "vultr"
    | "nvidia"
    | "upstage"
    | "groq"
    | "github-copilot"
    | "mistral"
    | "vercel"
    | "nebius"
    | "deepseek"
    | "alibaba-cn"
    | "google-vertex-anthropic"
    | "venice"
    | "chutes"
    | "cortecs"
    | "github-models"
    | "togetherai"
    | "azure"
    | "baseten"
    | "huggingface"
    | "opencode"
    | "fastrouter"
    | "google"
    | "google-vertex"
    | "cloudflare-workers-ai"
    | "inception"
    | "wandb"
    | "openai"
    | "zhipuai-coding-plan"
    | "perplexity"
    | "openrouter"
    | "zenmux"
    | "v0"
    | "iflowcn"
    | "synthetic"
    | "deepinfra"
    | "zhipuai"
    | "submodel"
    | "zai"
    | "inference"
    | "requesty"
    | "morph"
    | "lmstudio"
    | "anthropic"
    | "aihubmix"
    | "fireworks-ai"
    | "modelscope"
    | "llama"
    | "scaleway"
    | "amazon-bedrock"
    | "cerebras"
    | (string & {});
};

/** ModelSelectorLogo 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorLogo = ({
  provider,
  className,
  ...props
}: ModelSelectorLogoProps) => (
  <img
    {...props}
    alt={`${provider} logo`}
    className={cn("size-3 dark:invert", className)}
    height={12}
    src={`https://models.dev/logos/${provider}.svg`}
    width={12}
  />
);

/** ModelSelectorLogoGroupProps 的公开类型定义。 */
export type ModelSelectorLogoGroupProps = ComponentProps<"div">;

/** ModelSelectorLogoGroup 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorLogoGroup = ({
  className,
  ...props
}: ModelSelectorLogoGroupProps) => (
  <div
    className={cn(
      "[&>img]:bg-background dark:[&>img]:bg-foreground flex shrink-0 items-center -space-x-1 [&>img]:rounded-full [&>img]:p-px [&>img]:ring-1",
      className,
    )}
    {...props}
  />
);

/** ModelSelectorNameProps 的公开类型定义。 */
export type ModelSelectorNameProps = ComponentProps<"span">;

/** ModelSelectorName 组件：提供对应的界面结构与交互语义。 */
export const ModelSelectorName = ({
  className,
  ...props
}: ModelSelectorNameProps) => (
  <span
    className={cn("flex-1 truncate text-left text-xs", className)}
    {...props}
  />
);
