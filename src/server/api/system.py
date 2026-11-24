import json
import os
import platform
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from pydantic import BaseModel

from src.utils.config import (
    get_container_engine,
    TRACKER_DIR,
    BUFFER_DIR,
)
from src.model.manager.usage_tracer import usage_tracer

router = APIRouter(prefix="/api/system", tags=["System Environment"])


def _docker_sdk():
    """按需加载 Docker SDK——没装 docker 包也能正常启动服务。

    Docker 是可选增强：默认走本机 shell，只有显式切到 docker 后端、
    真的要连容器时才需要这个包。
    """
    try:
        import docker
        from docker.errors import DockerException, ImageNotFound

        return docker, DockerException, ImageNotFound
    except ImportError as exc:
        raise RuntimeError(
            "没装 Docker SDK（pip install docker），容器后端不可用"
        ) from exc


class EnvStatusResponse(BaseModel):
    is_ready: bool
    engine: Optional[str] = None
    engine_version: Optional[str] = None
    error: Optional[str] = None


class ImageStatusResponse(BaseModel):
    exists: bool
    image_name: str
    error: Optional[str] = None


class PullImageRequest(BaseModel):
    image_name: str


class PullImageResponse(BaseModel):
    status: str
    message: str


class InstallStatusResponse(BaseModel):
    status: str
    message: str
    progress: int = 0


class InstallRequest(BaseModel):
    engine: str = "docker"


class DetectResponse(BaseModel):
    os: str
    installed: dict[str, bool]
    recommend: str
    recommend_reason: str


_install_progress = 0
_install_status = "idle"
_install_error = None
_selected_engine = None


