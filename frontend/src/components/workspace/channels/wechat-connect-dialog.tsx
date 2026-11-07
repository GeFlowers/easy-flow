"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2Icon, CopyIcon, LoaderCircleIcon } from "lucide-react";
import Image from "next/image";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  cancelWechatLogin,
  connectChannelProvider,
  getWechatLogin,
  listChannelConnections,
  startWechatLogin,
} from "@/features/channels/api";
import {
  channelConnectionsQueryKey,
  channelProviderQueryKey,
} from "@/features/channels/hooks";
import type { ChannelConnectResponse } from "@/features/channels/types";

/** 先完成微信扫码登录，再展示将微信账号绑定到当前项目用户的一次性命令。 */
export function WechatConnectDialog({
  open,
  onOpenChange,
  initiallyAuthenticated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initiallyAuthenticated: boolean;
}) {
  const queryClient = useQueryClient();
  const [loginId, setLoginId] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [binding, setBinding] = useState<ChannelConnectResponse | null>(null);
  const [bindingVersion, setBindingVersion] = useState(0);
  // 打开窗口时固定起始步骤，避免后台刷新提供商状态后重复发起扫码。
  const [existingLogin] = useState(initiallyAuthenticated);

  useEffect(() => {
    if (!open) return;
    let closed = false;
    let activeLoginId: string | null = null;
    setLoginId(null);
    setBinding(null);
    setError(null);
    if (!existingLogin) {
      void startWechatLogin()
        .then((result) => {
          activeLoginId = result.login_id;
          if (closed) {
            void cancelWechatLogin(result.login_id).catch(() => undefined);
            return;
          }
          setLoginId(result.login_id);
        })
        .catch((reason: unknown) => {
          if (!closed)
            setError(
              reason instanceof Error ? reason.message : "无法生成微信二维码",
            );
        });
    }
    return () => {
      closed = true;
      if (activeLoginId)
        void cancelWechatLogin(activeLoginId).catch(() => undefined);
    };
  }, [open, refresh, existingLogin]);

  const loginQuery = useQuery({
    queryKey: ["wechatLogin", loginId],
    queryFn: () => getWechatLogin(loginId!),
    enabled: open && loginId !== null,
    retry: false,
    refetchInterval: (query) =>
      query.state.error ||
      ["confirmed", "expired", "failed", "canceled"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 1500,
  });
  const authenticated =
    existingLogin || loginQuery.data?.status === "confirmed";

  useEffect(() => {
    if (!open || !authenticated) return;
    let closed = false;
    setBinding(null);
    setError(null);
    void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
    void connectChannelProvider("wechat")
      .then((result) => {
        if (!closed) setBinding(result);
      })
      .catch((reason: unknown) => {
        if (!closed)
          setError(
            reason instanceof Error ? reason.message : "无法生成微信绑定码",
          );
      });
    return () => {
      closed = true;
    };
  }, [open, authenticated, bindingVersion, queryClient]);

  const connectionsQuery = useQuery({
    queryKey: channelConnectionsQueryKey,
    queryFn: listChannelConnections,
    enabled: open && authenticated,
    refetchInterval: (query) =>
      query.state.data?.some(
        (item) => item.provider === "wechat" && item.status === "connected",
      )
        ? false
        : 2000,
  });
  const connected =
    authenticated &&
    !connectionsQuery.isFetching &&
    connectionsQuery.data?.some(
      (item) => item.provider === "wechat" && item.status === "connected",
    );
  useEffect(() => {
    if (connected)
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
  }, [connected, queryClient]);

  const status = loginQuery.data?.status ?? "starting";
  const failure =
    error ??
    loginQuery.data?.error ??
    (loginQuery.error instanceof Error ? loginQuery.error.message : null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>连接个人微信</DialogTitle>
          <DialogDescription>
            先用手机微信扫码并确认登录，再向微信中的机器人发送绑定命令。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 text-sm">
          {connected ? (
            <div className="flex items-center gap-2">
              <CheckCircle2Icon className="text-green-600" />
              微信已绑定，现在可以向机器人直接发送问题。
            </div>
          ) : authenticated ? (
            <>
              <p>
                微信已登录，请在微信中打开刚连接的机器人会话，发送以下命令：
              </p>
              {binding ? (
                <div className="flex items-center gap-2 rounded-md border p-3">
                  <code className="min-w-0 flex-1 break-all select-all">
                    /connect {binding.code}
                  </code>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="复制微信绑定命令"
                    onClick={() => {
                      void navigator.clipboard
                        .writeText(`/connect ${binding.code}`)
                        .then(() => toast.success("绑定命令已复制"))
                        .catch(() => toast.error("复制失败，请手动复制命令"));
                    }}
                  >
                    <CopyIcon className="size-4" />
                  </Button>
                </div>
              ) : !failure ? (
                <p className="text-muted-foreground">正在生成绑定命令…</p>
              ) : null}
              <p className="text-muted-foreground">
                绑定码有效期为 10 分钟。收到绑定成功提示后，即可开始聊天。
              </p>
            </>
          ) : (
            <>
              {loginQuery.data?.qr_image ? (
                <div className="mx-auto w-fit rounded-md bg-white p-3">
                  <Image
                    src={loginQuery.data.qr_image}
                    alt="微信登录二维码"
                    width={240}
                    height={240}
                    unoptimized
                  />
                </div>
              ) : !failure && status === "starting" ? (
                <div className="flex items-center justify-center gap-2 py-10">
                  <LoaderCircleIcon className="size-5 animate-spin" />
                  正在获取二维码…
                </div>
              ) : null}
              {!failure ? (
                <p className="text-muted-foreground text-center">
                  {status === "scanned"
                    ? "已扫码，请在手机微信中确认登录。"
                    : "请使用手机微信扫一扫；二维码约 3 分钟内有效。"}
                </p>
              ) : null}
            </>
          )}
          {failure ? (
            <p role="alert" className="text-destructive">
              {failure}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          {!connected ? (
            <Button
              variant="outline"
              onClick={() =>
                authenticated
                  ? setBindingVersion((value) => value + 1)
                  : setRefresh((value) => value + 1)
              }
            >
              {authenticated ? "重新生成绑定码" : "刷新二维码"}
            </Button>
          ) : null}
          <Button onClick={() => onOpenChange(false)}>
            {connected ? "完成" : "关闭"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
