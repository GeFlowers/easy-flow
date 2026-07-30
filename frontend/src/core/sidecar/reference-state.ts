import type { SidecarContext } from "./context";

/** 侧栏面板状态中的一条引用及其界面标识。 */
export type SidecarReferenceStateItem = {
  id: number;
  context: SidecarContext;
};

/** 判断两个侧栏上下文是否指向同一条引用内容。 */
export function isSameSidecarContext(
  left: SidecarContext,
  right: SidecarContext,
) {
  return (
    left.type === right.type &&
    left.role === right.role &&
    left.messageId === right.messageId &&
    left.content === right.content
  );
}

/** 向侧栏引用列表追加未重复的上下文。 */
export function appendSidecarReference<
  TReference extends SidecarReferenceStateItem,
>(references: TReference[], nextReference: TReference) {
  if (
    references.some((reference) =>
      isSameSidecarContext(reference.context, nextReference.context),
    )
  ) {
    return references;
  }
  return [...references, nextReference];
}

/** 根据当前打开状态计算侧栏下一次应保留的引用集合。 */
export function getNextSidecarOpenState<
  TReference extends SidecarReferenceStateItem,
>({
  open,
  sidecarThreadId,
  activeReferences,
  nextReference,
}: {
  open: boolean;
  sidecarThreadId: string | null;
  activeReferences: TReference[];
  nextReference: TReference;
}) {
  const shouldAppendToCurrentSidecar =
    open && (Boolean(sidecarThreadId) || activeReferences.length > 0);

  return {
    sidecarThreadId,
    activeReferences: shouldAppendToCurrentSidecar
      ? appendSidecarReference(activeReferences, nextReference)
      : [nextReference],
  };
}
