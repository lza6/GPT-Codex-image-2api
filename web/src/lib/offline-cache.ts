"use client";

/**
 * 离线缓存工具 — 将 API 响应缓存到 localStorage，断网时读取缓存。
 *
 * 用法：
 *   const data = getCache<Account[]>("accounts") ?? await fetchAccounts();
 *   setCache("accounts", data);
 */
const CACHE_PREFIX = "oc_";
const CACHE_TTL = 300_000; // 5 min

interface CacheEntry<T> {
  data: T;
  ttl: number;
}

export function getCache<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key);
    if (!raw) return null;
    const entry: CacheEntry<T> = JSON.parse(raw);
    if (Date.now() > entry.ttl) {
      localStorage.removeItem(CACHE_PREFIX + key);
      return null;
    }
    return entry.data;
  } catch {
    return null;
  }
}

export function setCache(key: string, data: unknown): void {
  try {
    const entry: CacheEntry<unknown> = { data, ttl: Date.now() + CACHE_TTL };
    localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(entry));
  } catch {
    // localStorage full, ignore
  }
}

export function hasCache(key: string): boolean {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key);
    if (!raw) return false;
    const entry: CacheEntry<unknown> = JSON.parse(raw);
    return Date.now() <= entry.ttl;
  } catch {
    return false;
  }
}