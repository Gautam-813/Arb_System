use tokio::net::TcpListener;
use tokio::io::AsyncWriteExt;
use std::env;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::time::Duration;

const HOST: &str = "127.0.0.1";
const DEFAULT_PORT: u16 = 5555;
const MAX_PORT: u16 = 5600;
const PORT_FILE: &str = "arb_core_port.txt";

async fn bind_available_port() -> io::Result<(TcpListener, u16)> {
    let preferred = env::var("ARB_CORE_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(DEFAULT_PORT);

    let mut ports = vec![preferred];
    for port in DEFAULT_PORT..=MAX_PORT {
        if !ports.contains(&port) {
            ports.push(port);
        }
    }

    let mut last_error = None;
    for port in ports {
        match TcpListener::bind((HOST, port)).await {
            Ok(listener) => return Ok((listener, port)),
            Err(err) => {
                eprintln!("Port {} unavailable: {}", port, err);
                last_error = Some(err);
            }
        }
    }

    Err(last_error.unwrap_or_else(|| io::Error::new(io::ErrorKind::AddrNotAvailable, "no port candidates")))
}

fn port_file_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();

    if let Ok(path) = env::var("ARB_CORE_PORT_FILE") {
        paths.push(PathBuf::from(path));
    }

    if let Ok(cwd) = env::current_dir() {
        paths.push(cwd.join(PORT_FILE));
        if cwd.file_name().and_then(|name| name.to_str()) == Some("rust_core") {
            if let Some(parent) = cwd.parent() {
                paths.push(parent.join(PORT_FILE));
            }
        }
    }

    paths
}

fn publish_port(port: u16) {
    for path in port_file_paths() {
        if let Err(err) = fs::write(&path, port.to_string()) {
            eprintln!("Could not write {}: {}", path.display(), err);
        } else {
            println!("Published Rust ARB core port to {}", path.display());
        }
    }
}

#[tokio::main]
async fn main() {
    let (listener, port) = bind_available_port()
        .await
        .expect("No available Rust ARB core port in configured range");
    publish_port(port);
    println!("Rust ARB core listening on {}:{}", HOST, port);

    loop {
        let (mut socket, _) = listener.accept().await.unwrap();

        tokio::spawn(async move {
            // Simulated prices — real feed comes in Step 4
            let price_a_ask: f64 = 1.10050;
            let price_b_bid: f64 = 1.10080;
            let threshold: f64 = 0.00020;

            loop {
                let diff = price_b_bid - price_a_ask;

                let signal = if diff > threshold {
                    "BUY_A_SELL_B\n"
                } else if -diff > threshold {
                    "SELL_A_BUY_B\n"
                } else {
                    "NO_SIGNAL\n"
                };

                if socket.write_all(signal.as_bytes()).await.is_err() {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        });
    }
}
