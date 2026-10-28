"""
Anonimizador de chamados de suporte
-----------------------------------
Troca pessoas por rótulos neutros e consistentes ("Usuário 7", "Técnico 2"), e remove
e-mails, senhas, empresa/clientes, domínios, IPs internos, logins de AD e IDs internos,
para que chamados reais possam ser usados com IA sem expor ninguém.

Uso:
    python anonimizador.py <pasta_ou_arquivo_entrada> <pasta_saida> [--config config.json]

Aceita .csv e .json (exports do Supabase / backup do sistema de chamados).
Gera também:
    saida/_mapa_privado.json  -> quem é quem (NÃO publique, NÃO suba no GitHub)
    saida/_relatorio.json     -> quantas trocas de cada tipo foram feitas
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(10**9)

LETRA = r"[^\W\d_]"                      # qualquer letra, com ou sem acento
ANTES = rf"(?<!{LETRA})"
DEPOIS = rf"(?!{LETRA})"
SEPARADOR = r"(?:[ \t]+(?:d[aeo]s?[ \t]+)?|[._])"   # "Ana Clara", "Bia de Jesus", "joana.nunes"

VARIANTES = {"a": "aáàâã", "e": "eéèê", "i": "iíì", "o": "oóòôõ", "u": "uúùü", "c": "cç", "n": "nñ"}


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def padrao_flexivel(nome: str) -> str:
    """'Patricia' -> regex que casa Patricia/Patrícia/PATRÍCIA..."""
    return "".join(f"[{VARIANTES[c]}]" if c in VARIANTES else re.escape(c) for c in sem_acento(nome))


def slug(rotulo: str) -> str:
    return sem_acento(rotulo).replace(" ", "")          # "Usuário 7" -> "usuario7"


# =========================================================================== pessoas
class Pessoas:
    """Descobre QUEM é cada menção ("Patricia", "Patricia Ribeiro", "ribeiro", "pribeiro")
    e devolve sempre o mesmo rótulo para a mesma pessoa."""

    def __init__(self, cfg: dict):
        self.apelidos = {sem_acento(k): sem_acento(v) for k, v in cfg.get("apelidos", {}).items()}
        self.primeiros = {sem_acento(n) for n in cfg["nomes"]}
        self.sobrenomes = {sem_acento(n) for n in cfg["sobrenomes"]}
        self.arriscados = {sem_acento(n) for n in cfg.get("nomes_arriscados", [])}
        self.prim_arriscados = {sem_acento(n) for n in cfg.get("primeiros_arriscados", [])}
        self.todos = self.primeiros | self.sobrenomes | self.arriscados | set(self.apelidos)
        self.cfg = cfg

        alt = "|".join(padrao_flexivel(n) for n in sorted(self.todos, key=len, reverse=True))
        self.re_token = re.compile(f"{ANTES}(?:{alt}){DEPOIS}", re.I)
        self.re_trecho = re.compile(f"{ANTES}(?:{alt})(?:{SEPARADOR}(?:{alt}))*{DEPOIS}", re.I)

        login_sob = sorted({s for s in self.sobrenomes | self.arriscados
                            | {k for k, v in self.apelidos.items() if v in self.sobrenomes} if len(s) >= 4},
                           key=len, reverse=True)
        self.re_login_a = re.compile(rf"{ANTES}([a-z]{{1,2}})({'|'.join(map(re.escape, login_sob))}){DEPOIS}")
        login_b = [s for s in login_sob if len(s) >= 6 and s not in self.arriscados]
        self.re_login_b = re.compile(rf"{ANTES}({'|'.join(map(re.escape, login_b))})([a-z]){DEPOIS}")

        self.grupos = defaultdict(list)    # primeiro nome -> [{"sob": set, "n": int, "id": str}]
        self.rotulos = {}                  # id da pessoa -> "Usuário 7"
        self.tecnicos = {}
        self.variantes = defaultdict(set)  # id -> textos originais vistos
        self.n_usuarios = 0

    def canon(self, t: str) -> str:
        c = sem_acento(t)
        return self.apelidos.get(c, c)

    def classe(self, c: str) -> str:
        if c in self.primeiros:
            return "primeiro"
        if c in self.sobrenomes:
            return "sobrenome"
        return "arriscado"

    # ------------------------------------------------------------- segmentação
    def segmentos(self, trecho: str, ini: int = 0):
        """Quebra um trecho em pessoas. 'Renata Costa' = 1 pessoa; 'Marcelo Paz' = 1;
        'passos' sozinho = não é pessoa; 'Caio Augusto Lima' = 1."""
        toks = [(m.start() + ini, m.end() + ini, self.canon(m.group(0))) for m in self.re_token.finditer(trecho)]
        segs, atual = [], []
        for tok in toks:
            cl = self.classe(tok[2])
            if not atual:
                if cl == "arriscado":          # "Paz", "passos", "costa" sozinhos não são nome
                    continue
                atual = [tok]
            elif cl in ("sobrenome", "arriscado") or (
                    cl == "primeiro" and (self.classe(atual[-1][2]) == "primeiro" or atual[-1][2] in self.prim_arriscados)):
                atual.append(tok)              # "Ana Clara Mendes de Aguiar", "Rafael Antunes Barros"
            else:
                segs.append(atual)
                atual = [tok]
        if atual:
            segs.append(atual)
        return segs

    def _partes(self, seg):
        canons = [t[2] for t in seg]
        primeiro = canons[0] if self.classe(canons[0]) == "primeiro" else None
        sobs = {c for c in canons if self.classe(c) != "primeiro" and c not in self.prim_arriscados}
        return primeiro, sobs

    # ------------------------------------------------------------- registro
    def registrar(self, texto: str):
        """1ª passada: aprende quem é quem pelos nomes completos ('Patricia Ribeiro' ≠ 'Patricia Teixeira')."""
        quem_e = {" ".join(t[2] for t in s): v for k, v in self.cfg.get("quem_e", {}).items()
                  for s in self.segmentos(k)[:1]}
        for m in self.re_trecho.finditer(texto):
            for seg in self.segmentos(m.group(0)):
                chave = " ".join(t[2] for t in seg)
                if chave in quem_e:            # "Otávio Prado" conta como "Otávio Campos"
                    seg = (self.segmentos(quem_e[chave]) or [seg])[0]
                primeiro, sobs = self._partes(seg)
                if not (primeiro and sobs):
                    continue
                grupos = self.grupos[primeiro]
                juntos = [g for g in grupos if g["sob"] & sobs]
                if not juntos:
                    grupos.append({"sob": set(sobs), "n": 1, "id": f"{primeiro}#{len(grupos) + 1}"})
                    continue
                base = juntos[0]
                base["sob"] |= sobs
                base["n"] += 1
                for g in juntos[1:]:           # duas grafias da mesma pessoa se encontraram
                    base["sob"] |= g["sob"]
                    base["n"] += g["n"]
                    grupos.remove(g)

    def finalizar_registro(self):
        for i, desc in enumerate(self.cfg.get("tecnicos", []), 1):
            self.tecnicos[self.resolver_texto(desc)] = f"Técnico {i}"

    # ------------------------------------------------------------- resolução
    def resolver_texto(self, desc: str) -> str:
        segs = self.segmentos(desc)
        return self.resolver(segs[0]) if segs else f"?{desc}"

    def resolver(self, seg, usar_sozinho=True) -> str:
        canons = [t[2] for t in seg]
        if usar_sozinho:
            quem_e = {" ".join(t[2] for t in s): v for k, v in self.cfg.get("quem_e", {}).items()
                      for s in self.segmentos(k)[:1]}
            chave = " ".join(canons)
            if chave in quem_e:
                alvo_segs = self.segmentos(quem_e[chave])
                if [t[2] for t in alvo_segs[0]] == canons:
                    return f"{chave}*"         # a pessoa é o nome sozinho (ex.: "Pedro")
                return self.resolver(alvo_segs[0], usar_sozinho=False)

        primeiro, sobs = self._partes(seg)
        if primeiro and sobs:
            for g in self.grupos.get(primeiro, []):
                if g["sob"] & sobs:
                    return g["id"]
            return f"{primeiro}:{'-'.join(sorted(sobs))}"
        if primeiro:
            grupos = self.grupos.get(primeiro)
            return max(grupos, key=lambda g: g["n"])["id"] if grupos else primeiro
        candidatos = [g for gs in self.grupos.values() for g in gs if g["sob"] & sobs]
        return max(candidatos, key=lambda g: g["n"])["id"] if candidatos else f"~{min(sobs)}"

    def resolver_login(self, inicial: str, sobrenome: str, login: str) -> str:
        fixos = {k.lower(): v for k, v in self.cfg.get("logins", {}).items()}
        if login in fixos:
            return self.resolver_texto(fixos[login])
        s = self.canon(sobrenome)
        candidatos = [(p, g) for p, gs in self.grupos.items() for g in gs if s in g["sob"]]
        com_inicial = [g for p, g in candidatos if inicial and p.startswith(inicial)]
        escolha = com_inicial or [g for _, g in candidatos]
        return max(escolha, key=lambda g: g["n"])["id"] if escolha else f"login:{login}"

    def rotulo(self, pid: str, original: str) -> str:
        self.variantes[pid].add(original)
        if pid in self.tecnicos:
            return self.tecnicos[pid]
        if pid not in self.rotulos:
            self.n_usuarios += 1
            self.rotulos[pid] = f"Usuário {self.n_usuarios}"
        return self.rotulos[pid]

    # ------------------------------------------------------------- troca no texto
    def trocar(self, texto: str, contagem: Counter) -> str:
        def troca_trecho(m):
            inicio, pedacos, pos = m.start(), [], m.start()
            for seg in self.segmentos(m.group(0), ini=inicio):
                a, b = seg[0][0], seg[-1][1]
                original = texto[a:b]
                rot = self.rotulo(self.resolver(seg), original)
                vizinho = texto[a - 1:a] + texto[b:b + 1]
                if re.search(r"[._]", original) or "_" in vizinho:
                    rot = slug(rot)                       # nome de arquivo / e-mail: "usuario7.jpg"
                elif original.isupper() and len(original) > 2:
                    rot = rot.upper()
                pedacos.append(texto[pos:a] + rot)
                pos = b
                contagem["pessoa"] += 1
            pedacos.append(texto[pos:m.end()])
            return "".join(pedacos)
        return self.re_trecho.sub(troca_trecho, texto)

    def trocar_logins(self, texto: str, contagem: Counter) -> str:
        def a(m):
            contagem["login_ad"] += 1
            return slug(self.rotulo(self.resolver_login(m.group(1)[0], m.group(2), m.group(0)), m.group(0)))

        def b(m):
            contagem["login_ad"] += 1
            return slug(self.rotulo(self.resolver_login(m.group(2), m.group(1), m.group(0)), m.group(0)))
        texto = self.re_login_a.sub(a, texto)
        return self.re_login_b.sub(b, texto)

    def local_de_email(self, local: str):
        """'igor.lima' -> 'usuario12' (mesmo rótulo da pessoa); 'fiscal' -> None."""
        m = self.re_trecho.search(local)
        if m:
            segs = self.segmentos(m.group(0))
            if segs:
                return slug(self.rotulo(self.resolver(segs[0]), local))
        m = self.re_login_a.fullmatch(local.lower())
        if m:
            return slug(self.rotulo(self.resolver_login(m.group(1)[0], m.group(2), m.group(0)), local))
        return None


# =========================================================================== anonimizador
class Anonimizador:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.contagem = Counter()
        self.pessoas = Pessoas(cfg)
        self.re_email = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
        self.re_url = re.compile(r"https?://[^\s\"'\\)\]]+")
        self.re_token = re.compile(r"[A-Za-z0-9@!$#%&*._-]{6,}")
        self.re_cnpj = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/?\d{4}-?\d{2}\b")
        self.re_cpf = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")

    # 'infelizmenteCaio' -> 'infelizmente Caio' (só se a parte grudada for um nome conhecido)
    def separa_grudados(self, t):
        def troca(m):
            return f"{m.group(1)} {m.group(2)}" if self.pessoas.canon(m.group(2)) in self.pessoas.todos else m.group(0)
        return re.sub(r"([a-zà-ÿ])([A-ZÀ-Ý][a-zà-ÿ]+)", troca, t)

    def aprender(self, t: str):
        if t:
            self.pessoas.registrar(self.separa_grudados(t))

    # ------------------------------------------------------------- etapas
    def _ids_usuario(self, t):
        for real, falso in self.cfg.get("ids_de_usuario", {}).items():
            self.contagem["id_usuario_supabase"] += t.count(real)
            t = t.replace(real, falso)
        return t

    def _links_privados(self, t):
        def troca(m):
            if any(p in m.group(0) for p in self.cfg.get("links_privados", [])):
                self.contagem["link_privado"] += 1
                return "[link-privado-removido]"
            return m.group(0)
        return self.re_url.sub(troca, t)

    def _emails(self, t):
        def troca(m):
            local, dominio = m.group(0).split("@", 1)
            novo = self.pessoas.local_de_email(local)
            self.contagem["email"] += 1
            return f"{novo or local}@{self._empresas(dominio, contar=False)}"
        return self.re_email.sub(troca, t)

    def _empresas(self, t, contar=True):
        for real, falso in self.cfg.get("empresas", []):
            t, n = re.subn(re.escape(real), falso, t, flags=re.I)
            if contar:
                self.contagem["empresa_cliente_dominio"] += n
        return t

    def _parece_senha(self, tok):
        return (tok[0].isalnum() and re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok)
                and re.search(r"[@!$#%&*]", tok) and not self.re_email.fullmatch(tok))

    def _senhas(self, t):
        def troca(m):
            if self._parece_senha(m.group(0)):
                self.contagem["senha"] += 1
                return "[SENHA-REMOVIDA]"
            return m.group(0)
        return self.re_token.sub(troca, t)

    def _documentos(self, t):
        t, n1 = self.re_cnpj.subn("[CNPJ-REMOVIDO]", t)
        t, n2 = self.re_cpf.subn("[CPF-REMOVIDO]", t)
        self.contagem["cnpj_cpf"] += n1 + n2
        return t

    def _ids(self, t):
        for padrao, novo in self.cfg.get("ids", []):
            t, n = re.subn(padrao, lambda m, nv=novo: m.expand(nv), t, flags=re.I)
            self.contagem["tag_ou_id_interno"] += n
        for padrao, novo in self.cfg.get("palavras_empresa", []):
            def caso(m, nv=novo):
                o = m.group(0)
                return nv.upper() if o.isupper() else nv.lower() if o.islower() else nv
            t, n = re.subn(padrao, caso, t, flags=re.I)
            self.contagem["empresa_cliente_dominio"] += n
        return t

    def _ips(self, t):
        rede = self.cfg.get("rede_interna")
        if rede:
            self.contagem["ip_interno"] += t.count(rede["de"])
            t = t.replace(rede["de"], rede["para"])
        return t

    # ------------------------------------------------------------- pipeline
    def texto(self, t: str) -> str:
        if not t:
            return t
        t = self._ids_usuario(t)
        t = self._links_privados(t)
        t = self.separa_grudados(t)
        t = self._emails(t)
        t = self._empresas(t)

        guardadas = []                     # URLs públicas (HP, Lenovo, gov.br) ficam intactas

        def guarda(m):
            guardadas.append(m.group(0))
            return f"\x00URL{len(guardadas) - 1}\x00"
        t = self.re_url.sub(guarda, t)

        t = self._senhas(t)
        t = self._documentos(t)
        t = self._ids(t)
        t = self._ips(t)
        t = self.pessoas.trocar_logins(t, self.contagem)
        t = self.pessoas.trocar(t, self.contagem)
        return re.sub(r"\x00URL(\d+)\x00", lambda m: guardadas[int(m.group(1))], t)

    def valor(self, v, aprender=False):
        if isinstance(v, str):
            return self.aprender(v) if aprender else self.texto(v)
        if isinstance(v, list):
            return [self.valor(x, aprender) for x in v]
        if isinstance(v, dict):
            return {k: self.valor(x, aprender) for k, x in v.items()}   # chaves do JSON não mudam
        return v


# =========================================================================== arquivos
def ler(arquivos):
    dados = {}
    for arq in arquivos:
        if arq.suffix.lower() == ".csv":
            with arq.open(encoding="utf-8", newline="") as f:
                leitor = csv.DictReader(f)
                dados[arq] = ("csv", leitor.fieldnames, list(leitor))
        elif arq.suffix.lower() == ".json":
            dados[arq] = ("json", None, json.loads(arq.read_text(encoding="utf-8")))
    return dados


def processar(entrada: Path, saida: Path, anon: Anonimizador):
    saida.mkdir(parents=True, exist_ok=True)
    arquivos = [entrada] if entrada.is_file() else sorted(entrada.glob("*"))
    dados = ler(arquivos)

    # passada 1: aprender quem é quem em TODOS os arquivos antes de trocar qualquer coisa
    for tipo, _, conteudo in dados.values():
        if tipo == "csv":
            for linha in conteudo:
                for v in linha.values():
                    anon.aprender(v)
        else:
            anon.valor(conteudo, aprender=True)
    anon.pessoas.finalizar_registro()

    # passada 2: trocar
    for arq, (tipo, campos, conteudo) in dados.items():
        if tipo == "csv":
            with (saida / arq.name).open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=campos)
                w.writeheader()
                w.writerows({k: anon.texto(v) for k, v in linha.items()} for linha in conteudo)
        else:
            (saida / arq.name).write_text(json.dumps(anon.valor(conteudo), ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        print(f"  ok  {arq.name}")


def verificar(saida: Path, anon: Anonimizador) -> int:
    """Teste de vazamento: procura na saída nome real da lista, IP interno, empresa,
    ID do Supabase ou token com cara de senha."""
    texto = "\n".join(a.read_text(encoding="utf-8") for a in sorted(saida.glob("*"))
                      if not a.name.startswith("_") and a.suffix.lower() in (".csv", ".json"))
    p = anon.pessoas
    problemas = []
    for m in re.finditer(rf"{LETRA}+", texto):
        if p.canon(m.group(0)) in (p.todos - p.arriscados):
            problemas.append(f"nome real: {m.group(0)}")
    rede = anon.cfg.get("rede_interna", {}).get("de")
    if rede and rede in texto:
        problemas.append(f"IP interno {rede}x")
    for real, _ in anon.cfg.get("empresas", []):
        if real.lower() in texto.lower():
            problemas.append(f"empresa/cliente: {real}")
    for real in anon.cfg.get("ids_de_usuario", {}):
        if real in texto:
            problemas.append("id de usuário do Supabase")
    for m in anon.re_token.finditer(anon.re_url.sub(" ", texto)):   # URLs públicas têm & e # legítimos
        if anon._parece_senha(m.group(0)) and not re.match(r"(usuario|tecnico)\d+@", m.group(0)):
            problemas.append(f"possível senha: {m.group(0)}")

    print("\nTeste de vazamento:", "OK, nada encontrado" if not problemas else f"{len(set(problemas))} achados")
    for x in sorted(set(problemas)):
        print("  -", x)
    return len(problemas)


def main():
    ap = argparse.ArgumentParser(description="Anonimiza exports de chamados de suporte.")
    ap.add_argument("entrada", type=Path)
    ap.add_argument("saida", type=Path)
    ap.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    args = ap.parse_args()

    anon = Anonimizador(json.loads(args.config.read_text(encoding="utf-8")))
    print("Anonimizando...")
    processar(args.entrada, args.saida, anon)

    p = anon.pessoas
    quem = {}
    for pid, variantes in p.variantes.items():
        rot = p.tecnicos.get(pid) or p.rotulos.get(pid)
        quem.setdefault(rot, set()).update(variantes)
    ordem = sorted(quem, key=lambda r: (not r.startswith("Técnico"), int(r.split()[-1])))
    (args.saida / "_mapa_privado.json").write_text(
        json.dumps({r: sorted(quem[r]) for r in ordem}, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.saida / "_relatorio.json").write_text(
        json.dumps({"pessoas_distintas": len(quem), **dict(anon.contagem.most_common())},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nPessoas distintas: {len(quem)} ({len(p.tecnicos)} técnicos na lista)")
    print("Trocas feitas:")
    for k, n in anon.contagem.most_common():
        print(f"  {k:<26}{n:>6}")
    achados = verificar(args.saida, anon)
    print("\n_mapa_privado.json diz quem é quem: guarde só na sua máquina.")
    return 1 if achados else 0


if __name__ == "__main__":
    sys.exit(main())
