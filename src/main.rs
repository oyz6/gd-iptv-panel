use actix_web::{
    get, post,
    web::{Data, Json, Path, Query},
    App, HttpRequest, HttpResponse, HttpServer, Responder,
};
use anyhow::{anyhow, Result};
use argh::FromArgs;
use chrono::{FixedOffset, TimeZone, Utc};
use log::{info, warn};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    io::{BufWriter, Cursor, Read},
    net::SocketAddrV4,
    path::PathBuf,
    str::FromStr,
    sync::RwLock,
};
use xml::{
    reader::XmlEvent as XmlReadEvent,
    writer::{EmitterConfig, XmlEvent as XmlWriteEvent},
    EventReader,
};

mod auth;
mod config;
mod external;
mod group;
mod iptv;
mod merge;
mod m3u;
mod proxy;

use auth::TokenStore;
use config::{default_config_path, Config};
use iptv::{get_channels, get_icon, Channel};

#[derive(FromArgs)]
/// gd-iptv-panel - 广东电信 IPTV 播放列表 + EPG 面板
struct Args {
    /// 配置文件路径
    #[argh(option, short = 'c', default = "default_config_path().display().to_string()")]
    config: String,

    /// 监听地址（覆盖配置文件）
    #[argh(option, short = 'b')]
    bind: Option<String>,
}

pub struct AppState {
    pub config: RwLock<Config>,
    pub config_path: PathBuf,
    pub tokens: TokenStore,
}

// =========================
// 静态页面
// =========================
const INDEX_HTML: &str = include_str!("../static/index.html");

#[get("/")]
async fn index() -> impl Responder {
    HttpResponse::Ok()
        .content_type("text/html; charset=utf-8")
        .body(INDEX_HTML)
}

// =========================
// API：认证
// =========================
#[derive(Deserialize)]
struct LoginPayload {
    username: String,
    password: String,
}

#[derive(Serialize)]
struct LoginResponse {
    ok: bool,
    token: String,
}

#[post("/api/login")]
async fn api_login(state: Data<AppState>, body: Json<LoginPayload>) -> impl Responder {
    let cfg = state.config.read().unwrap();
    if body.username == cfg.admin_user && body.password == cfg.admin_pass {
        let token = state.tokens.issue();
        return HttpResponse::Ok().json(LoginResponse { ok: true, token });
    }
    HttpResponse::Unauthorized().json(serde_json::json!({
        "ok": false, "error": "用户名或密码错误"
    }))
}

#[post("/api/logout")]
async fn api_logout(state: Data<AppState>, req: HttpRequest) -> impl Responder {
    let token = req
        .headers()
        .get("X-Auth-Token")
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    state.tokens.revoke(token);
    HttpResponse::Ok().json(serde_json::json!({ "ok": true }))
}

#[get("/api/auth-check")]
async fn api_auth_check(state: Data<AppState>, req: HttpRequest) -> impl Responder {
    let token = req
        .headers()
        .get("X-Auth-Token")
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    HttpResponse::Ok().json(serde_json::json!({ "ok": state.tokens.check(token) }))
}

fn require_auth(state: &AppState, req: &HttpRequest) -> Result<()> {
    let token = req
        .headers()
        .get("X-Auth-Token")
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    if state.tokens.check(token) {
        Ok(())
    } else {
        Err(anyhow!("未登录"))
    }
}

// =========================
// API：配置
// =========================
#[get("/api/config")]
async fn api_get_config(state: Data<AppState>, req: HttpRequest) -> impl Responder {
    if require_auth(&state, &req).is_err() {
        return HttpResponse::Unauthorized().finish();
    }
    let cfg = state.config.read().unwrap();
    HttpResponse::Ok().json(&*cfg)
}

#[post("/api/config")]
async fn api_set_config(
    state: Data<AppState>,
    req: HttpRequest,
    body: Json<Config>,
) -> impl Responder {
    if require_auth(&state, &req).is_err() {
        return HttpResponse::Unauthorized().finish();
    }
    let mut cfg = body.into_inner();
    if let Ok(old) = state.config.read() {
        // bind 只在启动时生效，不允许运行时改
        cfg.bind = old.bind.clone();
    }
    if let Err(e) = cfg.save(&state.config_path) {
        return HttpResponse::InternalServerError()
            .json(serde_json::json!({ "ok": false, "error": e.to_string() }));
    }
    *state.config.write().unwrap() = cfg;
    HttpResponse::Ok().json(serde_json::json!({ "ok": true, "message": "配置已保存" }))
}

