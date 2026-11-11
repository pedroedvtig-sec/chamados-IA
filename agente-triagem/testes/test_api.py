import json

import pytest
from fastapi.testclient import TestClient

import api
from modelos import ErroProvedor, PrazoEsgotado
from triagem import conferir_ids

TRIAGEM_VALIDA = {
    "categoria": "Rede",
    "subcategoria": "VPN",
    "tipo": "incidente",
    "prioridade": "média",
    "motivo_prioridade": "uma pessoa atrapalhada, com contorno",
    "recorrencia": "recorrente",
    "chamados_relacionados": ["EX-0001", "EX-0007"],
    "motivo_recorrencia": "mesmo erro 809 do mesmo usuário",
    "procedimento_id": "PROC-03",
    "procedimento_titulo": "Configurar VPN com o cliente SSL",
    "aplicabilidade": "direta",
    "passos_sugeridos": ["Instalar o cliente SSL", "Testar o acesso"],
    "fonte_dos_passos": "procedimento",
    "resposta_usuario": "Vamos reinstalar o programa da VPN no seu notebook.",
    "confianca": "alta",
    "avisos": [],
    "ferramentas_usadas": [{"funcao": "historico", "argumentos": {"usuario": "Usuário 3"}}],
    "chamadas_ao_modelo": 3,
    "segundos": 8.2,
    "modelo": "modelo/teste",
}

PEDIDO = {"titulo": "VPN não conecta", "descricao": "Erro 809 de novo em casa", "usuario": "Usuário 3", "maquina": "PC-000087"}


@pytest.fixture
def gravacoes(tmp_path):
    arquivo = tmp_path / "gravacoes.json"
    arquivo.write_text(json.dumps([
        {"chamado": {"titulo": "VPN não conecta", "descricao": "erro 809 em casa"}, "resultado": TRIAGEM_VALIDA},
        {"chamado": {"titulo": "Mouse parou", "descricao": "mouse sem fio não funciona"},
         "resultado": {**TRIAGEM_VALIDA, "categoria": "Hardware", "subcategoria": "Periférico"}},
    ], ensure_ascii=False), encoding="utf-8")
    return arquivo


@pytest.fixture
def cliente(monkeypatch, gravacoes):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TRIAGEM_MODO", raising=False)
    monkeypatch.setenv("GRAVACOES_DEMO", str(gravacoes))
    with TestClient(api.app) as c:
        yield c


def test_saude_sem_chave_fica_em_demonstracao(cliente):
    r = cliente.get("/saude").json()
    assert r["modo"] == "demonstracao"
    assert r["banco"] == "memoria"
    assert r["chamados_na_base"] == 15
    assert r["triagens_gravadas_para_demo"] == 2


def test_demonstracao_escolhe_a_gravacao_mais_parecida_e_salva(cliente):
    r = cliente.post("/triagem", json={"titulo": "Mouse com defeito", "descricao": "o mouse sem fio parou"})
    assert r.status_code == 201
    corpo = r.json()
    assert corpo["modo"] == "demonstracao"
    assert corpo["chamado_gravado"] == "Mouse parou"
    assert corpo["triagem"]["categoria"] == "Hardware"
    lista = cliente.get("/triagens").json()
    assert lista["total"] == 1
    assert cliente.get(f"/triagens/{corpo['id']}").json()["id"] == corpo["id"]


def test_extrai_maquina_do_texto(cliente):
    r = cliente.post("/triagem", json={"titulo": "VPN não conecta", "descricao": "no pc-000087 dá erro 809"})
    assert r.json()["chamado"]["maquina"] == "PC-000087"


def test_pedido_invalido_da_422(cliente):
    assert cliente.post("/triagem", json={"titulo": "x"}).status_code == 422
    assert cliente.get("/triagens?limite=500").status_code == 422


def test_triagem_inexistente_da_404(cliente):
    assert cliente.get("/triagens/999").status_code == 404


