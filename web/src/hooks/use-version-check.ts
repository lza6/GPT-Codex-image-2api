"use client";

import { useMemo, useState } from "react";

import webConfig from "@/constants/common-env";
import type { ReleaseInfo } from "@/lib/release";

// 内部定制化部署：仅使用构建时注入的本地版本与 changelog，不访问外部远程源。
function readLocalReleases(): ReleaseInfo[] {
  try {
    return JSON.parse(process.env.NEXT_PUBLIC_APP_RELEASES || "[]");
  } catch {
    return [];
  }
}

export function useVersionCheck() {
  const currentVersion = webConfig.appVersion;
  const localReleases = useMemo(readLocalReleases, []);
  const [releases, setReleases] = useState<ReleaseInfo[]>(localReleases);
  const [checking, setChecking] = useState(false);
  const [open, setOpen] = useState(false);
  // 内部部署无远程版本源，latestVersion 恒等于当前版本，不提示"新版本"。
  const latestVersion = currentVersion;
  const hasNewVersion = false;

  const openReleaseModal = () => {
    setOpen(true);
    setReleases(localReleases);
  };

  return {
    open,
    setOpen,
    openReleaseModal,
    latestVersion,
    releases,
    checking,
    hasNewVersion,
    checkLatestRelease: openReleaseModal,
  };
}
