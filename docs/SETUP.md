# 📘 Guia de Setup - Jurix

## 🚀 Inicialização do Sistema

### 1. Pré-requisitos

- **Docker Desktop** instalado e rodando (WSL 2 no Windows)
- **Ollama** rodando no host com o modelo `llama3`
- **Git** configurado

### 2. Verificar Ollama

```bash
# No PowerShell do Windows
curl http://localhost:11434
```

Deve retornar: `Ollama is running`

Se não estiver acessível:
- Abra as configurações do Ollama
- Ative: **"Expose Ollama to the network"**
- Reinicie o Ollama

### 3. Clonar e Configurar

```bash
git clone <repository-url>
cd jurix
```

### 4. Criar arquivo .env

```powershell
# PowerShell
@"
POSTGRES_DB=jurix
POSTGRES_USER=jurix_user
POSTGRES_PASSWORD=jurix_pass_dev

DATABASE_URL=postgresql://jurix_user:jurix_pass_dev@db:5432/jurix
REDIS_URL=redis://redis:6379/0

OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3

DJANGO_SECRET_KEY=django-insecure-dev-key-change-in-production
DEBUG=True
"@ | Out-File -FilePath .env -Encoding UTF8
```

### 5. Build e Start

```bash
docker-compose up --build
```

### 6. Executar Migrações

Em outro terminal:

```bash
docker-compose exec web python manage.py makemigrations
docker-compose exec web python manage.py migrate
```

### 7. Criar Superusuário

```bash
docker-compose exec web python manage.py createsuperuser
```

### 8. Testar API SAPL

```bash
docker-compose exec web python manage.py test_sapl_client
```

### 9. Ingestão de Teste

```bash
# Ingestão síncrona (50 normas)
docker-compose exec web python manage.py ingest_sapl --limit 50

# Ingestão assíncrona via Celery
docker-compose exec web python manage.py ingest_sapl --limit 50 --async
```

### 10. Acessar o Sistema

- **Django Admin:** http://localhost:8000/admin
- **API:** http://localhost:8000/api

---

## 🧪 Validações

### Verificar containers rodando

```bash
docker-compose ps
```

Deve mostrar:
- `jurix_db` (PostgreSQL)
- `jurix_redis` (Redis)
- `jurix_web` (Django)
- `jurix_worker` (Celery)

### Verificar logs

```bash
docker-compose logs -f web
docker-compose logs -f worker
```

### Testar conexão Ollama do container

```bash
docker-compose exec web curl http://host.docker.internal:11434
```

### Verificar tarefas Celery

```bash
docker-compose exec worker celery -A config inspect active
```

---

## 🆘 Troubleshooting

### Erro: "Ollama connection refused"

1. Verifique se o Ollama está rodando no Windows
2. Verifique se a opção "Expose to network" está ativada
3. Teste: `curl http://localhost:11434` no PowerShell

### Erro: "Database connection failed"

1. Verifique se o container `db` está rodando: `docker-compose ps`
2. Verifique os logs: `docker-compose logs db`
3. Recrie os volumes: `docker-compose down -v && docker-compose up`

### Erro: "Permission denied" ao criar diretórios

No Windows com WSL 2, pode ser necessário ajustar permissões:

```bash
docker-compose exec web mkdir -p data/raw data/logs
docker-compose exec web chmod 777 data/raw data/logs
```

---

## 📊 Métricas de Sucesso (Sprint 1)

- [ ] `docker-compose up` sem erros
- [ ] Migrations executadas com sucesso
- [ ] Admin Django acessível
- [ ] `test_sapl_client` retorna normas
- [ ] `ingest_sapl --limit 50` salva 50 normas no banco
- [ ] Worker Celery processando tasks

