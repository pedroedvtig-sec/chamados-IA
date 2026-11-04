# Onboarding de colaborador novo

Quando alguém é contratado, o RH manda um e-mail "solicitação de máquina" para a TI. A partir daí eu preciso abrir o chamado, definir o usuário e o e-mail, responder o RH, preparar a máquina e os periféricos, gerar o termo e entregar tudo antes do primeiro dia. Nada disso é difícil, mas é fácil esquecer um passo ou perceber a data de início em cima da hora.

Esta automação faz a parte burocrática sozinha. Quando o e-mail do RH chega:

1. **Abre o chamado no meu sistema**, já agendado para a data de início, com prioridade alta, o procedimento de configuração do setor vinculado e um checklist de tudo que falta.
2. **Calcula o usuário e o e-mail** pelo padrão da empresa (primeira letra do nome + último sobrenome) e avisa se o login já existe.
3. **Deixa um rascunho de resposta ao RH** no Gmail, com o número do chamado, o usuário e o que ficou faltando no e-mail. Eu reviso e envio.
4. **Me lembra em dias úteis às 8h** de quem começa nos próximos dois dias e do que ainda está pendente.

✍️ *Antes: quanto tempo levava cada onboarding só na parte de registro e resposta, e quantos por mês.*

## Como funciona

```
Gmail (e-mail do RH)
   │  n8n: a cada 5 min, e-mails não lidos com "solicitação de máquina"
   ▼
função onboarding (Supabase)
   ├─ nome do colaborador ............ lido por regra no assunto ou na linha "Nome:"
   ├─ anonimização ................... nome, CPF, RG, telefone, e-mail e empresas viram marcadores
   ├─ IA (OpenRouter) ................ lê o texto anonimizado: setor, cargo, data de início,
   │                                   equipamentos e acessos fora do padrão, o que falta
   ├─ regras ......................... data e setor escritos no e-mail têm prioridade sobre a IA
   ├─ login e e-mail ................. calculados por código, com aviso de login repetido
   └─ chamado ........................ criado com checklist, procedimentos e data agendada
   ▼
n8n: rascunho de resposta no mesmo fio do Gmail → marca o e-mail como lido

n8n: dias úteis às 8h → função (acao: lembretes) → e-mail com quem começa em até 2 dias
```

**Divisão de trabalho.** O n8n só orquestra: gatilho, Gmail e agenda. A lógica e os segredos ficam numa função versionada no Git e testada. A chave da IA, a chave do banco e o domínio de e-mail nunca aparecem no workflow.

**Por que a IA não lê o nome.** O nome do colaborador novo ainda não está em nenhuma base, então um anonimizador comum não teria como reconhecê-lo. Por isso o nome é extraído **por regra antes** da IA, e o texto que sai já vai com `[COLABORADOR]` no lugar. Telefone, CPF, e-mail, a assinatura de quem mandou e o nome de quem mandou também saem antes. No retorno, a função devolve exatamente o que foi enviado à IA, para conferência.

**IA onde a regra não alcança.** "Começa segunda que vem", "vai precisar de um segundo monitor", "acesso à pasta do financeiro": a IA transforma isso em campos. Se ela falhar, o chamado é aberto do mesmo jeito, com o que as regras conseguiram ler e um aviso.

**O que continua manual, de propósito.** Criar o usuário no AD e o e-mail no Google Workspace exige permissão de administrador. Uma automação com esse poder, disparada por e-mail, é um risco maior do que os dois minutos que ela economizaria. Ela prepara tudo e deixa o checklist; quem cria as contas sou eu.

**Sem chamado duplicado.** O id do e-mail fica gravado no chamado. Se o mesmo e-mail chegar de novo, a função devolve o chamado que já existe.

## Arquivos

```
onboarding/
├── supabase/
│   ├── config.toml                      a função não usa login do Supabase: autentica por token
│   └── functions/onboarding/
│       ├── index.ts                     a função: criar chamado e lembretes
│       ├── extrair.ts                   regras: nome, data, setor, anonimização, login, checklist
│       └── extrair_test.ts              testes das regras
└── n8n/onboarding.json                  workflow para importar no n8n
```

## Como instalar

### 1. Publicar a função

```bash
cd onboarding
npx supabase functions deploy onboarding --project-ref SEU-PROJETO --no-verify-jwt

TOKEN=$(openssl rand -hex 32); echo "$TOKEN"
npx supabase secrets set --project-ref SEU-PROJETO \
  ONBOARDING_TOKEN="$TOKEN" \
  ONBOARDING_USER_ID="id-do-seu-usuário" \
  DOMINIO_EMAIL="suaempresa.com" \
  EMPRESAS_ANONIMIZAR="NomeDaEmpresa,NomeDoCliente"
```

- Guarde o token: ele vai no n8n.
- O id do usuário fica em **Authentication → Users** no painel do Supabase. É o dono dos chamados criados.
- `OPENROUTER_API_KEY` e `OPENROUTER_MODEL` são os mesmos segredos da função de triagem.

### 2. Importar no n8n

1. **Workflows → Import from file** → `n8n/onboarding.json`.
2. Nos dois nós HTTP, troque `SEU-PROJETO` pelo id do projeto e crie uma credencial **Header Auth** com nome `x-onboarding-token` e o token como valor.
3. Nos nós do Gmail, crie a credencial do Gmail (OAuth2).
4. No nó "Lembrete por e-mail", troque `SEU-EMAIL@exemplo.com`.
5. Teste com um e-mail **inventado** para você mesmo: assunto `Solicitação de máquina - Fulano de Tal`, corpo com `Setor: fiscal` e `Início: 10/11`.
6. Ative o workflow.

### 3. Testes

```bash
cd supabase/functions/onboarding
deno test extrair_test.ts
```

## Resultado

✍️ *Depois de alguns onboardings reais: tempo entre o e-mail do RH e o chamado aberto (antes × agora), passos esquecidos, e quantas vezes o aviso de login repetido apareceu.*

## Limitações

- O nome só é reconhecido no assunto ("solicitação de máquina - Nome") ou numa linha "Nome:". Fora disso, o chamado é aberto como "nome não identificado" e o rascunho pede o nome ao RH.
- A data escrita como "05/11" é lida por regra. Formas como "dia 5 de novembro" dependem da IA.
- O Gmail é consultado a cada 5 minutos, então não é instantâneo.
