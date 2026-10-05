//! 相似频道分组 + 画质识别。
use crate::iptv::Channel;
use std::collections::HashMap;
use std::sync::LazyLock;

static RE_CCTV_NUM: LazyLock<regex_lite::Regex> =
    LazyLock::new(|| regex_lite::Regex::new(r"cctv[\s\-_]*(\d+)").unwrap());

static RE_TRAILING_NUM: LazyLock<regex_lite::Regex> =
    LazyLock::new(|| regex_lite::Regex::new(r"\s*\d+\s*$").unwrap());

/// 画质等级（数字越小画质越好）
///
/// * 0 = 4K
/// * 1 = 超清 / 超高清
/// * 2 = 高清 / HD
/// * 3 = 其他（标清、普通等）
pub fn quality_rank(name: &str) -> u8 {
    let n = name.to_lowercase();
    if n.contains("4k") {
        return 0;
    }
    if n.contains("超高清") || n.contains("超清") {
        return 1;
    }
    if n.contains("高清") || n.contains("hd") {
        return 2;
    }
    3
}

/// 归一化：全角加号 → 半角
fn normalize_plus(s: &str) -> String {
    s.replace('＋', "+")
}

/// 解析 `CCTV-N` / `CCTV-N+` / `CCTV-Nplus`
///
/// 返回 `(N, has_plus)`。
pub(crate) fn parse_cctv_num(nl: &str) -> Option<(u32, bool)> {
    let cap = RE_CCTV_NUM.captures(nl)?;
    let n = cap[1].parse::<u32>().ok()?;
    let end = cap.get(0)?.end();
    let rest = &nl[end..];
    let has_plus = rest.starts_with('+') || rest.starts_with("plus");
    Some((n, has_plus))
}

/// 把频道名规范化为「基准名」，用于识别同一频道的不同版本。
fn base_name(name: &str) -> String {
    let name = normalize_plus(name);
    let nl = name.to_lowercase();

    // CCTV4K 是独立频道
    if nl.contains("cctv4k") || nl.contains("cctv-4k") {
        return "cctv4k".to_string();
    }

    // CCTV-N / CCTV-N+（+ 地域后缀）
    if let Some((n, has_plus)) = parse_cctv_num(&nl) {
        let plus_str = if has_plus { "plus" } else { "" };
        for suffix in ["欧洲", "美洲", "香港", "澳门", "台湾"] {
            if name.contains(suffix) {
                return format!("cctv{}{}{}", n, plus_str, suffix);
            }
        }
        return format!("cctv{}{}", n, plus_str);
    }

    // 非 CCTV 频道
    let mut n = name.to_string();

    for w in ["超高清", "超清", "高清", "标清", "4K", "4k", "HD", "hd"] {
        n = n.replace(w, "");
    }
    for w in [
        "开机", "测试", "时移专用", "窄色域",
        "1M", "2M", "4M", "8M",
        "25P", "25p", "50P", "50p", "30P", "30p", "60P", "60p",
    ] {
        n = n.replace(w, "");
    }
    n = n.replace("综合", "");

    // 去掉末尾孤立的数字（"广东4K超高清 窄色域 30" → "广东4K"）
    n = RE_TRAILING_NUM.replace(&n, "").to_string();

    n.chars()
        .filter(|c| !c.is_whitespace() && *c != '-' && *c != '_')
        .collect::<String>()
        .to_lowercase()
}

/// 按基准名分组：`base_name -> Vec<Channel>`
pub fn group_by_base_name(channels: Vec<Channel>) -> Vec<Vec<Channel>> {
    let mut groups: HashMap<String, Vec<Channel>> = HashMap::new();
    for ch in channels {
        let key = base_name(&ch.name);
        groups.entry(key).or_default().push(ch);
    }
    let mut list: Vec<Vec<Channel>> = groups.into_values().collect();
    for chs in list.iter_mut() {
        // 画质越高越靠前；同画质保持原顺序（稳定排序）
        chs.sort_by_key(|c| quality_rank(&c.name));
    }
    list
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cctv5_vs_plus() {
        assert_eq!(base_name("CCTV-5体育"), "cctv5");
        assert_eq!(base_name("CCTV-5超清"), "cctv5");
        assert_eq!(base_name("CCTV-5高清"), "cctv5");

        assert_eq!(base_name("CCTV5+体育高清"), "cctv5plus");
        assert_eq!(base_name("CCTV-5+"), "cctv5plus");
        assert_eq!(base_name("CCTV5＋体育高清-测试"), "cctv5plus");
        assert_eq!(base_name("CCTV5plus"), "cctv5plus");

        assert_ne!(
            base_name("CCTV-5体育"),
            base_name("CCTV5＋体育高清-测试")
        );
    }

    #[test]
    fn test_base_name_cctv() {
        assert_eq!(base_name("CCTV1-1M开机标清"), "cctv1");
        assert_eq!(base_name("CCTV-1综合"), "cctv1");
        assert_eq!(base_name("CCTV-1超清"), "cctv1");
        assert_eq!(base_name("CCTV-1高清"), "cctv1");
        assert_eq!(base_name("CCTV-3综艺"), "cctv3");
        assert_eq!(base_name("CCTV-3高清"), "cctv3");
        assert_eq!(base_name("CCTV-4中文国际"), "cctv4");
        assert_eq!(base_name("CCTV-4高清"), "cctv4");
        assert_eq!(base_name("CCTV4中文国际欧洲高清"), "cctv4欧洲");
        assert_eq!(base_name("CCTV4中文国际美洲高清"), "cctv4美洲");
        assert_eq!(base_name("CCTV-11戏曲"), "cctv11");
        assert_eq!(base_name("CCTV-11高清"), "cctv11");
        assert_eq!(base_name("CCTV4K-25P"), "cctv4k");
    }

    #[test]
    fn test_base_name_non_cctv() {
        assert_eq!(base_name("广东4K超高清"), "广东4k");
        assert_eq!(base_name("广东4K超高清 窄色域 30"), "广东4k");
        assert_eq!(base_name("广东卫视4k超高清"), "广东卫视4k");
        assert_eq!(base_name("广东卫视4k超高清25p"), "广东卫视4k");

        assert_eq!(base_name("广东珠江"), "广东珠江");
        assert_eq!(base_name("深圳卫视"), "深圳卫视");
    }

    #[test]
    fn test_quality_rank() {
        assert_eq!(quality_rank("广东4K超高清"), 0);
        assert_eq!(quality_rank("CCTV-1超清"), 1);
        assert_eq!(quality_rank("CCTV-1高清"), 2);
        assert_eq!(quality_rank("CCTV-1综合"), 3);
        assert_eq!(quality_rank("CCTV-5体育"), 3);
    }

    #[test]
    fn test_parse_cctv_num() {
        assert_eq!(parse_cctv_num("cctv1"), Some((1, false)));
        assert_eq!(parse_cctv_num("cctv-11高清"), Some((11, false)));
        assert_eq!(parse_cctv_num("cctv5+体育"), Some((5, true)));
        assert_eq!(parse_cctv_num("cctv5plus"), Some((5, true)));
        assert_eq!(parse_cctv_num("cctv-5体育高清"), Some((5, false)));
        assert_eq!(parse_cctv_num("凤凰卫视"), None);
    }
}
