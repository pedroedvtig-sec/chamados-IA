import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from base import Base, Ferramentas
from esquemas import Triagem
from modelos import ErroProvedor, criar_provedor
from triagem import DADOS_EXEMPLO, triar


def main():
    ap = argparse.ArgumentParser(description="Grava triagens reais dos chamados de exemplo para o modo demonstração da API.")
    ap.add_argument("--modelo", help="modelo na OpenRouter (padrão: OPENROUTER_MODEL)")
    ap.add_argument("--saida", default=str(DADOS_EXEMPLO / "gravacoes_demo.json"))
    args = ap.parse_args()

    try:
        provedor = criar_provedor("openrouter", args.modelo)
    except ErroProvedor as erro:
        sys.exit(str(erro))
    base = Base(DADOS_EXEMPLO)
    chamados = json.loads((DADOS_EXEMPLO / "chamados_demo.json").read_text(encoding="utf-8"))
    gravacoes = []
    for i, chamado in enumerate(chamados, 1):
        print(f"[{i}/{len(chamados)}] {chamado['titulo']}", flush=True)
        try:
            resultado = triar(chamado, Ferramentas(base, corte=datetime.now(timezone.utc)), provedor)
            Triagem.model_validate(resultado)
        except Exception as erro:
            sys.exit(f"falhou em '{chamado['titulo']}': {erro}")
        gravacoes.append({"chamado": chamado, "resultado": resultado,
                          "gravado_em": datetime.now(timezone.utc).date().isoformat()})
    Path(args.saida).write_text(json.dumps(gravacoes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(gravacoes)} triagens gravadas em {args.saida} com {provedor.modelos_usados[-1] if provedor.modelos_usados else provedor.modelo}")


if __name__ == "__main__":
    main()
