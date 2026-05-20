use tokio::net::TcpListener;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use std::env;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::Mutex;

const HOST: &str = "127.0.0.1";
const DEFAULT_PORT: u16 = 5555;
const MAX_PORT: u16 = 5600;
const PORT_FILE: &str = "arb_core_port.txt";

struct AppState {
    master_ask: f64,
    master_bid: f64,
    master_spread: f64,
    master_seen: bool,
    slave_ask: f64,
    slave_bid: f64,
    slave_spread: f64,
    slave_seen: bool,
    entry_th: f64,
    exit_th: f64,
    master_pnl: f64,
    slave_pnl: f64,
    combined_pnl: f64,
    last_signal: String,
}

impl AppState {
    fn diff(&self) -> f64 {
        (self.slave_ask - self.master_bid).abs()
    }

    fn signal(&self) -> &'static str {
        if !self.master_seen || !self.slave_seen {
            return "SIGNAL WATCH";
        }

        let diff = self.diff();
        if diff > self.entry_th {
            if self.slave_ask > self.master_bid { "SIGNAL BUY_A_SELL_B" }
            else { "SIGNAL SELL_A_BUY_B" }
        } else if diff < self.exit_th {
            "SIGNAL EXIT"
        } else {
            "SIGNAL WATCH"
        }
    }

    fn refresh_signal(&mut self) -> String {
        let signal = self.signal().to_string();
        self.last_signal = signal.clone();
        signal
    }
}

async fn bind_available_port() -> io::Result<(TcpListener, u16)> {
    let preferred = env::var("ARB_CORE_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(DEFAULT_PORT);
    let mut ports = vec![preferred];
    for p in DEFAULT_PORT..=MAX_PORT {
        if !ports.contains(&p) { ports.push(p); }
    }
    let mut last = None;
    for p in ports {
        match TcpListener::bind((HOST, p)).await {
            Ok(l) => return Ok((l, p)),
            Err(e) => last = Some(e),
        }
    }
    Err(last.unwrap_or_else(|| io::Error::new(io::ErrorKind::AddrNotAvailable, "no ports")))
}

fn port_file_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Ok(p) = env::var("ARB_CORE_PORT_FILE") { paths.push(PathBuf::from(p)); }
    if let Ok(cwd) = env::current_dir() {
        paths.push(cwd.join(PORT_FILE));
        if cwd.file_name().and_then(|n| n.to_str()) == Some("rust_core") {
            if let Some(parent) = cwd.parent() { paths.push(parent.join(PORT_FILE)); }
        }
    }
    paths
}

fn publish_port(port: u16) {
    for p in port_file_paths() {
        let _ = fs::write(&p, port.to_string());
    }
}

