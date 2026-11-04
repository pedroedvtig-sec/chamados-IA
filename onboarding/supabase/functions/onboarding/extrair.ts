export const DEPARTAMENTOS = ["ADM", "comercial", "diretoria", "estoque", "financeiro", "fiscal", "GA", "jurídico", "marketing", "OP", "RH", "TI", "Iter", "outro"];

const APELIDOS_SETOR: Record<string, string> = {
  adm: "ADM", administrativo: "ADM", comercial: "comercial", vendas: "comercial", diretoria: "diretoria",
  estoque: "estoque", financeiro: "financeiro", fiscal: "fiscal", ga: "GA", juridico: "jurídico",
  marketing: "marketing", op: "OP", operacional: "OP", operacoes: "OP", rh: "RH", "recursos humanos": "RH",
  ti: "TI", "tecnologia da informacao": "TI", iter: "Iter",
};

const PARTICULAS = new Set(["de", "da", "do", "dos", "das", "e"]);
const SUFIXOS = new Set(["filho", "filha", "junior", "neto", "neta", "sobrinho", "segundo", "terceiro"]);
const ASSINATURA = /^\s*(att\.?|atenciosamente|abs\.?|abraços?|obrigad[oa]|grat[oa]|--)\s*[,!.]?\s*$/im;

