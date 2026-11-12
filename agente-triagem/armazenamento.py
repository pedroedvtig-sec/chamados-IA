import threading
import time
from collections import deque
from datetime import datetime, timezone

TABELA = """
create table if not exists triagens (
    id bigserial primary key,
    criado_em timestamptz not null default now(),
    modo text not null check (modo in ('real', 'demonstracao')),
    modelo text not null default '',
    chamado jsonb not null,
    triagem jsonb not null,
    chamado_gravado text
);
create index if not exists triagens_criado_em on triagens (criado_em desc);
"""


class Postgres:
    nome = "postgres"

    def __init__(self, url, tentativas=15):
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        self.psycopg, self.dict_row, self.Jsonb = psycopg, dict_row, Jsonb
        self.url = url
        for tentativa in range(tentativas):
            try:
                with self._conectar() as conexao:
                    conexao.execute(TABELA)
                return
            except psycopg.OperationalError:
                if tentativa == tentativas - 1:
                    raise
                time.sleep(2)

    def _conectar(self):
        return self.psycopg.connect(self.url, row_factory=self.dict_row, connect_timeout=5)

    def salvar(self, modo, modelo, chamado, triagem, chamado_gravado=None):
        with self._conectar() as conexao:
            return conexao.execute(
                "insert into triagens (modo, modelo, chamado, triagem, chamado_gravado) values (%s, %s, %s, %s, %s) "
                "returning id, criado_em, modo, chamado, triagem, chamado_gravado",
                (modo, modelo, self.Jsonb(chamado), self.Jsonb(triagem), chamado_gravado)).fetchone()

    def listar(self, limite, deslocamento):
        with self._conectar() as conexao:
            total = conexao.execute("select count(*) as n from triagens").fetchone()["n"]
            linhas = conexao.execute(
                "select id, criado_em, modo, chamado, triagem, chamado_gravado from triagens "
                "order by id desc limit %s offset %s", (limite, deslocamento)).fetchall()
        return total, linhas

    def obter(self, id_triagem):
        with self._conectar() as conexao:
            return conexao.execute(
                "select id, criado_em, modo, chamado, triagem, chamado_gravado from triagens where id = %s",
                (id_triagem,)).fetchone()


class Memoria:
    nome = "memoria"

    def __init__(self, maximo=1000):
        self.linhas = deque(maxlen=maximo)
        self.proximo = 1
        self.trava = threading.Lock()

    def salvar(self, modo, modelo, chamado, triagem, chamado_gravado=None):
        with self.trava:
            linha = {"id": self.proximo, "criado_em": datetime.now(timezone.utc), "modo": modo,
                     "chamado": chamado, "triagem": triagem, "chamado_gravado": chamado_gravado}
            self.proximo += 1
            self.linhas.append(linha)
            return linha

    def listar(self, limite, deslocamento):
        with self.trava:
            ordem = list(reversed(self.linhas))
        return len(ordem), ordem[deslocamento:deslocamento + limite]

    def obter(self, id_triagem):
        with self.trava:
            return next((l for l in self.linhas if l["id"] == id_triagem), None)


def criar_armazenamento(url):
    return Postgres(url) if url else Memoria()
