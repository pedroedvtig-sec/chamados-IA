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


def test_com_chave_configurada_exige_o_cabecalho(cliente, monkeypatch):
    monkeypatch.setenv("TRIAGEM_CHAVE_API", "segredo-de-teste")
    assert cliente.post("/triagem", json=PEDIDO).status_code == 401
    assert cliente.get("/triagens").status_code == 401
    assert cliente.get("/triagens/1").status_code == 401
    assert cliente.post("/triagem", json=PEDIDO, headers={"X-API-Key": "errada"}).status_code == 401
    assert cliente.post("/triagem", json=PEDIDO, headers={"X-API-Key": "segredo-de-teste"}).status_code == 201
    assert cliente.get("/triagens", headers={"X-API-Key": "segredo-de-teste"}).json()["total"] == 1
    assert cliente.get("/saude").status_code == 200


def test_limite_por_minuto_no_modo_real(cliente, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "teste")
    monkeypatch.setenv("TRIAGEM_LIMITE_POR_MINUTO", "2")
    monkeypatch.setattr(api, "limitador", api.Limitador())
    monkeypatch.setattr(api, "triar", lambda *a, **k: dict(TRIAGEM_VALIDA))
    codigos = [cliente.post("/triagem", json=PEDIDO).status_code for _ in range(3)]
    assert codigos == [201, 201, 429]


def test_erro_do_provedor_nao_vaza_detalhe(cliente, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "teste")

    def falhar(*args, **kwargs):
        raise ErroProvedor('Sem créditos. Detalhe: {"user_id": "u-123", "conta": "x"}', 402)

    monkeypatch.setattr(api, "triar", falhar)
    r = cliente.post("/triagem", json=PEDIDO)
    assert r.status_code == 402
    assert "u-123" not in r.text


def test_fonte_web_so_aceita_http(cliente, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "teste")
    fontes = [{"titulo": "ok", "url": "https://exemplo.com/vpn"}, {"titulo": "ruim", "url": "javascript:alert(1)"}]
    monkeypatch.setattr(api, "triar", lambda *a, **k: {**TRIAGEM_VALIDA, "fontes_web": fontes})
    urls = [f["url"] for f in cliente.post("/triagem", json=PEDIDO).json()["triagem"]["fontes_web"]]
    assert urls == ["https://exemplo.com/vpn", ""]


def test_consulta_web_sai_sem_dados_internos():
    from base import consulta_publica
    consulta = consulta_publica("erro 809 VPN Usuário 3 PC-000087 EX-0007 joao.silva@empresa.com 12345678")
    assert consulta == "erro 809 VPN"


def test_pesquisa_web_pode_ser_desligada(monkeypatch):
    from base import Base, Ferramentas
    from triagem import DADOS_EXEMPLO
    monkeypatch.setenv("TRIAGEM_PESQUISA_WEB", "0")
    assert "desligada" in Ferramentas(Base(DADOS_EXEMPLO)).pesquisar_web("erro 809")["erro"]


def test_argumento_estranho_do_modelo_nao_derruba_a_triagem():
    from base import Base, Ferramentas
    from triagem import DADOS_EXEMPLO, triar

    class Provedor(ProvedorRoteirizado):
        def agente(self, sistema, pedido, declaracoes, executar, final, max_rodadas):
            saida = executar("buscar_procedimentos", {"consulta": ["lista", "no lugar de texto"]})
            assert "erro" in saida
            return dict(TRIAGEM_VALIDA), [], 1

    triar(PEDIDO, Ferramentas(Base(DADOS_EXEMPLO)), Provedor())


def test_procedimento_escrito_a_partir_do_chamado_nao_aparece_na_triagem_dele():
    from base import Base, Ferramentas
    from triagem import DADOS_EXEMPLO
    base = Base(DADOS_EXEMPLO)
    origem = base.por_id["EX-0004"]
    na_epoca = Ferramentas(base, corte=origem["data"], excluir={"EX-0004"})
    hoje = Ferramentas(base)
    consulta = "credenciais salvas Outlook Office"
    assert "N1-01" not in [r["id"] for r in na_epoca.buscar_procedimentos(consulta)["resultados"]]
    assert "N1-01" in [r["id"] for r in hoje.buscar_procedimentos(consulta)["resultados"]]


def test_procedimento_criado_depois_do_corte_fica_escondido():
    from datetime import timedelta
    from base import Base, Ferramentas
    from triagem import DADOS_EXEMPLO
    base = Base(DADOS_EXEMPLO)
    proc = base.procs_por_id["PROC-01"]
    corte = base.por_id["EX-0002"]["data"]
    proc["data"] = corte + timedelta(days=1)
    assert not Ferramentas(base, corte=corte).procedimento_visivel(proc)
    proc["data"] = corte - timedelta(days=1)
    assert Ferramentas(base, corte=corte).procedimento_visivel(proc)
