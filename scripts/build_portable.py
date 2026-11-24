#!/usr/bin/env python3
"""把 PurrCat 打包成便携版：解压即用，数据跟着目录走（SPEC-036）。

便携版 = 一个普通目录，内含：

    PurrCat.exe / PurrCat      Electron 运行时（从 node_modules/electron/dist 复制）
    resources/app.asar          应用代码（electron/ + package.json）
    resources/backend/          PyInstaller 后端 sidecar
    portable.flag               便携模式标记
    data/                       数据目录（随目录走，默认空）

**完全不依赖 electron-builder**：它会在 Windows 上为了给 exe 写图标/版本资源
去下载 winCodeSign，解压时要建符号链接，普通用户没有这个权限而失败。
便携版本来就不签名，也不需要安装包，所以没必要走那条路。

用法：
    uv run pyinstaller main.spec --noconfirm   # 先打后端
    python scripts/build_portable.py           # 组装便携目录 + zip
    python scripts/build_portable.py --no-zip  # 只要目录
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIST = ROOT / "dist" / "main"
ELECTRON_DIST = ROOT / "node_modules" / "electron" / "dist"
# 语义检索用的本地 ONNX 模型：安装版在 ~/.purrcat/embedding。
# 便携版要开箱就有完整搜索能力，所以把它一起打进包里。
EMBEDDING_SRC = Path.home() / ".purrcat" / "embedding"
PORTABLE_DIR = ROOT / "release" / "portable"
PORTABLE_FLAG = "portable.flag"
DATA_DIR = "data"

# Electron 运行时文件：从 node_modules/electron/dist 复制，跳过默认示例应用。
_RUNTIME_SKIP = {"resources", "debug.log"}


def _run_asar(app_dir: Path, out_file: Path) -> None:
    """把 electron/ + package.json 打成 app.asar。"""
    asar = ROOT / "node_modules" / ".bin" / ("asar.cmd" if os.name == "nt" else "asar")
    if not asar.exists():
        raise SystemExit(f"缺少 asar 工具：{asar}（先 npm install）")
    subprocess.run(
        [str(asar), "pack", str(app_dir), str(out_file)], cwd=ROOT, check=True
    )


def _prepare_app_stage() -> Path:
    """准备 app.asar 的输入目录：只放 Electron 主进程真正需要的文件。"""
    stage = ROOT / "release" / ".portable-app-stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    for name in ("main.js", "preload.js", "api-port.cjs"):
        source = ROOT / "electron" / name
        if source.is_file():
            shutil.copy2(source, stage / name)

    # 便携版不打包 electron-updater：它不是安装包管理的，自动更新没意义
    # （main.js 的 initAutoUpdate 在 PORTABLE 模式下直接 return）。
    # 主进程只需要 Node 内置模块，不需要任何第三方运行时依赖。

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    # 便携版不需要自动更新与发布配置；去掉 publish 避免误触。
    package.pop("publish", None)
    # 源码里 main 指向 electron/main.js，但 asar 里我们把主进程文件放在根，
    # 所以入口要改成 main.js，否则 Electron 找不到主脚本、窗口起不来。
    package["main"] = "main.js"
    (stage / "package.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stage


def _check_inputs() -> None:
    exe = "main.exe" if os.name == "nt" else "main"
    electron_exe = "electron.exe" if os.name == "nt" else "electron"
    if not (BACKEND_DIST / exe).is_file():
        raise SystemExit(
            f"缺少后端产物 {BACKEND_DIST / exe}\n"
            "先运行：uv run pyinstaller main.spec --noconfirm"
        )
    if not (ELECTRON_DIST / electron_exe).is_file():
        raise SystemExit(
            f"缺少 Electron 运行时：{ELECTRON_DIST / electron_exe}（先 npm install）"
        )


def _build_dir() -> None:
    """组装便携目录。"""
    if PORTABLE_DIR.exists():
        shutil.rmtree(PORTABLE_DIR)
    PORTABLE_DIR.parent.mkdir(parents=True, exist_ok=True)
    PORTABLE_DIR.mkdir(parents=True)

    # 1) Electron 运行时
    for item in ELECTRON_DIST.iterdir():
        if item.name in _RUNTIME_SKIP:
            continue
        # 把 electron.exe 改名为 PurrCat.exe：Electron 运行时支持改名，
        # 用户看到的才是真正的产品名而不是 "electron"。
        name = (
            "PurrCat.exe"
            if os.name == "nt" and item.name == "electron.exe"
            else (
                "PurrCat" if os.name != "nt" and item.name == "electron" else item.name
            )
        )
        target = PORTABLE_DIR / name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, target)

    # 2) 应用代码 → resources/app.asar
    resources = PORTABLE_DIR / "resources"
    resources.mkdir(exist_ok=True)
    asar_file = resources / "app.asar"
    stage = _prepare_app_stage()
    _run_asar(stage, asar_file)
    shutil.rmtree(stage, ignore_errors=True)

    # 3) 后端 sidecar
    shutil.copytree(BACKEND_DIST, resources / "backend", dirs_exist_ok=True)

    # 4) 便携标记与空数据目录
    (PORTABLE_DIR / PORTABLE_FLAG).write_text(
        "PurrCat portable build — data lives in ./data, no registry, no global install.\n",
        encoding="utf-8",
    )
    data = PORTABLE_DIR / DATA_DIR
    data.mkdir(exist_ok=True)
    (data / ".keep").write_text("", encoding="utf-8")

    # 语义检索模型：有就带上（约 120MB），让便携版开箱即有完整搜索。
    # 没有就跳过——关键词检索仍可用，只是没有语义向量。
    if EMBEDDING_SRC.is_dir():
        target = data / "embedding"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(EMBEDDING_SRC, target)
        print(f"[OK] 已带上本地嵌入模型：{target}")
    else:
        print(f"[warn] 没找到 {EMBEDDING_SRC}，便携版将只有关键词检索")


def _make_zip() -> Path:
    zip_path = ROOT / "release" / f"PurrCat-portable-{_version()}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(
        zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(PORTABLE_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(PORTABLE_DIR.parent))
    return zip_path


def _version() -> str:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    return str(package.get("version", "0"))


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 PurrCat 便携版")
    parser.add_argument("--no-zip", action="store_true", help="只产出目录，不压缩")
    args = parser.parse_args()

    _check_inputs()
    _build_dir()
    print(f"[OK] 便携目录：{PORTABLE_DIR}")
    print(f"     数据目录：{PORTABLE_DIR / DATA_DIR}（随目录走）")

    if not args.no_zip:
        zip_path = _make_zip()
        print(f"[OK] 便携压缩包：{zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
