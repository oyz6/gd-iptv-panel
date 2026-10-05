use anyhow::Result;
use log::{info, warn};
use reqwest::Client;
use std::sync::LazyLock;
use std::time::Duration;

static RE_ATTR: LazyLock<regex_lite::Regex> =
    LazyLock::new(|| regex_lite::Regex::new(r#"([\w-]+)="([^"]*)""#).unwrap());

#[derive(Debug, Clone)]
pub struct ExternalChannel {
    pub title: String,
    pub url: String,
    /// 原样保留的 EXTINF 属性（含 group-title、tvg-logo、tvg-id 等）
    pub attrs: Vec<(String, String)>,
}

/// 从外部 URL 拉取 M3U，解析为 ExternalChannel 列表。
///
/// 不做任何分组过滤，也不重写属性——完整保留源文件每条 EXTINF 的原始内容。
pub async fn fetch(url: &str, timeout_seconds: u64) -> Result<Vec<ExternalChannel>> {
    if url.is_empty() {
        return Ok(vec![]);
    }
    let client = Client::builder()
        .timeout(Duration::from_secs(timeout_seconds))
        .build()?;

    let text = client
        .get(url)
        .send()
        .await?
        .error_for_status()?
        .text()
        .await?;

    if !text.contains("#EXTM3U") && !text.contains("#EXTINF") {
        warn!("外部 M3U 内容不合法：{}", url);
        return Ok(vec![]);
    }

    let channels = parse(&text);
    info!("已解析 {} 个外部频道", channels.len());
    Ok(channels)
}

fn parse(text: &str) -> Vec<ExternalChannel> {
    let mut result = Vec::new();
    let mut current: Option<Pending> = None;
    // 相同 URL 只保留第一次出现，避免外部源里重复条目
    let mut seen_urls = std::collections::HashSet::new();

    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }

        if line.starts_with("#EXTINF") {
            let attrs = extract_attrs(line);
            let title = line.split(',').last().unwrap_or("").trim().to_string();
            current = Some(Pending { title, attrs });
        } else if line.starts_with('#') {
            // 其他 # 指令（如 #KODIPROP、#EXTVLCOPT）直接忽略
            continue;
        } else if let Some(p) = current.take() {
            if seen_urls.insert(line.to_string()) {
                result.push(ExternalChannel {
                    title: p.title,
                    url: line.to_string(),
                    attrs: p.attrs,
                });
            }
        }
    }

    result
}

struct Pending {
    title: String,
    attrs: Vec<(String, String)>,
}

fn extract_attrs(line: &str) -> Vec<(String, String)> {
    RE_ATTR
        .captures_iter(line)
        .filter_map(|c| {
            let key = c.get(1)?.as_str().to_string();
            let val = c.get(2)?.as_str().to_string();
            Some((key, val))
        })
        .collect()
}

/// 把 ExternalChannel 转成 M3U 行。
///
/// 原样输出 attrs（含 group-title），不再做任何覆盖或补写。
pub fn to_m3u_lines(ch: &ExternalChannel) -> Vec<String> {
    let attr_str = ch
        .attrs
        .iter()
        .map(|(k, v)| format!(r#"{}="{}""#, k, v.replace('"', "&quot;")))
        .collect::<Vec<_>>()
        .join(" ");

    let extinf = if attr_str.is_empty() {
        format!("#EXTINF:-1,{}", ch.title)
    } else {
        format!("#EXTINF:-1 {},{}", attr_str, ch.title)
    };

    vec![extinf, ch.url.clone()]
}
