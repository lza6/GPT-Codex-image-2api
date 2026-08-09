export type UsageStats = {
  success_24h: number;
  failed_24h: number;
  total_24h: number;
  by_summary: Record<string, number>;
  recent: Array<{ time: string; summary: string; status: string }>;
  hours?: number;
};

export function fetchSchedulerDashboard() {
  return httpRequest<SchedulerDashboard>("/api/dashboard/scheduler");
}

export function fetchOpsOverview() {
  return httpRequest<OpsOverview>("/api/dashboard/ops");
}

export function fetchUsageStats(hours?: number) {
  const params = hours && hours !== 24 ? `?hours=${hours}` : "";
  return httpRequest<UsageStats>(`/api/dashboard/usage${params}`);
}