def _get_engine_version(engine: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [engine, "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def _check_engine_running(engine: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _local_shell_info() -> dict:
    """探测本机 shell 是否可用（本地执行后端的就绪判定）。"""
    from src.tool.bash.backends import resolve_shell

    try:
        spec = resolve_shell()
        return {"ready": True, "kind": spec.kind, "path": spec.path}
    except Exception as e:
        return {"ready": False, "error": str(e)}


@router.get("/env/detect", response_model=DetectResponse)
def detect_environment():
    from src.tool.bash.backends import resolve_backend_name

    os_name = platform.system()
    has_docker = shutil.which("docker") is not None
    local = _local_shell_info()
    backend = resolve_backend_name()

    if local.get("ready"):
        recommend_engine = "local"
        recommend_reason = (
            f"默认使用本机 {local['kind']} 执行命令，无需 Docker。"
            "如需容器隔离，可设置 PURRCAT_EXEC_BACKEND=docker。"
        )
    elif has_docker:
        recommend_engine = "docker"
        recommend_reason = (
            "未找到可用的本机 shell，已检测到 Docker；"
            "可设置 PURRCAT_EXEC_BACKEND=docker 使用沙盒。"
        )
    else:
        recommend_engine = "local"
        recommend_reason = f"未找到可用的本机 shell：{local.get('error', '未知原因')}"

    return DetectResponse(
        os=os_name,
        installed={"docker": has_docker, "local": bool(local.get("ready"))},
        recommend=recommend_engine,
        recommend_reason=f"当前执行后端: {backend}。{recommend_reason}",
    )


@router.get("/env-status", response_model=EnvStatusResponse)
def get_environment_status():
    from src.tool.bash.backends import resolve_backend_name

    if resolve_backend_name() != "docker":
        local = _local_shell_info()
        if local.get("ready"):
            return EnvStatusResponse(
                is_ready=True,
                engine="local",
                engine_version=f"{local['kind']}: {local['path']}",
            )
        return EnvStatusResponse(
            is_ready=False, engine="local", error=local.get("error")
        )

    try:
        engine = get_container_engine()
        version = _get_engine_version(engine)
        if not _check_engine_running(engine):
            return EnvStatusResponse(
                is_ready=False,
                engine=engine,
                engine_version=version,
                error="Docker daemon 未启动，请启动 Docker Desktop。",
            )
        return EnvStatusResponse(is_ready=True, engine=engine, engine_version=version)
    except RuntimeError as e:
        return EnvStatusResponse(is_ready=False, error=str(e))


@router.get("/env/status")
def get_env_status_simple():
    from src.tool.bash.backends import resolve_backend_name

    backend = resolve_backend_name()
    has_docker = shutil.which("docker") is not None
    local = _local_shell_info()
    ready = has_docker if backend == "docker" else bool(local.get("ready"))
    return {
        "ready": ready,
        "engine": "docker" if backend == "docker" else "local",
        "has_docker": has_docker,
        "exec_backend": backend,
        "shell": f"{local.get('kind')}: {local.get('path')}"
        if local.get("ready")
        else local.get("error"),
    }


@router.get("/image-status", response_model=ImageStatusResponse)
def get_image_status(image_name: str = "my_agent_env:latest"):
    from src.tool.bash.backends import resolve_backend_name

    if resolve_backend_name() != "docker":
        # 本地执行不依赖镜像，直接报告就绪，避免部署页一直显示“镜像未拉取”
        return ImageStatusResponse(exists=True, image_name=image_name)

    try:
        get_container_engine()  # 校验 docker 存在，缺失时抛 RuntimeError
        sdk, DockerException, ImageNotFound = _docker_sdk()
        client = sdk.from_env()
        try:
            client.images.get(image_name)
            return ImageStatusResponse(exists=True, image_name=image_name)
        except ImageNotFound:
            return ImageStatusResponse(exists=False, image_name=image_name)
    except RuntimeError as e:
        return ImageStatusResponse(exists=False, image_name=image_name, error=str(e))
    except DockerException as e:
        return ImageStatusResponse(
            exists=False, image_name=image_name, error=f"Docker 连接失败: {str(e)}"
        )


def _pull_image_task(image_name: str):
    global _install_progress, _install_status, _install_error
    _install_status = "installing"
    _install_progress = 5
    try:
        sdk, _DockerException, _ImageNotFound = _docker_sdk()
        client = sdk.from_env()
        client.images.pull(image_name)
        _install_progress = 100
        _install_status = "completed"
        _install_error = None
    except Exception as e:
        _install_status = "failed"
        _install_error = str(e)


@router.post("/image/pull", response_model=PullImageResponse)
def pull_image(request: PullImageRequest, background_tasks: BackgroundTasks):
    from src.tool.bash.backends import resolve_backend_name

    if resolve_backend_name() != "docker":
        return PullImageResponse(status="completed", message="本地执行无需拉取镜像。")

    try:
        get_container_engine()  # 校验 docker 存在，缺失时抛 RuntimeError
        background_tasks.add_task(_pull_image_task, request.image_name)

        return PullImageResponse(
            status="started",
            message=f"已开始后台拉取镜像 {request.image_name}，请稍候...",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"镜像拉取启动失败: {str(e)}")


def _install_task(engine: str):
    global _install_progress, _install_status, _install_error, _selected_engine

    _selected_engine = engine

    from src.tool.bash.backends import resolve_backend_name

    if resolve_backend_name() != "docker":
        # 本地执行不需要安装容器引擎
        _install_status = "completed"
        _install_progress = 100
        _install_error = None
        return

    try:
        _install_status = "installing"
        _install_progress = 10

        if shutil.which("docker"):
            success = True
            message = "Docker 已安装"
        else:
            success = False
            message = (
                "Docker 未安装，请手动安装 Docker Desktop。\n"
                "安装指引: https://docs.docker.com/get-docker/"
            )

        if success:
            _install_status = "completed"
            _install_progress = 100
            _install_error = None
        else:
            _install_status = "failed"
            _install_error = message
    except Exception as e:
        _install_status = "failed"
        _install_error = str(e)


@router.post("/env/install", response_model=InstallStatusResponse)
def trigger_install(request: InstallRequest, background_tasks: BackgroundTasks):
    global _install_status

    if _install_status == "installing":
        return InstallStatusResponse(
            status="installing",
            message="正在安装中，请稍候...",
            progress=_install_progress,
        )

    background_tasks.add_task(_install_task, request.engine)

    return InstallStatusResponse(
        status="started", message=f"开始安装 {request.engine} 环境...", progress=0
    )


@router.get("/env/install/status", response_model=InstallStatusResponse)
def get_install_status():
    return InstallStatusResponse(
        status=_install_status,
        message=_install_error if _install_status == "failed" else "安装进行中...",
        progress=_install_progress,
    )


@router.get("/container-engine")
def get_container_engine_info():
    from src.tool.bash.backends import resolve_backend_name

    backend = resolve_backend_name()
    if backend != "docker":
        local = _local_shell_info()
        return {
            "engine": "local",
            "version": None,
            "available_engines": {
                "docker": shutil.which("docker") is not None,
                "local": bool(local.get("ready")),
            },
            "selected_engine": _selected_engine,
            "exec_backend": backend,
        }

    try:
        engine = get_container_engine()
        version = _get_engine_version(engine)

        return {
            "engine": engine,
            "version": version,
            "available_engines": {
                "docker": shutil.which("docker") is not None,
                "local": bool(_local_shell_info().get("ready")),
            },
            "selected_engine": _selected_engine,
            "exec_backend": backend,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 🌟 文件上传到 buffer 目录 ---
UPLOAD_BUFFER_DIR = Path(BUFFER_DIR) / "upload"


@router.post("/agent/upload")
async def upload_buffer_file(
    file: UploadFile = File(...),
    filename: Optional[str] = None,
):
    """上传单个文件到 agent_vm/.buffer/upload 目录，供 Agent 读取。"""
    import aiofiles

    UPLOAD_BUFFER_DIR.mkdir(parents=True, exist_ok=True)
    save_name = filename or file.filename or f"upload_{uuid.uuid4().hex[:8]}"
    dest = UPLOAD_BUFFER_DIR / save_name

    async with aiofiles.open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)

    return {
        "success": True,
        "saved_path": str(dest),
        "size_bytes": dest.stat().st_size,
        "agent_path": str(dest.resolve()),
    }


# --- 🌟 Agent 大盘统计接口 ---


def summarize_usage_days(day_summaries: dict, today: str) -> dict:
    """把 {日期: 当日 model_usage 列表} 汇总为今日用量与热力图。"""
    today_calls = 0
    today_tokens = 0
    today_cached_tokens = 0
    heatmap_data = {}

    for date_str, day_data in day_summaries.items():
        day_total_calls = sum(item.get("calls", 0) for item in day_data)
        day_total_tokens = sum(item.get("total_tokens", 0) for item in day_data)
        day_cached_tokens = sum(item.get("cached_tokens", 0) for item in day_data)

        heatmap_data[date_str] = day_total_calls

        if date_str == today:
            today_calls = day_total_calls
            today_tokens = day_total_tokens
            today_cached_tokens = day_cached_tokens

    return {
        "today": {
            "calls": today_calls,
            "total_tokens": today_tokens,
            "cached_tokens": today_cached_tokens,
        },
        "heatmap": heatmap_data,
    }


@router.get("/agent/stats")
def get_agent_stats():
    """前端首页调用：返回今日调用统计 + 热力图"""
    usage_tracer.flush()

    import glob
    from datetime import datetime

    target_dir = os.path.join(TRACKER_DIR, "model_usage")
    today_str = datetime.now().strftime("%Y-%m-%d")

    day_summaries = {}
    if os.path.exists(target_dir):
        file_paths = glob.glob(os.path.join(target_dir, "*_summary.json"))
        for path in file_paths:
            filename = os.path.basename(path)
            date_str = filename.split("_")[0]
            try:
                with open(path, "r", encoding="utf-8") as f:
                    day_summaries[date_str] = json.load(f)
            except Exception:
                continue

    return summarize_usage_days(day_summaries, today_str)
