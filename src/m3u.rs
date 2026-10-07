use crate::external::{self, ExternalChannel};
use crate::group;
use crate::iptv::Channel;
use crate::merge;
use std::sync::LazyLock;

static RE_TRAILING_DIGIT: LazyLock<regex_lite::Regex> =
    LazyLock::new(|| regex_lite::Regex::new(r"\s*\d+\s*$").unwrap());

/// 一个分组的预计算排序信息。
///
/// 把 `group_title` / `quality_rank` / `natural_key` 等昂贵计算从
/// `sort_by` 的比较闭包里挪出来，对每个分组只算一次，
/// 避免 O(n log n) 次重复计算。
struct GroupSortInfo {
    /// 分组在 GROUP_ORDER 里的下标
    group_idx: usize,
    /// 是否央视组
    is_cctv: bool,
    /// 央视组内排序键
    cctv_key: (u32, u16, String),
    /// 非央视组：画质等级
    quality: u8,
    /// 非央视组：自然排序 key
    natural: Vec<(u8, String)>,
    /// 组内第一个频道 id（最终兜底）
    id: u64,
}

/// 生成 M3U 播放列表。
///
/// 排序优先级：
///   1. 分组（置顶 / 央视 / 广东 / 卫视 / 少儿 / CGTN / 超清4K / 其他）
///   2. 央视组内：按 CCTV 号数字排序（CCTV-1 ~ CCTV-17，CCTV-4K/5+ 插入对应位置）
///   3. 其他组内：画质 + 自然排序
pub fn build_playlist(
    channels_in: Vec<Channel>,
    external: &[ExternalChannel],
    include_top: bool,
    include_catchup: bool,
    playseek_template: &str,
    scheme: &str,
    host: &str,
) -> String {
    // 1. 分组
    let groups = merge::group_by_base_name(channels_in);

    // 2. 为每个分组预先算好排序 key（只算一次）
    let mut ranked: Vec<(GroupSortInfo, Vec<Channel>)> = groups
        .into_iter()
        .map(|chs| {
            let name = &chs[0].name;
            let gt = group::group_title(name);
            let is_cctv = gt == "央视";
            let info = GroupSortInfo {
                group_idx: group::group_index(gt),
                is_cctv,
                cctv_key: if is_cctv {
                    extract_cctv_key(name)
                } else {
                    (0, 0, String::new())
                },
                quality: if is_cctv { 0 } else { merge::quality_rank(name) },
                natural: if is_cctv {
                    Vec::new()
                } else {
                    group::natural_key(name)
                },
                id: chs[0].id,
            };
            (info, chs)
        })
        .collect();

    // 3. 排序：比较的是预计算好的 key，不再有字符串分配 / 正则
    ranked.sort_by(|(a, _), (b, _)| {
        a.group_idx.cmp(&b.group_idx).then_with(|| {
            if a.is_cctv {
                a.cctv_key
                    .cmp(&b.cctv_key)
                    .then_with(|| a.id.cmp(&b.id))
            } else {
                a.quality
                    .cmp(&b.quality)
                    .then_with(|| a.natural.cmp(&b.natural))
                    .then_with(|| a.id.cmp(&b.id))
            }
        })
    });

    let mut out = String::from("#EXTM3U\n");

    // 4. 置顶副本
    if include_top {
        let mut tops: Vec<(&(GroupSortInfo, Vec<Channel>), u8)> = ranked
            .iter()
            .filter_map(|entry| {
                let rank = entry
                    .1
                    .iter()
                    .map(|c| group::match_top(&c.name))
                    .min()
                    .unwrap_or(0);
                if rank > 0 {
                    Some((entry, rank))
                } else {
                    None
                }
            })
            .collect();

        // sort_by_cached_key：key 只对每个入选组算一次
        tops.sort_by_cached_key(|(entry, rank)| {
            (*rank, group::natural_key(&entry.1[0].name))
        });

        for (entry, _) in tops {
            write_group(
                &mut out,
                &entry.1,
                "置顶",
                include_catchup,
                playseek_template,
                scheme,
                host,
            );
        }
    }

    // 5. 正常分组
    for (_, chs) in &ranked {
        let grp = group::group_title(&chs[0].name);
        write_group(
            &mut out,
            chs,
            grp,
            include_catchup,
            playseek_template,
            scheme,
            host,
        );
    }

    // 6. 外部源
    for ch in external {
        for line in external::to_m3u_lines(ch) {
            out.push_str(&line);
            out.push('\n');
        }
    }

    out
}

