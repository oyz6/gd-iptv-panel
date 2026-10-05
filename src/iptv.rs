use crate::config::Config;
use anyhow::{anyhow, Result};
use des::{
    cipher::{block_padding::Pkcs7, BlockEncryptMut, KeyInit},
    TdesEde3,
};
#[cfg(not(any(target_os = "android", target_os = "fuchsia", target_os = "linux")))]
use local_ip_address::list_afinet_netifas;
use log::{debug, info};
use rand::Rng;
use regex_lite::Regex;
use reqwest::Client;
use serde::Deserialize;
use std::{
    collections::HashMap,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::task::JoinSet;

// =========================
// HTTP 客户端
// =========================

fn get_client_with_if(#[allow(unused_variables)] if_name: Option<&str>) -> Result<Client> {
    let timeout = Duration::new(5, 0);
    #[allow(unused_mut)]
    let mut client = Client::builder().timeout(timeout).cookie_store(true);

    #[cfg(not(any(target_os = "android", target_os = "fuchsia", target_os = "linux")))]
    if let Some(i) = if_name {
        let network_interfaces = list_afinet_netifas()?;
        for (name, ip) in network_interfaces.iter() {
            debug!("{}: {}", name, ip);
            if name == i {
                client = client.local_address(ip.to_owned());
                break;
            }
        }
    }

    #[cfg(any(target_os = "android", target_os = "fuchsia", target_os = "linux"))]
    if let Some(i) = if_name {
        client = client.interface(i);
    }

    Ok(client.build()?)
}

// =========================
// 认证
// =========================

async fn get_base_url(client: &Client, cfg: &Config) -> Result<String> {
    let user = cfg.iptv.user.as_str();

    let params = [("Action", "Login"), ("return_type", "1"), ("UserID", user)];

    let url = reqwest::Url::parse_with_params(
        "http://eds.iptv.gd.cn:8082/EDS/jsp/AuthenticationURL",
        params,
    )?;

    let response = client.get(url).send().await?.error_for_status()?;

    let epgurl = reqwest::Url::parse(response.json::<AuthJson>().await?.epgurl.as_str())?;
    let base_url = format!(
        "{}://{}:{}",
        epgurl.scheme(),
        epgurl.host_str().ok_or(anyhow!("no host"))?,
        epgurl.port_or_known_default().ok_or(anyhow!("no host"))?,
    );
    debug!("Got base_url {base_url}");
    Ok(base_url)
}

// =========================
// 数据结构
// =========================

pub(crate) struct Program {
    pub(crate) start: i64,
    pub(crate) stop: i64,
    pub(crate) title: String,
    pub(crate) desc: String,
}

pub(crate) struct Channel {
    pub(crate) id: u64,
    pub(crate) name: String,
    pub(crate) rtsp: String,
    pub(crate) igmp: Option<String>,
    /// FEC 端口（ChannelFECPort），保留供后续使用
    #[allow(dead_code)]
    pub(crate) fec_port: Option<String>,
    pub(crate) epg: Vec<Program>,
}

#[derive(Deserialize)]
struct AuthJson {
    epgurl: String,
}

#[derive(Deserialize)]
struct TokenJson {
    #[serde(rename = "EncryToken")]
    encry_token: String,
}

#[derive(Deserialize)]
struct PlaybillList {
    #[serde(rename = "playbillLites")]
    list: Vec<Bill>,
}

#[derive(Deserialize)]
struct Bill {
    name: String,
    #[serde(rename = "startTime")]
    start_time: i64,
    #[serde(rename = "endTime")]
    end_time: i64,
}

// =========================
// 频道获取
// =========================

pub(crate) async fn get_channels(
    cfg: &Config,
    need_epg: bool,
    scheme: &str,
    host: &str,
) -> Result<Vec<Channel>> {
    info!("Obtaining channels");

    let user = cfg.iptv.user.as_str();
    let passwd = cfg.iptv.passwd.as_str();
    let mac = cfg.iptv.mac.as_str();
    let imei = cfg.iptv.imei.as_str();
    let ip = cfg.iptv.address.as_str();

    let client = get_client_with_if(cfg.iptv.interface.as_deref())?;

    let base_url = get_base_url(&client, cfg).await?;

    // ── 1. 获取 EncryToken ──
    let params = [
        ("response_type", "EncryToken"),
        ("client_id", "smcphone"),
        ("userid", user),
    ];
    let url = reqwest::Url::parse_with_params(
        format!("{base_url}/EPG/oauth/v2/authorize").as_str(),
        params,
    )?;
    let response = client.get(url).send().await?.error_for_status()?;

    let token = response.json::<TokenJson>().await?.encry_token;

    debug!("Got token {token}");

    // ── 2. 3DES 加密 authinfo ──
    let enc = ecb::Encryptor::<TdesEde3>::new_from_slice(
        format!("{:X}", md5::compute(passwd.as_bytes()))[0..24].as_bytes(),
    );
    let enc = match enc {
        Ok(enc) => Ok(enc),
        Err(e) => Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            format!("Encrpy error {e}"),
        )),
    }?;
    let data = format!(
        "{}${token}${user}${imei}${ip}${mac}$$CTC",
        rand::thread_rng().gen_range(0..10000000),
    );
    let auth = hex::encode_upper(enc.encrypt_padded_vec_mut::<Pkcs7>(data.as_bytes()));

    debug!("Got auth {auth}");

    // ── 3. 用 authinfo 换 token ──
    let params = [
        ("client_id", "smcphone"),
        ("DeviceType", "deviceType"),
        ("UserID", user),
        ("DeviceVersion", "deviceVersion"),
        ("userdomain", "2"),
        ("datadomain", "3"),
        ("accountType", "1"),
        ("authinfo", auth.as_str()),
        ("grant_type", "EncryToken"),
    ];
    let url =
        reqwest::Url::parse_with_params(format!("{base_url}/EPG/oauth/v2/token").as_str(), params)?;
    let _response = client.get(url).send().await?.error_for_status()?;

    // ── 4. 拉频道列表 ──
    let url = reqwest::Url::parse(format!("{base_url}/EPG/jsp/getchannellistHWCTC.jsp").as_str())?;

    let response = client.get(url).send().await?.error_for_status()?;

    let res = response.text().await?;
    let re = Regex::new("Authentication.CTCSetConfig\\('Channel','(.+?)'\\)")?;
    let mut channels = re
        .captures_iter(&res)
        .map(|cap| cap[1].to_string())
        .map(|s| {
            s.split("\",")
                .map(|s| s.split("=\"").collect::<Vec<_>>())
                .filter_map(|s| {
                    s.first()
                        .map(|a| String::from(*a))
                        .and_then(|a| s.get(1).map(|b| String::from(*b)).map(|b| (a, b)))
                })
                .collect::<HashMap<_, _>>()
        })
        .collect::<Vec<_>>();

    // ── 5. 解析频道字段 ──
    let channels = channels
        .iter_mut()
        .filter_map(|m| {
            m.get("ChannelID")
                .and_then(|i| str::parse::<u64>(i).ok())
                .map(|i| (i, m))
        })
        .filter_map(|(i, m)| m.get("ChannelName").cloned().map(|n| (i, n, m)))
        .filter_map(|(i, n, m)| {
            // 频道的 FCC（优先）
            let fcc_ip = m.get("ChannelFCCIP").cloned().unwrap_or_default();
            let fcc_port = m.get("ChannelFCCPort").cloned().unwrap_or_default();
            let channel_fcc = if !fcc_ip.is_empty() && !fcc_port.is_empty() {
                format!("{}:{}", fcc_ip, fcc_port)
            } else {
                String::new()
            };

            // 频道的 FEC 端口
            let fec_port = m.get("ChannelFECPort").cloned();

            m.get("ChannelURL")
                .and_then(|u| {
                    let rtsp = u.split('|').find(|u| u.starts_with("rtsp"));
                    let igmp = u.split('|').find(|u| u.starts_with("igmp"));
                    rtsp.map(|rtsp| (rtsp, igmp))
                })
                .map(|(rtsp, igmp)| {
                    (
                        // RTSP 直播流（用于回看 catchup-source）
                        if cfg.proxy.rtsp_proxy {
                            rtsp.replace("rtsp://", &format!("{}://{}/rtsp/", scheme, host))
                        } else {
                            rtsp.to_string()
                        }
                        .replace("zoneoffset=0", "zoneoffset=480"),
                        // IGMP 组播流（用于直播）
                        igmp.map(|igmp| {
                            if cfg.proxy.udp_proxy {
                                let mut url =
                                    igmp.replace("igmp://", &format!("{}://{}/rtp/", scheme, host));
                                // 加 FCC
                                let fcc = if !channel_fcc.is_empty() {
                                    channel_fcc.clone()
                                } else {
                                    cfg.proxy.fcc_server.clone()
                                };
                                if !fcc.is_empty() {
                                    url = format!(
                                        "{}?fcc={}&fcc-type={}",
                                        url, fcc, cfg.proxy.fcc_type
                                    );
                                }
                                // 加 FEC
                                if let Some(fec) = &fec_port {
                                    if !fec.is_empty() && fec != "0" {
                                        url = format!("{}&fec={}", url, fec);
                                    }
                                }
                                url
                            } else {
                                igmp.to_string()
                            }
                        }),
                    )
                })
                .map(|u| (i, n, u, fec_port))
        })
        .map(|(i, n, (rtsp, igmp), fec)| Channel {
            id: i,
            name: n.to_owned(),
            rtsp,
            igmp,
            fec_port: fec,
            epg: vec![],
        })
        .collect::<Vec<_>>();

    info!("Got {} channel(s)", channels.len());

    if !need_epg {
        return Ok(channels);
    }

    // ── 6. 拉取全部 EPG ──
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();

    let mut tasks = JoinSet::new();

    for channel in channels.into_iter() {
        let params = [
            ("channelId", format!("{}", channel.id)),
            ("begin", format!("{}", now - 86400000 * 2)),
            ("end", format!("{}", now + 86400000 * 5)),
        ];
        let url = reqwest::Url::parse_with_params(
            format!("{base_url}/EPG/jsp/iptvsnmv3/en/play/ajax/_ajax_getPlaybillList.jsp").as_str(),
            params,
        )?;
        let client = client.clone();
        tasks.spawn(async move { (client.get(url).send().await, channel) });
    }

    let mut channels = vec![];
    while let Some(Ok((Ok(res), mut channel))) = tasks.join_next().await {
        if let Ok(play_bill_list) = res.json::<PlaybillList>().await {
            for bill in play_bill_list.list.into_iter() {
                channel.epg.push(Program {
                    start: bill.start_time,
                    stop: bill.end_time,
                    title: bill.name.clone(),
                    desc: bill.name,
                })
            }
        }
        channels.push(channel);
    }

    info!("Got {} channel(s) with EPG", channels.len());
    Ok(channels)
}

// =========================
// 频道图标
// =========================

pub(crate) async fn get_icon(cfg: &Config, id: &str) -> Result<Vec<u8>> {
    let client = get_client_with_if(cfg.iptv.interface.as_deref())?;

    let base_url = get_base_url(&client, cfg).await?;

    let url = reqwest::Url::parse(&format!(
        "{base_url}/EPG/jsp/iptvsnmv3/en/list/images/channelIcon/{}.png",
        id
    ))?;

    let response = client.get(url).send().await?.error_for_status()?;
    Ok(response.bytes().await?.to_vec())
}
