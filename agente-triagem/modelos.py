import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _json_do_texto(texto):
    texto = (texto or "").strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        achado = re.search(r"\{.*\}", texto, re.S)
        if achado:
            return json.loads(achado.group(0))
        raise


def sem_acento(valor):
    if not isinstance(valor, str):
        return valor
    return "".join(c for c in unicodedata.normalize("NFKD", valor) if not unicodedata.combining(c)).strip().lower()


def _problemas(argumentos, esquema):
    if not isinstance(argumentos, dict):
        return {"campos_faltando": list(esquema.get("required", []))}
    propriedades = esquema.get("properties", {})
    faltando = [c for c in esquema.get("required", []) if argumentos.get(c) in (None, "", [])]
    vazados = [c for c, v in argumentos.items() if isinstance(v, str) and "<parameter" in v]
    invalidos = {c: propriedades[c]["enum"] for c, v in argumentos.items()
                 if c in propriedades and "enum" in propriedades[c] and v not in (None, "")
                 and sem_acento(v) not in {sem_acento(e) for e in propriedades[c]["enum"]}}
    problemas = {}
    if faltando:
        problemas["campos_faltando"] = faltando
    if vazados:
        problemas["campos_com_marcacao"] = vazados
    if invalidos:
        problemas["valores_invalidos_use_um_destes"] = invalidos
    return problemas


class ErroProvedor(Exception):
    def __init__(self, mensagem, status=503):
        super().__init__(mensagem)
        self.status = status


class PrazoEsgotado(TimeoutError):
    pass


def _esperar(espera, motivo, restante=None):
    if restante is not None:
        if restante() <= espera:
            raise PrazoEsgotado(f"o prazo da triagem acabou ({motivo})")
    print(f"  ({motivo}; esperando {espera}s...)", file=sys.stderr)
    time.sleep(espera)
    return min(espera * 2, 60)


