import argparse
import re
import sys
from pathlib import Path

INICIO, FIM = "<!-- resultados:inicio -->", "<!-- resultados:fim -->"
CAMPOS = ["categoria", "subcategoria", "tipo", "prioridade"]
NOMES = {
    "deepseek/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "anthropic/claude-haiku-5.5": "Claude Haiku 5.5",
    "openai/gpt-6-luna": "GPT-6 Luna",
}


def ler_relatorio(pasta):
    arquivo = Path(pasta) / "relatorio.md"
    if not arquivo.exists():
        sys.exit(f"não achei {arquivo}: a avaliação dessa pasta terminou?")
    texto = arquivo.read_text(encoding="utf-8")
    r = {"pasta": Path(pasta).name}

    m = re.search(r"Modelo: `(?:\w+: )?([^`]+)` · (\d+) chamados avaliados \(os (\d+) mais recentes\)(?: · (\d+) com erro)?", texto)
    if not m:
        sys.exit(f"{arquivo}: não reconheci a linha 'Modelo: ...'")
    r["modelo"] = m.group(1)
    r["avaliados"], r["total"] = int(m.group(2)), int(m.group(3))

    for campo in CAMPOS:
        m = re.search(rf"^\| {campo} \| (\d+)% \((\d+)/(\d+)\) \| (\d+)%", texto, re.M)
        if m:
            r[campo] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            r[f"base_{campo}"] = int(m.group(4))

    m = re.search(r"^- compatível: (\d+) \((\d+)%\)", texto, re.M)
    if m:
        r["compativel"] = (int(m.group(2)), int(m.group(1)))
    m = re.search(r"^- sem resolução escrita.*?: (\d+)", texto, re.M)
    r["sem_resolucao"] = int(m.group(1)) if m else None
    m = re.search(r"^- ([\d.]+) chamadas ao modelo por chamado", texto, re.M)
    r["chamadas"] = float(m.group(1)) if m else None
    m = re.search(r"^- ([\d.]+) s por chamado", texto, re.M)
    r["segundos"] = float(m.group(1)) if m else None
    return r


def br(numero, casas=1):
    return f"{numero:.{casas}f}".replace(".", ",")


def montar_tabela(relatorios, custos):
    cab = ["", *[NOMES.get(r["modelo"], r["modelo"]) for r in relatorios], "linha de base"]
    linhas = [cab, ["---"] * len(cab)]

    linhas.append(["chamados concluídos", *[f'{r["avaliados"]}/{r["total"]}' for r in relatorios], "—"])
    for campo in CAMPOS:
        base = next((r.get(f"base_{campo}") for r in relatorios if r.get(f"base_{campo}") is not None), None)
        valores = []
        for r in relatorios:
            if campo in r:
                pct, ok, n = r[campo]
                valores.append(f"{pct}% ({ok}/{n})")
            else:
                valores.append("—")
        linhas.append([campo, *valores, f"{base}%" if base is not None else "—"])
    linhas.append(["passos compatíveis (juiz)",
                   *[f'{r["compativel"][0]}% ({r["compativel"][1]})' if "compativel" in r else "—" for r in relatorios], "—"])
    linhas.append(["chamadas ao modelo por chamado",
                   *[br(r["chamadas"]) if r["chamadas"] is not None else "—" for r in relatorios], "—"])
    linhas.append(["segundos por chamado",
                   *[br(r["segundos"]) if r["segundos"] is not None else "—" for r in relatorios], "—"])
    linhas.append(["custo por chamado",
                   *[custos.get(r["pasta"].removeprefix("avaliacao-"), "✍️") for r in relatorios], "—"])

    tabela = "\n".join("| " + " | ".join(l) + " |" for l in linhas)
    sem = [r["sem_resolucao"] for r in relatorios if r["sem_resolucao"] is not None]
    nota = (f"\n\nOs passos só são julgados nos chamados que têm a resolução escrita"
            f"{f' ({max(sem)} não tinham)' if sem else ''}. A linha de base é chutar sempre a resposta mais comum"
            " nos chamados anteriores. Juiz: `google/gemini-3.5-flash`, o mesmo para todos os modelos."
            " A subcategoria só é conferida nos chamados em que o gabarito tem subcategoria."
            " O custo é aproximado, lido do painel de atividade da OpenRouter.")
    return tabela + nota


def main():
    p = argparse.ArgumentParser(description="Preenche a tabela de resultados do README a partir dos relatorio.md da avaliação.")
    p.add_argument("pastas", nargs="+", help="pastas de avaliação, ex.: avaliacao-deepseek avaliacao-haiku")
    p.add_argument("--custo", action="append", default=[], help="nome=dólares por chamado, ex.: deepseek=0.0004")
    p.add_argument("--readme", default="README.md")
    a = p.parse_args()

    custos = {}
    for item in a.custo:
        nome, _, valor = item.partition("=")
        try:
            custos[nome.strip()] = f"US$ {float(valor):.4f}".replace(".", ",")
        except ValueError:
            sys.exit(f"--custo inválido: {item} (use nome=0.0004)")

    relatorios = [ler_relatorio(pasta) for pasta in a.pastas]
    tabela = montar_tabela(relatorios, custos)

    readme = Path(a.readme)
    texto = readme.read_text(encoding="utf-8")
    if texto.count(INICIO) != 1 or texto.count(FIM) != 1:
        sys.exit(f"{readme}: precisa ter os marcadores {INICIO} e {FIM}, uma vez cada")
    antes, resto = texto.split(INICIO)
    _, depois = resto.split(FIM)
    readme.write_text(f"{antes}{INICIO}\n{tabela}\n{FIM}{depois}", encoding="utf-8")
    print(tabela)
    print(f"\nok: tabela gravada em {readme}")


if __name__ == "__main__":
    main()
