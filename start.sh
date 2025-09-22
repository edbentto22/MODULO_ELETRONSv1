#!/bin/bash
set -e

# Definir variáveis
export ENVIRONMENT=${ENVIRONMENT:-production}
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Função de log
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Função de cleanup
cleanup() {
    log "Received signal, shutting down..."
    if [ ! -z "$UVICORN_PID" ]; then
        kill $UVICORN_PID 2>/dev/null || true
        wait $UVICORN_PID 2>/dev/null || true
    fi
    if [ ! -z "$NGINX_PID" ]; then
        kill $NGINX_PID 2>/dev/null || true
    fi
    exit 0
}

# Configurar trap para cleanup
trap cleanup SIGTERM SIGINT

log "Starting YOLO Image Preprocessor Service"
log "Environment: $ENVIRONMENT"

# Verificar diretórios necessários
log "Checking directories..."
mkdir -p /app/imagens
mkdir -p /var/log/nginx
mkdir -p /var/lib/nginx/body
mkdir -p /var/lib/nginx/fastcgi
mkdir -p /var/lib/nginx/proxy
mkdir -p /var/lib/nginx/scgi
mkdir -p /var/lib/nginx/uwsgi

# Verificar permissões
if [ ! -w "/app/imagens" ]; then
    log "ERROR: /app/imagens is not writable"
    exit 1
fi

# Configurar nginx
log "Configuring nginx..."
cat > /etc/nginx/nginx.conf << 'EOF'
user www-data;
worker_processes auto;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                   '$status $body_bytes_sent "$http_referer" '
                   '"$http_user_agent" "$http_x_forwarded_for"';
    
    access_log /var/log/nginx/access.log main;
    error_log /var/log/nginx/error.log warn;

    # Preferir cabeçalhos X-Forwarded-* vindos do proxy externo (Traefik) quando existirem
    map $http_x_forwarded_proto $proxy_x_forwarded_proto { default $scheme; ~. $http_x_forwarded_proto; }
    map $http_x_forwarded_host  $proxy_x_forwarded_host  { default $host;   ~. $http_x_forwarded_host; }
    map $http_x_forwarded_port  $proxy_x_forwarded_port  { default $server_port; ~. $http_x_forwarded_port; }

    # Performance
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 50M;

    # Gzip
    gzip on;
    gzip_vary on;
    gzip_min_length 10240;
    # Removidos must-revalidate e max-age=0 (inválidos) e adicionado 'auth' conforme docs
    gzip_proxied expired no-cache no-store private auth;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/x-javascript
        application/xml+rss
        application/javascript
        application/json;

    # Rate limiting (ajustado: uploads permitem picos mais altos)
    limit_req_zone $binary_remote_addr zone=upload:10m rate=3r/s;
    limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;

    server {
        listen 80 default_server;
        server_name _;
        
        # Security headers
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;

        # Frontend estático
        location / {
            root /var/www/html;
            try_files $uri $uri/ /index.html;
            
            # Cache headers for static files
            location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
                expires 1y;
                add_header Cache-Control "public, immutable";
            }
        }

        # API endpoints
        location /api/ {
            limit_req zone=api burst=5 nodelay;
            
            proxy_pass http://127.0.0.1:8002/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
            proxy_set_header X-Forwarded-Host $proxy_x_forwarded_host;
            proxy_set_header X-Forwarded-Port $proxy_x_forwarded_port;
            
            # Timeouts
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Upload endpoint com rate limiting específico (mais permissivo)
        location /api/upload {
            # Permite até 3 requisições/segundo por IP, com burst de 15 e pequena fila (sem nodelay)
            limit_req zone=upload burst=15;
            
            proxy_pass http://127.0.0.1:8002/upload;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
            proxy_set_header X-Forwarded-Host $proxy_x_forwarded_host;
            proxy_set_header X-Forwarded-Port $proxy_x_forwarded_port;
            
            # Timeout mais longo para uploads
            proxy_connect_timeout 5s;
            proxy_send_timeout 300s;
            proxy_read_timeout 300s;
            
            client_max_body_size 50M;
        }

        # Servir imagens estáticas
        location /imagens/ {
            proxy_pass http://127.0.0.1:8002/imagens/;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
            proxy_set_header X-Forwarded-Host $proxy_x_forwarded_host;
            proxy_set_header X-Forwarded-Port $proxy_x_forwarded_port;
            
            # Cache headers para imagens
            expires 1d;
            add_header Cache-Control "public";
        }

        # Health check
        location /health {
            access_log off;
            proxy_pass http://127.0.0.1:8002/health;
            proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
            proxy_set_header X-Forwarded-Host $proxy_x_forwarded_host;
            proxy_set_header X-Forwarded-Port $proxy_x_forwarded_port;
        }
    }
}
EOF

# Testar configuração do nginx
log "Testing nginx configuration..."
nginx -t

if [ $? -ne 0 ]; then
    log "ERROR: nginx configuration is invalid"
    exit 1
fi

# Iniciar nginx
log "Starting nginx..."
nginx -g "daemon off;" &
NGINX_PID=$!

# Aguardar nginx inicializar
sleep 2

# Verificar se nginx está rodando
if ! kill -0 $NGINX_PID 2>/dev/null; then
    log "ERROR: nginx failed to start"
    exit 1
fi

log "Nginx started successfully (PID: $NGINX_PID)"

# Iniciar FastAPI
log "Starting FastAPI application..."
if [ "$ENVIRONMENT" = "development" ]; then
    uvicorn app:app --host 127.0.0.1 --port 8002 --reload --log-level debug --root-path /api &
else
    uvicorn app:app --host 127.0.0.1 --port 8002 --workers 2 --log-level info --root-path /api &
fi

UVICORN_PID=$!
log "FastAPI started (PID: $UVICORN_PID)"

# Aguardar FastAPI inicializar
sleep 3

# Health check
log "Performing health check..."
for i in {1..10}; do
    if curl -f http://127.0.0.1:8002/health >/dev/null 2>&1; then
        log "Health check passed"
        break
    fi
    if [ $i -eq 10 ]; then
        log "ERROR: Health check failed after 10 attempts"
        exit 1
    fi
    log "Health check attempt $i failed, retrying..."
    sleep 2
done

log "Service is ready and healthy"

# Aguardar qualquer processo finalizar
wait