class OpenRouter:
    nome = "openrouter"

    def __init__(self, modelo=None, reserva=None, tentativas=6, prazo=None):
        self.chave = os.environ.get("OPENROUTER_API_KEY")
        if not self.chave:
            raise ErroProvedor("Defina a variável OPENROUTER_API_KEY com a sua chave da OpenRouter.", 401)
        self.modelo = modelo or os.environ.get("OPENROUTER_MODEL", "openrouter/free")
        self.reserva = reserva if reserva is not None else os.environ.get("OPENROUTER_MODEL_RESERVA", "")
        self.tentativas = tentativas
        self.fim = time.monotonic() + prazo if prazo else None
        self.modelos_usados = []
        self.aceita_forcar = True

    def _restante(self):
        return self.fim - time.monotonic()

    def _post(self, corpo, tentativas=None):
        tentativas = tentativas or self.tentativas
        rota = {"models": [self.modelo, self.reserva]} if self.reserva and self.reserva != self.modelo else {"model": self.modelo}
        corpo = {
            **rota,
            "provider": {"data_collection": "deny", "require_parameters": True},
            **corpo,
        }
        pedido = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(corpo).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.chave}",
                "Content-Type": "application/json",
                "X-Title": "agente-triagem",
            },
        )
        espera = 5
        restante = self._restante if self.fim else None
        for tentativa in range(tentativas):
            limite = 120
            if restante:
                if restante() <= 1:
                    raise PrazoEsgotado("o prazo da triagem acabou antes da resposta do modelo")
                limite = min(limite, restante())
            try:
                with urllib.request.urlopen(pedido, timeout=limite) as r:
                    dados = json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as erro:
                detalhe = erro.read().decode("utf-8", "replace")[:2000]
                if erro.code == 401:
                    raise ErroProvedor("A OpenRouter recusou a chave (OPENROUTER_API_KEY inválida).", 401) from None
                if erro.code == 402:
                    raise ErroProvedor(f"Sem créditos na OpenRouter para o modelo {self.modelo}. "
                                       f"Use um modelo ':free' ou adicione créditos. Detalhe: {detalhe}", 402) from None
                if erro.code == 429 and "per-day" in detalhe.lower():
                    raise ErroProvedor(f"Limite diário de modelos gratuitos atingido na OpenRouter. Detalhe: {detalhe}", 429) from None
                if erro.code == 404 and "data policy" in detalhe.lower():
                    raise ErroProvedor("Nenhum provedor desse modelo atende à configuração de privacidade "
                                       f"(sem treino com os dados). Escolha outro modelo. Detalhe: {detalhe}", 422) from None
                if erro.code not in (408, 429, 500, 502, 503) or tentativa == tentativas - 1:
                    raise RuntimeError(f"OpenRouter respondeu {erro.code}: {detalhe}") from None
                espera = _esperar(espera, f"OpenRouter respondeu {erro.code}", restante)
                continue
            except (urllib.error.URLError, TimeoutError) as erro:
                if isinstance(erro, PrazoEsgotado):
                    raise
                if tentativa == tentativas - 1:
                    raise RuntimeError(f"sem conexão com a OpenRouter: {getattr(erro, 'reason', erro)}") from None
                espera = _esperar(espera, f"falha de conexão: {getattr(erro, 'reason', erro)}", restante)
                continue
            if dados.get("error"):
                if tentativa == tentativas - 1:
                    raise RuntimeError(f"OpenRouter: {dados['error']}")
                espera = _esperar(espera, f"erro do provedor: {str(dados['error'])[:80]}", restante)
                continue
            if dados.get("model"):
                self.modelos_usados.append(dados["model"])
            return dados
        raise RuntimeError("OpenRouter não respondeu")

    def agente(self, sistema, pedido, declaracoes, executar, final, max_rodadas=8):
        ferramentas = [{"type": "function", "function": {
            "name": d["name"], "description": d["description"], "parameters": d["parameters_json_schema"]}}
            for d in declaracoes]
        esquema_final = next((d["parameters_json_schema"] for d in declaracoes if d["name"] == final), {})
        mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": pedido}]
        escolha = "auto"
        rastro, chamadas = [], 0
        ultimo_problema = None
        for _ in range(max_rodadas):
            if escolha != "auto" and not self.aceita_forcar:
                escolha = "auto"
            try:
                dados = self._post({"messages": mensagens, "tools": ferramentas, "tool_choice": escolha})
            except RuntimeError as erro:
                if escolha == "auto" or "tool_choice" not in str(erro):
                    raise
                self.aceita_forcar = False
                escolha = "auto"
                dados = self._post({"messages": mensagens, "tools": ferramentas, "tool_choice": escolha})
            chamadas += 1
            mensagem = dados["choices"][0]["message"]
            pedidos = mensagem.get("tool_calls") or []
            mensagens.append({"role": "assistant", "content": mensagem.get("content") or "", "tool_calls": pedidos}
                             if pedidos else {"role": "assistant", "content": mensagem.get("content") or ""})
            if not pedidos:
                mensagens.append({"role": "user", "content": f"Entregue o resultado chamando a função {final}."})
                escolha = {"type": "function", "function": {"name": final}}
                continue
            for p in pedidos:
                nome = p["function"]["name"]
                brutos = p["function"].get("arguments") or "{}"
                try:
                    argumentos = brutos if isinstance(brutos, dict) else _json_do_texto(brutos)
                except (json.JSONDecodeError, ValueError):
                    argumentos = None
                if not isinstance(argumentos, dict):
                    argumentos = None
                if nome == final:
                    problemas = _problemas(argumentos, esquema_final)
                    if not problemas:
                        return argumentos, rastro, chamadas
                    ultimo_problema = problemas
                    mensagens.append({"role": "tool", "tool_call_id": p.get("id", nome), "content": json.dumps({
                        "erro": "chamada inválida: os argumentos precisam ser um JSON válido, com cada campo separado, "
                                "sem marcação <parameter> dentro dos textos e só com os valores permitidos",
                        **problemas}, ensure_ascii=False)})
                    escolha = {"type": "function", "function": {"name": final}}
                    continue
                argumentos = argumentos or {}
                saida = executar(nome, argumentos)
                rastro.append({"funcao": nome, "argumentos": argumentos})
                mensagens.append({"role": "tool", "tool_call_id": p.get("id", nome), "content": json.dumps(saida, ensure_ascii=False)})
        if ultimo_problema:
            motivo = f"a triagem final veio inválida: {json.dumps(ultimo_problema, ensure_ascii=False)[:300]}"
        else:
            motivo = "ferramentas usadas: " + (", ".join(r["funcao"] for r in rastro) or "nenhuma")
        raise RuntimeError(f"o agente não finalizou em {max_rodadas} rodadas ({motivo})")

    def json(self, sistema, pedido, esquema, tentativas=3):
        mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": pedido}]
        for tentativa in range(tentativas):
            dados = self._post({
                "messages": mensagens,
                "response_format": {"type": "json_schema", "json_schema": {"name": "resposta", "schema": esquema}},
            })
            texto = dados["choices"][0]["message"].get("content") or ""
            try:
                resposta = _json_do_texto(texto)
            except (json.JSONDecodeError, ValueError):
                resposta = None
            problemas = _problemas(resposta, esquema)
            if not problemas:
                return resposta
            if tentativa == tentativas - 1:
                raise RuntimeError(f"resposta inválida do modelo: {json.dumps(problemas, ensure_ascii=False)[:200]}")
            mensagens += [{"role": "assistant", "content": texto},
                          {"role": "user", "content": "Resposta inválida. Corrija e responda só com o JSON: "
                                                      + json.dumps(problemas, ensure_ascii=False)}]