#[get("/api/status")]
async fn api_status(state: Data<AppState>, req: HttpRequest) -> impl Responder {
    if require_auth(&state, &req).is_err() {
        return HttpResponse::Unauthorized().finish();
    }
    let cfg = state.config.read().unwrap();
    let groups: Vec<&str> = m3u::all_groups().to_vec();
    HttpResponse::Ok().json(serde_json::json!({
        "ok": true,
        "groups": groups,
        "config_path": state.config_path.display().to_string(),
        "bind": cfg.bind,
    }))
}

// =========================
// 播放列表
// =========================
#[get("/playlist")]
async fn playlist(state: Data<AppState>, req: HttpRequest) -> impl Responder {
    let cfg = state.config.read().unwrap().clone();
    if !cfg.output.enable_playlist {
        return HttpResponse::NotFound().body("playlist disabled");
    }
    let scheme = req.connection_info().scheme().to_owned();
    let host = req.connection_info().host().to_owned();

    let channels = match get_channels(&cfg, false, &scheme, &host).await {
        Ok(ch) => ch,
        Err(e) => return HttpResponse::InternalServerError().body(format!("Error: {}", e)),
    };

    let external_channels = if cfg.external.enabled && cfg.external.merge_into_playlist {
        match external::fetch(&cfg.external.url, cfg.external.timeout_seconds).await {
            Ok(ch) => ch,
            Err(e) => {
                warn!("外部源拉取失败：{}", e);
                vec![]
            }
        }
    } else {
        vec![]
    };

    let body = m3u::build_playlist(
        channels,
        &external_channels,
        cfg.output.enable_top_channels,
        cfg.proxy.include_catchup,
        &cfg.proxy.playseek_template,
        &scheme,
        &host,
    );

    HttpResponse::Ok()
        .content_type("application/vnd.apple.mpegurl")
        .body(body)
}

// =========================
// EPG
// =========================
fn to_xmltv_time(unix_time: i64) -> Result<String> {
    match Utc.timestamp_millis_opt(unix_time) {
        chrono::LocalResult::Single(t) => Ok(t
            .with_timezone(&FixedOffset::east_opt(8 * 60 * 60).ok_or(anyhow!(""))?)
            .format("%Y%m%d%H%M%S")
            .to_string()),
        _ => Err(anyhow!("fail to parse time")),
    }
}

fn to_xmltv<R: Read>(channels: Vec<Channel>, extra: Option<EventReader<R>>) -> Result<String> {
    let mut buf = BufWriter::new(Vec::new());
    let mut writer = EmitterConfig::new()
        .perform_indent(false)
        .create_writer(&mut buf);

    writer.write(
        XmlWriteEvent::start_element("tv")
            .attr("generator-info-name", "gd-iptv-panel")
            .attr("source-info-name", "gd-iptv-panel"),
    )?;

    for channel in channels.iter() {
        writer.write(
            XmlWriteEvent::start_element("channel").attr("id", &format!("{}", channel.id)),
        )?;
        writer.write(XmlWriteEvent::start_element("display-name"))?;
        writer.write(XmlWriteEvent::characters(&channel.name))?;
        writer.write(XmlWriteEvent::end_element())?;
        writer.write(XmlWriteEvent::end_element())?;
    }

    // 合并外部 XMLTV
    if let Some(extra) = extra {
        for e in extra {
            match e {
                Ok(XmlReadEvent::StartElement {
                    name, attributes, ..
                }) => {
                    let name = name.to_string();
                    let name = name.as_str();
                    if ![
                        "channel",
                        "display-name",
                        "desc",
                        "title",
                        "sub-title",
                        "programme",
                    ]
                    .contains(&name)
                    {
                        continue;
                    }
                    let name = if name == "title" {
                        let mut iter = attributes.iter();
                        loop {
                            let attr = match iter.next() {
                                Some(a) => a,
                                None => break "title",
                            };
                            if attr.name.to_string() == "lang" && attr.value != "chi" {
                                break "title_extra";
                            }
                        }
                    } else {
                        name
                    };
                    let mut tag = XmlWriteEvent::start_element(name);
                    for attr in attributes.iter() {
                        tag = tag.attr(attr.name.borrow(), &attr.value);
                    }
                    writer.write(tag)?;
                }
                Ok(XmlReadEvent::Characters(content)) => {
                    writer.write(XmlWriteEvent::characters(&content))?;
                }
                Ok(XmlReadEvent::EndElement { name }) => {
                    let name = name.to_string();
                    let name = name.as_str();
                    if ![
                        "channel",
                        "display-name",
                        "desc",
                        "title",
                        "sub-title",
                        "programme",
                    ]
                    .contains(&name)
                    {
                        continue;
                    }
                    writer.write(XmlWriteEvent::end_element())?;
                }
                _ => {}
            }
        }
    }

    // 节目
    for channel in channels.iter() {
        for epg in channel.epg.iter() {
            writer.write(
                XmlWriteEvent::start_element("programme")
                    .attr("start", &format!("{} +0800", to_xmltv_time(epg.start)?))
                    .attr("stop", &format!("{} +0800", to_xmltv_time(epg.stop)?))
                    .attr("channel", &format!("{}", channel.id)),
            )?;
            writer.write(XmlWriteEvent::start_element("title").attr("lang", "chi"))?;
            writer.write(XmlWriteEvent::characters(&epg.title))?;
            writer.write(XmlWriteEvent::end_element())?;
            if !epg.desc.is_empty() {
                writer.write(XmlWriteEvent::start_element("desc"))?;
                writer.write(XmlWriteEvent::characters(&epg.desc))?;
                writer.write(XmlWriteEvent::end_element())?;
            }
            writer.write(XmlWriteEvent::end_element())?;
        }
    }

    writer.write(XmlWriteEvent::end_element())?;
    Ok(String::from_utf8(buf.into_inner()?)?)
}

