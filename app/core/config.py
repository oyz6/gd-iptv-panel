"""配置模型：加载、保存、合并。首次启动自动从 example 初始化。"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, create_model

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("IPTV_DATA_DIR", "/data"))
CONFIG_PATH = DATA_DIR / "config.json"
OUTPUT_DIR = DATA_DIR / "output"
HEALTH_SAMPLES_PATH = DATA_DIR / "health_samples.json"

_BASE_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG_PATH = _BASE_DIR / "data" / "config.example.json"


class Config(BaseModel):
    """完整配置模型——所有字段都可以在前端修改。"""
    model_config = ConfigDict(extra="ignore")

    # 面板登录
    panel_username: str = "admin"
    panel_password: str = "admin"

    # IPTV 账号认证
    user_id: str = ""
    password: str = ""
    mac: str = ""
    imei: str = ""
    address: str = ""
    interface: str = ""              # 兼容占位，前端不显示，默认空
    source_address: str = ""

    # 网络与代理
    rtp2httpd_url: str = "http://192.168.1.189:4022"
    multicast_proxy_url: str = "http://192.168.1.189:4022"
    fcc_server: str = "183.59.156.166:8027"
    epg_xmltv_url: str = "/epg.xml"

    # 输出开关
    generate_rtp2httpd_rtp: bool = True
    generate_xmltv: bool = True
    generate_xmltv_gz: bool = False

    # EPG 抓取
    eds_url: str = "http://eds.iptv.gd.cn:8082/EDS/jsp/AuthenticationURL"
    http_timeout: int = 10
    epg_workers: int = 16
    epg_days_before: int = 7
    epg_days_after: int = 2

    # 播放链接
    rtp2httpd_fcc_type: str = "telecom"
    include_fec_in_rtp_urls: bool = True
    use_default_fcc_for_missing_channels: bool = True
    add_fcc_to_extinf_attributes: bool = False
    include_catchup: bool = True
    rtp2httpd_catchup_seek_mode: str = ""
    rtp2httpd_catchup_seek_offset: str = ""
    playseek_template: str = "${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}"

    # 外部源
    merge_external_m3u: bool = True
    external_m3u_url: str = "https://github.nezha.loc.cc/taoiptv.m3u"
    external_m3u_cache: str = "exports/external_hkat_cache.m3u"
    external_m3u_timeout: int = 15
    external_group_min_match: int = 3
    external_group_titles_json: str = '{"iptv源": "iptv源", "网络源": "网络源"}'

    # EPG 兜底
    fill_empty_epg_from_same_multicast: bool = True
    fill_empty_epg_from_channel_alias: bool = True
    fill_empty_epg_with_placeholder: bool = True
    placeholder_epg_title: str = "暂无节目表"
    placeholder_epg_desc: str = "运营商接口未提供该频道节目表"
    placeholder_epg_interval_hours: int = 6
    epg_alias_suffixes_json: str = '["时移专用"]'
    epg_alias_rules_json: str = '{"CCTV1-1M开机标清": ["CCTV-1综合"]}'
    no_epg_fallback_channel_names_json: str = '["CCTV4K-25P", "CCTV4K-50P"]'

    # 抓包兜底
    capture_fallback_json: str = "exports/pcap1_channels.json"

    # 链接健康检查
    schedule_enabled: bool = True
    schedule_interval_hours: int = 1
    health_timeout: int = 6
    health_max_samples: int = 6
    health_fail_threshold: float = 0.6


ConfigUpdate = create_model(
    "ConfigUpdate",
    __config__=ConfigDict(extra="ignore"),
    **{
        name: (Optional[field.annotation], None)
        for name, field in Config.model_fields.items()
    },
)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def bootstrap_config() -> None:
    """首次启动时，如果 config.json 不存在：

    1. 优先从 config.example.json 拷贝
    2. 没有 example 就用 Config 默认值生成
    绝不覆盖已存在的 config.json。
    """
    if CONFIG_PATH.exists():
        return
    ensure_dirs()
    if EXAMPLE_CONFIG_PATH.exists():
        try:
            shutil.copyfile(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
            try:
                os.chmod(CONFIG_PATH, 0o600)
            except OSError:
                pass
            logger.info("已从 %s 初始化 config.json", EXAMPLE_CONFIG_PATH)
            return
        except Exception as e:
            logger.warning("拷贝 example 失败，使用默认值: %s", e)
    save_config(Config().model_dump())
    logger.info("已使用默认值生成 config.json")


def load_config() -> dict[str, Any]:
    merged = Config().model_dump()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update({k: v for k, v in data.items() if k in merged})
        except Exception as e:
            logger.warning("读取配置失败，使用默认值: %s", e)
    return merged


def save_config(data: dict[str, Any]) -> None:
    ensure_dirs()
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def merge_config(update: ConfigUpdate) -> dict[str, Any]:
    existing = load_config()
    updates = update.model_dump(exclude_unset=True, exclude_none=True)
    existing.update(updates)
    return Config(**existing).model_dump()