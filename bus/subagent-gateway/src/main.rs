mod ws_server;

use std::net::SocketAddr;

use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive("subagent_gateway=info".parse().unwrap()))
        .init();

    let host = std::env::var("SUBAGENT_GATEWAY_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port: u16 = std::env::var("SUBAGENT_GATEWAY_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(17341);
    let nats_url = std::env::var("SUBAGENT_NATS_URL").unwrap_or_else(|_| "nats://127.0.0.1:4222".into());

    let app = ws_server::router(nats_url);
    let addr: SocketAddr = format!("{host}:{port}").parse().expect("invalid bind address");
    tracing::info!("subagent-gateway listening on http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await.expect("bind failed");
    axum::serve(listener, app).await.expect("server failed");
}
