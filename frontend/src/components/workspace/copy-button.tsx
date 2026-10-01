import { CheckIcon, CopyIcon } from "lucide-react";
import { useCallback, useState, type ComponentProps } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";

import { Tooltip } from "./tooltip";

/** 复制指定文本并以按钮状态反馈结果，避免调用方重复处理剪贴板交互。 */
export function CopyButton({
  clipboardData,
  ...props
}: ComponentProps<typeof Button> & {
  clipboardData: string;
}) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  /** 复制调用方提供的文本，并在成功或失败时反馈当前状态。 */
  const handleCopy = useCallback(() => {
    void (async () => {
      const didCopy = await writeTextToClipboard(clipboardData);
      if (!didCopy) {
        toast.error(t.clipboard.failedToCopyToClipboard);
        return;
      }

      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    })().catch(() => {
      toast.error(t.clipboard.failedToCopyToClipboard);
    });
  }, [clipboardData, t.clipboard.failedToCopyToClipboard]);
  return (
    <Tooltip content={t.clipboard.copyToClipboard}>
      <Button
        size="icon-sm"
        type="button"
        variant="ghost"
        onClick={handleCopy}
        {...props}
      >
        {copied ? (
          <CheckIcon className="text-green-500" size={12} />
        ) : (
          <CopyIcon size={12} />
        )}
      </Button>
    </Tooltip>
  );
}
