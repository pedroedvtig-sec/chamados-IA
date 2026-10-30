import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from base import RE_MAQUINA, Base, Ferramentas, cortar
from modelos import criar_provedor

DADOS_PADRAO = os.environ.get("DADOS_TRIAGEM", "~/dados_privados/dados_anonimizados")

TIPOS = ["incidente", "solicitacao", "tarefa"]
PRIORIDADES = ["baixa", "média", "alta", "crítica"]

SISTEMA = """Você é o agente de triagem do suporte de TI de uma empresa com um único analista de suporte.
Você recebe um chamado novo e devolve a triagem completa chamando a função finalizar_triagem.

Como trabalhar:
1. Chame buscar_procedimentos com os termos do problema (sintoma, aplicativo, equipamento).
2. Chame historico com o rótulo do usuário e com a máquina, se houver, para saber se o problema é recorrente.
3. Se nenhum procedimento servir direto, chame buscar_chamados_parecidos para ver como casos parecidos foram resolvidos.
4. Só se nem procedimento nem chamado anterior resolverem, chame pesquisar_web com uma consulta específica em português (aplicativo, modelo, mensagem de erro).
5. Termine SEMPRE chamando finalizar_triagem. Não responda em texto livre.

Tipo:
- incidente: algo que funcionava parou de funcionar. Inclui tinta ou toner que acabou e precisa ser trocado, e conta travada por falha do sistema.
- solicitacao: algo a mais que o usuário pede: acesso, equipamento por preferência, instalação, troca de nome no AD, reset de senha porque o usuário esqueceu, máquina para colaborador novo.
- tarefa: trabalho que parte do processo ou da própria TI, sem pedido do usuário: backup, desligamento de colaborador, formatação planejada, inventário, refazer termo ou documentação depois de uma troca de equipamento.

Categoria:
- Solicitação de máquina para colaborador novo (ou máquina temporária para quem vai entrar) é sempre hardware, mesmo que inclua configuração de contas e sistemas.

Prioridade = impacto × urgência.
Impacto: empresa inteira > setor inteiro ou serviço que vários usam > uma pessoa. Use o "Mapa de impacto" do pedido para saber quais máquinas e serviços afetam muita gente.
Urgência: parado sem alternativa > atrapalha mas tem contorno > sem pressa.
- crítica: empresa ou setor inteiro parado; risco de segurança ativo.
- alta: setor afetado mas com contorno; uma pessoa parada sem alternativa; desligamento de colaborador (os acessos precisam ser revogados logo); solicitação de máquina para colaborador novo.
- média: uma pessoa com o trabalho atrapalhado, mas com contorno; pedido comum com prazo normal.
- baixa: dúvida, ajuste, padronização ou melhoria sem impacto no trabalho.
Julgue pelo problema no momento em que foi relatado. Muitos chamados são registrados depois de resolvidos ("resetei", "deu certo"): isso não diminui a prioridade.
Na dúvida entre duas, escolha a menor e explique.

Recorrência:
- recorrente: o histórico do mesmo usuário ou da mesma máquina tem chamado do mesmo problema (mesmo sintoma, não só a mesma categoria). Cite os IDs.
- primeira_vez: não há chamado anterior do mesmo problema para esse usuário ou máquina.

Procedimento:
- Recomende um procedimento só se ele resolve esse problema. aplicabilidade "direta" quando serve inteiro, "parcial" quando só parte serve, "nenhuma" quando nenhum serve.
- Procedimentos de origem "rascunho N1 (revisar)" valem, mas diga isso no campo motivo.
- passos_sugeridos: passos concretos, na ordem, para o técnico. Se vieram da web, coloque as fontes em fontes_web.

Termos internos:
- Os chamados usam nomes de sistemas e siglas da empresa. Quando o pedido trouxer um "Glossário interno", use o significado dele, mesmo que a palavra tenha outro sentido comum (ex.: "impressão" num sistema pode ser exportação, não papel).
- Se o chamado citar um sistema ou sigla que você não conhece e que não está no glossário, não chute o significado: diga isso no motivo, use confiança "baixa" e sugira como primeiro passo confirmar com o usuário.

Subcategoria: precisa pertencer à categoria escolhida (a lista por categoria está na descrição do campo).

resposta_usuario: mensagem curta para a pessoa que abriu o chamado, em linguagem simples, sem jargão, sem prometer prazo e sem pedir senha.
Nunca invente IDs de chamados ou de procedimentos: use só os que as funções devolveram."""


