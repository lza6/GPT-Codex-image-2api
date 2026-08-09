"""Git 存储后端测试覆盖。

GitStorageBackend 使用本地 bare repo 模拟远程仓库，不依赖真实外部服务。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from services.storage.git_storage import GitStorageBackend


# ---------------------------------------------------------------------------
# 辅助：创建本地 bare repo 作为"远程"仓库
# ---------------------------------------------------------------------------


def _init_remote_repo(tmp_path: Path) -> Path:
    """初始化一个本地 bare repo 作为远程仓库，返回仓库路径。"""
    remote_path = tmp_path / "remote.git"
    bare_repo = Repo.init(str(remote_path), bare=True)
    bare_repo.close()
    return remote_path


def _init_and_push_initial_commit(remote_path: Path) -> None:
    """从远程仓库克隆一个本地仓库，创建初始提交并推送，使主分支可用。

    注意：git init --bare 的默认分支名可能是 master，需显式重命名为 main，
    确保后端 clone --branch=main 能找到对应分支。
    """
    local_path = remote_path.parent / "local_init"
    repo = Repo.clone_from(str(remote_path), str(local_path))
    # 将默认分支重命名为 main（bare repo 初始分支名因 git 版本而异）
    if repo.active_branch.name != "main":
        repo.git.branch("-m", repo.active_branch.name, "main")
    init_file = local_path / ".gitkeep"
    init_file.write_text("", encoding="utf-8")
    repo.index.add([".gitkeep"])
    repo.index.commit("init")
    # 分支重命名后旧上游不再匹配，需显式设置上游
    repo.git.push("--set-upstream", "origin", "main")
    repo.close()


def _make_backend(remote_path: Path, cache_dir: Path) -> GitStorageBackend:
    """创建指向本地 bare repo 的 GitStorageBackend 实例。"""
    return GitStorageBackend(
        repo_url=str(remote_path),
        token="",
        branch="main",
        file_path="accounts.json",
        auth_keys_file_path="auth_keys.json",
        local_cache_dir=cache_dir,
    )


# ---------------------------------------------------------------------------
# 基本 CRUD
# ---------------------------------------------------------------------------


class TestGitStorageBasicCRUD:
    def test_save_and_load_accounts(self, tmp_path):
        remote_path = _init_remote_repo(tmp_path)
        _init_and_push_initial_commit(remote_path)
        backend = _make_backend(remote_path, tmp_path / "cache")

        accounts = [
            {"access_token": "token-a", "name": "A"},
            {"access_token": "token-b", "name": "B"},
        ]
        backend.save_accounts(accounts)
        loaded = backend.load_accounts()
        assert loaded == accounts

    def test_save_and_load_accounts_overwrite(self, tmp_path):
        remote_path = _init_remote_repo(tmp_path)
        _init_and_push_initial_commit(remote_path)
        backend = _make_backend(remote_path, tmp_path / "cache")

        backend.save_accounts([{"access_token": "token-a", "name": "A"}])
        backend.save_accounts([{"access_token": "token-a", "name": "A updated"}])
        loaded = backend.load_accounts()
        assert loaded == [{"access_token": "token-a", "name": "A updated"}]

    def test_save_and_load_auth_keys(self, tmp_path):
        remote_path = _init_remote_repo(tmp_path)
        _init_and_push_initial_commit(remote_path)
        backend = _make_backend(remote_path, tmp_path / "cache")

        auth_keys = [{"id": "key-a", "name": "A"}]
        backend.save_auth_keys(auth_keys)
        loaded = backend.load_auth_keys()
        assert loaded == auth_keys

    def test_save_auth_keys_overwrite(self, tmp_path):
        remote_path = _init_remote_repo(tmp_path)
        _init_and_push_initial_commit(remote_path)
        backend = _make_backend(remote_path, tmp_path / "cache")

        backend.save_auth_keys([{"id": "key-a", "name": "A"}])
        backend.save_auth_keys([{"id": "key-a", "name": "A updated"}])
        loaded = backend.load_auth_keys()
        assert loaded == [{"id": "key-a", "name": "A updated"}]

    def test_load_empty_repo_returns_empty_list(self, tmp_path):
        remote_path = _init_remote_repo(tmp_path)
        _init_and_push_initial_commit(remote_path)
        backend = _make_backend(remote_path, tmp_path / "cache")

        assert backend.load_accounts() == []
        assert backend.load_auth_keys() == []

    def test_multiple_save_preserves_pushed_content(self, tmp_path):
        """多次 save 后验证数据已推送到远程（通过新 backend 实例 clone 确认）。"""
        remote_path = _init_remote_repo(tmp_path)
        _init_and_push_initial_commit(remote_path)
        backend = _make_backend(remote_path, tmp_path / "cache")

        backend.save_accounts([{"access_token": "tok-1", "name": "first"}])
        backend.save_accounts([
            {"access_token": "tok-1", "name": "first"},
            {"access_token": "tok-2", "name": "second"},
        ])

        # 使用另一个 cache 目录创建新 backend 实例，验证数据已推送
        fresh_backend = _make_backend(remote_path, tmp_path / "cache2")
        loaded = fresh_backend.load_accounts()
        assert len(loaded) == 2
        assert loaded[0]["access_token"] == "tok-1"


# ---------------------------------------------------------------------------
# 健康检查与后端信息
# ---------------------------------------------------------------------------


class TestGitStorageHealth:
    def test_health_check_healthy(self, tmp_path):
        remote_path = _init_remote_repo(tmp_path)
        _init_and_push_initial_commit(remote_path)
        backend = _make_backend(remote_path, tmp_path / "cache")
        backend.save_accounts([{"access_token": "tok-1"}])

        status = backend.health_check()
        assert status["status"] == "healthy"
        assert status["backend"] == "git"
        assert "last_commit" in status

    def test_health_check_unhealthy_when_no_remote(self, tmp_path):
        """指向不存在的远程路径时，health_check 应报 unhealthy。"""
        backend = _make_backend(tmp_path / "nonexistent.git", tmp_path / "cache")
        status = backend.health_check()
        assert status["status"] == "unhealthy"

    def test_get_backend_info(self, tmp_path):
        remote_path = _init_remote_repo(tmp_path)
        _init_and_push_initial_commit(remote_path)
        backend = _make_backend(remote_path, tmp_path / "cache")

        info = backend.get_backend_info()
        assert info["type"] == "git"
        assert info["branch"] == "main"
        assert info["file_path"] == "accounts.json"
        assert info["auth_keys_file_path"] == "auth_keys.json"
        # token 为空时不应包含 ****
        assert "****" not in info["repo_url"]
        # URL 应包含 remote 仓库路径
        assert str(remote_path) in info["repo_url"]


# ---------------------------------------------------------------------------
# 工具方法
# ---------------------------------------------------------------------------


class TestGitStorageUtilities:
    def test_mask_token_https(self):
        url = "https://token123@github.com/user/repo.git"
        masked = GitStorageBackend._mask_token(url)
        assert masked == "https://****@github.com/user/repo.git"

    def test_mask_token_no_token(self):
        url = "https://github.com/user/repo.git"
        masked = GitStorageBackend._mask_token(url)
        assert masked == url

    def test_mask_token_git_ssh(self):
        url = "git@github.com:user/repo.git"
        masked = GitStorageBackend._mask_token(url)
        # SSH 格式不含 ://，按 mask 逻辑直接返回
        assert masked == url

    def test_build_auth_url_https(self):
        result = GitStorageBackend._build_auth_url(
            "https://github.com/user/repo.git", "mytoken"
        )
        assert result == "https://mytoken@github.com/user/repo.git"

    def test_build_auth_url_empty_token(self):
        result = GitStorageBackend._build_auth_url(
            "https://github.com/user/repo.git", ""
        )
        assert result == "https://github.com/user/repo.git"

    def test_build_auth_url_git_ssh_format(self):
        result = GitStorageBackend._build_auth_url(
            "git@github.com:user/repo.git", "mytoken"
        )
        assert result == "https://mytoken@github.com/user/repo.git"

    def test_build_auth_url_local_path(self):
        result = GitStorageBackend._build_auth_url("/tmp/foo/repo.git", "mytoken")
        assert result == "/tmp/foo/repo.git"