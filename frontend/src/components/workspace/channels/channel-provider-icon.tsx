"use client";

import { MessageCircleIcon } from "lucide-react";
import type { SVGProps } from "react";

type ChannelProviderIconProps = SVGProps<SVGSVGElement> & {
  provider: string;
};

/** 为通道提供者输出统一的消息气泡图标，并保留提供者标识属性。 */
export function ChannelProviderIcon({
  provider,
  className,
  ...props
}: ChannelProviderIconProps) {
  return (
    <MessageCircleIcon
      data-provider={provider}
      aria-hidden="true"
      className={["size-5", className].filter(Boolean).join(" ")}
      {...props}
    />
  );
}
