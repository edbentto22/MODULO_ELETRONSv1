FROM python:3.11-slim

# Definir argumentos de build
ARG ENVIRONMENT=production

# Instalar dependências do sistema e curl para health checks
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Criar usuário não-root
RUN groupadd -r appuser && useradd -r -g appuser -m appuser

# Configurar diretório de trabalho
WORKDIR /app

# Copiar requirements e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY app.py .
COPY index.html /var/www/html/
COPY start.sh /app/start.sh

# Criar diretórios necessários com permissões corretas
RUN mkdir -p /app/imagens \
    /var/log/nginx \
    /var/lib/nginx/body \
    /var/lib/nginx/fastcgi \
    /var/lib/nginx/proxy \
    /var/lib/nginx/scgi \
    /var/lib/nginx/uwsgi \
    /var/cache/nginx && \
    chown -R appuser:appuser /app/imagens && \
    chown -R www-data:www-data /var/log/nginx /var/lib/nginx /var/cache/nginx

# Tornar script executável
RUN chmod +x /app/start.sh

# Remover configuração padrão do nginx
RUN rm -f /etc/nginx/sites-enabled/default

# Configurar variáveis de ambiente
ENV ENVIRONMENT=${ENVIRONMENT}
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expor porta
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost/api/health || exit 1

# Usar usuário não-root para executar a aplicação
# (nginx precisará rodar como root internamente para bind na porta 80)
USER appuser

# Comando de inicialização
CMD ["/app/start.sh"]