def declaracoes(base):
    texto = {"type": "string"}
    return [
        {"name": "buscar_procedimentos",
         "description": "Busca na base de procedimentos da TI (passo a passo oficial e rascunhos N1).",
         "parameters_json_schema": {"type": "object", "properties": {"consulta": texto}, "required": ["consulta"]}},
        {"name": "buscar_chamados_parecidos",
         "description": "Busca chamados antigos parecidos e como foram resolvidos, além de investigações detalhadas.",
         "parameters_json_schema": {"type": "object", "properties": {"consulta": texto}, "required": ["consulta"]}},
        {"name": "historico",
         "description": "Lista os chamados anteriores do mesmo usuário (rótulo 'Usuário N') e/ou da mesma máquina (tag 'PC-000123').",
         "parameters_json_schema": {"type": "object", "properties": {"usuario": texto, "maquina": texto}}},
        {"name": "pesquisar_web",
         "description": "Pesquisa na internet. Use só quando a base interna não tiver solução.",
         "parameters_json_schema": {"type": "object", "properties": {"consulta": texto}, "required": ["consulta"]}},
        {"name": "finalizar_triagem",
         "description": "Entrega a triagem final do chamado. Deve ser a última chamada.",
         "parameters_json_schema": {
             "type": "object",
             "properties": {
                 "categoria": {"type": "string", "enum": base.categorias},
                 "subcategoria": {"type": "string", "description": "Subcategoria da MESMA categoria, ou vazio. " + "; ".join(
                     f"{cat}: {', '.join(subs)}" for cat, subs in base.subs_por_categoria.items() if subs)},
                 "tipo": {"type": "string", "enum": TIPOS},
                 "prioridade": {"type": "string", "enum": PRIORIDADES},
                 "motivo_prioridade": texto,
                 "recorrencia": {"type": "string", "enum": ["primeira_vez", "recorrente"]},
                 "chamados_relacionados": {"type": "array", "items": texto},
                 "motivo_recorrencia": texto,
                 "procedimento_id": {"type": "string", "description": "ID do procedimento recomendado, ou vazio"},
                 "procedimento_titulo": texto,
                 "aplicabilidade": {"type": "string", "enum": ["direta", "parcial", "nenhuma"]},
                 "passos_sugeridos": {"type": "array", "items": texto},
                 "fonte_dos_passos": {"type": "string",
                                      "enum": ["procedimento", "chamados_anteriores", "pesquisa_web", "conhecimento_geral"]},
                 "fontes_web": {"type": "array", "items": {"type": "object",
                                                          "properties": {"titulo": texto, "url": texto}}},
                 "resposta_usuario": texto,
                 "confianca": {"type": "string", "enum": ["baixa", "media", "alta"]},
             },
             "required": ["categoria", "tipo", "prioridade", "motivo_prioridade", "recorrencia", "motivo_recorrencia",
                          "aplicabilidade", "passos_sugeridos", "fonte_dos_passos", "resposta_usuario", "confianca"],
         }},
    ]


def montar_pedido(chamado, base=None):
    linhas = [
        f"Título: {chamado.get('titulo') or '(sem título)'}",
        f"Descrição: {chamado.get('descricao') or '(sem descrição)'}",
        f"Usuário: {chamado.get('usuario') or '(não informado)'}",
        f"Departamento: {chamado.get('departamento') or '(não informado)'}",
        f"Máquina: {chamado.get('maquina') or '(não informada)'}",
    ]
    pedido = "Faça a triagem deste chamado:\n" + "\n".join(linhas)
    if base and base.impacto:
        pedido += "\n\nMapa de impacto da empresa:\n" + "\n".join(f"- {linha}" for linha in base.impacto)
    termos = base.termos_internos(f"{chamado.get('titulo', '')} {chamado.get('descricao', '')}") if base else {}
    if termos:
        pedido += "\n\nGlossário interno (termos que aparecem neste chamado):\n" + "\n".join(
            f"- {t}: {explicacao}" for t, explicacao in termos.items())
    return pedido


def triar(chamado, ferramentas, provedor, max_rodadas=8):
    funcoes = {
        "buscar_procedimentos": ferramentas.buscar_procedimentos,
        "buscar_chamados_parecidos": ferramentas.buscar_chamados_parecidos,
        "historico": ferramentas.historico,
        "pesquisar_web": ferramentas.pesquisar_web,
    }

    def executar(nome, argumentos):
        funcao = funcoes.get(nome)
        if not funcao:
            return {"erro": f"função desconhecida: {nome}"}
        try:
            return funcao(**argumentos)
        except TypeError as erro:
            return {"erro": f"argumentos inválidos para {nome}: {erro}"}

    inicio = time.time()
    resultado, rastro, chamadas = provedor.agente(
        SISTEMA, montar_pedido(chamado, ferramentas.base), declaracoes(ferramentas.base),
        executar, "finalizar_triagem", max_rodadas)
    resultado["ferramentas_usadas"] = rastro
    resultado["chamadas_ao_modelo"] = chamadas
    resultado["segundos"] = round(time.time() - inicio, 1)
    resultado["modelo"] = provedor.modelos_usados[-1] if provedor.modelos_usados else provedor.modelo
    return resultado