/// 央视排序键 `(CCTV号, 变体标志, 兜底名)`
///
/// * `CCTV-N`     → `(N, 0, "cctvN")`
/// * `CCTV-N+`    → `(N, 1, "cctvNplus")`（紧跟 CCTV-N 后）
/// * `CCTV-4K`    → `(4, 2, "cctv4k")`（紧跟 CCTV-4 后）
/// * 央视特色频道 → `(9999, 999, name)`（央视组内最后）
fn extract_cctv_key(name: &str) -> (u32, u16, String) {
    let name_norm = name.replace('＋', "+");
    let nl = name_norm.to_lowercase();

    // CCTV4K
    if nl.contains("cctv4k") || nl.contains("cctv-4k") {
        return (4, 2, "cctv4k".to_string());
    }

    // CCTV-N 或 CCTV-N+
    if let Some((n, has_plus)) = merge::parse_cctv_num(&nl) {
        let variant = if has_plus { 1u16 } else { 0u16 };
        let tail = if has_plus { "cctvNplus" } else { "cctvN" };
        return (n, variant, tail.to_string());
    }

    // 央视特色频道
    (9999, 999, name_norm.to_lowercase())
}

fn write_group(
    out: &mut String,
    chs: &[Channel],
    group_override: &str,
    include_catchup: bool,
    playseek_template: &str,
    scheme: &str,
    host: &str,
) {
    if chs.is_empty() {
        return;
    }

    let best = &chs[0];
    let display_name = clean_display_name(&best.name);

    out.push_str(&extinf_line(
        best,
        &display_name,
        group_override,
        include_catchup,
        playseek_template,
        scheme,
        host,
    ));
    out.push('\n');

    for ch in chs {
        let url = stream_url(ch);
        if !url.is_empty() {
            out.push_str(&url);
            out.push('\n');
        }
    }
}

/// 显示名清洗
fn clean_display_name(name: &str) -> String {
    let name_norm = name.replace('＋', "+");
    let nl = name_norm.to_lowercase();

    // CCTV4K
    if nl.contains("cctv4k") || nl.contains("cctv-4k") {
        return "CCTV-4K".to_string();
    }

    // CCTV-N 或 CCTV-N+
    if let Some((n, has_plus)) = merge::parse_cctv_num(&nl) {
        let suffix_str = if has_plus { "+" } else { "" };
        for suffix in ["欧洲", "美洲", "香港", "澳门", "台湾"] {
            if name_norm.contains(suffix) {
                return format!("CCTV-{}{}{}", n, suffix_str, suffix);
            }
        }
        return format!("CCTV-{}{}", n, suffix_str);
    }

    // 非 CCTV：去画质 / 版本 / 帧率后缀（保留 4K）
    let mut n = name.replace("4k", "4K");

    for w in [
        "超高清", "超清", "高清", "标清",
        "HD", "hd",
        "开机", "测试", "时移专用", "窄色域",
        "1M", "2M", "4M", "8M",
        "25P", "25p", "50P", "50p", "30P", "30p", "60P", "60p",
    ] {
        n = n.replace(w, "");
    }

    // 静态正则：不再每次编译
    n = RE_TRAILING_DIGIT.replace(&n, "").to_string();

    let n = n.trim().trim_end_matches(['-', '_', ' ']).trim().to_string();
    if n.is_empty() {
        name.to_string()
    } else {
        n
    }
}

fn extinf_line(
    ch: &Channel,
    display_name: &str,
    group: &str,
    include_catchup: bool,
    playseek_template: &str,
    scheme: &str,
    host: &str,
) -> String {
    let catchup = if include_catchup {
        let rtsp = ch.rtsp.as_str();
        let sep = if rtsp.contains('?') { '&' } else { '?' };
        format!(
            r#" catchup="default" catchup-source="{}{}playseek={}" "#,
            rtsp.replace(',', "%2C"),
            sep,
            playseek_template
        )
    } else {
        String::new()
    };

    format!(
        r#"#EXTINF:-1 tvg-id="{}" tvg-name="{}" tvg-chno="{}"{}tvg-logo="{}://{}/logo/{}.png" group-title="{}",{}"#,
        ch.id, display_name, ch.id, catchup, scheme, host, ch.id, group, display_name
    )
}

fn stream_url(ch: &Channel) -> String {
    if let Some(igmp) = &ch.igmp {
        if igmp.starts_with("http") {
            return igmp.clone();
        }
    }
    ch.rtsp.clone()
}

pub fn all_groups() -> &'static [&'static str] {
    crate::group::GROUP_ORDER
}
