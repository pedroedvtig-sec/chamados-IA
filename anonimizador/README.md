# Anonimizador de chamados de suporte

Antes de mandar chamados reais para uma IA, eles precisam perder tudo o que identifica alguém ou a empresa. Este script pega os exports do sistema de chamados (CSV do Supabase ou backup JSON) e devolve os mesmos arquivos com:

| O que sai | Vira o quê | Exemplo |
|---|---|---|
| Pessoa (nome sozinho, completo, minúsculo, sem acento, com erro de digitação, grudado em outra palavra, em nome de arquivo) | `Usuário N`, ou `Técnico N` para quem é da TI | `a Patrícia Ribeiro` → `a Usuário 3` |
| Login de AD (`jnunes`, `rlima`) | rótulo da mesma pessoa | `jnunes` → `usuario114` |
| E-mail com nome | rótulo da mesma pessoa + domínio genérico | `usuario71@empresa.example` |
| Senha escrita no chamado | `[SENHA-REMOVIDA]` | |
| Empresa, clientes, domínios internos | nomes genéricos | `minhaempresa.local` → `empresa.local` |
| CNPJ / CPF | `[CNPJ-REMOVIDO]` | |
| IP da rede interna | outra faixa | `192.168.0.20` → `10.20.30.20` |
| Tags de máquina e IDs de chamado | prefixo neutro, **mesmo número** | `NB-000087` → `PC-000087` |
| ID do usuário no Supabase | UUID falso | |

Links públicos (site da HP, Lenovo, gov.br) ficam intactos, porque ajudam no atendimento e não identificam ninguém.

## Como usar

```bash
cp config.exemplo.json config.json      # preencha com os dados reais
python anonimizador.py entrada/ saida/
```

Só usa a biblioteca padrão do Python, sem dependências.

No fim, o script roda um **teste de vazamento** na própria saída: procura qualquer nome da lista, IP interno, domínio da empresa, ID do Supabase ou texto com cara de senha. Se achar algo, lista o que achou e termina com código de erro 1.

Último uso real (352 chamados, 9 projetos, 12 procedimentos, 11 dossiês):

```
pessoas distintas     122   (9 técnicos)
menções a pessoas    1420
tag_ou_id_interno     674
id_usuario_supabase   440
empresa_cliente        85
login_ad               24
ip_interno             15
email                  14
senha                   9
cnpj_cpf                2
link_privado            1

Teste de vazamento: OK, nada encontrado
```

## Como ele descobre quem é quem

O difícil não é achar nomes, é saber **quem** é cada menção. Existem três Patrícias, quatro Fernandas e dois Thiagos na TI.

1. **Primeira passada:** o script lê todos os arquivos e agrupa os nomes completos por sobrenome. "Patricia Ribeiro" e "Patrícia Ribeiro" viram uma pessoa; "Patricia Teixeira" vira outra. Grafias diferentes que compartilham um sobrenome se juntam ("Camila Rezende" e "Camila Duarte Resende").
2. **Segunda passada:** cada menção é ligada a uma pessoa:
   - Nome completo vai pelo sobrenome.
   - Nome sozinho ("a Patrícia") vai para quem tem esse nome e mais aparece, a não ser que o `config.json` diga outra coisa em `quem_e` (ex.: "Thiago" sozinho é o Thiago da TI).
   - Login de AD (`jnunes`) vai pela inicial + sobrenome.
3. Quem está na lista `tecnicos` vira `Técnico N`; o resto vira `Usuário N`, na ordem em que aparece.

Sobrenomes que também são palavras comuns (`Paz`, `Cruz`, `Passos`, `Costa`) só contam como nome quando vêm depois de outro nome. Assim "Marcelo Paz" é trocado, mas "os passos do procedimento" fica intacto.

O arquivo `saida/_mapa_privado.json` mostra cada rótulo e todas as formas como aquela pessoa apareceu, para conferir os agrupamentos.

## Decisões de projeto

- **Rótulo neutro (`Usuário 7`) em vez de nome falso.** Fica óbvio que o dado foi anonimizado e não sobra nem o gênero da pessoa. A IA continua vendo padrões ("o Usuário 3 pede reset de senha toda semana").
- **Usuário × Técnico.** Separar quem pede de quem resolve é informação útil para um agente de triagem.
- **Os números de tags e chamados são mantidos**, porque projetos e procedimentos apontam para eles.
- **Determinístico.** A mesma entrada e o mesmo `config.json` geram sempre a mesma saída.
- **Baseado em lista, não em IA.** Os nomes vêm do `config.json`. Mandar os dados para uma IA descobrir os nomes seria justamente vazar o que se quer proteger.

## Limitações

- Uma pessoa que não está no `config.json` passa sem ser trocada. Ao exportar dados novos, revise a lista. O teste de vazamento só enxerga o que está na lista.
- Homônimos citados só pelo primeiro nome podem cair na pessoa errada. Corrija em `quem_e`.
- A detecção de senha procura tokens com letra + número + símbolo. Uma senha só de letras não é detectada.

## Arquivos privados (fora do Git)

- `config.json`: a lista dos nomes reais.
- `entrada/`: os dados originais.
- `saida/`: até os dados anonimizados ficam fora, porque ainda descrevem a operação interna.