def chamado_da_base(base, id_chamado):
    c = base.por_id.get(id_chamado.upper())
    if not c:
        sys.exit(f"Chamado {id_chamado} não encontrado na base.")
    novo = {
        "titulo": c["titulo"],
        "descricao": c["descricao"],
        "usuario": ", ".join(c["usuarios"]) or c["usuario_texto"],
        "departamento": c["departamento"],
        "maquina": ", ".join(c["maquinas"]),
    }
    return novo, Ferramentas(base, corte=c["data"], excluir={c["id"]}), c


def exibir(r):
    linha = "─" * 60
    print(linha)
    sub = f' / {r["subcategoria"]}' if r.get("subcategoria") else ""
    print(f'Categoria: {r.get("categoria")}{sub}    Tipo: {r.get("tipo")}    Prioridade: {r.get("prioridade")}')
    print(f'  {r.get("motivo_prioridade", "")}')
    relacionados = ", ".join(r.get("chamados_relacionados") or [])
    rec = "RECORRENTE" if r.get("recorrencia") == "recorrente" else "primeira vez"
    print(f'\nRecorrência: {rec}{f" ({relacionados})" if relacionados else ""}')
    print(f'  {r.get("motivo_recorrencia", "")}')
    if r.get("procedimento_titulo") and r.get("aplicabilidade") != "nenhuma":
        print(f'\nProcedimento: {r["procedimento_titulo"]} [{r.get("aplicabilidade")}]')
    else:
        print("\nProcedimento: nenhum na base")
    print(f'\nPassos sugeridos (fonte: {r.get("fonte_dos_passos")}):')
    for i, passo in enumerate(r.get("passos_sugeridos") or [], 1):
        print(f"  {i}. {passo}")
    for f in r.get("fontes_web") or []:
        print(f'     ↳ {f.get("titulo", "")}: {f.get("url", "")}')
    print("\nResposta para o usuário:")
    print(f'  {r.get("resposta_usuario", "")}')
    usadas = ", ".join(f'{u["funcao"]}({cortar(", ".join(str(v) for v in u["argumentos"].values()), 40)})'
                       for u in r.get("ferramentas_usadas", []))
    print(f'\nConfiança: {r.get("confianca")}    Ferramentas: {usadas or "nenhuma"}')
    print(f'{r.get("chamadas_ao_modelo")} chamadas ao modelo em {r.get("segundos")}s · modelo: {r.get("modelo")}')
    print(linha)


def main():
    ap = argparse.ArgumentParser(description="Agente de triagem de chamados de suporte.")
    ap.add_argument("texto", nargs="?", help="descrição do problema")
    ap.add_argument("--titulo", default="")
    ap.add_argument("--usuario", default="", help="rótulo do usuário, ex.: 'Usuário 3'")
    ap.add_argument("--departamento", default="")
    ap.add_argument("--maquina", default="", help="tag da máquina, ex.: PC-000087")
    ap.add_argument("--chamado", help="triar um chamado já existente da base, ex.: EMP-0349")
    ap.add_argument("--dados", default=DADOS_PADRAO)
    ap.add_argument("--provedor", help="openrouter ou gemini (padrão: LLM_PROVEDOR, ou openrouter se houver OPENROUTER_API_KEY)")
    ap.add_argument("--modelo", help="nome do modelo no provedor escolhido")
    ap.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    args = ap.parse_args()

    if not args.texto and not args.chamado:
        ap.error("informe o texto do chamado ou --chamado EMP-XXXX")
    provedor = criar_provedor(args.provedor, args.modelo)
    base = Base(args.dados)

    if args.chamado:
        chamado, ferramentas, original = chamado_da_base(base, args.chamado)
    else:
        texto = f"{args.titulo} {args.texto}"
        chamado = {
            "titulo": args.titulo or cortar(args.texto, 60),
            "descricao": args.texto,
            "usuario": args.usuario,
            "departamento": args.departamento,
            "maquina": args.maquina or ", ".join(sorted({m.upper() for m in RE_MAQUINA.findall(texto)})),
        }
        ferramentas, original = Ferramentas(base, corte=datetime.now(timezone.utc)), None

    resultado = triar(chamado, ferramentas, provedor)

    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return
    exibir(resultado)
    if original:
        print(f'Real: {original["categoria"]} / {original["tipo"]} / {original["prioridade"]}'
              f' | resolução registrada: {cortar(original["resolucao"] or original["descricao"], 120)}')


if __name__ == "__main__":
    main()
