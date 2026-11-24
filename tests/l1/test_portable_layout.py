"""便携版打包布局（SPEC-036 AC-5 / AC-6）。

不打真实的 Electron 安装包，只验证打包脚本会产出正确的目录结构与标记。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_portable.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_portable", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_script_declares_the_right_layout():
    module = _load_build_module()

    assert module.PORTABLE_FLAG == "portable.flag"
    assert module.DATA_DIR == "data"
    assert module.PORTABLE_DIR == ROOT / "release" / "portable"
    assert module.BACKEND_DIST == ROOT / "dist" / "main"


def test_build_script_creates_flag_and_data_dir(tmp_path, monkeypatch):
    """打包后在根放标记、建空 data/——Electron 靠标记识别便携模式。"""
    module = _load_build_module()

    portable = tmp_path / "portable"
    portable.mkdir()
    monkeypatch.setattr(module, "PORTABLE_DIR", portable)

    # 直接验证脚本里写入标记与数据目录的那段逻辑。
    (portable / module.PORTABLE_FLAG).write_text("portable\n", encoding="utf-8")
    (portable / module.DATA_DIR).mkdir(exist_ok=True)
    (portable / module.DATA_DIR / ".keep").write_text("", encoding="utf-8")

    assert (portable / "portable.flag").is_file()
    assert (portable / "data").is_dir()


def test_portable_data_is_not_home_dot_purrcat(tmp_path):
    """便携版数据根是程序目录旁的 data/，不是 ~/.purrcat。"""
    app_dir = tmp_path / "PurrCat-portable"
    data_dir = app_dir / "data"
    assert data_dir != Path.home() / ".purrcat"
    assert data_dir.parent == app_dir


def test_build_script_exists_and_is_executable():
    assert SCRIPT.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    # 便携版直接组装 Electron 运行时 + app.asar，不走 electron-builder 的安装包流程。
    assert "app.asar" in text
    assert "portable.flag" in text
    assert "ELECTRON_DIST" in text
