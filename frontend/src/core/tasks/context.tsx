import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import { computeNextSubtask, subtaskNotification } from "./subtask-update";
import type { Subtask } from "./types";

/** 子任务状态容器向后代组件提供的状态与更新接口。 */
export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  // 始终镜像渲染时最新的 tasks。异步回填通过此引用读写，避免闭包快照覆盖当前状态。
  tasksRef: React.RefObject<Record<string, Subtask>>;
  setTasks: (tasks: Record<string, Subtask>) => void;
}

/** 在子任务卡片树中共享状态的 React 上下文。 */
export const SubtaskContext = createContext<SubtaskContextValue>({
  tasks: {},
  tasksRef: { current: {} },
  setTasks: () => {},
});

/** 提供子任务状态及其更新能力。 */
export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<Record<string, Subtask>>({});
  const tasksRef = useRef(tasks);
  // 每次渲染均更新引用，确保异步回调读取的不是陈旧映射。
  tasksRef.current = tasks;
  return (
    <SubtaskContext.Provider value={{ tasks, tasksRef, setTasks }}>
      {children}
    </SubtaskContext.Provider>
  );
}

/** 读取子任务上下文；必须在子任务提供器内使用。 */
export function useSubtaskContext() {
  const context = useContext(SubtaskContext);
  if (context === undefined) {
    throw new Error(
      "useSubtaskContext must be used within a SubtaskContext.Provider",
    );
  }
  return context;
}

/** 按标识读取单个子任务。 */
export function useSubtask(id: string) {
  const { tasks } = useSubtaskContext();
  return tasks[id];
}

/** 返回可合并单个子任务流式更新的回调。 */
export function useUpdateSubtask() {
  const { tasksRef, setTasks } = useSubtaskContext();
  const shouldNotifyAfterRenderRef = useRef(false);
  // 不设置依赖：必须在每次渲染后检查渲染期间写入的引用。
  useEffect(() => {
    if (!shouldNotifyAfterRenderRef.current) {
      return;
    }
    shouldNotifyAfterRenderRef.current = false;
    setTasks({ ...tasksRef.current });
  });

  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string }) => {
      // 通过引用读取最新状态而非闭包快照，避免迟到的步骤回填覆盖 SSE 步骤、状态或并发新增的兄弟子任务。
      const current = tasksRef.current;
      const { next, becameTerminal, changed } = computeNextSubtask(
        current[task.id],
        task,
      );

      current[task.id] = next;

      // 仅在真实状态变化时更新。终态工具消息会在每次列表渲染重新解析，若只检查字段存在会持续创建新引用并触发循环。
      const notify = subtaskNotification(task, { becameTerminal, changed });
      if (notify === "eager") {
        setTasks({ ...current });
      } else if (notify === "deferred") {
        shouldNotifyAfterRenderRef.current = true;
      }
    },
    [tasksRef, setTasks],
  );

  return updateSubtask;
}
