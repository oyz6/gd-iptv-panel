"""健康检查：从 m3u 抽取样本、逐个探测。"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from pathlib import Path

from core.config import HEALTH_SAMPLES_PATH, OUTPUT_DIR

logger = logging.getLogger(__name__)


def check_url_alive(url: str, timeout: int = 6) -> bool:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "gd-iptv-panel-health"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(4096)
            return len(data) > 0
    except Exception as e:
        logger.debug("健康检查失败 %s: %s", url[:80], e)
        return False


def extract_samples(cfg: dict, max_samples: int = 8) -> list[str]:
    """从 gdctiptv4.m3u 抽取带 fcc 的 rtp2httpd 流地址。"""
    base = (cfg.get("rtp2httpd_url") or "").rstrip("/")
    if not base:
        return []

    m3u = OUTPUT_DIR / "gdctiptv4.m3u"
    if not m3u.exists():
        return []

    urls: list[str] = []
    for line in m3u.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith(base) or "/rtp/" not in line:
            continue
        if "fcc=" not in line:
            continue
        urls.append(line)

    if not urls:
        return []
    if len(urls) > max_samples:
        step = max(1, len(urls) // max_samples)
        urls = urls[::step][:max_samples]
    return urls


def save_samples(urls: list[str]) -> None:
    try:
        HEALTH_SAMPLES_PATH.write_text(
            json.dumps(
                {"urls": urls, "saved_at": time.time()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("保存健康样本失败: %s", e)


def load_samples() -> list[str]:
    if not HEALTH_SAMPLES_PATH.exists():
        return []
    try:
        data = json.loads(HEALTH_SAMPLES_PATH.read_text(encoding="utf-8"))
        urls = data.get("urls", [])
        return list(urls) if isinstance(urls, list) else []
    except Exception:
        return []


def run_check(cfg: dict) -> dict:
    samples = load_samples()
    if not samples:
        samples = extract_samples(cfg, int(cfg.get("health_max_samples", 8)))
        if samples:
            save_samples(samples)

    if not samples:
        return {"total": 0, "failed": 0, "rate": 0.0, "details": []}

    timeout = int(cfg.get("health_timeout", 6))
    details = []
    failed = 0
    for url in samples:
        ok = check_url_alive(url, timeout)
        details.append({"url": url, "ok": ok})
        if not ok:
            failed += 1

    return {
        "total": len(samples),
        "failed": failed,
        "rate": failed / len(samples),
        "details": details,
    }