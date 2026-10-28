import csv
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(10**9)

PARADAS = set("""
a o e de da do das dos em no na nos nas um uma uns umas para pra pro pros por com sem que se ao aos as os
foi ele ela eles elas dele dela isso esse essa este esta mas mais muito ja nao sim tem ter estava vou fui
fiz preciso precisa precisei hoje ontem me meu minha seu sua lhe la ai ou entao quando como tambem depois
porque pq ta tava usuario usuaria chamado
""".split())


def normalizar(texto):
    sem = "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")
    return sem.lower()


def termos(texto):
    return [p[:6] for p in re.findall(r"[a-z0-9]{2,}", normalizar(texto)) if p not in PARADAS]


def data(texto):
    if not texto:
        return None
    texto = texto.strip().replace(" ", "T", 1)
    texto = re.sub(r"(\.\d+)?(\+00(:00)?|Z)$", "", texto)
    try:
        return datetime.fromisoformat(texto).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def json_ou(texto, padrao):
    try:
        return json.loads(texto) if texto else padrao
    except json.JSONDecodeError:
        return padrao


def cortar(texto, limite):
    texto = re.sub(r"\s+", " ", texto or "").strip()
    return texto if len(texto) <= limite else texto[:limite].rsplit(" ", 1)[0] + "…"


class BM25:
    def __init__(self, documentos, k1=1.4, b=0.75):
        self.docs = [Counter(termos(d)) for d in documentos]
        self.tamanhos = [sum(d.values()) for d in self.docs]
        self.media = (sum(self.tamanhos) / len(self.docs)) if self.docs else 0
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def buscar(self, consulta, k=5, filtro=None):
        q = termos(consulta)
        notas = []
        for i, doc in enumerate(self.docs):
            if filtro and not filtro(i):
                continue
            s = 0.0
            for t in q:
                if t in doc:
                    tf = doc[t]
                    s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.tamanhos[i] / self.media))
            if s > 0:
                notas.append((s, i))
        notas.sort(reverse=True)
        return notas[:k]


RE_MAQUINA = re.compile(r"\b(?:PC|ATV)-\d+\b", re.I)
RE_ROTULO = re.compile(r"\b(?:Usuário|Técnico) \d+\b")


class Base:
    def __init__(self, pasta):
        pasta = Path(pasta).expanduser()
        self.chamados = self._chamados(pasta / "tickets_rows.csv")
        self.procedimentos = self._procedimentos(pasta / "procedimentos_rows.csv", pasta / "procedimentos_n1.json")
        self.dossies = self._dossies(pasta / "dossies_rows.csv")
        self.por_id = {c["id"]: c for c in self.chamados}
        self.categorias = sorted({c["categoria"] for c in self.chamados if c["categoria"]})
        self.subcategorias = sorted({c["subcategoria"] for c in self.chamados if c["subcategoria"]})
        self.subs_por_categoria = {cat: sorted({c["subcategoria"] for c in self.chamados
                                                if c["categoria"] == cat and c["subcategoria"]})
                                   for cat in self.categorias}
        arquivo_glossario = pasta / "glossario.json"
        self.glossario = json.loads(arquivo_glossario.read_text(encoding="utf-8")) if arquivo_glossario.exists() else {}

        self.idx_chamados = BM25([f'{c["titulo"]} {c["titulo"]} {c["descricao"]} {c["resolucao"]}' for c in self.chamados])
        self.idx_procs = BM25([f'{p["titulo"]} {p["titulo"]} {p["titulo"]} {p["categoria"]} {" ".join(p["passos"])}'
                               for p in self.procedimentos])
        self.idx_dossies = BM25([f'{d["titulo"]} {d["texto"]}' for d in self.dossies])

    def termos_internos(self, texto):
        achados = {}
        for termo, explicacao in self.glossario.items():
            if not explicacao:
                continue
            if termo.isupper():
                casou = re.search(rf"(?<![A-Za-z]){re.escape(termo)}(?![A-Za-z])", texto or "")
            else:
                casou = re.search(rf"(?<![a-z0-9]){re.escape(normalizar(termo))}(?![a-z0-9])", normalizar(texto))
            if casou:
                achados[termo] = explicacao
        return achados

    @staticmethod
    def _chamados(arquivo):
        saida = []
        for r in csv.DictReader(arquivo.open(encoding="utf-8")):
            timeline = json_ou(r.get("timeline"), [])
            resolucao = " | ".join(e.get("texto", "") for e in timeline if isinstance(e, dict))
            texto_total = f'{r["titulo"]} {r["descricao"]} {resolucao}'
            saida.append({
                "id": r["id"],
                "titulo": r["titulo"],
                "descricao": r["descricao"] or "",
                "usuarios": RE_ROTULO.findall(r.get("usuario") or ""),
                "usuario_texto": r.get("usuario") or "",
                "departamento": r.get("departamento") or "",
                "categoria": r.get("categoria") or "",
                "subcategoria": r.get("subcategoria") or "",
                "tipo": r.get("tipo") or "",
                "prioridade": r.get("prioridade") or "",
                "status": r.get("status") or "",
                "data": data(r.get("data_criacao")),
                "resolucao": resolucao,
                "maquinas": sorted({m.upper() for m in RE_MAQUINA.findall(texto_total)}),
                "procedimentos": json_ou(r.get("procedimentos"), []),
            })
        saida.sort(key=lambda c: c["data"] or datetime.min.replace(tzinfo=timezone.utc))
        return saida

    @staticmethod
    def _procedimentos(arquivo, arquivo_n1):
        saida = []
        if arquivo.exists():
            for r in csv.DictReader(arquivo.open(encoding="utf-8")):
                passos = []
                for p in json_ou(r.get("passos"), []):
                    linha = p.get("texto", "")
                    if p.get("comando"):
                        linha += f' → {p["comando"]}'
                    if p.get("opcional"):
                        linha += " (opcional)"
                    passos.append(linha)
                execucoes = json_ou(r.get("execucoes"), [])
                saida.append({
                    "id": r["id"],
                    "titulo": r["titulo"],
                    "categoria": r.get("categoria") or "",
                    "passos": passos,
                    "origem": "base oficial",
                    "chamados_que_usaram": sorted({e.get("ticket") for e in execucoes if isinstance(e, dict) and e.get("ticket")}),
                })
        if arquivo_n1.exists():
            for p in json.loads(arquivo_n1.read_text(encoding="utf-8")):
                saida.append({
                    "id": p["id"],
                    "titulo": p["titulo"],
                    "categoria": p.get("categoria", ""),
                    "passos": p["passos"],
                    "origem": "rascunho N1 (revisar)" if p.get("revisar") else "base N1",
                    "chamados_que_usaram": p.get("origem", []),
                })
        return saida

    @staticmethod
    def _dossies(arquivo):
        saida = []
        if arquivo.exists():
            for r in csv.DictReader(arquivo.open(encoding="utf-8")):
                entradas = json_ou(r.get("entradas"), [])
                saida.append({
                    "id": r["id"],
                    "titulo": r["titulo"],
                    "chamados": json_ou(r.get("chamados"), []),
                    "texto": " | ".join(f'[{e.get("tag", "")}] {e.get("texto", "")}' for e in entradas if isinstance(e, dict)),
                    "data": data(r.get("criado_em")),
                })
        return saida


