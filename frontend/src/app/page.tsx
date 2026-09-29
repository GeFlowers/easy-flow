import { redirect } from "next/navigation";

/** 将站点根路径直接导向登录入口。 */
export default function HomePage() {
  redirect("/login");
}
