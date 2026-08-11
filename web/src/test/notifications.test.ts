import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as NotificationsModule from "../store/notifications";

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

type NotificationInput = Omit<
  NotificationsModule.Notification,
  "id" | "timestamp" | "read"
> & { id?: string };

function makeNotification(
  type: NotificationsModule.NotificationType = "system",
  overrides: Partial<NotificationInput> = {},
): NotificationInput {
  return {
    type,
    title: "测试标题",
    message: "测试消息",
    ...overrides,
  };
}

const STORAGE_KEY = "notifications";

// 每次用例重置模块，保证模块级 notifications/listeners 干净，
// 同时用新的 localStorage mock 隔离持久化数据。
let mod: typeof NotificationsModule;

// 直接向 localStorage 写入种子数据（模块导入时才会读取）
function seedStorage(items: NotificationsModule.Notification[]) {
  globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

// 模拟页面刷新：重置模块并重新导入，localStorage 数据保留
async function reloadModule() {
  vi.resetModules();
  mod = await import("../store/notifications");
}

beforeEach(async () => {
  vi.resetModules();
  globalThis.localStorage = createStorageMock();
  mod = await import("../store/notifications");
});

// ─── 1. addNotification - 添加通知 ─────────────────────────────────

describe("addNotification - 添加通知", () => {
  it("返回 id，并插入列表头部（read=false、timestamp 存在）", () => {
    const id = mod.addNotification(makeNotification("alert", { title: "上游告警" }));

    expect(id).toBeTruthy();
    const list = mod.getNotifications();
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({
      id,
      type: "alert",
      title: "上游告警",
      message: "测试消息",
      read: false,
    });
    expect(list[0].timestamp).toBeTruthy();
  });

  it("使用调用方提供的自定义 id", () => {
    const id = mod.addNotification(makeNotification("system", { id: "custom-id" }));
    expect(id).toBe("custom-id");
    expect(mod.getNotifications()[0].id).toBe("custom-id");
  });

  it("未提供 id 时生成互不相同的唯一 id", () => {
    const a = mod.addNotification(makeNotification());
    const b = mod.addNotification(makeNotification());
    expect(a).not.toBe(b);
  });

  it("新通知按时间倒序返回（最新在前）", () => {
    mod.addNotification(makeNotification("system", { id: "older" }));
    mod.addNotification(makeNotification("alert", { id: "newer" }));
    expect(mod.getNotifications().map((n) => n.id)).toEqual(["newer", "older"]);
  });

  it("添加后同步写入 localStorage", () => {
    mod.addNotification(makeNotification("system", { id: "persist-me" }));

    const raw = globalThis.localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const saved = JSON.parse(raw!) as NotificationsModule.Notification[];
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ id: "persist-me", read: false });
  });
});

// ─── 2. markAsRead / markAllAsRead - 标记已读 ──────────────────────

describe("markAsRead / markAllAsRead - 标记已读", () => {
  it("markAsRead 将指定通知置为已读，其余不受影响", () => {
    mod.addNotification(makeNotification("system", { id: "a" }));
    mod.addNotification(makeNotification("system", { id: "b" }));

    mod.markAsRead("a");

    const list = mod.getNotifications();
    expect(list.find((n) => n.id === "a")?.read).toBe(true);
    expect(list.find((n) => n.id === "b")?.read).toBe(false);
  });

  it("markAsRead 不存在的 id 是无操作，不改变任何通知", () => {
    mod.addNotification(makeNotification("system", { id: "a" }));

    mod.markAsRead("missing");

    const list = mod.getNotifications();
    expect(list.find((n) => n.id === "a")?.read).toBe(false);
    const saved = JSON.parse(
      globalThis.localStorage.getItem(STORAGE_KEY)!,
    ) as NotificationsModule.Notification[];
    expect(saved[0].read).toBe(false);
  });

  it("对已读通知再次 markAsRead 无变化", () => {
    mod.addNotification(makeNotification("system", { id: "a" }));
    mod.markAsRead("a");

    mod.markAsRead("a");

    const list = mod.getNotifications();
    expect(list.find((n) => n.id === "a")?.read).toBe(true);
  });

  it("markAllAsRead 将全部通知置为已读", () => {
    for (let i = 0; i < 3; i++) {
      mod.addNotification(makeNotification("system", { id: `n-${i}` }));
    }

    mod.markAllAsRead();

    expect(mod.getNotifications().every((n) => n.read)).toBe(true);
    expect(mod.getUnreadCount()).toBe(0);
  });

  it("全部已读时 markAllAsRead 是无操作", () => {
    mod.addNotification(makeNotification("system", { id: "a" }));
    mod.markAllAsRead();

    expect(() => mod.markAllAsRead()).not.toThrow();
    expect(mod.getUnreadCount()).toBe(0);
  });

  it("标记已读后同步写入 localStorage", () => {
    mod.addNotification(makeNotification("system", { id: "a" }));

    mod.markAsRead("a");

    const saved = JSON.parse(
      globalThis.localStorage.getItem(STORAGE_KEY)!,
    ) as NotificationsModule.Notification[];
    expect(saved[0].read).toBe(true);
  });
});

// ─── 3. clearAll - 清空通知 ────────────────────────────────────────

