"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useCallback, useRef } from "react";

/** 校验 SSO 回跳地址，只允许站内相对路径以避免开放重定向。 */
function validateNextParam(next: string | null): string {
  if (!next) return "/workspace";
  if (!next.startsWith("/") || next.startsWith("//")) return "/workspace";
  if (next.startsWith("http://") || next.startsWith("https://"))
    return "/workspace";
  if (next.includes(":")) return "/workspace";
  return next;
}

/** 确认 SSO 会话已写入后，显示结果并跳转到安全的目标地址。 */
export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    "loading",
  );
  const calledRef = useRef(false);

  /** 仅执行一次认证状态确认，避免开发模式重复 Effect 导致多次跳转。 */
  const doAuthCheck = useCallback(async () => {
    if (calledRef.current) return;
    calledRef.current = true;

    const next = validateNextParam(searchParams.get("next"));

    try {
      const res = await fetch("/api/v1/auth/me", { credentials: "include" });

      if (res.ok) {
        setStatus("success");
        // 短暂展示成功状态，避免页面看起来无反馈地立即跳转。
        setTimeout(() => router.replace(next), 300);
      } else {
        setStatus("error");
        setTimeout(() => router.replace("/login?error=sso_failed"), 1500);
      }
    } catch {
      setStatus("error");
      setTimeout(() => router.replace("/login?error=sso_failed"), 1500);
    }
  }, [searchParams, router]);

  useEffect(() => {
    void doAuthCheck();
  }, [doAuthCheck]);

  return (
    <div className="bg-background relative flex min-h-screen items-center justify-center">
      <div className="text-center">
        {status === "loading" && (
          <>
            <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-current border-t-transparent" />
            <p className="text-muted-foreground">Signing you in...</p>
          </>
        )}
        {status === "success" && (
          <p className="text-muted-foreground">Redirecting...</p>
        )}
        {status === "error" && (
          <p className="text-muted-foreground">
            Authentication failed. Redirecting to login...
          </p>
        )}
      </div>
    </div>
  );
}
