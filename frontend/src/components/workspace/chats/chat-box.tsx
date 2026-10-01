import { FilesIcon, XIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

import {
  ArtifactFileDetail,
  ArtifactFileList,
  useArtifacts,
} from "../artifacts";
import { useThread } from "../messages/context";
import { SidecarPanel, useMaybeSidecar } from "../sidecar";

const RIGHT_PANEL_ANIMATION_MS = 280;

type RightPanelKind = "sidecar" | "artifacts";

/** 组织聊天页右侧的侧边对话和产物面板，并协调移动端呈现方式。 */
const ChatBox: React.FC<{ children: React.ReactNode; threadId: string }> = ({
  children,
  threadId,
}) => {
  const { thread } = useThread();
  const isMobile = useIsMobile();
  const pathname = usePathname();
  const threadIdRef = useRef(threadId);

  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    deselect,
    selectedArtifact,
  } = useArtifacts();
  const sidecar = useMaybeSidecar();
  const sidecarOpen = sidecar?.open ?? false;

  useEffect(() => {
    const threadArtifacts = Array.isArray(thread.values.artifacts)
      ? thread.values.artifacts
      : undefined;

    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
      setArtifacts([]);
    }

    // 使用当前线程的产物同步展示状态。
    if (threadArtifacts) {
      setArtifacts(threadArtifacts);
    }

    // 切换线程时暂不自动取消选择产物：产物自动发现尚未可靠工作。
  }, [threadId, deselect, setArtifacts, thread.values.artifacts]);

  const artifactPanelOpen = !sidecarOpen && artifactsOpen;

  const activeRightPanel: RightPanelKind | null = sidecarOpen
    ? "sidecar"
    : artifactPanelOpen
      ? "artifacts"
      : null;
  const rightPanelOpen = activeRightPanel !== null;
  const [renderedRightPanel, setRenderedRightPanel] =
    useState<RightPanelKind | null>(activeRightPanel);

  const resizableIdBase = useMemo(() => {
    return pathname.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  }, [pathname]);

  useEffect(() => {
    if (activeRightPanel) {
      setRenderedRightPanel(activeRightPanel);
      return;
    }

    const timeout = window.setTimeout(() => {
      setRenderedRightPanel(null);
    }, RIGHT_PANEL_ANIMATION_MS);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [activeRightPanel]);

  useEffect(() => {
    if (sidecarOpen && artifactsOpen) {
      setArtifactsOpen(false);
    }
  }, [artifactsOpen, setArtifactsOpen, sidecarOpen]);

  const rightPanelContent = useMemo(() => {
    if (renderedRightPanel === "sidecar") {
      return <SidecarPanel />;
    }
    if (renderedRightPanel === "artifacts" && selectedArtifact) {
      return (
        <ArtifactFileDetail
          className="size-full"
          filepath={selectedArtifact}
          threadId={threadId}
        />
      );
    }
    if (renderedRightPanel === "artifacts") {
      return (
        <div className="relative flex size-full justify-center">
          <div className="absolute top-1 right-1 z-30">
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => {
                setArtifactsOpen(false);
              }}
            >
              <XIcon />
            </Button>
          </div>
          {artifacts.length === 0 ? (
            <ConversationEmptyState
              icon={<FilesIcon />}
              title="No artifact selected"
              description="Select an artifact to view its details"
            />
          ) : (
            <div className="flex size-full max-w-(--container-width-sm) flex-col justify-center p-4 pt-8">
              <header className="shrink-0">
                <h2 className="text-lg font-medium">Artifacts</h2>
              </header>
              <main className="min-h-0 grow">
                <ArtifactFileList
                  className="max-w-(--container-width-sm) p-4 pt-12"
                  files={artifacts}
                  threadId={threadId}
                />
              </main>
            </div>
          )}
        </div>
      );
    }
    return null;
  }, [
    renderedRightPanel,
    selectedArtifact,
    threadId,
    artifacts,
    setArtifactsOpen,
  ]);

  if (isMobile) {
    return (
      <>
        <div className="relative size-full min-w-0">{children}</div>
        <Sheet
          open={rightPanelOpen}
          onOpenChange={(open) => {
            if (open) {
              return;
            }
            if (sidecarOpen) {
              sidecar?.close();
            }
            if (artifactsOpen) {
              setArtifactsOpen(false);
            }
          }}
        >
          <SheetContent
            className="w-[calc(100vw-1rem)] max-w-none gap-0 p-0 sm:max-w-md [&>button]:hidden"
            side="right"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>
                {renderedRightPanel === "sidecar" ? "Sidecar" : "Artifacts"}
              </SheetTitle>
              <SheetDescription>
                Browse the side panel for this conversation.
              </SheetDescription>
            </SheetHeader>
            <div className="min-h-0 flex-1 p-3 pt-10">{rightPanelContent}</div>
          </SheetContent>
        </Sheet>
      </>
    );
  }

  return (
    <div
      id={`${resizableIdBase}-panels`}
      className={cn(
        "[container-type:inline-size] grid size-full min-h-0 transition-[grid-template-columns] duration-[280ms] ease-out motion-reduce:transition-none",
        rightPanelOpen
          ? "grid-cols-[minmax(0,1fr)_1px_minmax(0,40%)]"
          : "grid-cols-[minmax(0,1fr)_0px_0px]",
      )}
    >
      <div className="relative min-h-0 min-w-0" id="chat">
        {children}
      </div>
      <div
        id={`${resizableIdBase}-separator`}
        aria-hidden="true"
        className={cn(
          "bg-border opacity-33 transition-opacity duration-200 ease-out motion-reduce:transition-none",
          !rightPanelOpen && "pointer-events-none opacity-0",
        )}
      />
      <aside
        aria-hidden={!rightPanelOpen}
        className={cn(
          "min-h-0 min-w-0 overflow-hidden transition-opacity duration-[280ms] ease-out motion-reduce:transition-none",
          !rightPanelOpen && "pointer-events-none opacity-0",
        )}
        id="artifacts"
      >
        <div
          className={cn(
            "ml-auto h-full w-[40cqw] transition-opacity duration-[280ms] ease-out motion-reduce:transition-none",
            renderedRightPanel === "sidecar" ? "p-0" : "p-4",
            rightPanelOpen ? "opacity-100" : "opacity-0",
          )}
        >
          {rightPanelContent}
        </div>
      </aside>
    </div>
  );
};

export { ChatBox };
