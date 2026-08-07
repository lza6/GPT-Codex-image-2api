"use client";

import { LoaderCircle } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";

import { ChatPanel } from "./components/chat-panel";

// v2.9.0：裁剪 PPT/PSD/Search/Skills 安装页（用户需求：只保留生图+号池+IP池+图片管理+日志+看板）
// 对话面板保留——chat completions / responses 路由是生图底层依赖，不能删，仅前端保留调试入口
export default function DebugPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[calc(100vh-49px)] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-49px)] w-full max-w-[1600px] flex-col gap-4 px-4 pt-3 pb-6 md:px-8">
      <ChatPanel />
    </div>
  );
}
