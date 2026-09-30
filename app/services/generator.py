"""模板渲染 + 子进程生成，实时流式输出日志。"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.config import OUTPUT_DIR
from core.tasks import gen_manager

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / "templates" / "gdctiptv.py.tmpl"

GENERATE_TIMEOUT = 1800


def _py_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _py_source_address(value: Any) -> str:
    if not value:
        return "None"
    return json.dumps(str(value), ensure_ascii=False)


def _py_from_json(value_str: str, default: Any) -> str:
    try:
        obj = json.loads(value_str) if isinstance(value_str, str) else value_str
    except Exception as e:
        logger.warning("JSON 解析失败，使用默认值: %s", e)
        obj = default
    return repr(obj)


_PLACEHOLDERS = {
    # 认证
    "__USER_ID__": lambda c: _py_literal(c.get("user_id", "")),
    "__PASSWORD__": lambda c: _py_literal(c.get("password", "")),
    "__MAC__": lambda c: _py_literal(c.get("mac", "")),
    "__IMEI__": lambda c: _py_literal(c.get("imei", "")),
    "__ADDRESS__": lambda c: _py_literal(c.get("address", "")),
    "__SOURCE_ADDRESS__": lambda c: _py_source_address(c.get("source_address", "")),
    "__EDS_URL__": lambda c: _py_literal(c.get("eds_url", "")),
    "__HTTP_TIMEOUT__": lambda c: str(int(c.get("http_timeout", 10))),
    "__EPG_WORKERS__": lambda c: str(int(c.get("epg_workers", 16))),

    # EPG
    "__EPG_DAYS_BEFORE__": lambda c: str(int(c.get("epg_days_before", 7))),
    "__EPG_DAYS_AFTER__": lambda c: str(int(c.get("epg_days_after", 2))),

    # 输出
    "__M3U_XMLTV_URL__": lambda c: _py_literal(c.get("epg_xmltv_url", "/epg.xml")),
    "__GENERATE_RTP2HTTPD_RTP__": lambda c: _py_literal(bool(c.get("generate_rtp2httpd_rtp", True))),
    "__GENERATE_XMLTV__": lambda c: _py_literal(bool(c.get("generate_xmltv", True))),
    "__GENERATE_XMLTV_GZ__": lambda c: _py_literal(bool(c.get("generate_xmltv_gz", False))),

    # 播放链接
    "__RTP2HTTPD_RTP_BASE_URL__": lambda c: _py_literal(c.get("rtp2httpd_url", "")),
    "__DEFAULT_FCC_SERVER__": lambda c: _py_literal(c.get("fcc_server", "")),
    "__USE_DEFAULT_FCC_FOR_MISSING_CHANNELS__": lambda c: _py_literal(bool(c.get("use_default_fcc_for_missing_channels", True))),
    "__RTP2HTTPD_FCC_TYPE__": lambda c: _py_literal(c.get("rtp2httpd_fcc_type", "telecom")),
    "__INCLUDE_FEC_IN_RTP_URLS__": lambda c: _py_literal(bool(c.get("include_fec_in_rtp_urls", True))),
    "__RTP2HTTPD_CATCHUP_SEEK_MODE__": lambda c: _py_literal(c.get("rtp2httpd_catchup_seek_mode", "")),
    "__RTP2HTTPD_CATCHUP_SEEK_OFFSET__": lambda c: _py_literal(c.get("rtp2httpd_catchup_seek_offset", "")),
    "__ADD_FCC_TO_EXTINF_ATTRIBUTES__": lambda c: _py_literal(bool(c.get("add_fcc_to_extinf_attributes", False))),
    "__INCLUDE_CATCHUP__": lambda c: _py_literal(bool(c.get("include_catchup", True))),
    "__PLAYSEEK_TEMPLATE__": lambda c: _py_literal(c.get("playseek_template", "${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}")),

    # 抓包兜底
    "__CAPTURE_FALLBACK_JSON__": lambda c: _py_literal(c.get("capture_fallback_json", "")),

    # EPG 兜底
    "__FILL_EMPTY_EPG_FROM_SAME_MULTICAST__": lambda c: _py_literal(bool(c.get("fill_empty_epg_from_same_multicast", True))),
    "__FILL_EMPTY_EPG_FROM_CHANNEL_ALIAS__": lambda c: _py_literal(bool(c.get("fill_empty_epg_from_channel_alias", True))),
    "__EPG_ALIAS_SUFFIXES__": lambda c: _py_from_json(c.get("epg_alias_suffixes_json", "[]"), []),
    "__EPG_ALIAS_RULES__": lambda c: _py_from_json(c.get("epg_alias_rules_json", "{}"), {}),
    "__NO_EPG_FALLBACK_CHANNEL_NAMES__": lambda c: _py_from_json(c.get("no_epg_fallback_channel_names_json", "[]"), []),
    "__FILL_EMPTY_EPG_WITH_PLACEHOLDER__": lambda c: _py_literal(bool(c.get("fill_empty_epg_with_placeholder", True))),
    "__PLACEHOLDER_EPG_TITLE__": lambda c: _py_literal(c.get("placeholder_epg_title", "暂无节目表")),
    "__PLACEHOLDER_EPG_DESC__": lambda c: _py_literal(c.get("placeholder_epg_desc", "")),
    "__PLACEHOLDER_EPG_INTERVAL_HOURS__": lambda c: str(int(c.get("placeholder_epg_interval_hours", 6))),

    # 外部源
    "__MERGE_EXTERNAL_M3U__": lambda c: _py_literal(bool(c.get("merge_external_m3u", True))),
    "__EXTERNAL_M3U_URL__": lambda c: _py_literal(c.get("external_m3u_url", "")),
    "__EXTERNAL_M3U_CACHE__": lambda c: _py_literal(c.get("external_m3u_cache", "")),
    "__EXTERNAL_M3U_TIMEOUT__": lambda c: str(int(c.get("external_m3u_timeout", 15))),
    "__EXTERNAL_GROUP_MIN_MATCH__": lambda c: str(int(c.get("external_group_min_match", 3))),
    "__EXTERNAL_GROUP_TITLES__": lambda c: _py_from_json(c.get("external_group_titles_json", "{}"), {}),
}


def patch_template(cfg: dict) -> str:
    if not TEMPLATE_PATH.exists():
        raise RuntimeError(f"模板脚本不存在: {TEMPLATE_PATH}")
    src = TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, fn in _PLACEHOLDERS.items():
        if key not in src:
            raise RuntimeError(f"模板缺少占位符: {key}")
        src = src.replace(key, fn(cfg))
    return src


def run_generate(cfg: dict) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_path = OUTPUT_DIR / "run_gdctiptv.py"
    patched = patch_template(cfg)
    run_path.write_text(patched, encoding="utf-8")

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(run_path)],
            cwd=str(OUTPUT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        logger.exception("启动生成子进程失败")
        return {"ok": False, "error": str(e)}

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            gen_manager.append_log(line)
        proc.wait(timeout=GENERATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        gen_manager.append_err("\n生成超时（30分钟）\n")
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        logger.exception("生成子进程异常")
        try:
            proc.kill()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}

    if proc.returncode == 0:
        return {"ok": True, "error": ""}
    return {"ok": False, "error": f"exit={proc.returncode}"}