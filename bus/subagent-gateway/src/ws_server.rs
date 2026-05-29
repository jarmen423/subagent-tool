use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path, State,
    },
    response::IntoResponse,
    routing::get,
    Router,
};
use futures_util::{SinkExt, StreamExt};

#[derive(Clone)]
struct AppState {
    nats_url: String,
}

pub fn router(nats_url: String) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/sessions/:session_id/stream", get(session_stream))
        .route("/waves/:wave_id/stream", get(wave_stream))
        .with_state(AppState { nats_url })
}

async fn health() -> impl IntoResponse {
    axum::Json(serde_json::json!({"status": "ok"}))
}

async fn session_stream(
    ws: WebSocketUpgrade,
    Path(session_id): Path<String>,
    State(state): State<AppState>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_session_stream(socket, session_id, state))
}

async fn wave_stream(
    ws: WebSocketUpgrade,
    Path(wave_id): Path<String>,
    State(state): State<AppState>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_wave_stream(socket, wave_id, state))
}

async fn handle_session_stream(socket: WebSocket, session_id: String, state: AppState) {
    let subject = format!("subagent.v1.session.{session_id}.>");
    bridge_nats_to_ws(socket, &state.nats_url, subject).await;
}

async fn handle_wave_stream(socket: WebSocket, wave_id: String, state: AppState) {
    let subject = format!("subagent.v1.wave.{wave_id}.events");
    bridge_nats_to_ws(socket, &state.nats_url, subject).await;
}

async fn bridge_nats_to_ws(mut socket: WebSocket, nats_url: &str, subject: String) {
    let client = match async_nats::connect(nats_url).await {
        Ok(c) => c,
        Err(err) => {
            let _ = socket
                .send(Message::Text(format!("{{\"error\":\"nats connect failed: {err}\"}}")))
                .await;
            return;
        }
    };

    let mut subscriber = match client.subscribe(subject).await {
        Ok(s) => s,
        Err(err) => {
            let _ = socket
                .send(Message::Text(format!("{{\"error\":\"nats subscribe failed: {err}\"}}")))
                .await;
            return;
        }
    };

    let (mut sender, mut receiver) = socket.split();

    loop {
        tokio::select! {
            maybe = subscriber.next() => {
                match maybe {
                    Some(msg) => {
                        let text = String::from_utf8_lossy(&msg.payload).into_owned();
                        if sender.send(Message::Text(text)).await.is_err() {
                            break;
                        }
                    }
                    None => break,
                }
            }
            maybe = receiver.next() => {
                match maybe {
                    Some(Ok(Message::Close(_))) | None => break,
                    Some(Ok(_)) => {}
                    Some(Err(_)) => break,
                }
            }
        }
    }
}
