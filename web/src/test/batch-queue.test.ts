import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as BatchQueueModule from "../store/batch-queue";

// ─── localStorage mock ──────────────────────────────────────────────

function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
    key: () => null,
    get length() {
      return store.size;
    },
  };
}

// ─── 类型与工具 ─────────────────────────────────────────────────────

type EnqueueInput = Omit<
  BatchQueueModule.BatchQueueItem,
  "id" | "status" | "progress" | "results" | "createdAt" | "completedAt"
> & { id?: string };

function makeEnqueueInput(
  tokens: string[] = ["token-1", "token-2"],
  overrides: Partial<Pick<EnqueueInput, "action" | "label" | "id">> = {},
): EnqueueInput {
  return {
    action: overrides.action ?? "refresh",
    label: overrides.label ?? "测试批量操作",
    tokens,
    id: overrides.id,
  };
}

// 每次用例重置模块，保证模块级 queue/abortControllers/listeners 干净，
// 同时用新的 localStorage mock 隔离持久化数据。
let mod: typeof BatchQueueModule;

beforeEach(async () => {
  vi.resetModules();
  globalThis.localStorage = createStorageMock();
  mod = await import("../store/batch-queue");
});

// ─── 1. enqueue - 添加任务到队列 ───────────────────────────────────

describe("enqueue - 添加任务到队列", () => {
  it("返回 id 并将任务加入运行队列（默认 queued/progress=0/results={}）", () => {
    const id = mod.enqueue(makeEnqueueInput());

    expect(id).toBeTruthy();
    const q = mod.getQueue();
    expect(q).toHaveLength(1);
    expect(q[0]).toMatchObject({
      id,
      action: "refresh",
      label: "测试批量操作",
      tokens: ["token-1", "token-2"],
      status: "queued",
      progress: 0,
      results: {},
    });
    expect(q[0].createdAt).toBeTruthy();
    expect(q[0].completedAt).toBeUndefined();
  });

  it("使用调用方提供的自定义 id", () => {
    const id = mod.enqueue(makeEnqueueInput(["token-1"], { id: "custom-id" }));
    expect(id).toBe("custom-id");
    expect(mod.getQueue()[0].id).toBe("custom-id");
  });

  it("未提供 id 时生成互不相同的唯一 id", () => {
    const a = mod.enqueue(makeEnqueueInput());
    const b = mod.enqueue(makeEnqueueInput());
    expect(a).not.toBe(b);
  });

  it("多次 enqueue 的任务按 createdAt 倒序返回", () => {
    mod.enqueue(makeEnqueueInput(["t1"], { id: "older" }));
    mod.enqueue(makeEnqueueInput(["t2"], { id: "newer" }));
    const q = mod.getQueue();
    expect(q.map((i) => i.id)).toEqual(["newer", "older"]);
  });
});

// ─── 2. cancel - 中断任务 ──────────────────────────────────────────

describe("cancel - 中断任务", () => {
  it("abort 控制器并从队列移除，以 cancelled 写入历史", () => {
    const id = mod.enqueue(makeEnqueueInput());
    const controller = mod.getAbortController(id);
    expect(controller).toBeInstanceOf(AbortController);
    const abortSpy = vi.spyOn(controller!, "abort");

    mod.cancel(id);

    expect(abortSpy).toHaveBeenCalledTimes(1);
    expect(mod.getAbortController(id)).toBeUndefined();
    expect(mod.getQueue()).toHaveLength(0);

    const history = mod.getHistory();
    expect(history).toHaveLength(1);
    expect(history[0]).toMatchObject({
      id,
      status: "cancelled",
      tokens: ["token-1", "token-2"],
    });
    expect(history[0].completedAt).toBeTruthy();
  });

  it("取消不存在的 id 是无操作，不写历史", () => {
    expect(() => mod.cancel("missing")).not.toThrow();
    expect(mod.getQueue()).toHaveLength(0);
    expect(mod.getHistory()).toHaveLength(0);
  });

  it("对已完成任务调用 cancel 不重复写入历史", () => {
    const id = mod.enqueue(makeEnqueueInput(["token-1"]));
    mod.updateItemResult(id, "token-1", true); // completed → 已出队并写入历史

    mod.cancel(id);

    expect(mod.getQueue()).toHaveLength(0);
    expect(mod.getHistory()).toHaveLength(1);
  });
});

