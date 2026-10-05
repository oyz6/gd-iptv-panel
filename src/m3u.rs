use crate::external::{self, ExternalChannel};
use crate::group;
use crate::iptv::Channel;
use crate::merge;

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
    let mut groups = merge::group_by_base_name(channels_in);

    // 2. 排序
    groups.sort_by(|a, b| {
        // 2.1 分组
        let ga = group::group_index(group::group_title(&a[0].name));
        let gb = group::group_index(group::group_title(&b[0].name));
        if ga != gb {
            return ga.cmp(&gb);
        }

        // 2.2 央视组内：按 CCTV 数字排序
        if group::group_title(&a[0].name) == "央视" {
            let ka = extract_cctv_key(&a[0].name);
            let kb = extract_cctv_key(&b[0].name);
            return ka.cmp(&kb).then_with(|| a[0].id.cmp(&b[0].id));
        }

        // 2.3 其他组：画质 + 自然排序
        let qa = merge::quality_rank(&a[0].name);
        let qb = merge::quality_rank(&b[0].name);
        qa.cmp(&qb)
            .then_with(|| group::natural_key(&a[0].name).cmp(&group::natural_key(&b[0].name)))
            .then_with(|| a[0].id.cmp(&b[0].id))
    });

    let mut out = String::from("#EXTM3U\n");

    // 3. 置顶副本
    if include_top {
        let mut tops: Vec<&Vec<Channel>> = groups
            .iter()
            .filter(|g| g.iter().any(|c| group::match_top(&c.name) > 0))
            .collect();
        tops.sort_by_key(|g| {
            let rank = g
                .iter()
                .map(|c| group::match_top(&c.name))
                .min()
                .unwrap_or(0);
            (rank, group::natural_key(&g[0].name))
        });
        for chs in tops {
            write_group(
                &mut out,
                chs,
                "置顶",
                include_catchup,
                playseek_template,
                scheme,
                host,
            );
        }
    }

    // 4. 正常分组
    for chs in &groups {
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

    // 5. 外部源
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

    if let Ok(re) = regex_lite::Regex::new(r"\s*\d+\s*$") {
        n = re.replace(&n, "").to_string();
    }

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