#[tokio::main]
async fn main() {
    let (listener, port) = bind_available_port().await.expect("no port available");
    publish_port(port);
    eprintln!("Rust ARB core listening on {}:{}", HOST, port);

    let state = Arc::new(Mutex::new(AppState {
        master_ask: 0.0, master_bid: 0.0,
        master_spread: 0.0, master_seen: false,
        slave_ask: 0.0, slave_bid: 0.0,
        slave_spread: 0.0, slave_seen: false,
        entry_th: 10.0, exit_th: 5.0,
        master_pnl: 0.0, slave_pnl: 0.0, combined_pnl: 0.0,
        last_signal: "SIGNAL WATCH".to_string(),
    }));

    loop {
        let (socket, _) = listener.accept().await.unwrap();
        let state = state.clone();
        tokio::spawn(async move {
            let (reader, mut writer) = socket.into_split();
            let mut buf = BufReader::new(reader);
            let mut line = String::new();
            loop {
                line.clear();
                match buf.read_line(&mut line).await {
                    Ok(0) => break,
                    Ok(_) => {
                        let trimmed = line.trim();
                        if trimmed.starts_with("PRICES ") {
                            let parts: Vec<&str> = trimmed[7..].split_whitespace().collect();
                            if parts.len() >= 4 {
                                let ma: f64 = parts[0].parse().unwrap_or(0.0);
                                let mb: f64 = parts[1].parse().unwrap_or(0.0);
                                let sa: f64 = parts[2].parse().unwrap_or(0.0);
                                let sb: f64 = parts[3].parse().unwrap_or(0.0);
                                let mut s = state.lock().await;
                                s.master_ask = ma; s.master_bid = mb;
                                s.slave_ask = sa; s.slave_bid = sb;
                                s.master_seen = true;
                                s.slave_seen = true;
                                let signal = s.refresh_signal();
                                let _ = writer.write_all(format!("{}\n", signal).as_bytes()).await;
                            }
                        } else if trimmed.starts_with("TICK ") {
                            let parts: Vec<&str> = trimmed[5..].split_whitespace().collect();
                            if parts.len() >= 5 {
                                let role = parts[0].to_ascii_uppercase();
                                let ask: f64 = parts[1].parse().unwrap_or(0.0);
                                let bid: f64 = parts[2].parse().unwrap_or(0.0);
                                let spread: f64 = parts[3].parse().unwrap_or(0.0);
                                let pnl: f64 = parts[4].parse().unwrap_or(0.0);
                                let mut s = state.lock().await;
                                if role == "MASTER" {
                                    s.master_ask = ask;
                                    s.master_bid = bid;
                                    s.master_spread = spread;
                                    s.master_pnl = pnl;
                                    s.master_seen = true;
                                } else if role == "SLAVE" {
                                    s.slave_ask = ask;
                                    s.slave_bid = bid;
                                    s.slave_spread = spread;
                                    s.slave_pnl = pnl;
                                    s.slave_seen = true;
                                }
                                s.combined_pnl = s.master_pnl + s.slave_pnl;
                                let signal = s.refresh_signal();
                                let _ = writer.write_all(format!("OK {}\n", signal).as_bytes()).await;
                            }
                        } else if trimmed.starts_with("PNL ") {
                            let parts: Vec<&str> = trimmed[4..].split_whitespace().collect();
                            if parts.len() >= 3 {
                                let mut s = state.lock().await;
                                s.master_pnl = parts[0].parse().unwrap_or(0.0);
                                s.slave_pnl = parts[1].parse().unwrap_or(0.0);
                                s.combined_pnl = parts[2].parse().unwrap_or(0.0);
                                s.refresh_signal();
                                let _ = writer.write_all(b"OK\n").await;
                            }
                        } else if trimmed == "GET" {
                            let s = state.lock().await;
                            let resp = format!(
                                "DATA {:.5} {:.5} {:.5} {:.5} {:.5} {:.5} {:.2} {:.2} {:.2} {:.0} {:.0} {}\n",
                                s.master_ask, s.master_bid,
                                s.slave_ask, s.slave_bid,
                                s.diff(), s.entry_th,
                                s.master_pnl, s.slave_pnl, s.combined_pnl,
                                s.master_spread, s.slave_spread, s.last_signal,
                            );
                            let _ = writer.write_all(resp.as_bytes()).await;
                        } else if trimmed == "RESET" {
                            let mut s = state.lock().await;
                            s.master_ask = 0.0;
                            s.master_bid = 0.0;
                            s.master_spread = 0.0;
                            s.master_seen = false;
                            s.slave_ask = 0.0;
                            s.slave_bid = 0.0;
                            s.slave_spread = 0.0;
                            s.slave_seen = false;
                            s.master_pnl = 0.0;
                            s.slave_pnl = 0.0;
                            s.combined_pnl = 0.0;
                            s.last_signal = "SIGNAL WATCH".to_string();
                            let _ = writer.write_all(b"OK\n").await;
                        } else if trimmed.starts_with("CONFIG ") {
                            let parts: Vec<&str> = trimmed[7..].split_whitespace().collect();
                            if parts.len() >= 2 {
                                let entry: f64 = parts[0].parse().unwrap_or(10.0);
                                let exit: f64 = parts[1].parse().unwrap_or(5.0);
                                let mut s = state.lock().await;
                                s.entry_th = entry;
                                s.exit_th = exit;
                                s.refresh_signal();
                                let _ = writer.write_all(b"OK\n").await;
                            }
                        }
                    }
                    Err(_) => break,
                }
            }
        });
    }
}
