"use client";

import {
  BellIcon,
  CableIcon,
  InfoIcon,
  BrainIcon,
  FileTextIcon,
  PaletteIcon,
  SparklesIcon,
  UserIcon,
  WrenchIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AboutSettingsPage } from "@/components/workspace/settings/about-settings-page";
import { AccountSettingsPage } from "@/components/workspace/settings/account-settings-page";
import { AppearanceSettingsPage } from "@/components/workspace/settings/appearance-settings-page";
import { ChannelsSettingsPage } from "@/components/workspace/settings/channels-settings-page";
import { InstructionsSettingsPage } from "@/components/workspace/settings/instructions-settings-page";
import { MemorySettingsPage } from "@/components/workspace/settings/memory-settings-page";
import { NotificationSettingsPage } from "@/components/workspace/settings/notification-settings-page";
import { SkillSettingsPage } from "@/components/workspace/settings/skill-settings-page";
import { ToolSettingsPage } from "@/components/workspace/settings/tool-settings-page";
import { useI18n } from "@/features/i18n/hooks";

type SettingsSection =
  | "account"
  | "appearance"
  | "channels"
  | "memory"
  | "instructions"
  | "tools"
  | "skills"
  | "notification"
  | "about";

type SettingsDialogProps = React.ComponentProps<typeof Dialog> & {
  defaultSection?: SettingsSection;
};

/** 承载工作区设置分区，并在打开时同步调用方指定的初始页面。 */
export function SettingsDialog(props: SettingsDialogProps) {
  const { defaultSection = "appearance", ...dialogProps } = props;
  const { t } = useI18n();
  const [activeSection, setActiveSection] =
    useState<SettingsSection>(defaultSection);

  useEffect(() => {
    // 打开时让活动分区跟随调用方意图，使“关于”等触发器可直接定位到对应页面。
    if (dialogProps.open) {
      setActiveSection(defaultSection);
    }
  }, [defaultSection, dialogProps.open]);

  const sections = useMemo(
    () => [
      {
        id: "account",
        label: t.settings.sections.account,
        icon: UserIcon,
      },
      {
        id: "appearance",
        label: t.settings.sections.appearance,
        icon: PaletteIcon,
      },
      {
        id: "notification",
        label: t.settings.sections.notification,
        icon: BellIcon,
      },
      {
        id: "channels",
        label: t.settings.sections.channels,
        icon: CableIcon,
      },
      {
        id: "instructions",
        label: t.settings.sections.instructions,
        icon: FileTextIcon,
      },
      {
        id: "memory",
        label: t.settings.sections.memory,
        icon: BrainIcon,
      },
      { id: "tools", label: t.settings.sections.tools, icon: WrenchIcon },
      { id: "skills", label: t.settings.sections.skills, icon: SparklesIcon },
      { id: "about", label: t.settings.sections.about, icon: InfoIcon },
    ],
    [
      t.settings.sections.account,
      t.settings.sections.appearance,
      t.settings.sections.channels,
      t.settings.sections.instructions,
      t.settings.sections.memory,
      t.settings.sections.tools,
      t.settings.sections.skills,
      t.settings.sections.notification,
      t.settings.sections.about,
    ],
  );
  return (
    <Dialog
      {...dialogProps}
      onOpenChange={(open) => props.onOpenChange?.(open)}
    >
      <DialogContent
        className="flex! h-[85dvh] max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)]! max-w-6xl! flex-col p-4! md:h-[75dvh] md:p-6!"
        aria-describedby={undefined}
      >
        <DialogHeader className="gap-1">
          <DialogTitle>{t.settings.title}</DialogTitle>
          <p className="text-muted-foreground text-sm">
            {t.settings.description}
          </p>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-3 md:grid-cols-[180px_minmax(0,1fr)] md:grid-rows-1 md:gap-4">
          <nav className="bg-sidebar max-h-[32dvh] min-h-0 overflow-y-auto rounded-lg border p-2 md:max-h-none">
            <ul className="grid grid-cols-4 gap-1 md:grid-cols-1">
              {sections.map(({ id, label, icon: Icon }) => {
                const active = activeSection === id;
                return (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => setActiveSection(id as SettingsSection)}
                      className={[
                        "flex h-full w-full items-center justify-center rounded-md px-1 py-2 text-xs font-medium transition-colors md:justify-start md:gap-3 md:px-3 md:text-sm",
                        active
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      <Icon className="hidden size-4 shrink-0 md:block" />
                      <span className="min-w-0 [overflow-wrap:anywhere]">
                        {label}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="@container min-h-0 min-w-0 overflow-y-auto rounded-lg border">
            <div className="min-w-0 space-y-8 p-3 @lg:p-6">
              {activeSection === "account" && <AccountSettingsPage />}
              {activeSection === "appearance" && <AppearanceSettingsPage />}
              {activeSection === "memory" && <MemorySettingsPage />}
              {activeSection === "instructions" && <InstructionsSettingsPage />}
              {activeSection === "tools" && <ToolSettingsPage />}
              {activeSection === "skills" && (
                <SkillSettingsPage
                  onClose={() => props.onOpenChange?.(false)}
                />
              )}
              {activeSection === "notification" && <NotificationSettingsPage />}
              {activeSection === "channels" && <ChannelsSettingsPage />}
              {activeSection === "about" && <AboutSettingsPage />}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
