FROM rust:1-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main(){}" > src/main.rs \
 && cargo build --release --locked --features rustls \
 && rm -rf src

COPY src ./src
COPY static ./static
RUN touch src/main.rs && cargo build --release --locked --features rustls

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata curl \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /data

ENV TZ=Asia/Shanghai IPTV_CONFIG=/data/config.json
WORKDIR /app
COPY --from=builder /build/target/release/gd-iptv-panel /usr/local/bin/gd-iptv-panel

EXPOSE 4022
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:4022/api/auth-check >/dev/null || exit 1

CMD ["gd-iptv-panel", "-c", "/data/config.json"]