// ─── 3. resume - 重试失败项 ────────────────────────────────────────

describe("resume - 重试失败项", () => {
  it("failedTokens 为空时返回 null", () => {
    expect(mod.resume("any-id", [])).toBeNull();
  });

  it("找不到原始任务时返回 null", () => {
    expect(mod.resume("missing", ["token-x"])).toBeNull();
  });

  it("基于历史中的失败项创建重试任务（label 追加（重试））", () => {
    const id = mod.enqueue(makeEnqueueInput(["ok", "bad"]));
    mod.updateItemResult(id, "ok", true);
    mod.updateItemResult(id, "bad", false, "上游错误"); // done → 进入历史

    const retryId = mod.resume(id, ["bad"]);

    expect(retryId).toBeTruthy();
    expect(retryId).not.toBe(id);
    const retried = mod.getQueue().find((i) => i.id === retryId);
    expect(retried).toMatchObject({
      action: "refresh",
      label: "测试批量操作（重试）",
      tokens: ["bad"],
      status: "queued",
      progress: 0,
    });
  });

  it("基于仍在队列中的进行中任务也能重试", () => {
    const id = mod.enqueue(makeEnqueueInput(["a", "b"]));
    mod.updateItemResult(id, "a", true); // 未完成 → 仍在队列，status=running

    const retryId = mod.resume(id, ["b"]);

    expect(retryId).toBeTruthy();
    const retried = mod.getQueue().find((i) => i.id === retryId);
    expect(retried?.tokens).toEqual(["b"]);
  });
});

// ─── 4. 历史记录持久化 ─────────────────────────────────────────────

describe("历史记录持久化", () => {
  it("任务完成后写入 localStorage", () => {
    const id = mod.enqueue(makeEnqueueInput(["token-1"]));
    expect(globalThis.localStorage.getItem("batch-queue-history")).toBeNull();

    mod.updateItemResult(id, "token-1", true);

    const raw = globalThis.localStorage.getItem("batch-queue-history");
    expect(raw).not.toBeNull();
    const saved = JSON.parse(raw!) as BatchQueueModule.BatchQueueItem[];
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ id, status: "completed", progress: 100 });
    expect(saved[0].completedAt).toBeTruthy();
  });

  it("重新导入模块后可从 localStorage 恢复历史", async () => {
    const id = mod.enqueue(makeEnqueueInput(["token-1"]));
    mod.updateItemResult(id, "token-1", true);

    // 模拟页面刷新：重置模块重新导入，localStorage 数据保留
    vi.resetModules();
    mod = await import("../store/batch-queue");

    const history = mod.getHistory();
    expect(history).toHaveLength(1);
    expect(history[0].id).toBe(id);
    expect(history[0].status).toBe("completed");
  });

  it("clearHistory 清空 localStorage 中的历史", () => {
    const id = mod.enqueue(makeEnqueueInput(["token-1"]));
    mod.updateItemResult(id, "token-1", true);
    expect(mod.getHistory()).toHaveLength(1);

    mod.clearHistory();

    expect(mod.getHistory()).toHaveLength(0);
    expect(globalThis.localStorage.getItem("batch-queue-history")).toBe("[]");
  });
});

// ─── 5. 超过 50 条自动截断 ─────────────────────────────────────────

describe("超过 50 条自动截断", () => {
  it("历史记录最多保留 50 条，最旧的多余记录被丢弃", () => {
    for (let i = 0; i < 55; i++) {
      const id = mod.enqueue(makeEnqueueInput([`token-${i}`]));
      mod.updateItemResult(id, `token-${i}`, true);
    }

    const history = mod.getHistory();
    expect(history).toHaveLength(50);

    const raw = globalThis.localStorage.getItem("batch-queue-history");
    const saved = JSON.parse(raw!) as BatchQueueModule.BatchQueueItem[];
    expect(saved).toHaveLength(50);
  });
});
