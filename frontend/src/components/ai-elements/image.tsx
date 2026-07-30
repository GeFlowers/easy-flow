import { cn } from "@/lib/utils";
import type { Experimental_GeneratedImage } from "ai";

/** ImageProps 的公开类型定义。 */
export type ImageProps = Experimental_GeneratedImage & {
  className?: string;
  alt?: string;
};

/** Image 组件：提供对应的界面结构与交互语义。 */
export const Image = ({
  base64,
  uint8Array,
  mediaType,
  ...props
}: ImageProps) => (
  <img
    {...props}
    alt={props.alt}
    className={cn(
      "h-auto max-w-full overflow-hidden rounded-md",
      props.className,
    )}
    src={`data:${mediaType};base64,${base64}`}
  />
);
