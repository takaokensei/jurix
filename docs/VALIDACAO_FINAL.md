# ✅ Validação Final do Sistema Jurix

## 📊 Status Atual do Sistema

### Dados Processados
- **356 normas** consolidadas (período 1990-2025)
- **4.916 dispositivos legais** indexados com embeddings
- **712 eventos de alteração** identificados
- **100% de cobertura** de embeddings (4.916/4.916)

### Infraestrutura
- ✅ Banco de dados PostgreSQL + pgvector rodando
- ⚠️ Redis com conflito de porta (6379)
- ⚠️ Containers web e worker precisam ser iniciados

---

## 🔍 Passo 0: Validação do Chatbot

### 1. Resolver Conflito de Porta do Redis

O Redis está tentando usar a porta 6379 que já está em uso. Opções:

**Opção A: Mudar porta do Redis no docker-compose.yml**
```yaml
redis:
  ports:
    - "6380:6379"  # Mapear porta externa 6380 para interna 6379
```

**Opção B: Parar processo que está usando a porta 6379**
```powershell
# No PowerShell (como Admin)
netstat -ano | findstr :6379
# Anotar o PID e encerrar:
taskkill /PID <PID> /F
```

### 2. Iniciar Todos os Containers

```bash
docker-compose up -d
```

Verificar status:
```bash
docker-compose ps
```

Deve mostrar:
- ✅ `jurix_db` (healthy)
- ✅ `jurix_redis` (healthy)
- ✅ `jurix_web` (running)
- ✅ `jurix_worker` (running)

### 3. Acessar o Chatbot

**URL:** http://localhost:8000/normas/chatbot/

### 4. Testar Perguntas Reais

Teste as seguintes perguntas para validar o sistema:

1. **Zoneamento Urbano:**
   ```
   Como funciona o zoneamento urbano em Natal?
   ```

2. **IPTU:**
   ```
   O que diz a lei sobre IPTU?
   ```

3. **Licença de Construção:**
   ```
   Quais são as regras para obter licença de construção?
   ```

4. **Alterações Legais:**
   ```
   Quais normas alteraram a lei de zoneamento?
   ```

### 5. Validar Respostas

Para cada resposta, verifique:
- ✅ A resposta é contextualizada e relevante?
- ✅ As fontes consultadas aparecem corretamente?
- ✅ Os scores de relevância são exibidos?
- ✅ A resposta cita dispositivos legais específicos?

---

## 📝 Checklist de Validação

- [ ] Todos os containers estão rodando (`docker-compose ps`)
- [ ] Chatbot acessível em http://localhost:8000/normas/chatbot/
- [ ] Pergunta sobre zoneamento retorna resposta relevante
- [ ] Pergunta sobre IPTU retorna resposta relevante
- [ ] Pergunta sobre licença retorna resposta relevante
- [ ] Fontes consultadas aparecem com scores de relevância
- [ ] Sistema responde em tempo razoável (< 10s)

---

## 🎯 Critérios de Sucesso

O sistema está validado se:
1. ✅ Chatbot responde perguntas em linguagem natural
2. ✅ Respostas são contextualizadas com dispositivos legais
3. ✅ Fontes consultadas são exibidas corretamente
4. ✅ Sistema acessa os 4.916 dispositivos indexados
5. ✅ Performance aceitável (< 10s por resposta)

---

## 🐛 Troubleshooting

### Erro: "Redis connection refused"
- Verifique se o container `jurix_redis` está rodando
- Verifique se a porta 6379 não está bloqueada
- Tente mudar a porta externa do Redis

### Erro: "Ollama connection refused"
- Verifique se o Ollama está rodando no Windows
- Verifique se "Expose to network" está ativado
- Teste: `curl http://localhost:11434`

### Chatbot não responde
- Verifique os logs: `docker-compose logs web`
- Verifique se há dispositivos com embeddings: `docker-compose exec web python manage.py shell -c "from apps.legislation.models import Dispositivo; print(Dispositivo.objects.exclude(embedding__isnull=True).count())"`

### Respostas genéricas ou irrelevantes
- Verifique se os embeddings foram gerados corretamente
- Verifique se a busca semântica está funcionando
- Teste com perguntas mais específicas

---

## 📊 Métricas Esperadas

Após validação, o sistema deve apresentar:
- **Latência média:** 2-5s por resposta
- **Taxa de sucesso:** > 90% das perguntas respondidas
- **Relevância:** > 70% das respostas consideradas relevantes
- **Cobertura:** Acesso a todos os 4.916 dispositivos

---

**Data de Validação:** _______________

**Validado por:** _______________

**Observações:** _______________

