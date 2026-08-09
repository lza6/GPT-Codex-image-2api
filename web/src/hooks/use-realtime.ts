"use client";

/**
 * 可复用的 SSE 实时数据订阅 hook。
 *
 * 用法：
 * ```tsx
 * function AccountList() {
 *   const accounts = useRealtime('accounts:list', []);
 *   // 账号列表自动更新，无需手动刷新
 * }
 * ```
 *
 * 支持：
 * - 自动重连（指数退避 1s → 30s max）
 * - 页面可见性感知（隐藏时断开，回到前台重连）
 * - 组件卸载时自动清理
 * - 可选的立即刷新回调
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { getStoredAuthKey } from "@/store/auth";

export interface RealtimeOptions {
  /** SSE 端点路径（默认 /api/dashboard/stream） */
  endpoint?: string;
  /** 是否启用自动重连（默认 true） */
  reconnect?: boolean;
  /** 兜底轮询间隔 ms（默认 0 = 不轮询） */
  pollInterval?: number;
  /** 消息通道过滤（只处理指定 channel 的消息） */
  channel?: string;
}

type RealtimeStatus = "connecting" | "connected" | "disconnected" | "error";

/**
 * 通用 SSE 实时数据订阅 hook。
 *
 * @param channel 数据通道名（如 "accounts:list"）
 * @param initial 初始值
 * @param extractor 从 SSE 消息中提取数据的函数，默认取 payload.data
 * @param options 配置选项
 */
export function useRealtime<T>(
  channel: string,
  initial: T,
  extractor?: (payload: Record<string, unknown>) => T | undefined,
  options: RealtimeOptions = {},
) {
  const [data, setData] = useState<T>(initial);
  const [status, setStatus] = useState<RealtimeStatus>("disconnected");
  const sourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const retryDelayRef = useRef(1000);
  const mountedRef = useRef(true);
  const reconnectRef = useRef(false);
  const channelRef = useRef(channel);
  channelRef.current = channel;

  const disconnect = useCallback(() => {
    reconnectRef.current = false;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    sourceRef.current?.close();
    sourceRef.current = null;
    if (mountedRef.current) setStatus("disconnected");
  }, []);

  const connect = useCallback(async () => {
    if (sourceRef.current || !mountedRef.current) return;

    const token = await getStoredAuthKey();
    if (!token || !mountedRef.current) return;

    const endpoint = options.endpoint ?? "/api/dashboard/stream";

    try {
      const source = new EventSource(
        `${endpoint}?token=${encodeURIComponent(token)}`,
      );
      sourceRef.current = source;

      if (mountedRef.current) setStatus("connecting");

      source.onopen = () => {
        retryDelayRef.current = 1000;
        if (mountedRef.current) setStatus("connected");
      };

      source.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as Record<string, unknown>;
          const msgChannel = (payload as { channel?: string }).channel ?? "";
          const filterChannel = options.channel ?? channelRef.current;

          // 通道过滤：只处理匹配通道的消息
          if (filterChannel && msgChannel && msgChannel !== filterChannel) {
            return;
          }

          // 使用自定义提取器
          if (extractor) {
            const extracted = extractor(payload);
            if (extracted !== undefined) {
              setData(extracted);
            }
            return;
          }

          // 默认：尝试 payload.data，或 payload 中匹配 channel 名的字段
          const payloadData = payload.data as T | undefined;
          if (payloadData !== undefined) {
            setData(payloadData);
          }
        } catch {
          // 忽略解析错误
        }
      };

      source.onerror = () => {
        source.close();
        sourceRef.current = null;
        if (mountedRef.current) setStatus("error");
        scheduleReconnect();
      };
    } catch {
      sourceRef.current = null;
      if (mountedRef.current) setStatus("error");
      scheduleReconnect();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.endpoint, options.channel, extractor]);

  const scheduleReconnect = useCallback(() => {
    if (options.reconnect === false) return;
    if (reconnectRef.current || !mountedRef.current) return;
    reconnectRef.current = true;
    reconnectTimerRef.current = setTimeout(() => {
      reconnectRef.current = false;
      if (mountedRef.current && !document.hidden) {
        void connect();
      }
    }, retryDelayRef.current);
    retryDelayRef.current = Math.min(retryDelayRef.current * 2, 30000);
  }, [options.reconnect, connect]);

  useEffect(() => {
    mountedRef.current = true;
    void connect();

    // 兜底轮询
    if (options.pollInterval && options.pollInterval > 0) {
      pollTimerRef.current = setInterval(() => {
        if (!document.hidden && mountedRef.current && !sourceRef.current) {
          void connect();
        }
      }, options.pollInterval);
    }

    // 页面可见性处理
    const onVisibility = () => {
      if (document.hidden) {
        disconnect();
      } else {
        retryDelayRef.current = 1000;
        void connect();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      mountedRef.current = false;
      disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
    };
  }, [connect, disconnect, options.pollInterval]);

  // 手动刷新函数
  const refresh = useCallback(() => {
    disconnect();
    retryDelayRef.current = 1000;
    void connect();
  }, [disconnect, connect]);

  return { data, status, refresh };
}