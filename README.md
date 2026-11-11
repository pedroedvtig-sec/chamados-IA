# IA aplicada ao suporte de TI

Sou o único analista de suporte de TI de uma consultoria com cerca de 90 chamados por mês. Este repositório reúne o que construí para tirar trabalho repetitivo do meu dia: classificar e documentar chamados, resumir a semana para o gestor e responder perguntas sobre os dados, sempre sem expor nada da empresa.

Tudo roda em chamados reais. Os números abaixo foram medidos, não estimados, a não ser onde está escrito "estimativa".

## Em números

| | |
|---|---|
| **78%** de acerto na categoria e **85%** no tipo do chamado | contra 45% e 50% de quem chuta sempre a resposta mais comum (40 chamados reais, gabarito revisado à mão) |
| **83%** dos passos sugeridos compatíveis com o que eu fiz de verdade | julgado por um modelo de outra empresa, o mesmo para todos os modelos avaliados |
| **US$ 0,002** por chamado | a avaliação inteira, com 40 chamados, custou menos de 9 centavos de dólar |
| **94%** dos chamados de uma semana com a sugestão da IA aceita inteira | categoria, subcategoria, tipo e prioridade, no uso diário (sou o único usuário: aceitar não prova que estava certa) |
| **4 passos** documentados por chamado com IA, contra **1** sem | mediana da linha do tempo; registrar com IA ainda não é mais rápido |
| **~2,9 h/mês** economizadas no resumo semanal para o gestor | estimativa: 40 min por semana para montar à mão, agora sai pronto toda segunda |
| **10 de 10** tentativas de abuso bloqueadas no agente que consulta o banco | DELETE, UPDATE, segundo comando, leitura de arquivo, outras tabelas |

## O que tem aqui

| Pasta | O que é | Status |
|---|---|---|
| [`agente-triagem`](agente-triagem) | Agente com *function calling* que recebe um chamado e devolve categoria, tipo, prioridade com motivo, recorrência, procedimento e passos. Inclui a avaliação contra gabarito e linha de base. | avaliado em 40 chamados reais |
| [`anonimizador`](anonimizador) | Tira pessoas, logins, e-mails, senhas, empresas, IPs e documentos dos chamados antes de qualquer uso com IA, mantendo as ligações entre registros. | usado em todos os dados do agente |
| [`onboarding`](onboarding) | Automação em n8n: o e-mail do RH vira chamado agendado, usuário e e-mail calculados, rascunho de resposta e lembrete diário. | funciona de ponta a ponta com dados de teste; não implantado |

## O sistema de chamados

O mesmo raciocínio do agente roda dentro do sistema de chamados que construí para a empresa, inspirado no ServiceNow. Antes dele, os chamados chegavam por formulário, e-mail e planilha. O código desse sistema fica num repositório privado, porque carrega regras internas da empresa. O que ele faz com IA:

- **Descrever com IA.** Escrevo do meu jeito ("pediu reset, resetei") e a IA preenche o formulário e a linha do tempo, separando o que foi feito do que ficou pendente. O alvo é o maior problema: chamado N1 resolvido no corredor não era registrado. Cerca de 1 em cada 4 chamados é N1, e a fatia deles entre os registrados subiu desde julho, mas o período ainda é curto para atribuir isso à IA.
- **Relatório semanal para o gestor.** Toda segunda às 8h, o n8n manda um e-mail com volume, categorias, SLA, fila parada e possíveis recorrências, com uma ação sugerida para cada uma. Os números saem do banco; a IA só interpreta. Todo número que ela escreve precisa existir nos dados, senão a frase volta para correção ou é descartada.
- **Pergunte aos chamados.** O gestor pergunta em português ("que setor mais abriu chamado de impressora?") e um agente decide as consultas SQL, lê os resultados e responde com texto, gráfico e o SQL usado, para conferir. As consultas rodam com um usuário do banco que só lê uma visão sem textos livres.
- **Medição embutida.** Cada registro grava o tempo ativo (aba visível e ação no último minuto), a espera pela IA à parte e quanto da sugestão foi mantido. É daí que vêm os 94%.

## Como funciona

```
chamado / pergunta / semana
   │
   ▼
anonimização ─────── pessoas, e-mails, empresas e senhas viram marcadores
   │
   ▼
modelo via OpenRouter ──► ferramentas: buscar procedimentos, histórico, casos parecidos,
   │                       consultar o banco (só leitura), web
   ▼
conferência no código ── campos obrigatórios, valores permitidos, números que existem nos dados
   │                      └─ se falhar, devolve ao modelo exatamente o que está errado
   ▼
desanonimização ──────── os nomes voltam só na saída, dentro da empresa
```

Três princípios atravessam tudo:

1. **A resposta do modelo é entrada não confiável.** Cada saída passa por conferência no código antes de ser usada.
2. **Conta e regra de negócio ficam no código, não no prompt.** O banco calcula os números, o código decide setor e login. A IA classifica, escreve e interpreta.
3. **Privacidade por padrão.** Todo pedido vai com `data_collection: deny` (só provedores que não treinam com os dados). Preferi pagar centavos a liberar os dados para um modelo gratuito. Nenhum dado, nem anonimizado, está neste repositório.

## Escolhas que foram minhas

O código foi escrito com IA. O que a IA não tinha como saber sozinha foi o meu trabalho:

- **O problema e o contexto:** quais chamados param um setor, o que é o MBOX, por que backup antes de formatar é prioridade alta, por que devolver um notebook não é desligamento.
- **Como medir:** gabarito revisado à mão, linha de base para não se enganar com acerto alto, juiz de outra empresa, tempo ativo em vez de tempo de relógio, espera da IA separada do tempo humano.
- **Duvidar do resultado:** "impressão" virando impressora, "pediu" virando "feito", a IA lendo "resolvidos no primeiro contato" como "primeiro contato feito". Todos apareceram usando o sistema com chamados reais e conferindo a saída.
- **Não trocar variável no meio do experimento:** a avaliação favoreceu o DeepSeek, mas o site segue com o Claude Haiku até o fim da medição de tempo, para não misturar os dois modelos nos mesmos números.

## Limitações

- Um único ambiente e 40 chamados na avaliação: é um retrato honesto, não um benchmark.
- O tempo de registro com e sem IA ainda está sendo medido. Até agora, registrar com IA não é mais rápido: mesmo sem a espera pela resposta, leva uns 13 s a mais por chamado. O ganho medido é documentação: 4 passos registrados contra 1. A amostra é pequena (4 chamados com IA e 11 manuais) e enviesada, porque usei a IA nos casos mais longos.
- O onboarding não foi implantado, e as horas economizadas do relatório são estimativa minha.
