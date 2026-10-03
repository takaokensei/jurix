# Production readiness — fonte canônica

Esta é a página canônica para o estado de produção do Jurix. Documentos de versões
anteriores são históricos e não devem ser usados como instruções operacionais sem
serem confrontados com este documento e com `docs/current-status.md`.

## Estado

- **Engineering gates:** executados pelo CI de produção.
- **RAG benchmark:** o gate aceita a ausência de corpus revisado; um benchmark jurídico
  humano-revisado continua sendo requisito antes de declarar qualidade jurídica de release.
- **Vector production gate:** verifica configuração/indexação de pgvector quando executado
  contra um ambiente com PostgreSQL disponível.
- **Acessibilidade:** não declarar conformidade WCAG sem auditoria formal.
- **Ingestão:** implementações são separadas por domínio; `tasks.py` é a superfície pública.

## Gates canônicos

| Área | Fonte | Quando usar |
|---|---|---|
| Status de engenharia | `docs/current-status.md` | referência rápida |
| Segurança | `scripts/security_audit_v2.py` | CI/release |
| Arquitetura | `scripts/architecture_budget_v2.py` | CI/release |
| Contratos | `scripts/check_service_contracts_v2.py` | CI/release |
| RAG jurídico | `scripts/run_legal_benchmark_v1.py` | quando houver corpus revisado |
| Vetores | `scripts/vector_production_gate_v5.py` | staging/produção |
| Preflight | `scripts/production_preflight_v2.py` | staging/produção |
| Contrato de staging | `scripts/validate_staging_contract.py` | antes da promoção |

## QA de dependências Python

As dependências devem ser instaladas e auditadas num ambiente isolado antes de atualizar
qualquer ambiente local ou de produção. `pip-audit` é ferramenta de QA: não deve ser
adicionado a `requirements.txt` de runtime.

Baseline validado em 2026-10-02, com Python 3.12.10/Windows x64:

| Distribuição | Pin do projeto | Compatibilidade verificada |
|---|---:|---|
| Requests | 2.33.0 | Wheel `py3-none-any`; inclui a correção do advisory que exigia 2.33.0 |
| python-dotenv | 1.2.4 | Wheel `py3-none-any`; substitui a versão vulnerável 1.0.1 |
| Pillow | 12.3.0 | Wheel CPython 3.12 Windows x64; corrige os advisories encontrados para 11.0.0 |
| PyMuPDF | 1.28.2 | Wheel `cp310-abi3-win_amd64`, compatível com Python 3.12 |
| pytest | 9.1.1 | Substitui 8.3.4, versão afetada pelo advisory identificado |

Fontes primárias de releases: [Requests](https://pypi.org/project/requests/2.33.0/),
[python-dotenv](https://pypi.org/project/python-dotenv/1.2.4/),
[Pillow](https://pypi.org/project/pillow/12.3.0/),
[PyMuPDF](https://pypi.org/project/pymupdf/1.28.2/) e
[pytest](https://pypi.org/project/pytest/9.1.1/).

Resultado QA: `pip check` sem dependências quebradas; `pip-audit -r requirements.txt`
sem vulnerabilidades conhecidas; suíte Python completa com **848 passed, 6 skipped**.
Foram observados sete avisos de teste do Django sobre override de `DATABASES`, causados
pela configuração de banco descartável usada para não escrever no banco local. A venv
ativa do projeto não foi alterada durante essa validação. O smoke de OCR no Python QA
reconheceu texto de uma imagem sintética com Tesseract 5.5.3 e o idioma `por`. O caminho
temporário foi apontado, somente nesse processo, para um diretório ASCII em
`C:\Windows\Temp`: o caminho padrão do perfil Windows com caractere não ASCII fez o
Tesseract retornar erro de filesystem. Confirmar/configurar `TEMP`/`TMP` no serviço real
de ingestão permanece uma verificação operacional; nenhum arquivo de configuração foi
alterado nesta tarefa.

Roteiro reproduzível no Windows (crie um diretório de QA novo e ajuste `$qaPython`):

```powershell
py -3.12 -m venv $qaRoot\venv
$qaPython = "$qaRoot\venv\Scripts\python.exe"
& $qaPython -m pip install -r requirements.txt
& $qaPython -m pip install pip-audit
& $qaPython -m pip check
& $qaPython -m pip_audit -r requirements.txt
```

Para executar a suíte sem usar o banco configurado no projeto, defina em memória um
nome exclusivo para o banco de teste antes de iniciar pytest. Django criará e removerá
somente esse banco de teste; nunca reutilize um nome de banco existente:

```powershell
@'
import os, tempfile
from pathlib import Path
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import config.settings as project_settings
db = project_settings.DATABASES["default"]
if db["ENGINE"].endswith("sqlite3"):
    db.setdefault("TEST", {})["NAME"] = str(Path(tempfile.gettempdir()) / "jurix_qa_unique.sqlite3")
else:
    db.setdefault("TEST", {})["NAME"] = "jurix_qa_replace_with_unique_suffix"
import pytest
raise SystemExit(pytest.main(["-q"]))
'@ | & $qaPython -
```

Use um sufixo novo para o nome PostgreSQL em cada execução. O relatório de auditoria
datado em `docs/audit/2026-10-02/` preserva os advisories de entrada e não é substituído
por este resultado de QA.

## Regra de documentação

Não criar novos `production-readiness-vN.md`, `production-final-vN.md` ou gates paralelos
para a mesma responsabilidade. Se um gate mudar, atualize esta página e a fonte executável
correspondente.

## Release checklist

1. CI de produção verde.
2. Preflight executado contra o ambiente-alvo.
3. Benchmark jurídico revisado por humano disponível, quando a release fizer alegações de
   qualidade jurídica.
4. Vector gate validado contra o PostgreSQL/pgvector do ambiente-alvo.
5. Auditoria manual de UX/acessibilidade concluída quando houver alegação de conformidade.

Antes da promoção, confirme também o backup restaurável do ambiente e o rollback
documentado e testado no staging.
O histórico de assurance e readiness permanece em `docs/archive/`; esses arquivos
não são fontes operacionais alternativas.
