import { AnimatePresence, motion } from "motion/react";

import { cn } from "@/lib/utils";

/** 以翻转动画平滑呈现离散数值变化，避免状态更新造成视觉跳变。 */
export function FlipDisplay({
  uniqueKey,
  children,
  className,
}: {
  uniqueKey: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("relative overflow-hidden", className)}>
      <AnimatePresence mode="wait">
        <motion.div
          key={uniqueKey}
          initial={{ y: 8, opacity: 0 }}
          animate={{ y: 2, opacity: 1 }}
          exit={{ y: -8, opacity: 0 }}
          transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
