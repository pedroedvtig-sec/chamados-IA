import argparse

from base import Base, Ferramentas
from triagem import DADOS_PADRAO


def procedimentos_escondidos(base, teste):
    escondidos = {}
    for c in teste:
        ferramentas = Ferramentas(base, corte=c["data"], excluir={c["id"]})
        for p in base.procedimentos:
            if not ferramentas.procedimento_visivel(p):
                escondidos.setdefault(p["id"], []).append(c["id"])
    return escondidos


def main():
    ap = argparse.ArgumentParser(description="Mostra quais procedimentos ainda não existiam na data de cada chamado de teste.")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--dados", default=DADOS_PADRAO)
    args = ap.parse_args()

    base = Base(args.dados)
    teste = [c for c in base.chamados if c["status"] != "cancelado" and c["data"]][-args.n:]
    sem_data = [p["id"] for p in base.procedimentos if not p["data"] and not p["escrito_a_partir_de"]]
    escondidos = procedimentos_escondidos(base, teste)

    print(f"{len(teste)} chamados de teste, {len(base.procedimentos)} procedimentos")
    if escondidos:
        print(f"{len(escondidos)} procedimentos posteriores a pelo menos um chamado de teste:")
        for pid, chamados in sorted(escondidos.items()):
            print(f"  {pid}: {len(chamados)} chamados ({', '.join(chamados[:5])}{'…' if len(chamados) > 5 else ''})")
    else:
        print("Nenhum procedimento posterior aos chamados de teste.")
    if sem_data:
        print(f"{len(sem_data)} procedimentos sem data nem origem, tratados como anteriores: {', '.join(sem_data)}")


if __name__ == "__main__":
    main()
