from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import base64, os, re, uuid, logging
from typing import Optional

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IMAGES_ROOT = os.path.abspath("./imagens")
os.makedirs(IMAGES_ROOT, exist_ok=True)

BASE_URL_ENV = os.getenv("BASE_URL")

# CORS: restringe via variável de ambiente CORS_ORIGINS (lista separada por vírgula)
# Ex.: CORS_ORIGINS="https://app.seu-dominio.com,https://www.seu-dominio.com"
_raw_origins = os.getenv("CORS_ORIGINS", "").strip()
CORS_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]
if not CORS_ORIGINS:
    # default seguro p/ dev local; em produção, configure CORS_ORIGINS
    CORS_ORIGINS = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:80",
        "http://127.0.0.1:80",
        # incluir 8002 para quando o backend roda nessa porta localmente
        "http://localhost:8002",
        "http://127.0.0.1:8002",
        # incluir 8006 quando servir frontend local com http.server 8006
        "http://localhost:8006",
        "http://127.0.0.1:8006",
    ]

DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w\-\.+/]+);base64,(?P<b64>.+)$")
ALLOWED_MIMES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

# Permitir configurar o tamanho máximo por variável de ambiente (padrão 25MB)
try:
    MAX_SIZE_MB = int(os.getenv("MAX_SIZE_MB", "25"))
except ValueError:
    MAX_SIZE_MB = 25

FILENAME_RE = re.compile(r"^(?P<registro>\d+)-(?P<ponto>\d+)\.(?P<ext>jpg|jpeg|png|webp)$", re.IGNORECASE)

class UploadIn(BaseModel):
    filename: str
    data_url: str
    registro: Optional[int] = None
    ponto: Optional[int] = None

app = FastAPI(
    title="Upload Service",
    description="Serviço de upload e pré-processamento de imagens YOLO",
    version="1.0.0"
)

# Configurar CORS com configurações mais específicas para produção
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,  # Melhor segurança
    allow_methods=["GET", "POST", "OPTIONS"],  # Apenas métodos necessários
    allow_headers=["Content-Type", "Authorization"],  # Headers específicos
)

# Montar arquivos estáticos com configurações de segurança
app.mount("/imagens", StaticFiles(directory=IMAGES_ROOT), name="imagens")


def parse_data_url(data_url: str):
    """Parse e valida data URL base64."""
    if not isinstance(data_url, str) or len(data_url) > 50 * 1024 * 1024:  # Limite de 50MB na string
        raise HTTPException(status_code=400, detail="data_url inválido ou muito grande")
    
    m = DATA_URL_RE.match(data_url)
    if not m:
        raise HTTPException(status_code=400, detail="data_url inválido")
    
    mime = m.group("mime").lower()
    b64 = m.group("b64")
    
    if mime not in ALLOWED_MIMES:
        raise HTTPException(status_code=400, detail=f"MIME não permitido: {mime}")
    
    try:
        binary = base64.b64decode(b64, validate=True)
    except Exception as e:
        logger.error(f"Erro ao decodificar base64: {e}")
        raise HTTPException(status_code=400, detail="base64 inválido")
    
    if len(binary) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Arquivo > {MAX_SIZE_MB}MB")
    
    return mime, binary


def get_base_url(request: Request) -> str:
    """
    Determina a BASE_URL dinamicamente quando não definida em ambiente,
    respeitando proxies reversos (X-Forwarded-*) normalmente usados por Coolify/Traefik
    """
    if BASE_URL_ENV:
        return BASE_URL_ENV.rstrip("/")
    
    # Verificar headers de proxy reverso (Coolify/Traefik)
    f_proto = request.headers.get("x-forwarded-proto")
    f_host = request.headers.get("x-forwarded-host")
    f_port = request.headers.get("x-forwarded-port")
    
    if f_host:
        scheme = f_proto or request.url.scheme
        host = f_host
        
        # Não adicionar porta se já estiver no host ou for porta padrão
        if f_port and ":" not in host and f_port not in ("80", "443"):
            # Só adicionar porta se não for a padrão do esquema
            if not ((scheme == "http" and f_port == "80") or (scheme == "https" and f_port == "443")):
                host = f"{host}:{f_port}"
        
        return f"{scheme}://{host}"
    
    # fallback direto
    base_url = str(request.base_url).rstrip("/")
    logger.info(f"Using fallback base URL: {base_url}")
    return base_url


