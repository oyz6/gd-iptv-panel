/// 频道分组和置顶逻辑。

/// 置顶优先级（越小越靠前，0 = 不置顶）
pub fn match_top(name: &str) -> u8 {
    let nl = name.to_lowercase();
    if name.contains("广东珠江") { return 1; }
    if name.contains("岭南戏曲") { return 2; }
    if name.contains("大湾区") { return 3; }
    if name.contains("广东卫视") { return 4; }
    if name.contains("广东") && nl.contains("4k") && !name.contains("卫视") {
        return 5;
    }
    if regex_lite::Regex::new(r"cctv[\s\-_]*11(?:\D|$)")
        .unwrap()
        .is_match(&nl)
    {
        return 6;
    }
    0
}

const CCTV_SPECIAL: &[&str] = &[
    "风云音乐", "风云足球", "风云剧场", "风云",
    "第一剧场", "怀旧剧场", "世界地理", "女性时尚",
    "兵器科技", "电视指南", "央视精品", "央视台球",
    "高尔夫网球", "CCTV4K", "cctv4k",
    "CCTV4欧洲", "CCTV4美洲", "cctv4欧洲", "cctv4美洲",
];

const GD_LOCAL: &[&str] = &[
    "云浮", "肇庆", "汕头", "潮州", "梅州", "河源",
    "揭阳", "清远", "茂名", "阳江", "湛江", "中山",
    "珠海", "江门", "佛山", "东莞", "韶关", "惠州",
    "广州", "深圳",
];

const GD_KEYWORDS: &[&str] = &[
    "广东", "珠江", "岭南", "大湾区", "嘉佳卡通", "南方",
];

const KIDS: &[&str] = &["少儿", "卡通", "KAKU", "kaku"];

pub const GROUP_ORDER: &[&str] = &[
    "置顶", "央视", "广东", "卫视", "少儿", "CGTN", "超清4K", "其他",
];

/// 根据频道名返回分组标题
pub fn group_title(name: &str) -> &'static str {
    let nl = name.to_lowercase();

    if nl.contains("cgtn") {
        return "CGTN";
    }

    for k in CCTV_SPECIAL {
        if name.contains(k) || nl.contains(&k.to_lowercase()) {
            if !name.contains("广东") {
                return "央视";
            }
        }
    }

    if let Ok(re) = regex_lite::Regex::new(r"cctv[\s\-_]*(\d+)") {
        if let Some(cap) = re.captures(&nl) {
            if let Ok(n) = cap[1].parse::<u32>() {
                if (1..=17).contains(&n) {
                    return "央视";
                }
            }
        }
    }

    if name.contains("央视") && !name.contains("风云") && !name.contains("特色") {
        return "央视";
    }

    for k in KIDS {
        if name.contains(k) || nl.contains(&k.to_lowercase()) {
            return "少儿";
        }
    }

    for k in GD_LOCAL {
        if name.contains(k) {
            return "广东";
        }
    }
    for k in GD_KEYWORDS {
        if name.contains(k) {
            return "广东";
        }
    }

    if name.contains("卫视") {
        return "卫视";
    }

    if nl.contains("4k") || name.contains("超高清") || name.contains("超清") {
        return "超清4K";
    }

    "其他"
}

/// 分组排序索引：按 `GROUP_ORDER` 返回位置，未匹配的排最后
pub fn group_index(title: &str) -> usize {
    GROUP_ORDER
        .iter()
        .position(|&g| g == title)
        .unwrap_or(GROUP_ORDER.len())
}

/// 频道自然排序 key："CCTV2" 排在 "CCTV10" 前面
pub fn natural_key(name: &str) -> Vec<(u8, String)> {
    let re = regex_lite::Regex::new(r"\d+|\D+").unwrap();
    let mut key = Vec::new();
    for part in re.find_iter(name).map(|m| m.as_str()) {
        if part.is_empty() {
            continue;
        }
        if part.chars().all(|c| c.is_ascii_digit()) {
            key.push((0, format!("{:010}", part.parse::<u64>().unwrap_or(0))));
        } else {
            let normalized = part
                .chars()
                .filter(|c| !c.is_whitespace() && *c != '-' && *c != '+' && *c != '_' && *c != '/')
                .collect::<String>()
                .to_lowercase();
            if !normalized.is_empty() {
                key.push((1, normalized));
            }
        }
    }
    key
}
