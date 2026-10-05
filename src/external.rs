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
    pub group: String,
    pub attrs: Vec<(String, String)>,
}

/// 从外部 URL 拉取 M3U，解析为 ExternalChannel 列表。
///
/// 分组过滤：只保留 group-title 包含 "iptv源" 或 "网络源" 的条目。
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
            let group = p.attrs.iter()
                .find(|(k, _)| k == "group-title")
                .map(|(_, v)| v.clone())
                .unwrap_or_default();

            let target_group = match_target_group(&group);
            if !target_group.is_empty() && seen_urls.insert(line.to_string()) {
                result.push(ExternalChannel {
                    title: p.title,
                    url: line.to_string(),
                    group: target_group,
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

fn match_target_group(source_group: &str) -> String {
    let norm = source_group
        .chars()
        .filter(|c| c.is_alphanumeric() || is_cjk(*c))
        .collect::<String>()
        .to_lowercase();

    if norm.contains("iptv") {
        return "iptv源".to_string();
    }
    if norm.contains("网络") {
        return "网络源".to_string();
    }
    String::new()
}

fn is_cjk(c: char) -> bool {
    matches!(c as u32, 0x4E00..=0x9FFF)
}

/// 把 ExternalChannel 转成 M3U 行
pub fn to_m3u_lines(ch: &ExternalChannel) -> Vec<String> {
    let mut attrs = ch.attrs.clone();
    // 覆盖 group-title
    if let Some(slot) = attrs.iter_mut().find(|(k, _)| k == "group-title") {
        slot.1 = ch.group.clone();
    } else {
        attrs.push(("group-title".to_string(), ch.group.clone()));
    }

    let attr_str = attrs
        .iter()
        .map(|(k, v)| format!(r#"{}="{}""#, k, v.replace('"', "&quot;")))
        .collect::<Vec<_>>()
        .join(" ");

    vec![
        format!("#EXTINF:-1 {},{}", attr_str, ch.title),
        ch.url.clone(),
    ]
}
