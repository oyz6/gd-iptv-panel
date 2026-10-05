use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Config {
    #[serde(default = "default_bind")]
    pub bind: String,

    #[serde(default = "default_admin_user")]
    pub admin_user: String,

    #[serde(default = "default_admin_pass")]
    pub admin_pass: String,

    #[serde(default)]
    pub iptv: IptvConfig,

    #[serde(default)]
    pub proxy: ProxyConfig,

    #[serde(default)]
    pub output: OutputConfig,

    #[serde(default)]
    pub external: ExternalConfig,
}

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct IptvConfig {
    #[serde(default)]
    pub user: String,
    #[serde(default)]
    pub passwd: String,
    #[serde(default)]
    pub mac: String,
    #[serde(default)]
    pub imei: String,
    #[serde(default)]
    pub address: String,
    #[serde(default)]
    pub interface: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ProxyConfig {
    #[serde(default)]
    pub udp_proxy: bool,
    #[serde(default)]
    pub rtsp_proxy: bool,
    #[serde(default = "default_true")]
    pub include_catchup: bool,
    #[serde(default = "default_playseek")]
    pub playseek_template: String,
    /// 默认 FCC 服务器地址（IP:端口）。频道有自己的 FCC 时优先用频道的。
    #[serde(default)]
    pub fcc_server: String,
    /// FCC 协议类型：telecom / huawei
    #[serde(default = "default_fcc_type")]
    pub fcc_type: String,
}

impl Default for ProxyConfig {
    fn default() -> Self {
        Self {
            udp_proxy: false,
            rtsp_proxy: false,
            include_catchup: true,
            playseek_template: "${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}".to_string(),
            fcc_server: String::new(),
            fcc_type: "telecom".to_string(),
        }
    }
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct OutputConfig {
    #[serde(default = "default_true")]
    pub enable_playlist: bool,
    #[serde(default = "default_true")]
    pub enable_xmltv: bool,
    #[serde(default = "default_true")]
    pub enable_logo: bool,
    #[serde(default = "default_true")]
    pub enable_top_channels: bool,
}

impl Default for OutputConfig {
    fn default() -> Self {
        Self {
            enable_playlist: true,
            enable_xmltv: true,
            enable_logo: true,
            enable_top_channels: true,
        }
    }
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ExternalConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub url: String,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: u64,
    #[serde(default = "default_true")]
    pub merge_into_playlist: bool,
}

impl Default for ExternalConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            url: String::new(),
            timeout_seconds: 15,
            merge_into_playlist: true,
        }
    }
}

fn default_bind() -> String { "0.0.0.0:4022".to_string() }
fn default_admin_user() -> String { "admin".to_string() }
fn default_admin_pass() -> String { "admin".to_string() }
fn default_true() -> bool { true }
fn default_timeout() -> u64 { 15 }
fn default_playseek() -> String {
    "${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}".to_string()
}
fn default_fcc_type() -> String { "telecom".to_string() }

impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        if !path.exists() {
            let cfg = Self::default();
            cfg.save(path)?;
            return Ok(cfg);
        }
        let text = std::fs::read_to_string(path)?;
        let cfg: Self = serde_json::from_str(&text)?;
        Ok(cfg)
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let text = serde_json::to_string_pretty(self)?;
        let tmp = path.with_extension("json.tmp");
        std::fs::write(&tmp, text)?;
        std::fs::rename(&tmp, path)?;
        Ok(())
    }

    pub fn validate(&self) -> Result<()> {
        if self.iptv.user.is_empty() {
            return Err(anyhow!("iptv.user 未配置"));
        }
        if self.iptv.passwd.is_empty() {
            return Err(anyhow!("iptv.passwd 未配置"));
        }
        if self.iptv.mac.is_empty() {
            return Err(anyhow!("iptv.mac 未配置"));
        }
        Ok(())
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            bind: default_bind(),
            admin_user: default_admin_user(),
            admin_pass: default_admin_pass(),
            iptv: IptvConfig::default(),
            proxy: ProxyConfig::default(),
            output: OutputConfig::default(),
            external: ExternalConfig::default(),
        }
    }
}

pub fn default_config_path() -> PathBuf {
    std::env::var("IPTV_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("./config.json"))
}