describe("clearAll - 清空通知", () => {
  it("清空内存通知并同步写入空数组到 localStorage", () => {
    mod.addNotification(makeNotification("system", { id: "a" }));
    mod.addNotification(makeNotification("alert", { id: "b" }));

    mod.clearAll();

    expect(mod.getNotifications()).toHaveLength(0);
    expect(mod.getUnreadCount()).toBe(0);
    expect(globalThis.localStorage.getItem(STORAGE_KEY)).toBe("[]");
  });

  it("空列表时 clearAll 是无操作，不写入 localStorage", () => {
    expect(() => mod.clearAll()).not.toThrow();
    expect(mod.getNotifications()).toHaveLength(0);
    expect(globalThis.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

// ─── 4. getUnreadCount - 未读数 ────────────────────────────────────

describe("getUnreadCount - 未读数", () => {
  it("统计未读通知数量", () => {
    mod.addNotification(makeNotification("system", { id: "a" }));
    mod.addNotification(makeNotification("system", { id: "b" }));
    mod.addNotification(makeNotification("system", { id: "c" }));

    mod.markAsRead("a");

    expect(mod.getUnreadCount()).toBe(2);
  });

  it("全部已读后未读数为 0", () => {
    mod.addNotification(makeNotification("system", { id: "a" }));
    mod.markAllAsRead();
    expect(mod.getUnreadCount()).toBe(0);
  });
});

// ─── 5. getNotifications - 类型/状态/时间过滤 ─────────────────────

describe("getNotifications - 类型过滤", () => {
  function seedThree() {
    mod.addNotification(makeNotification("system", { id: "sys" }));
    mod.addNotification(makeNotification("alert", { id: "alr" }));
    mod.addNotification(makeNotification("operation", { id: "opr" }));
  }

  it("按单一类型过滤", () => {
    seedThree();
    const alerts = mod.getNotifications({ type: "alert" });
    expect(alerts.map((n) => n.id)).toEqual(["alr"]);
  });

  it("按类型数组过滤", () => {
    seedThree();
    // 最新添加的在头部：内存顺序为 [opr, alr, sys]
    const items = mod.getNotifications({ type: ["system", "operation"] });
    expect(items.map((n) => n.id)).toEqual(["opr", "sys"]);
  });

  it("按已读状态过滤", () => {
    seedThree();
    mod.markAsRead("alr");

    // 最新添加的在头部：内存顺序为 [opr, alr, sys]
    expect(mod.getNotifications({ read: false }).map((n) => n.id)).toEqual(["opr", "sys"]);
    expect(mod.getNotifications({ read: true }).map((n) => n.id)).toEqual(["alr"]);
  });

  it("按时间范围 since/until 过滤（含边界，ISO 字符串比较）", async () => {
    const seed: NotificationsModule.Notification[] = [
      { id: "a", type: "system", title: "t", message: "m", timestamp: "2026-01-01T00:00:00.000Z", read: false },
      { id: "b", type: "alert", title: "t", message: "m", timestamp: "2026-02-01T00:00:00.000Z", read: false },
      { id: "c", type: "operation", title: "t", message: "m", timestamp: "2026-03-01T00:00:00.000Z", read: false },
    ];
    seedStorage(seed);
    await reloadModule();

    expect(mod.getNotifications({ since: "2026-02-01T00:00:00.000Z" }).map((n) => n.id)).toEqual(["b", "c"]);
    expect(mod.getNotifications({ until: "2026-02-01T00:00:00.000Z" }).map((n) => n.id)).toEqual(["a", "b"]);
    expect(
      mod
        .getNotifications({ since: "2026-01-02T00:00:00.000Z", until: "2026-02-28T00:00:00.000Z" })
        .map((n) => n.id),
    ).toEqual(["b"]);
  });

  it("无过滤条件时返回全部通知", () => {
    seedThree();
    expect(mod.getNotifications()).toHaveLength(3);
  });
});

// ─── 6. localStorage 持久化 ────────────────────────────────────────

describe("localStorage 持久化", () => {
  it("重新导入模块后从 localStorage 恢复通知（含 id 与已读状态）", async () => {
    mod.addNotification(makeNotification("system", { id: "a" }));
    mod.addNotification(makeNotification("alert", { id: "b" }));
    mod.markAsRead("a");

    await reloadModule();

    const list = mod.getNotifications();
    expect(list).toHaveLength(2);
    expect(list.map((n) => n.id)).toEqual(["b", "a"]);
    expect(list.find((n) => n.id === "a")?.read).toBe(true);
    expect(list.find((n) => n.id === "b")?.read).toBe(false);
  });

  it("localStorage 中为无效 JSON 时回退为空列表", async () => {
    globalThis.localStorage.setItem(STORAGE_KEY, "{not-json");
    await reloadModule();

    expect(mod.getNotifications()).toHaveLength(0);
    expect(mod.getUnreadCount()).toBe(0);
  });
});

// ─── 7. 超过 200 条自动截断 ────────────────────────────────────────

describe("超过 200 条自动截断", () => {
  it("localStorage 最多保留 200 条，最旧的被丢弃；重新加载后仅恢复 200 条", async () => {
    for (let i = 0; i < 250; i++) {
      mod.addNotification(makeNotification("system", { id: `n-${i}` }));
    }

    // 注：当前实现只在持久化层截断，内存数组保留全部
    expect(mod.getNotifications()).toHaveLength(250);

    const raw = globalThis.localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const saved = JSON.parse(raw!) as NotificationsModule.Notification[];
    expect(saved).toHaveLength(200);
    expect(saved[0].id).toBe("n-249"); // 最新一条保留
    expect(saved.some((n) => n.id === "n-49")).toBe(false); // 最旧 50 条被丢弃

    // 模拟刷新：重新导入后仅恢复 200 条，最新一条仍在头部
    await reloadModule();
    expect(mod.getNotifications()).toHaveLength(200);
    expect(mod.getNotifications()[0].id).toBe("n-249");
  });
});
