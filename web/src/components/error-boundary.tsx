"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type ErrorBoundaryProps = {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
};

type ErrorBoundaryState = {
  error: Error | null;
  errorInfo: ErrorInfo | null;
  expanded: boolean;
};

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { error: null, errorInfo: null, expanded: false };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo });
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ error: null, errorInfo: null, expanded: false });
  };

  toggleExpanded = () => {
    this.setState((prev) => ({ expanded: !prev.expanded }));
  };

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback;
    }

    const { error, errorInfo, expanded } = this.state;

    return (
      <div className="flex min-h-[240px] items-center justify-center p-6">
        <Card className="w-full max-w-lg">
          <CardHeader className="flex flex-col items-center gap-3 text-center">
            <div className="flex size-12 items-center justify-center rounded-2xl bg-rose-50 dark:bg-rose-900/20">
              <AlertTriangle className="size-6 text-rose-500" />
            </div>
            <CardTitle className="text-lg">页面渲染异常</CardTitle>
            <p className="text-muted-foreground text-sm">
              发生了意外错误，请尝试刷新或重试。如果问题持续存在，请检查控制台日志。
            </p>
          </CardHeader>
          <CardContent className="flex flex-col items-center gap-4">
            <Button variant="outline" onClick={this.handleRetry}>
              <RefreshCw className="mr-1.5 size-4" />
              重试
            </Button>

            <button
              type="button"
              onClick={this.toggleExpanded}
              className="inline-flex items-center gap-1 text-xs text-stone-400 transition hover:text-stone-600 dark:text-stone-500 dark:hover:text-stone-300"
            >
              {expanded ? (
                <ChevronDown className="size-3.5" />
              ) : (
                <ChevronRight className="size-3.5" />
              )}
              错误详情
            </button>

            {expanded && (
              <div className="w-full space-y-2 rounded-2xl bg-stone-50 p-4 dark:bg-stone-800/50">
                <p className="break-all text-xs font-medium text-rose-600 dark:text-rose-400">
                  {error.name}: {error.message}
                </p>
                {error.stack && (
                  <pre className={cn(
                    "max-h-[200px] overflow-auto whitespace-pre-wrap break-all text-[11px] leading-relaxed text-stone-500 dark:text-stone-400",
                    "scrollbar-thin scrollbar-track-transparent scrollbar-thumb-stone-200 dark:scrollbar-thumb-stone-700",
                  )}>
                    {error.stack}
                  </pre>
                )}
                {errorInfo?.componentStack && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[11px] font-medium text-stone-400 hover:text-stone-600 dark:text-stone-500 dark:hover:text-stone-300">
                      组件栈
                    </summary>
                    <pre className="mt-1 max-h-[120px] overflow-auto whitespace-pre-wrap break-all text-[11px] leading-relaxed text-stone-400 dark:text-stone-500">
                      {errorInfo.componentStack}
                    </pre>
                  </details>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }
}