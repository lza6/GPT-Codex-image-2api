from __future__ import annotations

import pytest

# 需真实上游/活服务(localhost:23456)的测试，CI 默认排除（pytest -m live 本地手动跑）
pytestmark = pytest.mark.live

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.openai_backend_api import OpenAIBackendAPI


def main() -> None:
    ACCESS_TOKEN = ""
    PROMPT = "帮我去网上搜索关于chatgpt2api的相关项目"
    if not ACCESS_TOKEN.strip():
        raise ValueError("ACCESS_TOKEN is empty")
    print(json.dumps(OpenAIBackendAPI(ACCESS_TOKEN).search(PROMPT), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