def test_demonstracao_sem_gravacoes_da_503(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("GRAVACOES_DEMO", str(tmp_path / "nao_existe.json"))
    with TestClient(api.app) as c:
        r = c.post("/triagem", json=PEDIDO)
    assert r.status_code == 503
    assert "gravar_demo.py" in r.json()["detail"]


@pytest.mark.parametrize("erro, status", [
    (ErroProvedor("sem créditos", 402), 402),
    (ErroProvedor("chave recusada", 401), 401),
    (PrazoEsgotado("o prazo da triagem acabou"), 504),
    (RuntimeError("o agente não finalizou em 8 rodadas"), 502),
])
def test_falhas_do_modelo_viram_http(cliente, monkeypatch, erro, status):
    monkeypatch.setenv("OPENROUTER_API_KEY", "teste")

    def falhar(*args, **kwargs):
        raise erro

    monkeypatch.setattr(api, "triar", falhar)
    r = cliente.post("/triagem", json=PEDIDO)
    assert r.status_code == status
    assert cliente.get("/triagens").json()["total"] == 0


def test_saida_fora_do_contrato_da_502_e_nao_salva(cliente, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "teste")
    monkeypatch.setattr(api, "triar", lambda *a, **k: {**TRIAGEM_VALIDA, "prioridade": "urgentíssima", "passos_sugeridos": []})
    r = cliente.post("/triagem", json=PEDIDO)
    assert r.status_code == 502
    campos = {p["campo"] for p in r.json()["detail"]["problemas"]}
    assert campos == {"prioridade", "passos_sugeridos"}
    assert cliente.get("/triagens").json()["total"] == 0


def test_acentos_do_modelo_sao_normalizados(cliente, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "teste")
    monkeypatch.setattr(api, "triar", lambda *a, **k: {**TRIAGEM_VALIDA, "confianca": "Média", "tipo": "Solicitação"})
    r = cliente.post("/triagem", json=PEDIDO).json()
    assert r["triagem"]["confianca"] == "media"
    assert r["triagem"]["tipo"] == "solicitacao"


def test_subcategoria_de_outra_categoria_vira_aviso(cliente, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "teste")
    monkeypatch.setattr(api, "triar", lambda *a, **k: {**TRIAGEM_VALIDA, "subcategoria": "Toner"})
    r = cliente.post("/triagem", json=PEDIDO).json()
    assert r["triagem"]["subcategoria"] == ""
    assert any("Toner" in a for a in r["triagem"]["avisos"])


def test_conferir_ids_remove_o_que_o_modelo_inventou():
    resultado = {**TRIAGEM_VALIDA, "chamados_relacionados": ["EX-0001", "EX-9999"], "procedimento_id": "PROC-77"}
    avisos = conferir_ids(resultado, {"EX-0001", "PROC-03"})
    assert resultado["chamados_relacionados"] == ["EX-0001"]
    assert resultado["procedimento_id"] == "" and resultado["aplicabilidade"] == "nenhuma"
    assert len(avisos) == 2


def test_recorrencia_sem_chamado_confirmado_e_rebaixada():
    resultado = {**TRIAGEM_VALIDA, "chamados_relacionados": ["EX-9999"]}
    conferir_ids(resultado, {"PROC-03"})
    assert resultado["recorrencia"] == "primeira_vez"


class ProvedorRoteirizado:
    nome = "roteiro"
    modelo = "roteiro/teste"
    modelos_usados = []

    def agente(self, sistema, pedido, declaracoes, executar, final, max_rodadas):
        executar("historico", {"usuario": "Usuário 3", "maquina": "PC-000087"})
        executar("buscar_procedimentos", {"consulta": "vpn erro 809"})
        return {**TRIAGEM_VALIDA, "chamados_relacionados": ["EX-0007", "EX-0420"]}, [{"funcao": "historico", "argumentos": {}}], 3


def test_triar_confere_ids_contra_o_que_as_ferramentas_devolveram():
    from base import Base, Ferramentas
    from triagem import DADOS_EXEMPLO, triar
    resultado = triar(PEDIDO, Ferramentas(Base(DADOS_EXEMPLO)), ProvedorRoteirizado())
    assert resultado["chamados_relacionados"] == ["EX-0007"]
    assert resultado["procedimento_id"] == "PROC-03"
    assert any("EX-0420" in a for a in resultado["avisos"])
