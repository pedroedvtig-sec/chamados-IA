# Agente de triagem de chamados

[![agente-triagem](https://github.com/pedroedvtig-sec/chamados-IA/actions/workflows/agente-triagem.yml/badge.svg)](https://github.com/pedroedvtig-sec/chamados-IA/actions/workflows/agente-triagem.yml)

Sou o único analista de suporte de TI de uma empresa de consultoria. Todo chamado precisa ser lido, classificado, ligado a um procedimento e documentado, e a maior parte disso é repetitiva. Este agente faz essa primeira etapa: recebe o chamado e devolve a triagem pronta para eu revisar.

**Resumo**

- Acerta a categoria em **78%** dos chamados e o tipo em **80%**, contra 45% e 50% de quem chuta sempre a resposta mais comum. *(DeepSeek V4.1 Flash, 40 chamados reais: tabela completa em [Resultados](#resultados).)*
- Os passos sugeridos foram julgados compatíveis com o que eu fiz de verdade em **70%** dos casos que tinham a resolução escrita (16 de 23).
- Custa cerca de **US$ 0,003 por chamado**: a avaliação inteira, com 40 chamados, saiu por cerca de 12 centavos de dólar, fora o juiz.
- Os chamados reais passam pelo anonimizador antes de qualquer uso com IA, e nenhum dado fica neste repositório. A API daqui espera texto já anonimizado (detalhes em [Privacidade](#privacidade)).
- O mesmo raciocínio roda dentro do meu sistema de chamados, em chamados reais. Não deixou o registro mais rápido, mas o chamado registrado com IA sai com cerca de 4 vezes mais passos documentados (detalhes em [No dia a dia](#no-dia-a-dia)).

## Testar em 2 minutos

Precisa só de Docker. Não precisa de chave de API.

```bash
git clone https://github.com/pedroedvtig-sec/chamados-IA.git
cd chamados-IA/agente-triagem
docker compose up --build
```

Abra **http://localhost:8000/docs**, escolha `POST /triagem`, clique em *Try it out* e em *Execute*. O exemplo já vem preenchido.

- **Sem chave**, a API sobe em **modo demonstração**: devolve a triagem real, gravada antes pelo agente, do chamado de exemplo mais parecido com o que você mandou. A resposta diz `"modo": "demonstracao"` e qual chamado gravado foi usado.
- **Com chave**, o agente roda de verdade: `cp .env.example .env`, preencha `OPENROUTER_API_KEY` e suba de novo. Cada triagem custa cerca de US$ 0,003.
- Os chamados que o agente consulta vêm de [`dados_exemplo/`](dados_exemplo): 15 chamados, 5 procedimentos, um glossário e um mapa de impacto de uma empresa **fictícia**. Nada ali veio da empresa real.

| Endpoint | O que faz |
|---|---|
| `POST /triagem` | tria um chamado e grava o resultado no Postgres |
| `GET /triagens` | histórico, do mais novo para o mais antigo (`limite`, `deslocamento`) |
| `GET /triagens/{id}` | uma triagem |
| `GET /saude` | modo (real ou demonstração), banco e tamanho da base |

## O problema

Registrar um chamado direito leva cerca de **1 minuto num N1** e até **3 minutos num caso mais complexo**: escolher categoria, tipo e prioridade, escrever o que foi feito e achar o procedimento certo. Com a fila cheia, o que acontece é previsível:

- **N1 resolvido no corredor não é registrado.** "Pediu reset de senha, resetei" some, e com ele a recorrência: a mesma pessoa ou a mesma máquina volta toda semana e ninguém enxerga.
- **A base de conhecimento não cresce.** Se a resolução não é escrita, o próximo caso igual começa do zero.
- **A prioridade vira "média" por padrão.** Nos chamados recentes, quase todos ficaram com o valor inicial do formulário.

Volume: média de 93 chamados por mês de agosto a outubro de 2026. No total desde julho, cerca de 1 em cada 4 é N1: reset de senha, permissão e mapeamento de rede, periférico, toner, certificado digital e instalação de aplicativos simples. A contagem é por palavra-chave no título e na descrição, então é aproximada.

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

### Quando a IA falha

O modelo cai, demora, inventa e sai do formato. Cada caso tem uma resposta definida no código, e a API nunca grava uma triagem que não passou pelas conferências.

| O que acontece | O que o código faz | Na API |
|---|---|---|
| OpenRouter fora do ar, 429 ou 5xx | tenta de novo com espera crescente; com `OPENROUTER_MODEL_RESERVA`, a própria OpenRouter passa para o modelo reserva | 502 se esgotar |
| Demora | prazo total por triagem (`TRIAGEM_PRAZO_SEGUNDOS`, padrão 90 s), somando tentativas e esperas | 504 |
| Sem créditos, chave inválida, limite diário | erro claro, sem tentar de novo | 402, 401, 429 |
| Campo faltando, valor fora da lista, JSON quebrado | devolve ao modelo exatamente o que está errado e pede de novo | 502 se não corrigir |
| Formato final diferente do contrato | validação com Pydantic, com os campos problemáticos na resposta | 502 |
| **Chamado ou procedimento inventado** | todo ID citado precisa ter vindo de uma ferramenta; o que não veio é removido e registrado em `avisos`. Se nenhum chamado anterior sobra, a recorrência volta para `primeira_vez` | 201 com `avisos` |
| Subcategoria de outra categoria | removida, com aviso | 201 com `avisos` |
| Acento trocado ou maiúscula (`Média`, `Solicitação`) | normalizado antes de validar | 201 |

### Organização do código

| Arquivo | Responsabilidade |
|---|---|
| `triagem.py` | o agente: prompt, ferramentas declaradas ao modelo, laço de *function calling*, conferência de IDs; também a linha de comando |
| `modelos.py` | provedores de IA (OpenRouter e Gemini): tentativas, prazo, modelo reserva, conferência da saída |
| `base.py` | dados e busca: carrega chamados, procedimentos e investigações e faz a busca BM25 |
| `api.py` | rotas HTTP e tradução de falhas em códigos HTTP |
| `esquemas.py` | contratos de entrada e saída (Pydantic) |
| `armazenamento.py` | histórico em Postgres, ou em memória quando não há banco |
| `demo.py` / `gravar_demo.py` | modo demonstração e a gravação das triagens reais que ele usa |
| `avaliar.py` | avaliação contra o gabarito |
| `checar_corte.py` | lista os procedimentos que ainda não existiam na data de cada chamado de teste |
| `testes/` | testes da API, das conferências e do laço do agente com um modelo roteirizado, sem rede |

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
- **Conferi o juiz.** Na avaliação anterior ao corte de datas, revisei à mão os 23 vereditos e concordei com todos, inclusive com os 4 em que ele reprovou os passos do agente.
- **Chamados sem resolução escrita** são contados à parte, em vez de distorcer o resultado.
- **Sem olhar o futuro.** Chamados, investigações e procedimentos criados depois do chamado avaliado ficam escondidos, inclusive o rascunho de procedimento escrito a partir dele. `checar_corte.py` mostra o que esse corte esconde em cada chamado de teste.
- **Achei um vazamento na minha própria avaliação.** Na primeira versão, a busca de procedimentos não respeitava a data: 8 dos 26 procedimentos, alguns escritos a partir dos próprios chamados de teste, apareciam para chamados mais antigos. Corrigi o filtro, criei o `checar_corte.py` e refiz a avaliação dos dois modelos. A categoria não mudou (78%), mas os passos compatíveis caíram de 83% para 70%: parte do acerto antigo era cola.

### Resultados

<!-- resultados:inicio -->
|  | DeepSeek V4.1 Flash | Claude Haiku 5.5 | linha de base |
| --- | --- | --- | --- |
| chamados concluídos | 40/40 | 40/40 | — |
| categoria | 78% (31/40) | 72% (29/40) | 45% |
| subcategoria | 56% (14/25) | 56% (14/25) | 8% |
| tipo | 80% (32/40) | 82% (33/40) | 50% |
| prioridade | 72% (29/40) | 62% (25/40) | 45% |
| passos compatíveis (juiz) | 70% (16) | 74% (17) | — |
| chamadas ao modelo por chamado | 3,2 | 3,6 | — |
| segundos por chamado | 22,7 | 17,9 | — |
| custo por chamado | US$ 0,0029 | US$ 0,0040 | — |

Os passos só são julgados nos chamados que têm a resolução escrita (17 não tinham). A linha de base é chutar sempre a resposta mais comum nos chamados anteriores. Juiz: `google/gemini-3.5-flash`, o mesmo para todos os modelos.
<!-- resultados:fim -->

**De v1 para a versão final.** Na primeira avaliação com o DeepSeek, 6 dos 40 chamados falharam, todos pelo mesmo motivo: o modelo corrompia "média" em `mຝia`, e a conferência recusava o valor até esgotar as tentativas. A correção foi mandar as prioridades ao modelo sem acento e converter de volta no código. Com isso, os 40 chamados passaram a ser concluídos.

**Por que o DeepSeek.** Os dois modelos empataram. O DeepSeek foi melhor em categoria (78% × 72%) e prioridade (72% × 62%); o Haiku, um pouco melhor no tipo (82% × 80%) e nos passos (74% × 70%). Com 40 chamados, a margem de erro fica em torno de 14 pontos, e todas essas diferenças cabem nela. O que decidiu foi o custo: o DeepSeek saiu cerca de 30% mais barato (US$ 0,0029 × US$ 0,0040 por chamado) e fez menos chamadas ao modelo (3,2 × 3,6), mesmo sendo um pouco mais lento (23 s × 18 s).

**E por que o site ainda usa o Haiku.** O sistema de chamados começou a usar o Haiku antes da avaliação final. Quando os resultados saíram, ele já estava sendo medido em chamados reais (tempo de registro e aceitação das sugestões), e trocar no meio misturaria os dois modelos na mesma medição. Por isso, o Haiku fica até o fim da medição, e depois o site passa para o DeepSeek. No uso real, o Haiku teve a sugestão aceita inteira em 92% dos chamados (24 de 26).

## Onde ele erra

- **"Impressão" virou impressora.** O agente não conhecia o jargão interno. A solução foi o glossário, que vai junto no pedido quando o termo aparece.
- **Valores que não existem.** Um modelo devolveu a prioridade `mຝia`. Outro vazou campos para dentro dos textos (`<parameter name="confianca">`). A solução foi a conferência no código, que devolve o erro ao modelo e pede de novo.
- **"Pediu" virou "feito".** No sistema de chamados, "pediu pra resetar a senha" foi salvo como resolvido. A solução foi uma regra explícita: pedido não é ação feita, e na dúvida o passo fica pendente.
- **Prioridade rebaixada porque "já foi resolvido".** Backup, termo e troca de cartucho caíram para média ou baixa porque a anotação dizia que estava feito, mesmo com o prompt mandando julgar pelo momento da abertura. **Ainda em aberto.** É a maior fonte de erro de prioridade, e a prioridade (72%) é o campo com menos acerto depois da subcategoria (56%).

## No dia a dia

O mesmo raciocínio virou o campo **"Descrever com IA"** no meu sistema de chamados, inspirado no ServiceNow que eu usava num emprego anterior. Antes dele, os chamados chegavam por formulário, e-mail e planilha. Agora escrevo do meu jeito ("pediu reset, resetei") e a IA preenche o formulário e a linha do tempo, com o feito e o pendente separados.

- O texto é **anonimizado antes de sair** e desanonimizado na volta. Senhas são apagadas e não voltam. O limite: um nome só é reconhecido se já apareceu em algum chamado, por isso a tela mostra exatamente o que foi enviado à IA.
- A chave da IA fica nos segredos do servidor, nunca no navegador.
- Para colaborador novo, o **usuário e o e-mail são calculados por código** a partir do nome, com aviso quando o login já existe.

O sistema mede sozinho, sem mostrar nada na tela, quanto tempo cada registro leva e quanto da sugestão da IA eu mantive:

| | manual | com IA |
|---|---|---|
| tempo ativo mediano para registrar um chamado | 70 s | 88 s |
| o mesmo, sem a espera pela resposta da IA | 64 s | 77 s |
| passos registrados na linha do tempo (mediana) | 1 | 4 |
| chamados registrados no período (09 a 11/11/2026) | 11 | 4 |

"Tempo ativo" conta só os segundos com a aba visível e alguma ação minha no último minuto. Café e interrupção não entram.

| Sugestão da IA mantida sem edição | % |
|---|---|
| categoria | 100 |
| subcategoria | 96 |
| tipo | 100 |
| prioridade | 96 |
| **tudo junto** | **92** |

Dados de 26 chamados registrados com IA, de 30/10 a 11/11/2026. Sou o único usuário, então manter a sugestão não prova que ela estava certa.

**O resultado até agora: a IA não deixou o registro mais rápido.** Mesmo descontando os cerca de 12 s de espera pela resposta, levo uns 13 s a mais por chamado. O ganho foi outro: o chamado registrado com IA sai com uma mediana de 4 passos na linha do tempo, contra 1 no manual. São esses passos que alimentam a base de conhecimento e a detecção de recorrência.

Dois cuidados ao ler esses números. A amostra é pequena (4 chamados com IA e 11 manuais). E ela tem viés: usei a IA justamente nos chamados mais longos (uma macro com erro, um acesso remoto, a preparação de uma máquina), enquanto os manuais foram, na maioria, trocas de cabo e instalações de certificado. A comparação justa exige misturar os dois modos nos mesmos tipos de chamado, e é isso que estou medindo agora.

Uma observação, ainda sem força de conclusão: a fatia de N1 entre os chamados registrados subiu de 18% em julho para 45% em outubro, e novembro segue em ritmo parecido. Combina com a ideia de que o N1 resolvido no corredor passou a ser registrado, mas o período é curto demais para afirmar.

## Como construí

O código foi escrito com IA. O meu papel foi o que a IA não tinha como saber sozinha:

- **O problema e o contexto.** Quais chamados param um setor, o que são softwares especificos da empresa, por que um backup antes de formatar é alta, por que devolver um notebook não é desligamento.
- **As decisões.** Anonimizar antes de qualquer coisa. Pagar centavos por um modelo que não treina com os dados, em vez de usar um gratuito que treina. Revisar o gabarito à mão. Usar um juiz de outra empresa.
- **Testar e duvidar do resultado.** Os erros da lista acima apareceram usando o agente com chamados reais e conferindo a saída, não lendo o código.

## Como rodar

Com Docker, veja [Testar em 2 minutos](#testar-em-2-minutos). Para apontar a API para outra pasta de chamados, defina `DADOS_LOCAL` no `.env`.

Sem Docker (o histórico fica em memória se `DATABASE_URL` não estiver definida):

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
uvicorn api:app --reload
```

| Variável | Para quê |
|---|---|
| `OPENROUTER_API_KEY` | chave da OpenRouter; vazia, a API fica em modo demonstração |
| `OPENROUTER_MODEL` | modelo principal (avaliado: `deepseek/deepseek-v4.1-flash`) |
| `OPENROUTER_MODEL_RESERVA` | modelo usado pela OpenRouter se o principal falhar |
| `TRIAGEM_PRAZO_SEGUNDOS` | tempo máximo de uma triagem |
| `DADOS_TRIAGEM` / `DADOS_LOCAL` | pasta dos chamados (sem Docker / com Docker); padrão: `dados_exemplo` |
| `DATABASE_URL` | Postgres do histórico; o compose já define |
| `TRIAGEM_CHAVE_API` | se definida, `POST /triagem` e `GET /triagens` exigem o cabeçalho `X-API-Key`; obrigatória fora do `127.0.0.1` |
| `TRIAGEM_LIMITE_POR_MINUTO` | triagens reais por minuto antes de responder 429; padrão 10, `0` desliga |
| `TRIAGEM_PESQUISA_WEB` | `0` desliga a ferramenta de pesquisa na web |

### Segurança

- **Acesso:** o compose publica a porta só em `127.0.0.1`. Para expor a API, defina `TRIAGEM_CHAVE_API`: sem ela, quem alcança a porta gasta seus créditos e lê o histórico de triagens. Comparação da chave em tempo constante.
- **Custo:** limite global de triagens reais por minuto e prazo total por triagem.
- **Injeção de prompt:** o texto do chamado chega ao modelo marcado como dado, não instrução. O que o modelo devolve passa por Pydantic, IDs inventados são removidos e links de fontes só saem se forem `http(s)`. Argumento malformado numa ferramenta vira erro para o modelo, não 500.
- **Vazamento pela pesquisa na web:** é a única saída para a internet. Antes de pesquisar, a consulta perde e-mails, rótulos de usuário, tags de máquina, IDs de chamado e números longos, e é cortada em 150 caracteres. `TRIAGEM_PESQUISA_WEB=0` desliga de vez.
- **Erros:** detalhes do provedor de IA ficam no log do servidor; o cliente recebe só o motivo.
- **Segredos:** `.env` e backups ficam fora do Git (`.gitignore`); só `.env.example`, vazio, é versionado. O container roda sem root.

As triagens do modo demonstração são geradas pelo próprio agente com `python gravar_demo.py` e ficam em `dados_exemplo/gravacoes_demo.json`.

Linha de comando e avaliação com os dados reais, anonimizados, fora do repositório:

```bash
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
python preencher_resultados.py avaliacao-deepseek avaliacao-haiku --custo deepseek=VALOR --custo haiku=VALOR
```

A avaliação salva o progresso e continua de onde parou. Para ela seguir rodando se o terminal fechar, use `nohup ... &`.

## Privacidade

Os chamados vêm de um ambiente real. Antes de qualquer uso com IA, eles passam pelo [anonimizador](../anonimizador): pessoas viram "Usuário N" e "Técnico N", e senhas, e-mails, domínios, IPs e nomes de empresas e clientes são removidos.

- Todo pedido à OpenRouter vai com `data_collection: deny`, ou seja, só para provedores que não treinam com os dados.
- Os modelos gratuitos não passaram nesse filtro. Em vez de liberar os dados, paguei pelo uso: a avaliação inteira custa centavos.
- **Onde a anonimização acontece.** No sistema de chamados, numa Edge Function, antes de o texto sair do servidor. Na avaliação, pelo anonimizador, antes de os dados chegarem à pasta local. A API deste repositório não anonimiza: ela espera texto já anonimizado, e o modo demonstração usa só dados fictícios.
- Nenhum dado da empresa, nem anonimizado, fica neste repositório. O agente lê os dados reais de uma pasta local (`DADOS_TRIAGEM`), e as pastas de avaliação e o gabarito estão no `.gitignore`. A pasta `dados_exemplo` é inventada do zero, de uma empresa fictícia.

## Limitações

- A avaliação usa 40 chamados de um único ambiente. É um retrato honesto, não um benchmark.
- Não há chamados críticos na amostra, então o acerto nessa classe não foi medido.
- A pesquisa na web usa o DuckDuckGo (`ddgs`), para funcionar igual com qualquer provedor.
- A API não chama o anonimizador. Quem a usar com dados reais precisa anonimizar antes.
- Para chamados que ainda não passaram pelo anonimizador, o histórico por usuário só funciona com o rótulo ("Usuário 12"), não com o nome real.
