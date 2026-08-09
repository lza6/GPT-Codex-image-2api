"use client";

import { useEffect, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

type ImageThumbnailProps = {
  src: string;
  thumbnailSrc?: string;
  alt?: string;
  className?: string;
  imageClassName?: string;
};

export function getImageThumbnailUrl(src: string) {
  // 上游直链（chatgpt.com / oaidalle）→ 走后端代理下载
  if (src.includes("chatgpt.com") || src.includes("oaidalle")) {
    const base = typeof window !== "undefined" ? window.location.origin : "";
    return `${base}/api/images/proxy-download?url=${encodeURIComponent(src)}`;
  }
  const marker = "/images/";
  const index = src.indexOf(marker);
  if (index < 0) return src;
  return `${src.slice(0, index)}/image-thumbnails/${src.slice(index + marker.length)}`;
}

export function ImageThumbnail({ src, thumbnailSrc, alt = "", className, imageClassName }: ImageThumbnailProps) {
  const initialSrc = useMemo(() => thumbnailSrc || getImageThumbnailUrl(src), [src, thumbnailSrc]);
  const [currentSrc, setCurrentSrc] = useState(initialSrc);
  // v2.9.0：防原图也失败时反复请求 —— 记录已降级状态
  const [fallbackFailed, setFallbackFailed] = useState(false);

  useEffect(() => {
    setCurrentSrc(initialSrc);
    setFallbackFailed(false);
  }, [initialSrc]);

  // fallbackFailed 时显示占位框，不渲染 img（避免破图 + 不再请求）
  if (fallbackFailed) {
    return (
      <span className={cn("flex items-center justify-center bg-stone-100 text-stone-400", className)}>
        <svg className="size-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      </span>
    );
  }

  return (
    <span className={cn("block overflow-hidden bg-stone-100", className)}>
      <img
        src={currentSrc}
        alt={alt}
        className={cn("h-full w-full object-cover", imageClassName)}
        loading="lazy"
        decoding="async"
        onError={() => {
          if (currentSrc !== src) {
            // 缩略图失败 → 降级到原图
            setCurrentSrc(src);
          } else {
            // 原图也失败 → 显示占位框，不再重试
            setFallbackFailed(true);
          }
        }}
      />
    </span>
  );
}