def next_sequential_name(dir_path: str, base_prefix: str, ext: str, start: int = 1) -> str:
    """
    Adiciona parâmetro opcional 'start' para iniciar a busca a partir de um índice específico
    """
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)
    
    n = max(1, int(start))
    max_attempts = 10000  # Evitar loop infinito
    attempts = 0
    
    while attempts < max_attempts:
        candidate = f"{base_prefix}-{n}.{ext}"
        full = os.path.join(dir_path, candidate)
        
        if not os.path.exists(full):
            try:
                # Usar 'x' mode para criar apenas se não existir
                with open(full, "x") as f:
                    pass  # Criar arquivo vazio
                # Remover o arquivo temporário
                os.unlink(full)
                return candidate
            except FileExistsError:
                pass  # Arquivo foi criado entre a verificação e a tentativa
        
        n += 1
        attempts += 1
    
    raise HTTPException(status_code=500, detail="Não foi possível gerar nome único")


@app.get("/health")
def health() -> dict:
    """Endpoint simples de verificação de vida para Traefik/monitoração."""
    return {
        "status": "ok",
        "service": "upload-service",
        "images_root_exists": os.path.exists(IMAGES_ROOT),
        "images_root_writable": os.access(IMAGES_ROOT, os.W_OK)
    }


@app.get("/")
def root_info(request: Request) -> dict:
    """
    Informações úteis para diagnosticar roteamento em produção.
    Observação: a porta efetiva é definida no comando de inicialização do Uvicorn
    (ex.: --port 8002) e no mapeamento do proxy reverso. Este endpoint ajuda a
    confirmar BASE_URL, CORS e limites.
    """
    return {
        "service": "upload-service",
        "version": "1.0.0",
        "base_url": get_base_url(request),
        "cors_origins": CORS_ORIGINS,
        "max_size_mb": MAX_SIZE_MB,
        "allowed_mimes": list(ALLOWED_MIMES.keys()),
        "images_root": IMAGES_ROOT,
        "environment": os.getenv("ENVIRONMENT", "development")
    }


@app.post("/upload")
async def upload(payload: UploadIn, request: Request):
    """Upload de imagem com metadados opcionais."""
    try:
        # Validações de entrada
        if not payload.filename or not payload.data_url:
            raise HTTPException(status_code=400, detail="filename e data_url são obrigatórios")
        
        # Parse da imagem
        mime, binary = parse_data_url(payload.data_url)
        ext_by_mime = ALLOWED_MIMES[mime]
        
        # Sanitizar filename
        filename = os.path.basename(payload.filename or f"upload.{ext_by_mime}")
        filename = re.sub(r'[^\w\-_\.]', '', filename)  # Remover caracteres perigosos
        
        if not filename:
            filename = f"upload.{ext_by_mime}"

        registro = payload.registro
        ponto = payload.ponto

        # Extrair informações do nome do arquivo se seguir o padrão
        mfn = FILENAME_RE.match(filename.lower())
        if mfn:
            if registro is None:
                registro = int(mfn.group("registro"))
            if ponto is None:
                ponto = int(mfn.group("ponto"))

        # Determinar diretório e nome base
        if registro is None:
            dir_path = os.path.join(IMAGES_ROOT, "misc")
            base_prefix = uuid.uuid4().hex[:8]
        else:
            if not isinstance(registro, int) or registro < 0:
                raise HTTPException(status_code=400, detail="registro inválido")
            dir_path = os.path.join(IMAGES_ROOT, str(registro))
            base_prefix = str(registro)

        os.makedirs(dir_path, exist_ok=True)

        # Validar ponto
        if ponto is not None and (not isinstance(ponto, int) or ponto < 0):
            raise HTTPException(status_code=400, detail="ponto inválido")

        # Determinar nome final
        if ponto is not None:
            tentative_name = f"{base_prefix}-{ponto}.{ext_by_mime}"
            full_path = os.path.join(dir_path, tentative_name)
            if os.path.exists(full_path):
                final_name = next_sequential_name(dir_path, base_prefix, ext_by_mime, start=ponto + 1)
            else:
                final_name = tentative_name
        else:
            final_name = next_sequential_name(dir_path, base_prefix, ext_by_mime)

        full_path = os.path.join(dir_path, final_name)

        # Escrever arquivo
        try:
            with open(full_path, "wb") as f:
                f.write(binary)
        except OSError as e:
            logger.error(f"Erro ao escrever arquivo {full_path}: {e}")
            raise HTTPException(status_code=500, detail="Erro ao salvar arquivo")

        # Construir URL de resposta
        if registro is None:
            rel_url = f"/imagens/misc/{final_name}"
        else:
            rel_url = f"/imagens/{registro}/{final_name}"

        base = get_base_url(request)
        link = f"{base}{rel_url}"

        logger.info(f"Arquivo salvo: {full_path}, link: {link}")

        return {
            "link": link,
            "mime": mime,
            "size": len(binary),
            "registro": registro,
            "ponto": ponto,
            "path": rel_url,
            "filename": final_name
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro inesperado no upload: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# Middleware de log para debug
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware para log de requisições (apenas em desenvolvimento)."""
    if os.getenv("ENVIRONMENT") == "development":
        logger.info(f"{request.method} {request.url}")
    response = await call_next(request)
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002)