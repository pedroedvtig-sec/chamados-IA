# Agente de triagem de chamados

Sou o único analista de suporte de TI de uma empresa de consultoria. Todo chamado precisa ser lido, classificado, ligado a um procedimento e documentado, e a maior parte disso é repetitiva. Este agente faz essa primeira etapa: recebe o chamado e devolve a triagem pronta para eu revisar.

**Resumo**

- Acerta a categoria em **78%** dos chamados e o tipo em **85%**, contra 45% e 50% de quem chuta sempre a resposta mais comum. *(DeepSeek V4.1 Flash, 40 chamados reais: tabela completa em [Resultados](#resultados).)*
- Os passos sugeridos foram julgados compatíveis com o que eu fiz de verdade em **83%** dos casos que tinham a resolução escrita.
- Custa cerca de **US$ 0,002 por chamado**: a avaliação inteira, com 40 chamados, saiu por menos de 9 centavos de dólar.
- Nenhum dado da empresa sai sem anonimização, e nenhum dado fica neste repositório.
- O mesmo raciocínio roda dentro do meu sistema de chamados: registrar um chamado com IA levou **29 s** no primeiro teste. ✍️ *Atualizar com a mediana medida em 1 a 2 semanas de uso.*

## O problema

Registrar um chamado direito leva cerca de **1 minuto num N1** e até **3 minutos num caso mais complexo**: escolher categoria, tipo e prioridade, escrever o que foi feito e achar o procedimento certo. Com a fila cheia, o que acontece é previsível:

- **N1 resolvido no corredor não é registrado.** "Pediu reset de senha, resetei" some, e com ele a recorrência: a mesma pessoa ou a mesma máquina volta toda semana e ninguém enxerga.
- **A base de conhecimento não cresce.** Se a resolução não é escrita, o próximo caso igual começa do zero.
- **A prioridade vira "média" por padrão.** Nos chamados recentes, quase todos ficaram com o valor inicial do formulário.

✍️ *Volume: cerca de N chamados por mês, sendo uns X% de N1.*

## O que ele devolve

| Campo | Exemplo |
|---|---|
| Categoria / subcategoria | rede / compartilhamento |
| Tipo | incidente, solicitação ou tarefa |
| Prioridade e o motivo | alta: a pessoa está sem acesso ao e-mail e não tem alternativa |
| Recorrência | **recorrente** (EMP-0217, EMP-0250): a mesma pasta caiu na mesma máquina há duas semanas |
| Procedimento recomendado | "Pasta de rede sumiu ou não abre" |
| Passos para o técnico | 1. Confirmar o grupo do usuário no AD 2. Rodar o script de mapeamento… |
| Fonte dos passos | procedimento, chamados anteriores, pesquisa na web ou conhecimento geral |
| Resposta para o usuário | mensagem curta, sem jargão |

## Como funciona

O agente usa um modelo de linguagem com *function calling*: o modelo decide quais ferramentas chamar, lê o resultado e só então decide.

```
chamado novo
   │
   ▼
modelo (via OpenRouter) ──► buscar_procedimentos        base oficial + rascunhos N1 (busca BM25 local)
   │                    ──► historico                    chamados anteriores do mesmo usuário e da mesma máquina
   │                    ──► buscar_chamados_parecidos    casos parecidos + procedimentos e investigações ligados a eles
   │                    ──► pesquisar_web                só quando a base interna não resolve
   ▼
finalizar_triagem  (saída estruturada)
   │
   ▼
conferência no código: campos obrigatórios, valores permitidos, JSON válido
   └─► se falhar, devolve ao modelo exatamente o que está errado e pede de novo
```

- **A busca é local.** Chamados, procedimentos e investigações ficam na máquina, indexados com BM25. Só os trechos relevantes vão para o modelo.
- **Um chamado parecido traz o contexto dele.** Junto com cada caso parecido vêm o procedimento executado e a investigação (dossiê) ligados a ele. Na base atual são 78 ligações entre procedimento e chamado e 13 entre investigação e chamado. Tudo respeita a data: o agente nunca vê algo criado depois do chamado que está triando.
- **A resposta do modelo é tratada como entrada não confiável.** O esquema diz quais valores são permitidos, mas nem todo provedor obriga o modelo a respeitar. Por isso o código confere cada resposta.
- **Regras de negócio que não dependem do modelo ficam no código.** Um exemplo do sistema de chamados: o anonimizador troca o nome de uma empresa cliente por `[EMPRESA_1]` antes de enviar o texto. Então o modelo nunca vê o nome e não tem como saber o setor. O setor é decidido pelo código, olhando o texto original.
- **Glossário interno.** No primeiro teste real, o agente leu "erro de impressão no MBOX" como problema de impressora. Só que MBOX é o software de e-mail do jurídico, e "impressão" ali é exportar a mensagem. Agora, quando o chamado cita um termo do glossário, a definição vai junto. Termos desconhecidos baixam a confiança, em vez de virarem um chute.
- **Mapa de impacto.** O agente sabe quais máquinas param um setor inteiro: as máquinas comunitárias do operacional, a máquina que hospeda as automações internas e os access points de cada setor.

## A régua

O agente e o gabarito da avaliação usam as mesmas definições.

| Tipo | Definição | Exemplo |
|---|---|---|
| incidente | algo que funcionava parou de funcionar | monitor piscando, tinta que acabou |
| solicitação | algo a mais que o usuário pede | reset de senha porque esqueceu, monitor novo, máquina para colaborador novo |
| tarefa | trabalho que parte do processo ou da própria TI, sem pedido do usuário | backup, desligamento, refazer termo após troca de equipamento |

**Prioridade = impacto × urgência.** Impacto: empresa > setor > uma pessoa. Urgência: parado sem alternativa > atrapalha com contorno > sem pressa.

| Prioridade | Quando |
|---|---|
| crítica | empresa ou setor inteiro parado; risco de segurança ativo |
| alta | setor afetado com contorno; uma pessoa parada sem alternativa; desligamento; máquina para colaborador novo; backup antes de formatar (perder arquivo não tem volta) |
| média | uma pessoa atrapalhada, mas com contorno; pedido comum |
| baixa | dúvida, ajuste, padronização |

A prioridade é julgada pelo que se sabia **quando o chamado foi aberto**. Um driver de Wi-Fi que depois corrompeu a máquina continua sendo "alta" na triagem, porque ninguém sabia disso na abertura.

## Avaliação

`avaliar.py` pega os 40 chamados mais recentes e tria cada um **como se fosse novo**: o agente só enxerga o que existia antes dele, para não "colar" da resposta.

- **Gabarito revisado à mão** com a régua acima: 40 chamados, sendo 18 de prioridade alta, 18 média e 4 baixa. Nenhum crítico na amostra.
- **Linha de base:** "chutar sempre a resposta mais comum". Acertar 70% não diz nada se 70% dos chamados são da mesma categoria.
- **Passos sugeridos** comparados com o que foi feito de verdade, por um **modelo juiz de outra empresa**, o mesmo para todos os modelos avaliados. Assim nenhum corrige a própria prova.
- **Conferi o juiz.** Revisei os vereditos duvidosos e discordei de 1 em 4: ele é generoso quando a resolução escrita é curta. ✍️ *Atualizar depois de conferir mais vereditos na avaliação final.*
- **Chamados sem resolução escrita** são contados à parte, em vez de distorcer o resultado.

### Resultados

<!-- resultados:inicio -->
|  | DeepSeek V4.1 Flash | Claude Haiku 5.5 | linha de base |
| --- | --- | --- | --- |
| chamados concluídos | 40/40 | 40/40 | — |
| categoria | 78% (31/40) | 72% (29/40) | 45% |
| subcategoria | 68% (17/25) | 56% (14/25) | 8% |
| tipo | 85% (34/40) | 82% (33/40) | 50% |
| prioridade | 70% (28/40) | 65% (26/40) | 45% |
| passos compatíveis (juiz) | 83% (19) | 70% (16) | — |
| chamadas ao modelo por chamado | 2,8 | 3,6 | — |
| segundos por chamado | 19,0 | 18,0 | — |
| custo por chamado | US$ 0,0021 | US$ 0,0041 | — |

Os passos só são julgados nos chamados que têm a resolução escrita (17 não tinham). A linha de base é chutar sempre a resposta mais comum nos chamados anteriores. Juiz: `google/gemini-3.5-flash`, o mesmo para todos os modelos.
<!-- resultados:fim -->

**De v1 para a versão final.** Na primeira avaliação com o DeepSeek, 6 dos 40 chamados falharam, todos pelo mesmo motivo: o modelo corrompia "média" em `mຝia`, e a conferência recusava o valor até esgotar as tentativas. A correção foi mandar as prioridades ao modelo sem acento e converter de volta no código. Com isso, os 40 chamados foram concluídos e o acerto subiu em todos os campos: categoria de 68% para 78%, tipo de 79% para 85% e prioridade de 65% para 70%.

**Por que o DeepSeek.** Ele acertou mais que o Claude Haiku 5.5 em todos os campos (categoria 78% × 72%, passos compatíveis 83% × 70%), precisou de menos chamadas ao modelo por chamado (2,8 × 3,6) e custou cerca de metade (US$ 0,0021 × US$ 0,0041 por chamado). ✍️ *Revise com as suas palavras.*

## Onde ele erra

- **"Impressão" virou impressora.** O agente não conhecia o jargão interno. A solução foi o glossário, que vai junto no pedido quando o termo aparece.
- **Valores que não existem.** Um modelo devolveu a prioridade `mຝia`. Outro vazou campos para dentro dos textos (`<parameter name="confianca">`). A solução foi a conferência no código, que devolve o erro ao modelo e pede de novo.
- **"Pediu" virou "feito".** No sistema de chamados, "pediu pra resetar a senha" foi salvo como resolvido. A solução foi uma regra explícita: pedido não é ação feita, e na dúvida o passo fica pendente.
- **Prioridade rebaixada porque "já foi resolvido".** Backup, termo e troca de cartucho caíram para média ou baixa porque a anotação dizia que estava feito, mesmo com o prompt mandando julgar pelo momento da abertura. **Ainda em aberto.** É a maior fonte de erro de prioridade, e a prioridade é o campo com menor acerto na avaliação final (70%).

## No dia a dia

O mesmo raciocínio virou o campo **"Descrever com IA"** no meu sistema de chamados, inspirado no ServiceNow que eu usava num emprego anterior. Antes dele, os chamados chegavam por formulário, e-mail e planilha. Agora escrevo do meu jeito ("pediu reset, resetei") e a IA preenche o formulário e a linha do tempo, com o feito e o pendente separados.

- O texto é **anonimizado antes de sair** e desanonimizado na volta. Senhas são apagadas e não voltam.
- A chave da IA fica nos segredos do servidor, nunca no navegador.
- Para colaborador novo, o **usuário e o e-mail são calculados por código** a partir do nome, com aviso quando o login já existe.

O sistema mede sozinho, sem mostrar nada na tela, quanto tempo cada registro leva e quanto da sugestão da IA eu mantive:

| | manual | com IA |
|---|---|---|
| tempo mediano para registrar um chamado | ✍️ | ✍️ |
| chamados registrados no período | ✍️ | ✍️ |

| Sugestão da IA mantida sem edição | % |
|---|---|
| categoria | ✍️ |
| tipo | ✍️ |
| prioridade | ✍️ |

✍️ **A conta:** N chamados por mês × (tempo manual − tempo com IA) = **X horas por mês**. E quantos N1 passaram a ser registrados.

## Como construí

O código foi escrito com IA. O meu papel foi o que a IA não tinha como saber sozinha:

- **O problema e o contexto.** Quais chamados param um setor, o que é o MBOX, por que um backup antes de formatar é alta, por que devolver um notebook não é desligamento.
- **As decisões.** Anonimizar antes de qualquer coisa. Pagar centavos por um modelo que não treina com os dados, em vez de usar um gratuito que treina. Revisar o gabarito à mão. Usar um juiz de outra empresa.
- **Testar e duvidar do resultado.** Os erros da lista acima apareceram usando o agente com chamados reais e conferindo a saída, não lendo o código.

✍️ *Revise com as suas palavras: o que você pediu, o que corrigiu e um momento em que a IA errou e você percebeu.*

## Como rodar

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY="sua-chave-da-openrouter"
export DADOS_TRIAGEM=~/dados_privados/dados_anonimizados

# triar um texto livre ou um chamado da base
python triagem.py "a pasta Z sumiu do computador" --usuario "Usuário 12" --maquina PC-000049 --modelo deepseek/deepseek-v4.1-flash
python triagem.py --chamado EMP-0349 --modelo deepseek/deepseek-v4.1-flash

# avaliar
python avaliar.py --gerar-gabarito gabarito.csv
python avaliar.py --n 40 --gabarito gabarito.csv --modelo deepseek/deepseek-v4.1-flash \
  --juiz google/gemini-3.5-flash --saida avaliacao-deepseek

# preencher a tabela de resultados deste README
python preencher_resultados.py avaliacao-deepseek avaliacao-haiku --custo deepseek=0.0004 --custo haiku=0.003
```

A avaliação salva o progresso e continua de onde parou. Para ela seguir rodando se o terminal fechar, use `nohup ... &`.

## Privacidade

Os chamados vêm de um ambiente real. Antes de qualquer uso com IA, eles passam pelo [anonimizador](../anonimizador): pessoas viram "Usuário N" e "Técnico N", e senhas, e-mails, domínios, IPs e nomes de empresas e clientes são removidos.

- Todo pedido à OpenRouter vai com `data_collection: deny`, ou seja, só para provedores que não treinam com os dados.
- Os modelos gratuitos não passaram nesse filtro. Em vez de liberar os dados, paguei pelo uso: a avaliação inteira custa centavos.
- Nenhum dado, nem anonimizado, fica neste repositório. O agente lê tudo de uma pasta local (`DADOS_TRIAGEM`), e as pastas de avaliação e o gabarito estão no `.gitignore`.

## Limitações

- A avaliação usa 40 chamados de um único ambiente. É um retrato honesto, não um benchmark.
- Não há chamados críticos na amostra, então o acerto nessa classe não foi medido.
- A pesquisa na web usa o DuckDuckGo (`ddgs`), para funcionar igual com qualquer provedor.
- Para chamados que ainda não passaram pelo anonimizador, o histórico por usuário só funciona com o rótulo ("Usuário 12"), não com o nome real.
