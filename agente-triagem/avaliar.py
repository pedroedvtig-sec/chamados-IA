import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

from base import Base, cortar
from modelos import criar_provedor
from triagem import DADOS_PADRAO, PRIORIDADES, TIPOS, chamado_da_base, triar

CAMPOS = ["categoria", "subcategoria", "tipo", "prioridade"]

JUIZ = """Você avalia um agente de triagem de suporte de TI.
Compare os passos que o agente sugeriu com o que o técnico realmente fez para resolver o chamado.
- compativel: seguindo os passos sugeridos, o técnico chegaria à mesma solução.
- parcial: a solução real aparece entre os passos, mas misturada com passos desnecessários, ou falta uma parte importante.
- diferente: os passos sugeridos não levariam à solução que resolveu o caso.
Julgue só pela solução, não pela forma de escrever."""

ESQUEMA_JUIZ = {
    "type": "object",
    "properties": {
        "veredito": {"type": "string", "enum": ["compativel", "parcial", "diferente"]},
        "motivo": {"type": "string"},
    },
    "required": ["veredito", "motivo"],
}


def julgar(juiz, original, passos):
    pedido = (f"Problema: {original['titulo']} — {cortar(original['descricao'], 600)}\n\n"
              f"O que o técnico fez: {cortar(original['resolucao'] or original['descricao'], 1200)}\n\n"
              "Passos sugeridos pelo agente:\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(passos, 1)))
    return juiz.json(JUIZ, pedido, ESQUEMA_JUIZ)


def tem_registro(original):
    return len(f"{original['descricao']} {original['resolucao']}".strip()) >= 60 and bool(original["resolucao"])


def avaliar_um(base, original, provedor, juiz, com_juiz):
    chamado, ferramentas, _ = chamado_da_base(base, original["id"])
    r = triar(chamado, ferramentas, provedor)
    gabarito_proc = sorted(p["id"] for p in base.procedimentos
                           if p["origem"] == "base oficial" and original["id"] in p["chamados_que_usaram"])
    linha = {
        "id": original["id"],
        "titulo": original["titulo"],
        "real": {c: original[c] for c in CAMPOS},
        "previsto": {c: r.get(c, "") for c in CAMPOS},
        "motivo_prioridade": r.get("motivo_prioridade", ""),
        "recorrencia": r.get("recorrencia", ""),
        "chamados_relacionados": r.get("chamados_relacionados", []),
        "procedimento_previsto": r.get("procedimento_id", "") if r.get("aplicabilidade") != "nenhuma" else "",
        "procedimento_gabarito": gabarito_proc,
        "fonte_dos_passos": r.get("fonte_dos_passos", ""),
        "passos_sugeridos": r.get("passos_sugeridos", []),
        "usou_web": any(u["funcao"] == "pesquisar_web" for u in r.get("ferramentas_usadas", [])),
        "ferramentas": [u["funcao"] for u in r.get("ferramentas_usadas", [])],
        "chamadas_ao_modelo": r.get("chamadas_ao_modelo", 0),
        "segundos": r.get("segundos", 0),
        "modelo": r.get("modelo", ""),
        "juiz_modelo": juiz.modelo if com_juiz else "",
    }
    if not com_juiz:
        linha["juiz"] = {"veredito": "nao_avaliado", "motivo": ""}
    elif not tem_registro(original):
        linha["juiz"] = {"veredito": "sem_registro", "motivo": "o chamado não tem a resolução escrita"}
    else:
        linha["juiz"] = julgar(juiz, original, linha["passos_sugeridos"])
    return linha


def porcentagem(a, b):
    return f"{100 * a / b:.0f}%" if b else "—"


def matriz(linhas, campo, valores):
    cab = "| real \\ agente | " + " | ".join(valores) + " |\n|---|" + "---|" * len(valores) + "\n"
    corpo = ""
    for real in valores:
        cont = Counter(l["previsto"][campo] for l in linhas if l["real"][campo] == real)
        corpo += f"| **{real}** | " + " | ".join(str(cont.get(v, 0)) for v in valores) + " |\n"
    return cab + corpo


def relatorio(linhas, erros, base, teste, modelo, juiz_modelo):
    ok = [l for l in linhas if "erro" not in l]
    n = len(ok)
    inicio_teste = min(c["data"] for c in teste)
    anteriores = [c for c in base.chamados if c["data"] and c["data"] < inicio_teste]

    md = ["# Avaliação do agente de triagem\n",
          f"Modelo: `{modelo}` · {n} chamados avaliados (os {len(teste)} mais recentes) · {len(erros)} com erro\n",
          "Cada chamado foi triado como se fosse novo: o agente só enxerga chamados abertos **antes** dele.\n",
          "## Classificação\n",
          "A linha de base é \"chutar sempre a resposta mais comum\" nos chamados anteriores. "
          "O agente só agrega valor onde passa dela.\n",
          "| campo | agente | linha de base (sempre a mais comum) |", "|---|---|---|"]
    for campo in CAMPOS:
        validos = [l for l in ok if l["real"][campo]]
        acertos = sum(l["previsto"][campo] == l["real"][campo] for l in validos)
        comum, _ = Counter(c[campo] for c in anteriores if c[campo]).most_common(1)[0]
        base_acertos = sum(l["real"][campo] == comum for l in validos)
        md.append(f"| {campo} | {porcentagem(acertos, len(validos))} ({acertos}/{len(validos)}) | "
                  f"{porcentagem(base_acertos, len(validos))} (sempre \"{comum}\") |")

    md += ["\n### Prioridade (linhas = o que você marcou, colunas = o que o agente sugeriu)\n", matriz(ok, "prioridade", PRIORIDADES),
           "\n### Tipo\n", matriz(ok, "tipo", TIPOS)]

    com_gabarito = [l for l in ok if l["procedimento_gabarito"]]
    acertos_proc = sum(l["procedimento_previsto"] in l["procedimento_gabarito"] for l in com_gabarito)
    recomendou = sum(bool(l["procedimento_previsto"]) for l in ok)
    md += ["\n## Procedimentos\n",
           f"- O agente recomendou algum procedimento em {porcentagem(recomendou, n)} dos chamados ({recomendou}/{n}).",
           f"- Nos chamados em que você registrou a execução de um procedimento oficial, ele recomendou o mesmo em "
           f"{porcentagem(acertos_proc, len(com_gabarito))} ({acertos_proc}/{len(com_gabarito)})."]

    fontes = Counter(l["fonte_dos_passos"] for l in ok)
    md += ["\n## De onde vieram os passos\n"] + [f"- {f}: {q}" for f, q in fontes.most_common()]
    md.append(f"- pesquisou na web em {sum(l['usou_web'] for l in ok)} chamados")

    rec = Counter(l["recorrencia"] for l in ok)
    md += ["\n## Recorrência\n",
           f"- recorrente: {rec.get('recorrente', 0)} · primeira vez: {rec.get('primeira_vez', 0)}"]

    juiz = Counter(l["juiz"]["veredito"] for l in ok)
    julgados = sum(juiz.get(v, 0) for v in ("compativel", "parcial", "diferente"))
    juizes = sorted({l.get("juiz_modelo", "") for l in ok if l.get("juiz_modelo")})
    quem = ", ".join(f"`{j}`" for j in juizes) or f"`{juiz_modelo}`"
    md += ["\n## Os passos sugeridos resolveriam?\n",
           f"Um modelo juiz ({quem}) comparou os passos do agente com o que foi feito de verdade.\n",
           f"- compatível: {juiz.get('compativel', 0)} ({porcentagem(juiz.get('compativel', 0), julgados)})",
           f"- parcial: {juiz.get('parcial', 0)} ({porcentagem(juiz.get('parcial', 0), julgados)})",
           f"- diferente: {juiz.get('diferente', 0)} ({porcentagem(juiz.get('diferente', 0), julgados)})",
           f"- sem resolução escrita no chamado (não dá para julgar): {juiz.get('sem_registro', 0)}"]

    md += ["\n## Custo\n",
           f"- {sum(l['chamadas_ao_modelo'] for l in ok) / max(n, 1):.1f} chamadas ao modelo por chamado",
           f"- {sum(l['segundos'] for l in ok) / max(n, 1):.1f} s por chamado"]
    usados = Counter(l.get("modelo", "") for l in ok if l.get("modelo"))
    if len(usados) > 1:
        md += ["- modelos que responderam: " + ", ".join(f"`{m}` ({q})" for m, q in usados.most_common())]

    divergentes = [l for l in ok if l["previsto"]["prioridade"] != l["real"]["prioridade"]]
    if divergentes:
        md += ["\n## Prioridades diferentes (vale revisar quem está certo)\n",
               "| chamado | você | agente | motivo do agente |", "|---|---|---|---|"]
        md += [f"| {l['id']} {cortar(l['titulo'], 40)} | {l['real']['prioridade']} | {l['previsto']['prioridade']} | "
               f"{cortar(l['motivo_prioridade'], 120)} |" for l in divergentes]
    if erros:
        md += ["\n## Erros\n"] + [f"- {e['id']}: {e['erro']}" for e in erros]
    return "\n".join(md) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Avalia o agente nos chamados mais recentes da base.")
    ap.add_argument("--n", type=int, default=40, help="quantos chamados recentes avaliar")
    ap.add_argument("--dados", default=DADOS_PADRAO)
    ap.add_argument("--provedor", help="openrouter ou gemini")
    ap.add_argument("--modelo", help="nome do modelo no provedor escolhido; para avaliar, prefira um modelo fixo")
    ap.add_argument("--juiz", help="modelo que julga os passos; use o mesmo em todas as avaliações para comparar modelos")
    ap.add_argument("--saida", default="avaliacao")
    ap.add_argument("--sem-juiz", action="store_true", help="não compara os passos com a resolução real")
    ap.add_argument("--pausa", type=float, default=4, help="segundos entre chamados, para respeitar o limite gratuito")
    ap.add_argument("--gabarito", help="CSV revisado à mão (id + categoria/subcategoria/tipo/prioridade) que substitui os rótulos da base")
    ap.add_argument("--gerar-gabarito", metavar="ARQUIVO", help="gera o CSV dos chamados de teste para você revisar e sai")
    args = ap.parse_args()

    base = Base(args.dados)
    teste = [c for c in base.chamados if c["status"] != "cancelado" and c["data"]][-args.n:]

    if args.gerar_gabarito:
        with open(args.gerar_gabarito, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "titulo", "descricao"] + CAMPOS)
            for c in teste:
                w.writerow([c["id"], c["titulo"], cortar(c["descricao"], 200)] + [c[k] for k in CAMPOS])
        print(f"Gabarito gerado em {args.gerar_gabarito}: revise as colunas {', '.join(CAMPOS)} e rode com --gabarito.")
        return

    if args.gabarito:
        for linha in csv.DictReader(open(args.gabarito, encoding="utf-8")):
            if linha.get("id") in base.por_id:
                for campo in CAMPOS:
                    if linha.get(campo) is not None:
                        base.por_id[linha["id"]][campo] = linha[campo].strip()

    provedor = criar_provedor(args.provedor, args.modelo)
    if provedor.modelo in ("openrouter/free", "openrouter/auto"):
        print(f"Aviso: '{provedor.modelo}' escolhe um modelo diferente a cada pedido. "
              "Para uma avaliação comparável, fixe um modelo com --modelo.", file=sys.stderr)
    juiz = criar_provedor(args.provedor, args.juiz) if args.juiz else provedor
    if not args.juiz and not args.sem_juiz:
        print("Aviso: sem --juiz, o próprio modelo avaliado julga os passos. "
              "Para comparar modelos, use o mesmo --juiz em todas as avaliações.", file=sys.stderr)

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    arquivo = saida / "resultados.jsonl"
    feitos = {}
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            item = json.loads(linha)
            if "erro" not in item:
                feitos[item["id"]] = item

    for i, original in enumerate(teste, 1):
        if original["id"] in feitos:
            continue
        print(f"[{i}/{len(teste)}] {original['id']} {cortar(original['titulo'], 50)}", flush=True)
        try:
            item = avaliar_um(base, original, provedor, juiz, not args.sem_juiz)
        except Exception as erro:
            item = {"id": original["id"], "erro": f"{type(erro).__name__}: {cortar(str(erro), 200)}"}
            print(f"  erro: {item['erro']}", file=sys.stderr)
        with arquivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        if "erro" not in item:
            feitos[item["id"]] = item
        time.sleep(args.pausa)

    ordem = [c["id"] for c in teste]
    linhas = [feitos[i] for i in ordem if i in feitos]
    erros = []
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        item = json.loads(linha)
        if "erro" in item and item["id"] not in feitos:
            erros.append(item)

    (saida / "relatorio.md").write_text(
        relatorio(linhas, erros, base, teste, f"{provedor.nome}: {provedor.modelo}", juiz.modelo), encoding="utf-8")
    with (saida / "resultados.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "titulo"] + [f"{c}_real" for c in CAMPOS] + [f"{c}_agente" for c in CAMPOS]
                   + ["recorrencia", "procedimento_agente", "procedimento_gabarito", "fonte_dos_passos", "juiz", "motivo_juiz"])
        for l in linhas:
            w.writerow([l["id"], l["titulo"]] + [l["real"][c] for c in CAMPOS] + [l["previsto"][c] for c in CAMPOS]
                       + [l["recorrencia"], l["procedimento_previsto"], " ".join(l["procedimento_gabarito"]),
                          l["fonte_dos_passos"], l["juiz"]["veredito"], l["juiz"]["motivo"]])
    print(f"\nRelatório em {saida / 'relatorio.md'}")


if __name__ == "__main__":
    main()
