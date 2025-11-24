# ⚠️ GitHub Actions CI - Problema de Billing (RESOLVIDO)

## 🚨 Situação

O pipeline CI está falhando devido a um problema de billing na conta do GitHub:

```
The job was not started because your account is locked due to a billing issue.
```

## ✅ Soluções

### Opção 1: Resolver o Billing (Recomendado)

**Problema Comum:** Mesmo com 0 minutos usados, o GitHub pode bloquear o CI se:
- Não houver método de pagamento cadastrado
- O limite de gastos estiver em $0

**Solução:**

1. Acesse: https://github.com/settings/billing
2. **Adicione um método de pagamento** (mesmo que não vá usar - o plano Free não cobra nada)
   - Vá em "Payment information"
   - Adicione um cartão de crédito (não será cobrado se ficar dentro do limite gratuito)
3. **Ajuste o limite de gastos:**
   - Vá em "Budgets and alerts" ou "Spending limits"
   - Defina um limite acima de $0 (ex: $5 ou $10)
   - Isso permite que o GitHub Actions funcione mesmo sem cobrança
4. GitHub Actions oferece **2.000 minutos/mês gratuitos** para contas pessoais

### Opção 2: Executar Testes Localmente (Temporário)

Enquanto o billing não é resolvido, você pode executar os testes localmente:

```bash
# Executar todos os testes
docker-compose exec web pytest

# Executar com cobertura
docker-compose exec web pytest --cov=src --cov-report=html

# Executar testes específicos
docker-compose exec web pytest src/tests/test_rag_service.py
```

### Opção 3: Desabilitar CI Temporariamente

Se necessário, você pode comentar o workflow ou adicionar uma condição para pular em certas situações:

```yaml
# Em .github/workflows/ci.yml
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:  # Permite execução manual
```

### Opção 4: Usar Self-Hosted Runner (Avançado)

Para evitar custos do GitHub Actions, você pode configurar um runner self-hosted:

1. Instalar GitHub Actions Runner no seu ambiente
2. Configurar o workflow para usar o runner self-hosted

## 📊 Status Atual

- **Código:** ✅ Funcional e testado localmente
- **CI Pipeline:** ⚠️ Bloqueado por billing
- **Testes Locais:** ✅ Passando (14 testes)

## 💡 Solução Rápida (Passo a Passo)

### Para Resolver Agora:

1. **Na página "Budgets and alerts"** (onde você está agora):
   - Clique nos **três pontos (⋮)** ao lado de "Actions"
   - Selecione **"Edit budget"** ou **"Update budget"**
   - Altere o valor de **"$0 budget"** para **"$5"** ou **"$10"**
   - Salve as alterações

2. **Alternativamente:**
   - Clique no botão **"New budget"** no topo
   - Selecione "Actions" como produto
   - Defina um limite (ex: $5)
   - Salve

3. **Após ajustar:**
   - Faça um novo commit ou re-execute o workflow manualmente
   - O CI deve funcionar normalmente

**Importante:** Você não será cobrado enquanto estiver dentro dos 2.000 minutos gratuitos. O limite é apenas uma proteção.

## 💡 Recomendação

1. **Imediato:** Ajuste o limite de gastos para $5-$10
2. **Curto Prazo:** Adicione método de pagamento (opcional, mas recomendado)
3. **Longo Prazo:** Configure alertas para monitorar uso

---

**Nota:** O código está funcional e os testes passam localmente. O problema é apenas de infraestrutura de CI/CD, não de qualidade do código.

