# 🏛️ Jurix - Sistema de Consolidação Normativa

Sistema de Consolidação Normativa e Rastreabilidade Jurídica Inteligente para legislação municipal de Natal/RN.

## 🚀 Quick Start

### Pré-requisitos

- Docker Desktop com WSL 2 (Windows)
- Ollama rodando no host com o modelo `llama3`
- Python 3.12+ (para desenvolvimento local)

### Configuração do Ollama

1. Certifique-se de que o Ollama está instalado e rodando
2. Ative a opção "Expose Ollama to the network" nas configurações
3. Verifique se está acessível em `http://localhost:11434`

### Iniciando o Projeto

1. Clone o repositório:
```bash
git clone <repo-url>
cd jurix
```

2. Copie o arquivo de exemplo de variáveis de ambiente:
```bash
cp .env.example .env
```

3. Inicie os containers:
```bash
docker-compose up --build
```

4. Acesse o sistema:
- Django Admin: http://localhost:8000/admin
- API: http://localhost:8000/api

## 🏗️ Arquitetura

- **Backend:** Django 5.0
- **Database:** PostgreSQL 16 + pgvector
- **Task Queue:** Celery + Redis
- **AI Engine:** Ollama (llama3) via host
- **Frontend:** Django Templates + HTMX

## 📁 Estrutura do Projeto

```
jurix/
├── config/               # Configurações Django
├── src/
│   ├── apps/            # Django Apps
│   │   ├── core/        # Modelos base
│   │   ├── legislation/ # Modelos de Normas
│   │   └── ingestion/   # Controle de ingestão
│   ├── clients/         # API Clients (SAPL)
│   ├── processing/      # OCR, NLP, Parsers
│   └── llm_engine/      # Integração Ollama
├── data/                # Dados (não versionado)
├── docker/              # Dockerfiles
└── docs/                # Documentação
```

## 📊 Sprint 1 - Infraestrutura Base

- [x] Setup Docker Compose
- [ ] Cliente SAPL API
- [ ] Ingestão de teste (50 PDFs)

## 🔧 Desenvolvimento

### Migrações

```bash
docker-compose exec web python manage.py makemigrations
docker-compose exec web python manage.py migrate
```

### Criar Superusuário

```bash
docker-compose exec web python manage.py createsuperuser
```

### Logs

```bash
docker-compose logs -f web
docker-compose logs -f worker
```

## 📝 Licença

Este projeto é desenvolvido como parte do PIBIC/UFRN.

