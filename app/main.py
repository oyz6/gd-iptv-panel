"""gd-iptv-panel - FastAPI 后端入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import (
    CONFIG_PATH,
    OUTPUT_DIR,
    ConfigUpdate,
    bootstrap_config,
    ensure_dirs,
    load_config,
    merge_config,
    save_config,
)
from core.security import (
    client_key,
    login_throttle,
    require_auth,
    token_store,
)
from core.tasks import gen_manager
from models.schemas import LoginPayload, LoginResponse
from services import health as health_service
from services.generator import run_generate
from services.scheduler import get_schedule_state, start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logger = logging.getLogger("gd-iptv-panel")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    bootstrap_config()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="gd-iptv-panel", version="1.0.0", lifespan=lifespan)


def _generate_worker(cfg: dict, trigger: str = "manual") -> None:
    logger.info("开始生成任务 (trigger=%s)", trigger)
    try:
        result = run_generate(cfg)
        gen_manager.finish(result["ok"], result.get("error", ""))
        if result["ok"]:
            samples = health_service.extract_samples(
                cfg, int(cfg.get("health_max_samples", 8))
            )
            if samples:
                health_service.save_samples(samples)
                logger.info("[health] 已刷新健康样本：%d 个", len(samples))
    except Exception:
        logger.exception("生成任务异常")
        gen_manager.finish(False, "exception")


# =========================
# 认证
# =========================
@app.post("/api/login", response_model=LoginResponse)
def api_login(payload: LoginPayload, request: Request):
    key = client_key(request)
    if not login_throttle.allow(key):
        raise HTTPException(429, "登录尝试过于频繁，请稍后再试")

    cfg = load_config()
    if (
        payload.username == cfg.get("panel_username", "admin")
        and payload.password == cfg.get("panel_password", "admin")
    ):
        login_throttle.clear(key)
        return LoginResponse(ok=True, token=token_store.issue())

    login_throttle.record_failure(key)
    raise HTTPException(401, "用户名或密码错误")


@app.post("/api/logout")
def api_logout(request: Request):
    token = request.headers.get("X-Auth-Token", "")
    token_store.revoke(token)
    return {"ok": True}


@app.get("/api/auth-check")
def api_auth_check(request: Request):
    token = request.headers.get("X-Auth-Token", "")
    return {"ok": token_store.check(token)}


# =========================
# 配置
# =========================
@app.get("/api/config")
def api_get_config(request: Request):
    require_auth(request)
    return load_config()


@app.post("/api/config")
def api_set_config(cfg: ConfigUpdate, request: Request):
    require_auth(request)
    merged = merge_config(cfg)
    save_config(merged)
    return {"ok": True, "message": "配置已保存"}


# =========================
# 状态
# =========================
@app.get("/api/status")
def api_status(request: Request):
    require_auth(request)

    files = []
    if OUTPUT_DIR.exists():
        for f in sorted(OUTPUT_DIR.iterdir()):
            if f.is_file() and f.name != "run_gdctiptv.py":
                st = f.stat()
                files.append({
                    "name": f.name,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                })

    cfg = load_config()
    sched = get_schedule_state()
    return {
        "has_config": CONFIG_PATH.exists(),
        "output_files": files,
        "generating": gen_manager.is_running(),
        "health": {
            "enabled": cfg.get("schedule_enabled", False),
            "interval_hours": cfg.get("schedule_interval_hours", 1),
            "last_check": sched["last_check"],
            "last_generate": sched["last_generate"],
            "sample_count": len(health_service.load_samples()),
        },
    }


# =========================
# 生成
# =========================
@app.post("/api/generate")
def api_generate(request: Request, background: BackgroundTasks):
    require_auth(request)
    cfg = load_config()
    missing = [k for k in ("user_id", "password", "mac") if not (cfg.get(k) or "").strip()]
    if missing:
        raise HTTPException(400, f"缺少配置: {', '.join(missing)}")

    if not gen_manager.try_begin("manual"):
        raise HTTPException(409, "已有生成任务在运行，请稍候")

    background.add_task(_generate_worker, cfg, "manual")
    return {"ok": True, "message": "生成任务已启动"}


@app.get("/api/generate/status")
def api_generate_status(request: Request):
    require_auth(request)
    return gen_manager.snapshot()


# =========================
# 健康检查
# =========================
@app.post("/api/health-check")
def api_health_check(request: Request):
    require_auth(request)
    cfg = load_config()
    result = health_service.run_check(cfg)
    if result["total"] == 0:
        return {"ok": False, "message": "没有可检查的样本"}
    return {
        "ok": True,
        "total": result["total"],
        "failed": result["failed"],
        "rate": result["rate"],
        "details": result["details"],
    }


# =========================
# 结果文件
# =========================
@app.get("/playlist.m3u")
def api_playlist():
    p = OUTPUT_DIR / "gdctiptv4.m3u"
    if not p.exists():
        raise HTTPException(404, "播放列表尚未生成")
    return FileResponse(
        p,
        media_type="audio/x-mpegurl",
        filename="iptv.m3u",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/epg.xml")
def api_epg():
    p = OUTPUT_DIR / "gdctepg.xml"
    if not p.exists():
        raise HTTPException(404, "EPG 尚未生成")
    return FileResponse(
        p,
        media_type="application/xml",
        filename="epg.xml",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/playlist-content")
def api_playlist_content(request: Request):
    require_auth(request)
    p = OUTPUT_DIR / "gdctiptv4.m3u"
    if not p.exists():
        return {"ok": False, "content": ""}
    return {"ok": True, "content": p.read_text(encoding="utf-8", errors="replace")}


@app.get("/api/download/{filename}")
def api_download(filename: str, request: Request):
    require_auth(request)
    safe = Path(filename).name
    p = OUTPUT_DIR / safe
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(p, filename=safe)


# =========================
# 静态页面（最后挂载）
# =========================
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    @app.get("/")
    def _no_static():
        return JSONResponse(
            {"error": "静态目录缺失", "expected": str(STATIC_DIR)},
            status_code=500,
        )