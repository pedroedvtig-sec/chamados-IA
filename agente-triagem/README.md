# Agente de triagem de chamados

Sou o único analista de suporte de TI da empresa. Cada chamado que chega precisa ser lido, classificado, ligado a um procedimento e respondido, e boa parte disso é repetitivo. Este agente faz essa primeira etapa: recebe o chamado e devolve a triagem pronta para eu revisar.

## O que ele devolve

| Campo | Exemplo |
|---|---|
| Categoria / subcategoria | rede / compartilhamento |
| Tipo | incidente, solicitação, tarefa ou compra |
| Prioridade e o motivo | alta: a pessoa está sem acesso ao e-mail e não tem alternativa |
| Recorrência | **recorrente** (EMP-0217, EMP-0250): a mesma pasta caiu na mesma máquina há duas semanas |
| Procedimento recomendado | "Pasta de rede sumiu ou não abre" [direta] |
| Passos para o técnico | 1. Confirmar o grupo do usuário no AD 2. Rodar o script de mapeamento… |
| Fonte dos passos | procedimento, chamados anteriores, pesquisa na web ou conhecimento geral |
| Resposta para o usuário | mensagem curta, sem jargão |

## Como funciona

O agente usa o Gemini com *function calling*: o modelo decide quais ferramentas chamar, lê o resultado e só então decide.

```
chamado novo
   │
   ▼
Gemini ──► buscar_procedimentos       base oficial + rascunhos N1 (busca BM25 local)
   │  ──► historico                   chamados anteriores do mesmo usuário e da mesma máquina
   │  ──► buscar_chamados_parecidos   como casos parecidos foram resolvidos + investigações
   │  ──► pesquisar_web               só quando a base interna não resolve
   ▼
finalizar_triagem  (saída estruturada, validada por esquema)
```

- **A busca é local.** Procedimentos e chamados ficam na máquina; só os trechos relevantes vão para o modelo.
- **A saída é uma chamada de função com esquema** (categorias e prioridades como `enum`), não texto livre para depois interpretar.
- **Glossário interno.** No primeiro teste real, o agente leu "erro de impressão no MBOX" como problema de impressora. Só que MBOX é o software de e-mail do jurídico, e "impressão" ali é exportar a mensagem. Agora, quando o chamado cita um termo do `glossario.json`, a definição vai junto no pedido. Termos desconhecidos baixam a confiança, em vez de virarem um chute.
- **A recorrência é por sintoma, não por categoria.** O agente recebe o histórico do usuário e da máquina e precisa citar os IDs dos chamados que provam a recorrência.

## Avaliação

`avaliar.py` pega os N chamados mais recentes e tria cada um **como se fosse novo**: o agente só enxerga chamados abertos antes dele, para não "colar" da resposta.

Para cada chamado, o relatório compara:

- **categoria, tipo e prioridade** com o que eu marquei, e com uma linha de base ("chutar sempre a mais comum"). Acertar 70% não diz nada se 70% dos chamados são da mesma categoria.
- **procedimento recomendado** com o procedimento que eu realmente executei, quando isso foi registrado.
- **os passos sugeridos** com o que foi feito de verdade. Um segundo modelo atua como juiz: compatível, parcial ou diferente.

Dois problemas reais dos dados, que a avaliação deixa à mostra:

1. **Muitos chamados N1 não têm a resolução escrita** ("pediu reset de senha, resetei"). Esses casos são contados à parte, como "sem registro", em vez de distorcer o resultado. Os procedimentos N1 em rascunho existem para preencher essa lacuna.
2. **Nos chamados recentes, quase toda prioridade ficou no padrão "média".** Por isso existe o gabarito revisado à mão (`--gerar-gabarito` / `--gabarito`): comparar com um rótulo que ninguém preencheu não mede nada.

### Resultados

> Rode a avaliação e cole aqui o resumo de `avaliacao/relatorio.md`.

## Como rodar

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="sua-chave-do-google-ai-studio"
export DADOS_TRIAGEM=~/dados_privados/dados_anonimizados

python triagem.py "a pasta Z sumiu do computador" --usuario "Usuário 12" --maquina PC-000049
python triagem.py --chamado EMP-0349

python avaliar.py --gerar-gabarito gabarito.csv
python avaliar.py --n 40 --gabarito gabarito.csv
```

O modelo padrão é `gemini-3.8-flash`; troque com `--modelo` ou com a variável `GEMINI_MODEL`. A avaliação salva o progresso em `avaliacao/resultados.jsonl` e continua de onde parou se o limite gratuito da API estourar.

## Privacidade

Os chamados vêm de um ambiente real. Antes de qualquer uso com IA, eles passam pelo [anonimizador](../anonimizador): pessoas viram "Usuário N" e "Técnico N", e senhas, e-mails, domínios, IPs e nomes de empresa e clientes são removidos. Nenhum dado, nem anonimizado, fica neste repositório: o agente lê tudo de uma pasta local (`DADOS_TRIAGEM`), e a pasta `avaliacao/` está no `.gitignore`.

## Limitações

- A pesquisa na web usa o DuckDuckGo (`ddgs`), porque o *grounding* com Google Search não está disponível no plano gratuito do Gemini.
- No plano gratuito, o Google pode usar o conteúdo enviado para melhorar os produtos dele. Por isso só dados anonimizados são enviados.
- Para chamados novos que ainda não passaram pelo anonimizador, o histórico por usuário só funciona com o rótulo ("Usuário 12"), não com o nome real.