class Gemini:
    nome = "gemini"

    def __init__(self, modelo=None):
        if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
            raise ErroProvedor("Defina a variável GEMINI_API_KEY com a sua chave do Google AI Studio.", 401)
        from google import genai
        self.cliente = genai.Client()
        self.modelo = modelo or os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
        self.modelos_usados = []

    def _chamar(self, conteudos, config, tentativas=6):
        from google.genai import errors
        espera = 5
        for tentativa in range(tentativas):
            try:
                resposta = self.cliente.models.generate_content(model=self.modelo, contents=conteudos, config=config)
                self.modelos_usados.append(self.modelo)
                return resposta
            except errors.APIError as erro:
                mensagem = str(getattr(erro, "message", "") or erro)
                if erro.code == 429 and ("limit: 0" in mensagem or "PerDay" in mensagem):
                    raise ErroProvedor(f"O modelo {self.modelo} não tem cota disponível na sua chave agora. "
                                       f"Detalhe: {mensagem[:300]}", 429) from None
                if erro.code not in (429, 500, 503) or tentativa == tentativas - 1:
                    raise
                motivo = "limite por minuto" if erro.code == 429 else "servidor sobrecarregado"
                espera = _esperar(espera, f"{motivo}, erro {erro.code}")

    def agente(self, sistema, pedido, declaracoes, executar, final, max_rodadas=8):
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=sistema,
            tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**d) for d in declaracoes])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )
        conteudos = [types.Content(role="user", parts=[types.Part.from_text(text=pedido)])]
        rastro, chamadas = [], 0
        for _ in range(max_rodadas):
            resposta = self._chamar(conteudos, config)
            chamadas += 1
            if not resposta.candidates or not resposta.candidates[0].content:
                raise RuntimeError("o modelo não devolveu resposta")
            conteudos.append(resposta.candidates[0].content)
            pedidos = resposta.function_calls or []
            if not pedidos:
                conteudos.append(types.Content(role="user", parts=[types.Part.from_text(
                    text=f"Entregue o resultado chamando a função {final}.")]))
                continue
            fim = next((p for p in pedidos if p.name == final), None)
            if fim:
                return dict(fim.args or {}), rastro, chamadas
            partes = []
            for p in pedidos:
                argumentos = dict(p.args or {})
                saida = executar(p.name, argumentos)
                rastro.append({"funcao": p.name, "argumentos": argumentos})
                partes.append(types.Part.from_function_response(name=p.name, response=saida))
            conteudos.append(types.Content(role="user", parts=partes))
        raise RuntimeError(f"o agente não finalizou em {max_rodadas} rodadas")

    def json(self, sistema, pedido, esquema):
        from google.genai import types
        config = types.GenerateContentConfig(system_instruction=sistema, temperature=0,
                                             response_mime_type="application/json", response_json_schema=esquema)
        return _json_do_texto(self._chamar(pedido, config).text)


def criar_provedor(nome=None, modelo=None, **opcoes):
    nome = (nome or os.environ.get("LLM_PROVEDOR") or ("openrouter" if os.environ.get("OPENROUTER_API_KEY") else "gemini")).lower()
    if nome == "openrouter":
        return OpenRouter(modelo, **opcoes)
    if nome == "gemini":
        return Gemini(modelo)
    raise ErroProvedor(f"Provedor desconhecido: {nome}. Use 'openrouter' ou 'gemini'.", 400)
