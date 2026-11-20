"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fetch } from "@/features/api/fetcher";
import { useAuth } from "@/features/auth/AuthProvider";
import { useI18n } from "@/features/i18n/hooks";

import { SettingsSection } from "./settings-section";

export function InstructionsSettingsPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [conflict, setConflict] = useState(false);
  const isAdmin = user?.system_role === "admin";

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setLoadError(false);
    try {
      const response = await fetch("/api/global-instructions", { signal });
      if (!response.ok) throw new Error("Unable to load instructions");
      const data = (await response.json()) as { content: string };
      if (signal?.aborted) return;
      setContent(data.content);
      setOriginalContent(data.content);
      setConflict(false);
    } catch {
      if (!signal?.aborted) setLoadError(true);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [isAdmin, load]);

  async function save() {
    setSaving(true);
    try {
      const response = await fetch("/api/global-instructions", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, original_content: originalContent }),
      });
      if (response.status === 409) {
        setConflict(true);
        return;
      }
      if (!response.ok) throw new Error("Unable to save instructions");
      setOriginalContent(content);
      toast.success(t.settings.instructions.saved);
    } catch {
      toast.error(t.settings.instructions.saveError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsSection
      title={t.settings.instructions.title}
      description={t.settings.instructions.description}
    >
      {!isAdmin ? (
        <p className="text-muted-foreground text-sm">
          {t.settings.instructions.adminOnly}
        </p>
      ) : loading ? (
        <p className="text-muted-foreground text-sm">{t.common.loading}</p>
      ) : loadError ? (
        <div className="space-y-3">
          <p className="text-destructive text-sm">
            {t.settings.instructions.loadError}
          </p>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            {t.settings.instructions.reload}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <label htmlFor="global-instructions" className="text-sm font-medium">
            {t.settings.instructions.label}
          </label>
          <Textarea
            id="global-instructions"
            className="min-h-64 resize-y"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder={t.settings.instructions.placeholder}
            disabled={saving}
          />
          {conflict && (
            <p role="alert" className="text-destructive text-sm">
              {t.settings.instructions.conflict}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={() => void save()}
              disabled={saving || conflict || content === originalContent}
            >
              {saving ? t.settings.instructions.saving : t.common.save}
            </Button>
            {conflict && (
              <Button variant="outline" onClick={() => void load()}>
                {t.settings.instructions.reload}
              </Button>
            )}
          </div>
        </div>
      )}
    </SettingsSection>
  );
}
