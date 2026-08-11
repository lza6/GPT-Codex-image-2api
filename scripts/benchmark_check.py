"""性能基准断言（V-04）：比对最近一次 stress_test JSON 与提交的基准阈值。

基线文件：docs/benchmark-baseline.json（提交入库，标注环境/日期/实测值）。
数据源：reports/stress/ 下最新的 *.json（由 scripts/stress_test.py 生成）。
断言项（对应"吞吐/延迟/错误率"关键指标）：
  - spike.throughput_rps >= thresholds.min_throughput_rps
  - spike.p99_ms         <= thresholds.max_p99_ms
  - spike.error_rate     <= thresholds.max_error_rate
  - slow_storage.p99_ms  <= thresholds.max_slow_p99_ms

用法：
    .venv/Scripts/python.exe scripts/benchmark_check.py
退出码：任一指标低于阈值或缺失数据 = 1（FAIL）；全过 = 0（PASS）。
"""

from __future__ import annotations

import glob
import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_baseline() -> dict:
    path = ROOT / "docs" / "benchmark-baseline.json"
    if not path.exists():
        raise SystemExit("[FAIL] docs/benchmark-baseline.json 缺失——请先创建基准基线文件")
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_stress() -> dict:
    hits = sorted(glob.glob(str(ROOT / "reports" / "stress" / "*.json")), key=os.path.getmtime)
    if not hits:
        raise SystemExit(
            "[FAIL] 未找到 reports/stress/*.json——请先运行 scripts/stress_test.py（本防线必须排在施压之后）"
        )
    return json.loads(Path(hits[-1]).read_text(encoding="utf-8"))


def main() -> int:
    baseline = _load_baseline()
    thr = baseline["thresholds"]
    stress = _latest_stress()
    spike = stress.get("spike", {})
    slow = stress.get("slow_storage", {})
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    checks: list[tuple[str, bool, object, object, str]] = [
        ("吞吐 ≥ 下限", spike.get("throughput_rps", -1) >= thr["min_throughput_rps"],
         spike.get("throughput_rps"), f"{thr['min_throughput_rps']} rps", "rps"),
        ("常规 p99 ≤ 上限", spike.get("p99_ms", 1e9) <= thr["max_p99_ms"],
         spike.get("p99_ms"), f"{thr['max_p99_ms']} ms", "ms"),
        ("错误率 ≤ 上限", spike.get("error_rate", 1.0) <= thr["max_error_rate"],
         spike.get("error_rate"), f"{thr['max_error_rate']}", "rate"),
        ("慢存储 p99 ≤ 上限", slow.get("p99_ms", 1e9) <= thr["max_slow_p99_ms"],
         slow.get("p99_ms"), f"{thr['max_slow_p99_ms']} ms", "ms"),
    ]
    if slow.get("slow_storage_injected") is False:
        print("[warn] 最近一次施压的慢存储注入未命中（injected=False），该项断言为空跑，请检查 log 文件名模式")
    if not stress.get("overall_pass", False):
        print("[warn] 最近一次施压本身 overall_pass=False，基准断言仅作数值下限参考")

    lines = [f"# 性能基准断言 {stamp}", "", "- 数据源：reports/stress/ 最新 JSON", ""]
    all_ok = True
    for name, ok, actual, budget, unit in checks:
        mark = "PASS" if ok else "FAIL"
        lines.append(f"| {name} | {mark} | {actual} | {budget} |")
        print(f"{mark}  {name}: actual={actual} {unit}  budget={budget}")
        all_ok = all_ok and ok

    out_dir = ROOT / "reports" / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.txt").write_text(
        "\n".join(lines) + f"\n总体: {'PASS' if all_ok else 'FAIL'}\n", encoding="utf-8"
    )
    print(f"[benchmark] 总体: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