#[get("/xmltv")]
async fn xmltv(state: Data<AppState>, req: HttpRequest) -> impl Responder {
    let cfg = state.config.read().unwrap().clone();
    if !cfg.output.enable_xmltv {
        return HttpResponse::NotFound().body("xmltv disabled");
    }
    let scheme = req.connection_info().scheme().to_owned();
    let host = req.connection_info().host().to_owned();

    match get_channels(&cfg, true, &scheme, &host).await {
        Err(e) => HttpResponse::InternalServerError().body(format!("Error: {}", e)),
        Ok(ch) => match to_xmltv(ch, None::<EventReader<Cursor<String>>>) {
            Ok(xml) => HttpResponse::Ok()
                .content_type("text/xml; charset=utf-8")
                .body(xml),
            Err(e) => HttpResponse::InternalServerError().body(format!("Error: {}", e)),
        },
    }
}

// =========================
// Logo
// =========================
#[get("/logo/{id}.png")]
async fn logo(state: Data<AppState>, path: Path<String>) -> impl Responder {
    let cfg = state.config.read().unwrap().clone();
    if !cfg.output.enable_logo {
        return HttpResponse::NotFound().body("logo disabled");
    }
    match get_icon(&cfg, &path).await {
        Ok(icon) => HttpResponse::Ok().content_type("image/png").body(icon),
        Err(e) => HttpResponse::NotFound().body(format!("Error: {}", e)),
    }
}

// =========================
// 代理：RTSP
// =========================
#[get("/rtsp/{tail:.*}")]
async fn rtsp(
    state: Data<AppState>,
    mut path: Path<String>,
    mut params: Query<BTreeMap<String, String>>,
) -> impl Responder {
    let interface = state.config.read().unwrap().iptv.interface.clone();
    let path = &mut *path;
    let params = &mut *params;
    let mut params = params.iter().map(|(k, v)| format!("{}={}", k, v));
    let param = params.next().unwrap_or("".to_string());
    let param = params.fold(param, |o, q| format!("{}&{}", o, q));
    HttpResponse::Ok().streaming(proxy::rtsp(
        format!("rtsp://{}?{}", path, param),
        interface,
    ))
}

// =========================
// 代理：UDP 组播（仅 /rtp/）
// =========================
#[get("/rtp/{addr}")]
async fn rtp_udp(addr: Path<String>) -> impl Responder {
    let addr_str: &str = &addr;
    let addr = match SocketAddrV4::from_str(addr_str) {
        Ok(addr) => addr,
        Err(e) => return HttpResponse::BadRequest().body(format!("Error: {}", e)),
    };
    HttpResponse::Ok().streaming(proxy::udp(addr))
}

// =========================
// 入口
// =========================
#[actix_web::main]
async fn main() -> std::io::Result<()> {
    env_logger::init();
    let args: Args = argh::from_env();
    let config_path = PathBuf::from(&args.config);

    let mut cfg = Config::load(&config_path)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))?;
    if let Some(bind) = args.bind {
        cfg.bind = bind;
    }

    let bind = cfg.bind.clone();
    info!("配置文件：{}", config_path.display());
    info!("监听地址：{}", bind);

    let state = Data::new(AppState {
        config: RwLock::new(cfg),
        config_path,
        tokens: TokenStore::new(),
    });

    HttpServer::new(move || {
        App::new()
            .app_data(state.clone())
            // 静态页面
            .service(index)
            // API
            .service(api_login)
            .service(api_logout)
            .service(api_auth_check)
            .service(api_get_config)
            .service(api_set_config)
            .service(api_status)
            // 内容
            .service(playlist)
            .service(xmltv)
            .service(logo)
            // 代理
            .service(rtsp)
            .service(rtp_udp)
    })
    .bind(&bind)?
    .run()
    .await
}
