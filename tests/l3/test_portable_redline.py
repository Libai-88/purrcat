"""便携版红线：Electron 侧必须正确识别便携模式并注入数据根（SPEC-036）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN_JS = ROOT / "electron" / "main.js"


def test_electron_detects_portable_flag():
    text = MAIN_JS.read_text(encoding="utf-8")
    assert "portable.flag" in text
    assert "PORTABLE_FLAG" in text
    assert "fs.existsSync(PORTABLE_FLAG)" in text


def test_electron_sets_user_data_before_gpu_flag():
    """userData 必须在读 GPU flag 之前设好，否则 flag 还落在用户目录。"""
    text = MAIN_JS.read_text(encoding="utf-8")
    setpath = text.find("app.setPath('userData'")
    gpuget = text.find("app.getPath('userData')")
    assert setpath >= 0, "没有把 userData 设到便携目录"
    assert gpuget >= 0
    assert setpath < gpuget, "setPath 必须在 getPath 之前"


def test_electron_injects_purrcat_dir_into_backend():
    """后端必须拿到 PURRCAT_DIR，否则 Python 侧还是写 ~/.purrcat。"""
    text = MAIN_JS.read_text(encoding="utf-8")
    assert "backendEnv.PURRCAT_DIR = PORTABLE_DATA_DIR" in text
    assert "env: backendEnv" in text


def test_portable_mode_is_opt_in():
    """便携模式由标记触发，安装版（无标记）行为完全不变。"""
    text = MAIN_JS.read_text(encoding="utf-8")
    assert "const PORTABLE = !IS_DEV && fs.existsSync(PORTABLE_FLAG)" in text


def test_portable_does_not_require_docker():
    """便携版不引入任何 Docker 依赖。"""
    script = (ROOT / "scripts" / "build_portable.py").read_text(encoding="utf-8")
    assert "docker" not in script.lower()


def test_asar_entry_point_is_main_js():
    """asar 里主进程文件在根目录，package.json 的 main 必须指向 main.js。

    以前它照抄源码的 "electron/main.js"，asar 里没有这个路径，
    Electron 找不到入口、窗口根本起不来。
    """
    script = (ROOT / "scripts" / "build_portable.py").read_text(encoding="utf-8")
    assert 'package["main"] = "main.js"' in script


def test_portable_build_does_not_use_electron_builder():
    """便携版不签名、不需要管理员权限，不走 electron-builder 的下载/符号链接流程。"""
    script = (ROOT / "scripts" / "build_portable.py").read_text(encoding="utf-8")
    # 只看实际调用：注释里解释「为什么不用 electron-builder」是允许的。
    code_lines = [
        line
        for line in script.splitlines()
        if not line.strip().startswith(("#", "*", '"""'))
    ]
    code = "\n".join(code_lines)
    assert '"electron-builder"' not in code
    assert "app.asar" in script
    assert "node_modules/electron/dist" in script.replace("\\", "/")


def test_electron_runtime_is_renamed_to_product_name():
    """便携目录的 exe 要叫 PurrCat，不是 electron.exe。"""
    script = (ROOT / "scripts" / "build_portable.py").read_text(encoding="utf-8")
    assert "PurrCat.exe" in script
