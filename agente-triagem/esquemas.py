from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modelos import sem_acento

EXEMPLO = {
    "titulo": "VPN não conecta",
    "descricao": "Usuário 3 sem VPN de casa de novo, aparece erro 809.",
    "usuario": "Usuário 3",
    "departamento": "Engenharia",
    "maquina": "PC-000087",
}


class PedidoTriagem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, json_schema_extra={"examples": [EXEMPLO]})

    titulo: str = Field(min_length=3, max_length=200)
    descricao: str = Field(min_length=3, max_length=4000)
    usuario: str = Field(default="", max_length=100, description="rótulo anonimizado, ex.: 'Usuário 3'")
    departamento: str = Field(default="", max_length=100)
    maquina: str = Field(default="", max_length=200, description="tag da máquina, ex.: PC-000087")


class FonteWeb(BaseModel):
    titulo: str = ""
    url: str = ""


class FerramentaUsada(BaseModel):
    funcao: str
    argumentos: dict = {}


class Triagem(BaseModel):
    categoria: str
    subcategoria: str = ""
    tipo: Literal["incidente", "solicitacao", "tarefa"]
    prioridade: Literal["baixa", "média", "alta", "crítica"]
    motivo_prioridade: str
    recorrencia: Literal["primeira_vez", "recorrente"]
    chamados_relacionados: list[str] = []
    motivo_recorrencia: str
    procedimento_id: str = ""
    procedimento_titulo: str = ""
    aplicabilidade: Literal["direta", "parcial", "nenhuma"]
    passos_sugeridos: list[str] = Field(min_length=1)
    fonte_dos_passos: Literal["procedimento", "chamados_anteriores", "pesquisa_web", "conhecimento_geral"]
    fontes_web: list[FonteWeb] = []
    resposta_usuario: str = Field(min_length=1)
    confianca: Literal["baixa", "media", "alta"]
    avisos: list[str] = []
    ferramentas_usadas: list[FerramentaUsada] = []
    chamadas_ao_modelo: int = 0
    segundos: float = 0
    modelo: str = ""

    @field_validator("tipo", "recorrencia", "aplicabilidade", "fonte_dos_passos", "confianca", mode="before")
    @classmethod
    def sem_acento_e_minusculo(cls, valor):
        return sem_acento(valor)

    @field_validator("subcategoria", "procedimento_id", "procedimento_titulo", mode="before")
    @classmethod
    def vazio_quando_nulo(cls, valor):
        return valor or ""


class RespostaTriagem(BaseModel):
    id: int
    criado_em: datetime
    modo: Literal["real", "demonstracao"]
    chamado: PedidoTriagem
    triagem: Triagem
    chamado_gravado: str | None = Field(
        default=None, description="no modo demonstração, o chamado de exemplo cuja triagem gravada foi devolvida")


class ListaTriagens(BaseModel):
    total: int
    itens: list[RespostaTriagem]


class Saude(BaseModel):
    status: Literal["ok"]
    modo: Literal["real", "demonstracao"]
    banco: Literal["postgres", "memoria"]
    chamados_na_base: int
    triagens_gravadas_para_demo: int
