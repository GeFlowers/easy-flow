import { redirect } from "next/navigation";

/** 将工作区入口重定向到新建会话页。 */
export default function WorkspacePage() {
  return redirect("/workspace/chats/new");
}
