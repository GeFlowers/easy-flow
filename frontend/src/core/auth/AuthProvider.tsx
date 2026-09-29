"use client";

import { useRouter, usePathname } from "next/navigation";
import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";

import { type User, buildLoginUrl } from "./types";

// 为使用方重新导出用户类型。
export type { User };

/**
 * 提供给消费组件的认证上下文。
 */
interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  applyUser: (user: User | null) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/** AuthProvider 所需的初始服务端用户和子组件。 */
interface AuthProviderProps {
  children: ReactNode;
  initialUser: User | null;
}

/**
 * 应用的统一认证上下文提供组件。
 *
 * 遵循 RFC-001：
 * - 仅保存用于展示的用户信息，绝不保存 JWT 或令牌；
 * - ``initialUser`` 来自服务端守卫，避免客户端界面闪烁；
 * - 提供登出和刷新用户信息的能力。
 */
export function AuthProvider({ children, initialUser }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(initialUser);
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const isAuthenticated = user !== null;

  /**
   * 应用调用方（例如横幅探测）已获取的用户值。该操作等价于 setUser，但以稳定名称
   * 对外暴露，使消费方无需接触 React 内部实现。
   */
  const applyUser = useCallback((next: User | null) => {
    setUser(next);
  }, []);

  /**
   * 从 FastAPI 获取当前用户。
   * 当 ``initialUser`` 可能陈旧时使用（例如标签页曾处于非活动状态）。
   */
  const refreshUser = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await fetch("/api/v1/auth/me", {
        credentials: "include",
      });

      if (res.ok) {
        const data = await res.json();
        setUser(data);
      } else if (res.status === 401) {
        // 会话已过期或无效。
        setUser(null);
        // 仅在受保护路由中跳转至登录页。
        if (pathname?.startsWith("/workspace")) {
          router.push(buildLoginUrl(pathname));
        }
      }
    } catch (err) {
      console.error("Failed to refresh user:", err);
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, [pathname, router]);

  /**
   * 登出：调用 FastAPI 登出端点并清除本地状态。
   * 遵循 RFC-001：立即清除本地状态，不等待服务端确认。
   *
   * Gateway 不可达时，fetch 会静默失败；SPA 的 ``router.push("/")`` 会让用户停留在
   * ``/``，同时仍持有陈旧的 React 状态以及所有进行中的 SSE / fetch / 查询订阅。
   * 因此回退为硬导航（``window.location.href``），像旧版表单 POST 登出一样丢弃全部
   * 客户端状态。
   */
  const logout = useCallback(async () => {
    // 立即清除本地状态，防止界面闪烁。
    setUser(null);

    let logoutFailed = false;
    try {
      const res = await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) logoutFailed = true;
    } catch (err) {
      console.error("Logout request failed:", err);
      logoutFailed = true;
    }

    if (logoutFailed && typeof window !== "undefined") {
      // 硬导航确保拆除全部进行中的订阅，与 Gateway 故障期间旧版表单 POST 登出的行为一致。
      window.location.href = "/";
      return;
    }

    // 跳转至首页。
    router.push("/");
  }, [router]);

  /**
   * 处理可见性变化：标签页重新可见时刷新用户。
   * 节流为最多每 60 秒一次，避免快速切换标签页时频繁请求后端。
   */
  const lastCheckRef = React.useRef(0);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible" || user === null) return;
      const now = Date.now();
      if (now - lastCheckRef.current < 60_000) return;
      lastCheckRef.current = now;
      void refreshUser();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [user, refreshUser]);

  const value: AuthContextType = {
    user,
    isAuthenticated,
    isLoading,
    logout,
    refreshUser,
    applyUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * 访问认证上下文的 Hook。
 * 在 AuthProvider 外使用会抛出异常，这是为保证正确使用方式而有意设计的。
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

/**
 * 强制要求认证的 Hook：未认证时跳转至登录页。
 * 可作为服务端守卫之外的客户端侧检查。
 */
export function useRequireAuth(): AuthContextType {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // 仅在确定用户未认证时跳转，不能仅因仍在加载就跳转。
    if (!auth.isLoading && !auth.isAuthenticated) {
      router.push(buildLoginUrl(pathname || "/workspace"));
    }
  }, [auth.isAuthenticated, auth.isLoading, router, pathname]);

  return auth;
}