export function normalizar(s: string): string {
  return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

function capitalizar(nome: string): string {
  return nome.toLowerCase().split(/\s+/).map((p) => PARTICULAS.has(p) ? p : p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

function nomeValido(bruto: string): string | null {
  const limpo = bruto.replace(/\(.*?\)/g, " ").replace(/[|–—:;,.!?]+.*$/, "").replace(/\s+-\s+.*$/, "").replace(/\s+/g, " ").trim();
  const palavras = limpo.split(" ").filter(Boolean);
  if (palavras.length < 2 || palavras.length > 7) return null;
  if (!palavras.every((p) => /^[A-Za-zÀ-ÿ'-]+$/.test(p))) return null;
  return capitalizar(limpo);
}

export function nomeDoEmail(assunto: string, corpo: string): string | null {
  const linha = (corpo || "").match(/^[ \t>*-]*nome(?:\s+completo)?(?:\s+do\s+colaborador)?\s*:\s*(.+)$/im);
  if (linha) {
    const nome = nomeValido(linha[1]);
    if (nome) return nome;
  }
  const semPrefixo = (assunto || "").replace(/^\s*((re|res|fw|fwd|enc|tr)\s*:\s*)+/i, "");
  const doAssunto = semPrefixo.match(/solicita[çc][ãa]o\s+de\s+(?:m[áa]quina|equipamento|notebook|computador|acesso)s?\s*(?:[-–—:+|]|para|p\/)?\s*(.+)$/i);
  if (doAssunto) {
    const nome = nomeValido(doAssunto[1].replace(/^(o|a)\s+(colaborador|colaboradora|novo|nova)\s+/i, "").replace(/^(colaborador|colaboradora)\s+/i, ""));
    if (nome) return nome;
  }
  return null;
}

export function partesDoNome(nome: string): string[] {
  return (nome.match(/[A-Za-zÀ-ÿ]+/g) || []).map(normalizar).filter((p) => !PARTICULAS.has(p));
}

export function loginDe(nome: string, dominio: string) {
  const partes = partesDoNome(nome);
  if (partes.length < 2) return null;
  const primeiro = partes[0];
  const ultimo = partes[partes.length - 1];
  return { primeiro, ultimo, usuario: primeiro[0] + ultimo, email: `${primeiro}.${ultimo}@${dominio}` };
}

export function acesso(nome: string, dominio: string, usuariosDoHistorico: string[]) {
  const login = loginDe(nome, dominio);
  if (!login) return null;
  const avisos: string[] = [];
  if (SUFIXOS.has(login.ultimo)) avisos.push(`o nome termina em "${login.ultimo}": confira qual sobrenome usar no login`);
  const proprio = partesDoNome(nome).join(" ");
  const mesmos = new Set<string>();
  for (const campo of usuariosDoHistorico) {
    for (const pessoa of (campo || "").split(/[,;/]| e /)) {
      const outro = loginDe(pessoa, dominio);
      if (outro && outro.usuario === login.usuario && partesDoNome(pessoa).join(" ") !== proprio) mesmos.add(pessoa.trim());
    }
  }
  if (mesmos.size) avisos.push(`já existem chamados de ${[...mesmos].slice(0, 3).join(", ")}, que geraria o mesmo login: confira no AD`);
  return { usuario: login.usuario, email: login.email, avisos };
}

function dataValida(ano: number, mes: number, dia: number): Date | null {
  const d = new Date(Date.UTC(ano, mes - 1, dia));
  return d.getUTCFullYear() === ano && d.getUTCMonth() === mes - 1 && d.getUTCDate() === dia ? d : null;
}

function datasDaLinha(linha: string, hoje: Date): Date[] {
  const achadas: Date[] = [];
  for (const m of linha.matchAll(/\b(\d{1,2})[\/.-](\d{1,2})(?:[\/.-](\d{2,4}))?\b/g)) {
    const dia = +m[1], mes = +m[2];
    let ano = m[3] ? +m[3] : hoje.getUTCFullYear();
    if (ano < 100) ano += 2000;
    let d = dataValida(ano, mes, dia);
    if (d && !m[3] && d.getTime() < hoje.getTime() - 30 * 86400000) d = dataValida(ano + 1, mes, dia);
    if (d) achadas.push(d);
  }
  return achadas;
}

export function dataDeInicio(texto: string, hoje: Date): string | null {
  const linhas = (texto || "").split(/\r?\n/);
  const chave = /(in[íi]cio|inicia|come[çc]a|admiss[ãa]o|primeiro dia|entra(?:da)?\b)/i;
  const candidatas = [...linhas.filter((l) => chave.test(l)), ...linhas.filter((l) => !chave.test(l))];
  for (const linha of candidatas) {
    const datas = datasDaLinha(linha, hoje);
    if (datas.length) return datas[0].toISOString().slice(0, 10);
  }
  return null;
}

export function setorDoTexto(texto: string): string | null {
  const explicito = (texto || "").match(/^[ \t>*-]*(?:setor|[áa]rea|departamento)\s*:\s*(.+)$/im);
  if (explicito) {
    const valor = normalizar(explicito[1]).replace(/[^a-z\s]/g, " ").replace(/\s+/g, " ").trim();
    if (APELIDOS_SETOR[valor]) return APELIDOS_SETOR[valor];
    for (const [apelido, setor] of Object.entries(APELIDOS_SETOR)) {
      if (new RegExp(`(^|\\s)${apelido}(\\s|$)`).test(valor)) return setor;
    }
  }
  const corrido = normalizar(texto);
  for (const [apelido, setor] of Object.entries(APELIDOS_SETOR)) {
    if (setor === "TI" || apelido.length < 3) continue;
    if (new RegExp(`(^|[^a-z])${apelido}([^a-z]|$)`).test(corrido)) return setor;
  }
  return null;
}

export function semAssinatura(texto: string): string {
  const m = (texto || "").match(ASSINATURA);
  return m && m.index !== undefined ? texto.slice(0, m.index).trimEnd() : (texto || "");
}

export function esconder(texto: string, nome: string, outrosNomes: string[], empresas: string[]) {
  let t = texto;
  const trocas: Record<string, number> = {};
  const contar = (tipo: string) => { trocas[tipo] = (trocas[tipo] || 0) + 1; };
  const trocar = (re: RegExp, marcador: string, tipo: string) => {
    t = t.replace(re, () => { contar(tipo); return marcador; });
  };
  trocar(/[\w.+-]+@[\w-]+(\.[\w-]+)+/g, "[EMAIL]", "email");
  trocar(/\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b/g, "[CPF]", "documento");
  trocar(/\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dxX]\b/g, "[DOCUMENTO]", "documento");
  trocar(/(?:\+?55\s*)?\(?\b\d{2}\)?\s*9?\d{4}[-\s]?\d{4}\b/g, "[TELEFONE]", "telefone");
  trocar(/\b\d{8,}\b/g, "[NUMERO]", "documento");
  for (const empresa of empresas.filter(Boolean)) {
    trocar(new RegExp(`\\b${empresa.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "gi"), "[EMPRESA]", "empresa");
  }
  const escapar = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pedacos = (n: string) => (n.match(/[A-Za-zÀ-ÿ]+/g) || []).filter((p) => p.length >= 3 && !PARTICULAS.has(normalizar(p)));
  if (nome) {
    trocar(new RegExp(escapar(nome), "gi"), "[COLABORADOR]", "colaborador");
    for (const p of pedacos(nome)) trocar(new RegExp(`(?<![A-Za-zÀ-ÿ])${escapar(p)}(?![A-Za-zÀ-ÿ])`, "gi"), "[COLABORADOR]", "colaborador");
  }
  for (const outro of outrosNomes.filter(Boolean)) {
    for (const p of pedacos(outro)) trocar(new RegExp(`(?<![A-Za-zÀ-ÿ])${escapar(p)}(?![A-Za-zÀ-ÿ])`, "gi"), "[PESSOA]", "pessoa");
  }
  return { texto: t, trocas };
}

const APARELHO_DE_CONTATO = /\b(celular|smartphone|telefone|aparelho)\b/i;
const LINHA_DE_CONTATO = /^[ \t>*-]*(celular|cel|telefone|tel|fone|whats(app)?|contato)\s*:/i;

/* "Celular: (11) 9...." é o contato do colaborador, não um pedido de aparelho.
   Só mantém o celular se o e-mail falar dele fora das linhas de contato. */
export function equipamentosPedidos(equipamentos: string[], texto: string): string[] {
  const foraDoContato = (texto || "").split(/\r?\n/).filter((l) => !LINHA_DE_CONTATO.test(l)).join("\n");
  const pedeAparelho = /\b(celular|smartphone|aparelho telef[oô]nico|telefone corporativo)\b/i.test(foraDoContato);
  return equipamentos.filter((e) => pedeAparelho || !APARELHO_DE_CONTATO.test(e));
}

export function checklist(usuario: string, email: string, setor: string, equipamentos: string[], acessos: string[]): string[] {
  return [
    usuario ? `Criar o usuário ${usuario} no AD${setor ? ` e colocar no grupo do setor ${setor}` : ""}` : "Definir e criar o usuário no AD",
    email ? `Criar o e-mail ${email} no Google Workspace` : "Criar o e-mail no Google Workspace",
    "Separar e preparar a máquina (procedimento de configuração vinculado)",
    "Separar periféricos: mouse, teclado, headset e monitor, se houver",
    ...equipamentos.map((e) => `Providenciar: ${e}`),
    ...acessos.map((a) => `Liberar acesso: ${a}`),
    "Gerar o termo de responsabilidade na intranet",
    "Imprimir a folha de credenciais",
    "Entregar a máquina e colher a assinatura do termo",
  ];
}

export function dataBr(iso: string | null): string {
  if (!iso) return "";
  const [a, m, d] = iso.split("-");
  return `${d}/${m}/${a}`;
}
