"use client";

/**
 * 6.1：统一「异步按钮」——点击后必须有 loading 反馈，避免"点了没反应"。
 *
 * 设计约定（与 web/src/lib/request.ts 拦截器配套）：
 * - 拦截器不 toast；异步错误由调用方 catch 后经 error.userMessage 展示。
 * - 本组件只负责「点击 → isLoading 禁用 + spinner」与「可选成功后清态」，
 *   不替调用方做 toast（避免双重 toast 历史 bug）。
 */
import * as React from "react";
import { LoaderCircle } from "lucide-react";

import { Button } from "./button";
import { cn } from "@/lib/utils";

type BaseButtonProps = React.ComponentProps<typeof Button>;

export type AsyncButtonProps = Omit<BaseButtonProps, "disabled" | "onClick"> & {
  isLoading?: boolean;
  loadingText?: string;
  onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void | Promise<unknown>;
  /** 成功后自动退出 loading（默认 true；若调用方自己管理可设 false）。 */
  autoReset?: boolean;
  /** 图标（loading 时替换为 spinner）。 */
  icon?: React.ReactNode;
};

function AsyncButtonBase(
  { isLoading = false, loadingText, onClick, autoReset = true, icon, children, className, ...rest }: AsyncButtonProps,
  ref: React.Ref<HTMLButtonElement>,
) {
  const [internalLoading, setInternalLoading] = React.useState(false);
  const loading = isLoading || internalLoading;
  const mountedRef = React.useRef(true);

  React.useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const handleClick = async (event: React.MouseEvent<HTMLButtonElement>) => {
    if (loading || !onClick) return;
    setInternalLoading(true);
    try {
      await onClick(event);
    } finally {
      if (mountedRef.current && autoReset) {
        setInternalLoading(false);
      }
    }
  };

  return (
    <Button
      ref={ref}
      className={cn(className)}
      disabled={loading}
      onClick={(event) => {
        void handleClick(event);
      }}
      {...rest}
    >
      {loading ? (
        <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
      ) : (
        icon
      )}
      {loading ? (loadingText ?? children) : children}
    </Button>
  );
}

const AsyncButton = React.forwardRef<HTMLButtonElement, AsyncButtonProps>(AsyncButtonBase);
AsyncButton.displayName = "AsyncButton";

export { AsyncButton };
