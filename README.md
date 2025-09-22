# MODULO-YOLO

Frontend estático + Backend FastAPI para pré-processamento de imagens com opção de redimensionamento 640x640 (YOLO-style letterbox), geração de links públicos e envio de payload.

## Funcionalidades
- Pré-processamento no navegador com opção de redimensionar para 640x640 (letterbox, preserva proporção).
- Conversão para JPEG (qualidade 0.9) no browser.
- Renomeação manual e automática (registro-sequencial.jpg).
- Geração de link público por imagem via endpoint de upload.
- Envio de payload com imagens inline (base64) ou somente links.
- Backend em FastAPI servindo uploads estáticos.
- Evita conflitos: backend auto-incrementa o nome quando o arquivo já existe.

## Requisitos
- Python 3.11+

## Instalação
```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

## Execução
- Backend (FastAPI):
```bash
python3 -m uvicorn app:app --host 127.0.0.1 --port 8002
```
- Frontend (http.server):
```bash
python3 -m http.server 8000 --bind 127.0.0.1
```
- Acesse a UI: http://127.0.0.1:8000/index.html

## Configuração na UI
- Em "Gerar link público por imagem", use o endpoint:
  - http://127.0.0.1:8002/upload
- Em "Destino do Webhook", configure o seu endpoint de destino.
- Campo "Registro" opcional para organizar os uploads por pasta.
- Campo "Ponto": se preencher, o servidor garantirá nome único (auto-incrementa em caso de conflito).

# Upload Service

## Variáveis de Ambiente
- BASE_URL: (opcional) URL base para compor links públicos. Se não definida, o serviço infere automaticamente via cabeçalhos X-Forwarded-* ou request.base_url.
  - Ex.: `export BASE_URL="https://preprocessor.matika.app"`
- CORS_ORIGINS: (recomendado em produção) lista separada por vírgula dos domínios permitidos para chamadas do navegador.
  - Ex.: `export CORS_ORIGINS="https://preprocessor.matika.app,https://www.seudominio.com"`
- MAX_SIZE_MB: tamanho máximo de arquivo (MB). Padrão: 25

## CORS
- Em desenvolvimento local, o serviço libera por padrão `http://localhost:8000` e `http://127.0.0.1:8000`.
- Em produção, defina CORS_ORIGINS para restringir o acesso aos domínios da UI.

## Links Públicos
- Em produção atrás de proxy (Coolify/Traefik), deixar BASE_URL em branco é suportado: o backend detectará automaticamente o esquema/host usando `X-Forwarded-Proto`, `X-Forwarded-Host` e `X-Forwarded-Port`, caindo para `request.base_url` quando ausentes.

## Docker Compose (produção com Nginx)
```yaml
version: "3.9"
services:
  app:
    build: .
    container_name: modulo-yolo-app
    ports:
      - "80:80"
    environment:
      - CORS_ORIGINS=https://preprocessor.matika.app
      - MAX_SIZE_MB=25
      # BASE_URL opcional; se omitido será inferido pelos headers
      # - BASE_URL=https://preprocessor.matika.app
    volumes:
      - uploads:/app/imagens
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
volumes:
  uploads:
    driver: local
```

## Segurança
- Restrinja CORS_ORIGINS em produção.
- Não exponha segredos. Não faça commit de .env (já ignorado no .gitignore).

## Publicação no GitHub
1) Inicialize o repositório local
```bash
git init
git checkout -b main || git branch -M main
```
2) Adicione os arquivos e faça o commit inicial
```bash
git add .
git commit -m "feat: FastAPI upload + UI YOLO 640x640; proxy Nginx; ajustes dev local"
```
3) Crie um repositório vazio no GitHub e conecte o remoto
```bash
git remote add origin https://github.com/<seu-usuario>/<seu-repo>.git
```
4) Envie para o GitHub
```bash
git push -u origin main
```

## Licença
Defina a licença de sua preferência (MIT/Apache-2.0/etc.).