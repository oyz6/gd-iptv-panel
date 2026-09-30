"""定时健康检查调度。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from core.config import load_config
from core.tasks import gen_manager
from services import health as health_service

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_thread: Optional[threading.Thread] = None
_state_lock = threading.Lock()
_last_health_check = 0.0
_last_generate_time = 0.0


def _update_last(check: Optional[float] = None,
                 generate: Optional[float] = None) -> None:
    global _last_health_check, _last_generate_time
    with _state_lock:
        if check is not None:
            _last_health_check = check
        if generate is not None:
            _last_generate_time = generate


def get_schedule_state() -> dict:
    with _state_lock:
        return {
            "last_check": _last_health_check,
            "last_generate": _last_generate_time,
        }


def _run_health_then_generate(cfg: dict) -> None:
    try:
        result = health_service.run_check(cfg)
        total = result["total"]
        failed = result["failed"]
        rate = result["rate"]

        if total == 0:
            logger.info("[health] 无样本可检查，跳过")
            return

        logger.info("[health] 失败 %d/%d (%.0f%%)", failed, total, rate * 100)
        for d in result["details"]:
            tag = "OK  " if d["ok"] else "FAIL"
            logger.info("[health] %s %s", tag, d["url"][:90])

        threshold = float(cfg.get("health_fail_threshold", 0.6))
        if rate >= threshold:
            logger.info(
                "[health] 失败率 %.0f%% ≥ %.0f%%，触发重新生成",
                rate * 100, threshold * 100,
            )
            if gen_manager.try_begin("health"):
                from services.generator import run_generate
                try:
                    gresult = run_generate(cfg)
                    gen_manager.finish(gresult["ok"], gresult.get("error", ""))
                    _update_last(generate=time.time())
                    if gresult["ok"]:
                        new_samples = health_service.extract_samples(
                            cfg, int(cfg.get("health_max_samples", 8))
                        )
                        if new_samples:
                            health_service.save_samples(new_samples)
                            logger.info("[health] 已刷新健康样本：%d 个",
                                        len(new_samples))
                except Exception:
                    logger.exception("[health] 生成异常")
                    gen_manager.finish(False, "exception")
            else:
                logger.info("[health] 已有生成任务在运行，跳过")
        else:
            logger.info("[health] 链接正常，无需重新生成")
    except Exception:
        logger.exception("[scheduler] 健康检查异常")


def _loop() -> None:
    while not _stop_event.is_set():
        try:
            cfg = load_config()
            if not cfg.get("schedule_enabled", False):
                if _stop_event.wait(60):
                    break
                continue

            hours = max(1, int(cfg.get("schedule_interval_hours", 1)))
            state = get_schedule_state()
            elapsed = time.time() - state["last_check"]

            if state["last_check"] == 0 or elapsed >= hours * 3600:
                if gen_manager.is_running():
                    logger.info("[scheduler] 有生成任务进行中，跳过本轮")
                else:
                    _update_last(check=time.time())
                    threading.Thread(
                        target=_run_health_then_generate,
                        args=(cfg,),
                        daemon=True,
                        name="health-worker",
                    ).start()

            if _stop_event.wait(60):
                break
        except Exception:
            logger.exception("[scheduler] 循环异常")
            if _stop_event.wait(60):
                break


def start_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="health-scheduler")
    _thread.start()
    logger.info("[scheduler] 已启动")


def stop_scheduler() -> None:
    _stop_event.set()