class Ferramentas:
    def __init__(self, base, corte=None, excluir=()):
        self.base = base
        self.corte = corte
        self.excluir = set(excluir)
        self.web = None

    def _visivel(self, chamado):
        if chamado["id"] in self.excluir:
            return False
        return not (self.corte and chamado["data"] and chamado["data"] >= self.corte)

    def buscar_procedimentos(self, consulta):
        achados = self.base.idx_procs.buscar(consulta, k=3)
        achados = [(s, i) for s, i in achados if s >= achados[0][0] * 0.4] if achados else []
        if not achados:
            return {"resultados": [], "aviso": "nenhum procedimento parecido na base"}
        return {"resultados": [{
            "id": p["id"],
            "titulo": p["titulo"],
            "origem": p["origem"],
            "relevancia": round(s, 2),
            "passos": [cortar(x, 220) for x in p["passos"]],
        } for s, p in ((s, self.base.procedimentos[i]) for s, i in achados)]}

    def buscar_chamados_parecidos(self, consulta):
        achados = self.base.idx_chamados.buscar(
            consulta, k=5,
            filtro=lambda i: self._visivel(self.base.chamados[i]) and self.base.chamados[i]["status"] != "cancelado")
        resultados = [{
            "id": c["id"],
            "data": c["data"].date().isoformat() if c["data"] else "",
            "titulo": c["titulo"],
            "categoria": c["categoria"],
            "tipo": c["tipo"],
            "prioridade": c["prioridade"],
            "descricao": cortar(c["descricao"], 300),
            "como_foi_resolvido": cortar(c["resolucao"], 500) or "(sem registro de resolução)",
        } for _, c in ((s, self.base.chamados[i]) for s, i in achados)]
        dossies = self.base.idx_dossies.buscar(
            consulta, k=2, filtro=lambda i: not (self.corte and self.base.dossies[i]["data"]
                                                and self.base.dossies[i]["data"] >= self.corte))
        return {
            "chamados": resultados,
            "investigacoes": [{"titulo": d["titulo"], "resumo": cortar(d["texto"], 700)}
                              for _, d in ((s, self.base.dossies[i]) for s, i in dossies)],
        }

    def historico(self, usuario="", maquina=""):
        usuarios = set(RE_ROTULO.findall(usuario or ""))
        maquinas = {m.upper() for m in RE_MAQUINA.findall(maquina or "")}
        if not usuarios and not maquinas:
            return {"chamados": [], "aviso": "informe um rótulo de usuário (ex.: 'Usuário 3') ou uma máquina (ex.: 'PC-000087')"}
        achados = [c for c in self.base.chamados if self._visivel(c)
                   and (usuarios & set(c["usuarios"]) or maquinas & set(c["maquinas"]))]
        achados = achados[-15:]
        return {
            "total": len(achados),
            "por_categoria": dict(Counter(c["categoria"] for c in achados)),
            "chamados": [{
                "id": c["id"],
                "data": c["data"].date().isoformat() if c["data"] else "",
                "titulo": c["titulo"],
                "categoria": c["categoria"],
                "mesmo_usuario": bool(usuarios & set(c["usuarios"])),
                "mesma_maquina": bool(maquinas & set(c["maquinas"])),
                "resolucao": cortar(c["resolucao"], 160),
            } for c in reversed(achados)],
        }

    def pesquisar_web(self, consulta):
        try:
            from ddgs import DDGS
            resultados = DDGS().text(consulta, region="br-pt", max_results=5)
        except Exception as erro:
            return {"erro": f"pesquisa indisponível: {type(erro).__name__}"}
        return {"resultados": [{"titulo": r.get("title", ""), "url": r.get("href", ""), "trecho": cortar(r.get("body", ""), 300)}
                               for r in resultados]}
