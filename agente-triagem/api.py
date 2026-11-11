import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from armazenamento import criar_armazenamento
from base import RE_MAQUINA, Base, Ferramentas
from demo import Demonstracao
from esquemas import ListaTriagens, PedidoTriagem, RespostaTriagem, Saude, Triagem
from modelos import ErroProvedor, PrazoEsgotado, criar_provedor
from triagem import DADOS_EXEMPLO, DADOS_PADRAO, triar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("triagem")
estado = {}


def modo_atual():
    if os.environ.get("TRIAGEM_MODO") == "demonstracao":
        return "demonstracao"
    return "real" if os.environ.get("OPENROUTER_API_KEY") else "demonstracao"


@asynccontextmanager
async def ciclo_de_vida(app):
    estado["base"] = Base(DADOS_PADRAO)
    estado["demo"] = Demonstracao(os.environ.get("GRAVACOES_DEMO", DADOS_EXEMPLO / "gravacoes_demo.json"))
    estado["armazenamento"] = criar_armazenamento(os.environ.get("DATABASE_URL"))
    log.info("modo %s, banco %s, %d chamados na base", modo_atual(), estado["armazenamento"].nome,
             len(estado["base"].chamados))
    yield
    estado.clear()


app = FastAPI(
    title="Agente de triagem de chamados",
    description="Recebe um chamado de suporte de TI e devolve categoria, tipo, prioridade com motivo, recorrência, "
                "procedimento e passos sugeridos. Sem OPENROUTER_API_KEY, responde em modo demonstração com "
                "triagens reais gravadas antes.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)


def conferir_classificacao(triagem, base):
    avisos = []
    if base.categorias and triagem.categoria not in base.categorias:
        avisos.append(f"categoria '{triagem.categoria}' não existe na base")
    elif triagem.subcategoria and triagem.subcategoria not in base.subs_por_categoria.get(triagem.categoria, []):
        avisos.append(f"subcategoria '{triagem.subcategoria}' não pertence a '{triagem.categoria}', removida")
        triagem.subcategoria = ""
    return avisos


def triagem_real(chamado):
    prazo = float(os.environ.get("TRIAGEM_PRAZO_SEGUNDOS", "90"))
    try:
        provedor = criar_provedor("openrouter", tentativas=3, prazo=prazo)
        return triar(chamado, Ferramentas(estado["base"], corte=datetime.now(timezone.utc)), provedor)
    except ErroProvedor as erro:
        raise HTTPException(erro.status, str(erro)) from None
    except PrazoEsgotado as erro:
        raise HTTPException(504, f"{erro} ({prazo:.0f} s)") from None
    except RuntimeError as erro:
        log.warning("falha do modelo: %s", erro)
        raise HTTPException(502, f"o modelo não entregou uma triagem válida: {erro}") from None


def para_resposta(linha):
    return RespostaTriagem(**linha)


@app.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/docs")


@app.get("/saude", response_model=Saude, tags=["sistema"])
def saude():
    return Saude(status="ok", modo=modo_atual(), banco=estado["armazenamento"].nome,
                 chamados_na_base=len(estado["base"].chamados), triagens_gravadas_para_demo=len(estado["demo"]))


@app.post("/triagem", response_model=RespostaTriagem, status_code=201, tags=["triagem"],
          responses={422: {"description": "pedido inválido"}, 502: {"description": "o modelo falhou ou saiu do contrato"},
                     503: {"description": "modo demonstração sem triagens gravadas"},
                     504: {"description": "o modelo passou do prazo"}})
def criar_triagem(pedido: PedidoTriagem):
    chamado = pedido.model_dump()
    if not chamado["maquina"]:
        texto = f'{chamado["titulo"]} {chamado["descricao"]}'
        chamado["maquina"] = ", ".join(sorted({m.upper() for m in RE_MAQUINA.findall(texto)}))

    modo, gravado = modo_atual(), None
    if modo == "real":
        bruto = triagem_real(chamado)
    else:
        try:
            bruto, gravado = estado["demo"].triar(chamado)
        except LookupError as erro:
            raise HTTPException(503, f"{erro}; rode gravar_demo.py com uma chave da OpenRouter") from None

    try:
        triagem = Triagem.model_validate(bruto)
    except ValidationError as erro:
        problemas = [{"campo": ".".join(map(str, e["loc"])), "erro": e["msg"]} for e in erro.errors(include_input=False)]
        log.warning("triagem fora do contrato: %s", problemas)
        raise HTTPException(502, {"mensagem": "a resposta do modelo saiu do contrato", "problemas": problemas}) from None
    triagem.avisos += conferir_classificacao(triagem, estado["base"])

    linha = estado["armazenamento"].salvar(modo, triagem.modelo, chamado, triagem.model_dump(), gravado)
    log.info("triagem %s: %s/%s/%s em %.1fs (%s)", linha["id"], triagem.categoria, triagem.tipo,
             triagem.prioridade, triagem.segundos, modo)
    return para_resposta(linha)


@app.get("/triagens", response_model=ListaTriagens, tags=["triagem"])
def listar_triagens(limite: int = Query(20, ge=1, le=100), deslocamento: int = Query(0, ge=0)):
    total, linhas = estado["armazenamento"].listar(limite, deslocamento)
    return ListaTriagens(total=total, itens=[para_resposta(l) for l in linhas])


@app.get("/triagens/{id_triagem}", response_model=RespostaTriagem, tags=["triagem"],
         responses={404: {"description": "triagem não encontrada"}})
def obter_triagem(id_triagem: int):
    linha = estado["armazenamento"].obter(id_triagem)
    if not linha:
        raise HTTPException(404, "triagem não encontrada")
    return para_resposta(linha)
