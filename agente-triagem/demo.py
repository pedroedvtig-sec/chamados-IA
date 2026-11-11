import json
from pathlib import Path

from base import termos


class Demonstracao:
    def __init__(self, arquivo):
        arquivo = Path(arquivo)
        self.gravacoes = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
        self.termos = [set(termos(f'{g["chamado"]["titulo"]} {g["chamado"]["descricao"]}')) for g in self.gravacoes]

    def __len__(self):
        return len(self.gravacoes)

    def triar(self, chamado):
        if not self.gravacoes:
            raise LookupError("não há triagens gravadas para o modo demonstração")
        pedido = set(termos(f'{chamado.get("titulo", "")} {chamado.get("descricao", "")}'))
        notas = [len(pedido & t) / (len(pedido | t) or 1) for t in self.termos]
        escolhida = self.gravacoes[max(range(len(notas)), key=notas.__getitem__)]
        return dict(escolhida["resultado"]), escolhida["chamado"]["titulo"]
