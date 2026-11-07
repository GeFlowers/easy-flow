/** 代表代理执行进度中的单个待办事项。 */
export interface Todo {
  content?: string;
  status?: "pending" | "in_progress" | "completed";
}
