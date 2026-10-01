"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateScheduledTask,
  useUpdateScheduledTask,
  useDeleteScheduledTask,
  usePauseScheduledTask,
  useResumeScheduledTask,
  useScheduledTaskRuns,
  useScheduledTasks,
  useTriggerScheduledTask,
  useThreadScheduledTasks,
} from "@/core/scheduled-tasks/hooks";
import { RECIPES, type Recipe } from "@/core/scheduled-tasks/recipes";
import type {
  ScheduledTask,
  ScheduledTaskRun,
} from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

const NONE = "—";

/** 将任务时间戳格式化为当前界面语言对应的绝对时间。 */
function formatTimestamp(value: string | null, locale: string): string {
  if (!value) {
    return NONE;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  // 使用本地化短格式；下次执行时间必须显示绝对时间，不能显示相对的“多久前”。
  const intlLocale = locale === "zh-CN" ? "zh-CN" : "en-US";
  return new Intl.DateTimeFormat(intlLocale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** 管理计划任务的创建、筛选、编辑、触发、暂停与删除。 */
export default function ScheduledTasksPage() {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const searchParams = useSearchParams();
  const threadId = searchParams.get("thread_id");
  const allTasksQuery = useScheduledTasks();
  const threadTasksQuery = useThreadScheduledTasks(threadId);
  const data = threadId ? threadTasksQuery.data : allTasksQuery.data;
  const queryError = threadId ? threadTasksQuery.error : allTasksQuery.error;
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [contextMode, setContextMode] = useState<
    "fresh_thread_per_run" | "reuse_thread"
  >(threadId ? "reuse_thread" : "fresh_thread_per_run");
  const [targetThreadId, setTargetThreadId] = useState(threadId ?? "");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [createSchedule, setCreateSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "",
  });
  const [statusFilter, setStatusFilter] = useState<
    "all" | "enabled" | "paused" | "running" | "completed" | "failed"
  >("all");
  const [typeFilter, setTypeFilter] = useState<"all" | "once" | "cron">("all");
  const [formError, setFormError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [editSchedule, setEditSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
  });
  const [createNonce, setCreateNonce] = useState(0);
  const filteredData = (data ?? []).filter((task) => {
    const statusPass = statusFilter === "all" || task.status === statusFilter;
    const typePass = typeFilter === "all" || task.schedule_type === typeFilter;
    return statusPass && typePass;
  });
  const selectedTask =
    filteredData.find((task) => task.id === selectedTaskId) ?? filteredData[0];
  const taskRunsQuery = useScheduledTaskRuns(selectedTask?.id);
  const createTask = useCreateScheduledTask();
  const updateTask = useUpdateScheduledTask(selectedTask?.id ?? "");
  const pauseTask = usePauseScheduledTask();
  const resumeTask = useResumeScheduledTask();
  const triggerTask = useTriggerScheduledTask();
  const deleteTask = useDeleteScheduledTask();

  /** 把任务计划类型标识转换为本地化标签，未知值保留原始文本。 */
  const scheduleTypeLabel = (v: string) =>
    v === "cron"
      ? st.scheduleType.cron
      : v === "once"
        ? st.scheduleType.once
        : v;
  /** 显示任务状态对应的本地化名称，并兼容服务端新增状态值。 */
  const statusLabel = (v: string) =>
    (st.status as Record<string, string>)[v] ?? v;
  /** 将每次运行新建线程或复用线程的策略转为设置页文案。 */
  const contextModeLabel = (v: string) =>
    v === "fresh_thread_per_run"
      ? st.context.fresh
      : v === "reuse_thread"
        ? st.context.reuse
        : v;
  /** 将运行触发来源映射为本地化文本，保留未识别的来源标识。 */
  const runTriggerLabel = (v: string) =>
    (st.runTrigger as Record<string, string>)[v] ?? v;
  /** 将单次运行状态映射为本地化文本，兼容未知状态。 */
  const runStatusLabel = (v: string) =>
    (st.runStatus as Record<string, string>)[v] ?? v;
  /** 组合任务的计划类型和当前状态，供任务列表摘要显示。 */
  const taskSummary = (task: ScheduledTask) =>
    `${scheduleTypeLabel(task.schedule_type)} · ${statusLabel(task.status)}`;
  /** 组合单次运行的触发来源和执行状态，供运行历史列表显示。 */
  const runSummary = (run: ScheduledTaskRun) =>
    `${runTriggerLabel(run.trigger)} · ${runStatusLabel(run.status)}`;
  /** 将预设配方写入创建表单，并重置计划输入组件。 */
  const applyRecipe = (recipe: Recipe) => {
    const labels = st.recipes[recipe.titleKey];
    setTitle(labels.title);
    setPrompt(recipe.prompt);
    setCreateSchedule(recipe.schedule);
    setContextMode("fresh_thread_per_run");
    setCreateNonce((n) => n + 1);
  };

  useEffect(() => {
    document.title = `${t.sidebar.scheduledTasks} - ${t.pages.appName}`;
  }, [t.pages.appName, t.sidebar.scheduledTasks]);

  useEffect(() => {
    if (!selectedTaskId) {
      return;
    }
    const stillVisible = filteredData.some(
      (task) => task.id === selectedTaskId,
    );
    if (!stillVisible) {
      setSelectedTaskId(filteredData[0]?.id ?? null);
      setEditing(false);
    }
  }, [filteredData, selectedTaskId]);

  useEffect(() => {
    if (!selectedTask) {
      setEditing(false);
      return;
    }
    setEditTitle(selectedTask.title);
    setEditPrompt(selectedTask.prompt);
    const spec = selectedTask.schedule_spec as {
      cron?: string;
      run_at?: string;
    };
    setEditSchedule({
      schedule_type: selectedTask.schedule_type,
      schedule_spec: {
        cron: typeof spec.cron === "string" ? spec.cron : undefined,
        run_at: typeof spec.run_at === "string" ? spec.run_at : undefined,
      },
      timezone: selectedTask.timezone || "UTC",
    });
    // 仅依赖任务 ID，后台刷新产生的新对象引用不会抹去用户正在编辑的内容。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTask?.id]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-4 p-6">
          <h1 className="text-2xl font-semibold">{t.sidebar.scheduledTasks}</h1>
          <div
            className="grid gap-2 rounded-lg border p-4"
            data-testid="scheduled-task-create-form"
          >
            <div className="font-medium">{st.create.title}</div>
            <div
              className="flex flex-wrap items-center gap-1"
              data-testid="schedule-recipes"
            >
              <span className="text-muted-foreground text-sm">
                {st.recipes.label}:
              </span>
              {RECIPES.map((recipe) => (
                <Button
                  key={recipe.id}
                  variant="outline"
                  size="sm"
                  onClick={() => applyRecipe(recipe)}
                >
                  <span aria-hidden>{recipe.icon}</span>
                  {st.recipes[recipe.titleKey].title}
                </Button>
              ))}
            </div>
            <div className="flex gap-2">
              <Button
                variant={
                  contextMode === "fresh_thread_per_run" ? "default" : "outline"
                }
                size="sm"
                onClick={() => setContextMode("fresh_thread_per_run")}
              >
                {st.context.fresh}
              </Button>
              <Button
                variant={contextMode === "reuse_thread" ? "default" : "outline"}
                size="sm"
                onClick={() => setContextMode("reuse_thread")}
              >
                {st.context.reuse}
              </Button>
            </div>
            {contextMode === "reuse_thread" && (
              <Input
                value={targetThreadId}
                onChange={(event) => setTargetThreadId(event.target.value)}
                placeholder={st.context.threadIdPlaceholder}
              />
            )}
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={st.create.taskTitle}
            />
            <Textarea
              rows={4}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={st.create.prompt}
            />
            <ScheduledTaskScheduleInput
              key={createNonce}
              initial={createSchedule}
              onChange={setCreateSchedule}
            />
            {formError && (
              <div className="text-destructive text-sm">{formError}</div>
            )}
            <Button
              onClick={() => {
                const hasSchedule =
                  Boolean(createSchedule.schedule_spec.cron) ||
                  Boolean(createSchedule.schedule_spec.run_at);
                if (
                  !title ||
                  !prompt ||
                  !hasSchedule ||
                  (contextMode === "reuse_thread" && !targetThreadId)
                ) {
                  setFormError(st.create.fillRequired);
                  return;
                }
                setFormError(null);
                createTask.mutate(
                  {
                    context_mode: contextMode,
                    thread_id:
                      contextMode === "reuse_thread" ? targetThreadId : null,
                    title,
                    prompt,
                    schedule_type: createSchedule.schedule_type,
                    schedule_spec: createSchedule.schedule_spec,
                    timezone: createSchedule.timezone || "UTC",
                  },
                  {
                    onSuccess: () => {
                      // 清空表单，确保后续创建任务不会继承本次输入。
                      setTitle("");
                      setPrompt("");
                      setTargetThreadId("");
                      setContextMode("fresh_thread_per_run");
                      setCreateSchedule({
                        schedule_type: "cron",
                        schedule_spec: { cron: "0 9 * * *" },
                        timezone: "",
                      });
                      setCreateNonce((n) => n + 1);
                    },
                  },
                );
              }}
              disabled={
                !title ||
                !prompt ||
                (!createSchedule.schedule_spec.cron &&
                  !createSchedule.schedule_spec.run_at) ||
                (contextMode === "reuse_thread" && !targetThreadId) ||
                createTask.isPending
              }
            >
              {st.create.submit}
            </Button>
          </div>
          {threadId && (
            <div className="text-muted-foreground text-sm">
              {st.detail.filteredByThread.replace("{id}", threadId)}
            </div>
          )}
          {queryError ? (
            <div
              className="text-destructive text-sm"
              data-testid="scheduled-task-load-error"
            >
              {st.detail.loadFailed}: {queryError.message}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              variant={statusFilter === "all" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("all")}
            >
              {st.filters.allStatuses}
            </Button>
            <Button
              variant={statusFilter === "enabled" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("enabled")}
            >
              {st.filters.enabled}
            </Button>
            <Button
              variant={statusFilter === "paused" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("paused")}
            >
              {st.filters.paused}
            </Button>
            <Button
              variant={statusFilter === "completed" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("completed")}
            >
              {st.filters.completed}
            </Button>
            <Button
              variant={statusFilter === "failed" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("failed")}
            >
              {st.filters.failed}
            </Button>
            <Button
              variant={typeFilter === "all" ? "default" : "outline"}
              size="sm"
              onClick={() => setTypeFilter("all")}
            >
              {st.filters.allTypes}
            </Button>
            <Button
              variant={typeFilter === "cron" ? "default" : "outline"}
              size="sm"
              onClick={() => setTypeFilter("cron")}
            >
              {st.filters.cron}
            </Button>
            <Button
              variant={typeFilter === "once" ? "default" : "outline"}
              size="sm"
              onClick={() => setTypeFilter("once")}
            >
              {st.filters.once}
            </Button>
          </div>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div
              data-testid="scheduled-task-list"
              className="flex flex-col gap-3"
            >
              {filteredData.map((task) => {
                const isSelected = selectedTask?.id === task.id;
                return (
                  <button
                    type="button"
                    key={task.id}
                    onClick={() => setSelectedTaskId(task.id)}
                    data-testid={`scheduled-task-item-${task.id}`}
                    className={cn(
                      "rounded-lg border p-4 text-left",
                      isSelected ? "border-foreground" : "border-border",
                    )}
                  >
                    <div className="font-medium">{task.title}</div>
                    <div className="text-muted-foreground text-sm">
                      {taskSummary(task)}
                    </div>
                  </button>
                );
              })}
            </div>
            <div
              className="rounded-lg border p-4"
              data-testid="scheduled-task-detail"
            >
              {selectedTask ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-lg font-semibold">
                      {selectedTask.title}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing((value) => !value)}
                    >
                      {editing ? st.actions.cancelEdit : st.actions.edit}
                    </Button>
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {st.detail.contextMode}:{" "}
                    {contextModeLabel(selectedTask.context_mode)}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {selectedTask.context_mode === "reuse_thread"
                      ? `${st.detail.thread}: ${selectedTask.thread_id ?? NONE}`
                      : `${st.detail.lastThread}: ${selectedTask.last_thread_id ?? NONE}`}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {st.detail.schedule}:{" "}
                    {scheduleTypeLabel(selectedTask.schedule_type)}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {st.detail.nextRun}:{" "}
                    {formatTimestamp(selectedTask.next_run_at, locale)}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {st.detail.lastRun}:{" "}
                    {formatTimestamp(selectedTask.last_run_at, locale)}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {st.detail.lastRunId}: {selectedTask.last_run_id ?? NONE}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {st.detail.lastError}: {selectedTask.last_error ?? NONE}
                  </div>
                  {editing ? (
                    <div className="flex flex-col gap-2 rounded-lg border p-3">
                      <Input
                        value={editTitle}
                        onChange={(event) => setEditTitle(event.target.value)}
                        placeholder={st.edit.titlePlaceholder}
                      />
                      <Textarea
                        rows={4}
                        value={editPrompt}
                        onChange={(event) => setEditPrompt(event.target.value)}
                        placeholder={st.edit.promptPlaceholder}
                      />
                      <ScheduledTaskScheduleInput
                        key={selectedTask.id}
                        initial={editSchedule}
                        onChange={setEditSchedule}
                        scheduleTypeLocked
                      />
                      <Button
                        size="sm"
                        onClick={() =>
                          updateTask.mutate({
                            title: editTitle,
                            prompt: editPrompt,
                            schedule_spec: editSchedule.schedule_spec,
                            timezone: editSchedule.timezone || "UTC",
                          })
                        }
                        disabled={updateTask.isPending}
                      >
                        {st.edit.submit}
                      </Button>
                    </div>
                  ) : (
                    <div className="text-sm">{selectedTask.prompt}</div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        selectedTask.status === "paused"
                          ? resumeTask.mutate(selectedTask.id)
                          : pauseTask.mutate(selectedTask.id)
                      }
                    >
                      {selectedTask.status === "paused"
                        ? st.actions.resume
                        : st.actions.pause}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => triggerTask.mutate(selectedTask.id)}
                    >
                      {st.actions.trigger}
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => setDeleteOpen(true)}
                    >
                      {st.actions.delete}
                    </Button>
                  </div>
                  <div data-testid="scheduled-task-runs">
                    {(taskRunsQuery.data ?? []).length === 1
                      ? st.detail.runsCountOne.replace(
                          "{count}",
                          String((taskRunsQuery.data ?? []).length),
                        )
                      : st.detail.runsCount.replace(
                          "{count}",
                          String((taskRunsQuery.data ?? []).length),
                        )}
                  </div>
                  <div
                    className="flex flex-col gap-2"
                    data-testid="scheduled-task-run-list"
                  >
                    {(taskRunsQuery.data ?? []).length > 0 ? (
                      (taskRunsQuery.data ?? []).map((run) => (
                        <div
                          key={run.id}
                          className="rounded-md border p-3 text-sm"
                        >
                          <div className="font-medium">{runSummary(run)}</div>
                          <div className="text-muted-foreground text-xs">
                            {run.run_id ?? NONE}
                          </div>
                          <div className="text-muted-foreground text-xs">
                            {formatTimestamp(run.scheduled_for, locale)}
                          </div>
                          {run.error && (
                            <div className="text-destructive text-xs">
                              {run.error}
                            </div>
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="text-muted-foreground text-sm">
                        {st.detail.noRuns}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-muted-foreground text-sm">
                  {st.detail.noSelection}
                </div>
              )}
            </div>
          </div>
        </div>
      </WorkspaceBody>

      {/* 删除前需二次确认，交互方式与代理卡片一致。 */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{st.actions.delete}</DialogTitle>
            <DialogDescription>{st.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteTask.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (selectedTask) {
                  deleteTask.mutate(selectedTask.id, {
                    onSuccess: () => setDeleteOpen(false),
                  });
                }
              }}
              disabled={deleteTask.isPending}
            >
              {deleteTask.isPending ? t.common.loading : st.actions.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </WorkspaceContainer>
  );
}
