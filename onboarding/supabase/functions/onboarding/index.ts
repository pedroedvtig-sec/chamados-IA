import { createClient, SupabaseClient } from "npm:@supabase/supabase-js@2";
import {
  acesso, checklist, dataBr, dataDeInicio, DEPARTAMENTOS, equipamentosPedidos, esconder, nomeDoEmail, normalizar, semAssinatura, setorDoTexto,
} from "./extrair.ts";
import { fmtHoras, type Historico, slaDe } from "./sla.ts";

const TOKEN = Deno.env.get("ONBOARDING_TOKEN") ?? "";
const DONO = Deno.env.get("ONBOARDING_USER_ID") ?? "";
const DOMINIO = Deno.env.get("DOMINIO_EMAIL") ?? "";
const EMPRESAS = (Deno.env.get("EMPRESAS_ANONIMIZAR") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
const MODELO = Deno.env.get("OPENROUTER_MODEL") ?? "deepseek/deepseek-v4.1-flash";
const PREFIXO_ID = (Deno.env.get("PREFIXO_CHAMADO") ?? "").replace(/[^A-Za-z0-9]/g, "") || "CHM";
const PREFIXO_TITULO = "Onboarding - ";
const PROCEDIMENTO_MAQUINA = "configuracao de maquina";
const PROCEDIMENTO_USUARIO = "configuracao de usuario - ";
const NOME_SETOR_PROCEDIMENTO: Record<string, string> = { OP: "operacional", "jurídico": "juridico" };

const SISTEMA = `Você lê o e-mail em que o RH pede a preparação de um colaborador novo e extrai os dados para o suporte de TI.
O nome do colaborador aparece como [COLABORADOR]; outros marcadores ([PESSOA], [EMAIL], [CPF], [TELEFONE], [EMPRESA]) escondem dados pessoais. Nunca tente adivinhar o que está por trás deles.
Regras:
- setor: um dos valores permitidos, ou vazio se o e-mail não deixa claro.
- cargo: como o e-mail descreve, ou vazio.
- data_inicio: AAAA-MM-DD. Datas relativas ("segunda que vem") contam a partir da data de hoje informada. Vazio se não houver.
- equipamentos: só o que foge do padrão (notebook, mouse, teclado, headset). Ex.: segundo monitor, celular corporativo, desktop no lugar do notebook. Uma linha "Celular: [TELEFONE]" ou "Telefone: [TELEFONE]" é o contato do colaborador, não um pedido de aparelho.
- acessos: sistemas, pastas ou softwares específicos pedidos.
- observacoes: só algo que o técnico precise saber e que ainda não esteja em setor, cargo, data, equipamentos ou acessos, em uma frase. Nunca comente marcadores, dados ocultos ou anonimização. Na dúvida, vazio.
- faltando: o que falta para preparar tudo (ex.: data de início, setor). Não liste o nome nem dados pessoais.`;

function esquema() {
  return {
    type: "object",
    properties: {
      setor: { type: "string", enum: [...DEPARTAMENTOS, ""] },
      cargo: { type: "string" },
      data_inicio: { type: "string" },
      equipamentos: { type: "array", items: { type: "string" } },
      acessos: { type: "array", items: { type: "string" } },
      observacoes: { type: "string" },
      faltando: { type: "array", items: { type: "string" } },
    },
    required: ["setor", "cargo", "data_inicio", "equipamentos", "acessos", "observacoes", "faltando"],
    additionalProperties: false,
  };
}

type Extracao = {
  setor: string; cargo: string; data_inicio: string; equipamentos: string[]; acessos: string[]; observacoes: string; faltando: string[];
};

function resposta(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });
}

function mesmoToken(recebido: string, esperado: string) {
  const a = new TextEncoder().encode(recebido);
  const b = new TextEncoder().encode(esperado);
  let diferenca = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diferenca |= (a[i] ?? 0) ^ (b[i] ?? 0);
  return diferenca === 0;
}

function textoDoModelo(texto: string) {
  try {
    return JSON.parse(texto);
  } catch {
    const achado = texto.match(/\{[\s\S]*\}/);
    if (achado) return JSON.parse(achado[0]);
    throw new Error("o modelo não devolveu JSON");
  }
}

function limparExtracao(bruto: Record<string, unknown>): Extracao {
  const lista = (v: unknown) => Array.isArray(v) ? v.map(String).map((s) => s.trim()).filter(Boolean).slice(0, 8) : [];
  const texto = (v: unknown) => typeof v === "string" ? v.trim().slice(0, 300) : "";
  const setor = DEPARTAMENTOS.includes(String(bruto.setor)) ? String(bruto.setor) : "";
  const data = /^\d{4}-\d{2}-\d{2}$/.test(String(bruto.data_inicio)) ? String(bruto.data_inicio) : "";
  return {
    setor, cargo: texto(bruto.cargo), data_inicio: data, equipamentos: lista(bruto.equipamentos), acessos: lista(bruto.acessos),
    observacoes: /ocult|marcador|anonimi|\[[A-Z]+\]/i.test(texto(bruto.observacoes)) ? "" : texto(bruto.observacoes),
    faltando: lista(bruto.faltando),
  };
}

async function extrairComIA(textoAnonimo: string, hoje: string): Promise<Extracao> {
  const chave = Deno.env.get("OPENROUTER_API_KEY");
  if (!chave) throw new Error("OPENROUTER_API_KEY não configurada");
  let espera = 2000;
  for (let tentativa = 0; tentativa < 3; tentativa++) {
    const r = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${chave}`, "X-Title": "onboarding" },
      body: JSON.stringify({
        model: MODELO,
        provider: { data_collection: "deny", require_parameters: true },
        messages: [
          { role: "system", content: SISTEMA },
          { role: "user", content: `Hoje é ${hoje}.\n\nE-mail do RH:\n${textoAnonimo}` },
        ],
        response_format: { type: "json_schema", json_schema: { name: "onboarding", strict: true, schema: esquema() } },
      }),
    });
    if (r.ok) {
      const dados = await r.json();
      if (!dados.error) return limparExtracao(textoDoModelo(dados?.choices?.[0]?.message?.content ?? ""));
    } else if (![408, 429, 500, 502, 503].includes(r.status)) {
      throw new Error(`OpenRouter respondeu ${r.status}: ${(await r.text()).slice(0, 200)}`);
    }
    await new Promise((ok) => setTimeout(ok, espera));
    espera *= 2;
  }
  throw new Error("a IA não respondeu");
}

async function proximoId(sb: SupabaseClient) {
  const { data, error } = await sb.from("tickets").select("id").like("id", `${PREFIXO_ID}-%`).order("id", { ascending: false }).limit(200);
  if (error) throw error;
  const numeros = (data ?? []).map((t) => new RegExp(`^${PREFIXO_ID}-(\\d+)$`).exec(t.id)).filter(Boolean).map((m) => parseInt(m![1], 10));
  return Math.max(0, ...numeros) + 1;
}

function procedimentosDoSetor(procs: { id: string; titulo: string }[], setor: string) {
  const ids: string[] = [];
  const maquina = procs.find((p) => normalizar(p.titulo) === PROCEDIMENTO_MAQUINA);
  if (maquina) ids.push(maquina.id);
  if (setor) {
    const alvo = PROCEDIMENTO_USUARIO + (NOME_SETOR_PROCEDIMENTO[setor] ?? normalizar(setor));
    const doSetor = procs.find((p) => normalizar(p.titulo) === alvo);
    if (doSetor) ids.push(doSetor.id);
  }
  return ids;
}

function rascunhoParaRH(nome: string, ticketId: string, setor: string, data: string, usuario: string, email: string, faltando: string[]) {
  const linhas = [
    "Olá!",
    "",
    `Recebi a solicitação para ${nome}${setor ? ` (${setor})` : ""}${data ? `, com início em ${dataBr(data)}` : ""}. Abri o chamado ${ticketId}.`,
  ];
  if (usuario) linhas.push("", `O usuário de rede será ${usuario} e o e-mail ${email}.`);
  if (faltando.length) linhas.push("", "Para deixar tudo pronto, preciso de:", ...faltando.map((f) => `- ${f}`));
  linhas.push("", "Aviso assim que a máquina estiver pronta.");
  return { assunto: "", corpo: linhas.join("\n") };
}

async function criar(sb: SupabaseClient, corpo: Record<string, unknown>) {
  const assunto = String(corpo.assunto ?? "").slice(0, 300);
  const texto = semAssinatura(String(corpo.corpo ?? "")).slice(0, 4000);
  const mensagemId = String(corpo.mensagem_id ?? "").replace(/[^\w.@<>=+-]/g, "").slice(0, 200);
  const remetenteNome = String(corpo.remetente_nome ?? "");
  const hoje = new Date();
  const hojeIso = hoje.toISOString().slice(0, 10);

  if (mensagemId) {
    const { data: existente } = await sb.from("tickets").select("id").ilike("descricao", `%${mensagemId}%`).limit(1);
    if (existente?.length) return { ok: true, duplicado: true, ticket_id: existente[0].id };
  }

  const nome = nomeDoEmail(assunto, texto);
  const avisos: string[] = [];
  const faltando: string[] = [];
  if (!nome) faltando.push("nome completo do colaborador");

  const { textoAnonimo, trocas } = (() => {
    const r = esconder(`Assunto: ${assunto}\n\n${texto}`, nome ?? "", [remetenteNome], EMPRESAS);
    return { textoAnonimo: r.texto, trocas: r.trocas };
  })();

  let ia: Extracao | null = null;
  try {
    ia = await extrairComIA(textoAnonimo, hojeIso);
  } catch (erro) {
    avisos.push(`a IA não respondeu (${(erro as Error).message}); só os dados lidos por regra foram usados`);
  }

  const setor = setorDoTexto(texto) ?? (ia?.setor || "");
  const dataInicio = dataDeInicio(texto, new Date(Date.UTC(hoje.getUTCFullYear(), hoje.getUTCMonth(), hoje.getUTCDate()))) ?? (ia?.data_inicio || null);
  if (!setor) faltando.push("setor");
  if (!dataInicio) faltando.push("data de início");
  for (const f of ia?.faltando ?? []) {
    if (!/setor|data|in[íi]cio|nome/i.test(f)) faltando.push(f);
  }

  const [historico, procs] = await Promise.all([
    sb.from("tickets").select("usuario").limit(5000),
    sb.from("procedimentos").select("id, titulo"),
  ]);
  const login = nome && DOMINIO ? acesso(nome, DOMINIO, (historico.data ?? []).map((h) => h.usuario as string)) : null;
  if (login) avisos.push(...login.avisos);
  if (nome && !DOMINIO) avisos.push("DOMINIO_EMAIL não configurado: usuário e e-mail não foram calculados");

  const equipamentos = equipamentosPedidos(ia?.equipamentos ?? [], texto);
  const acessos = ia?.acessos ?? [];
  const pendentes = checklist(login?.usuario ?? "", login?.email ?? "", setor, equipamentos, acessos);
  const agora = Date.now();
  const timeline = [
    { data: new Date(agora).toISOString(), texto: "Solicitação recebida do RH por e-mail e chamado aberto automaticamente", tipo: "concluido" },
    ...pendentes.map((p, i) => ({ data: new Date(agora + i + 1).toISOString(), texto: p, tipo: "pendente" })),
  ];

  const nomeExibido = nome ?? "colaborador novo (nome não identificado)";
  const descricao = [
    `Colaborador novo: ${nomeExibido}`,
    setor ? `Setor: ${setor}` : "",
    ia?.cargo ? `Cargo: ${ia.cargo}` : "",
    dataInicio ? `Início: ${dataBr(dataInicio)}` : "",
    login ? `Usuário: ${login.usuario} · E-mail: ${login.email}` : "",
    equipamentos.length ? `Equipamentos extras: ${equipamentos.join("; ")}` : "",
    acessos.length ? `Acessos: ${acessos.join("; ")}` : "",
    ia?.observacoes ? `Observações: ${ia.observacoes}` : "",
    faltando.length ? `Faltando no e-mail do RH: ${faltando.join("; ")}` : "",
  ].filter(Boolean).join("\n") + `\n\nOrigem: e-mail do RH${mensagemId ? ` (id ${mensagemId})` : ""}`;

  let numero = await proximoId(sb);
  let ticketId = "";
  for (let tentativa = 0; tentativa < 5; tentativa++) {
    ticketId = `${PREFIXO_ID}-` + String(numero).padStart(4, "0");
    const { error } = await sb.from("tickets").insert({
      id: ticketId,
      user_id: DONO,
      titulo: PREFIXO_TITULO + nomeExibido,
      descricao,
      usuario: nome ?? "",
      departamento: setor,
      categoria: "hardware",
      subcategoria: "notebooks",
      prioridade: "alta",
      impacto: "baixo",
      urgencia: "alta",
      tipo: "solicitacao",
      status: dataInicio ? "agendado" : "aberto",
      historico_status: [{ para: dataInicio ? "agendado" : "aberto", em: new Date().toISOString(), criacao: true }],
      data_agendamento: dataInicio ? `${dataInicio}T09:00:00-03:00` : null,
      procedimentos: procedimentosDoSetor(procs.data ?? [], setor),
      timeline,
      anexos: [],
      com_ia: !!ia,
      ia_sugestao: ia ? { origem: "onboarding", setor: ia.setor, data_inicio: ia.data_inicio, modelo: MODELO } : null,
    });
    if (!error) break;
    if (error.code !== "23505" || tentativa === 4) throw new Error(`não consegui criar o chamado: ${error.message}`);
    numero++;
  }

  const rascunho = rascunhoParaRH(nomeExibido, ticketId, setor, dataInicio ?? "", login?.usuario ?? "", login?.email ?? "", faltando);
  rascunho.assunto = assunto.match(/^\s*re\s*:/i) ? assunto : `Re: ${assunto}`;

  return {
    ok: true, duplicado: false, ticket_id: ticketId, nome, setor, data_inicio: dataInicio,
    usuario: login?.usuario ?? "", email: login?.email ?? "", faltando, avisos,
    rascunho_resposta: rascunho, privacidade: { enviado_a_ia: ia ? textoAnonimo : "", trocas },
  };
}

async function lembretes(sb: SupabaseClient, dias: number) {
  const limite = new Date(Date.now() + dias * 86400000).toISOString();
  const { data, error } = await sb.from("tickets")
    .select("id, titulo, usuario, departamento, status, data_agendamento, timeline")
    .like("titulo", `${PREFIXO_TITULO}%`)
    .in("status", ["agendado", "aberto", "andamento", "aguardando"])
    .order("data_agendamento", { ascending: true, nullsFirst: false });
  if (error) throw error;
  const itens = (data ?? [])
    .filter((t) => !t.data_agendamento || t.data_agendamento <= limite)
    .map((t) => {
      const pend = ((t.timeline ?? []) as { tipo: string; texto: string }[]).filter((p) => p.tipo === "pendente");
      return {
        id: t.id, nome: t.titulo.slice(PREFIXO_TITULO.length), setor: t.departamento,
        inicio: t.data_agendamento ? dataBr(String(t.data_agendamento).slice(0, 10)) : "sem data",
        atrasado: !!t.data_agendamento && new Date(t.data_agendamento).getTime() < Date.now(),
        pendentes: pend.map((p) => p.texto),
      };
    });
  const blocos = itens.map((i) =>
    `${i.id} · ${i.nome}${i.setor ? ` (${i.setor})` : ""} · início ${i.inicio}${i.atrasado ? " · JÁ PASSOU" : ""}\n` +
    (i.pendentes.length ? i.pendentes.map((p) => `  [ ] ${p}`).join("\n") : "  tudo feito, falta só fechar o chamado"));

  const sla = await slaEmAlerta(sb);
  const partes: string[] = [];
  if (sla.length) {
    partes.push("SLA — chamados que pedem atenção hoje\n" + sla.map((s) =>
      `${s.estourado ? "ESTOURADO" : "em risco "} ${s.id} · ${s.titulo} · ${s.prioridade} · ` +
      (s.estourado ? `passou ${fmtHoras(-s.restante)} da meta de ${s.meta}h` : `restam ${fmtHoras(s.restante)} de ${s.meta}h`) +
      (s.pausado ? " (relógio parado)" : "")).join("\n"));
  }
  if (itens.length) partes.push(`Onboarding — começando em até ${dias} dia(s)\n\n` + blocos.join("\n\n"));

  const estourados = sla.filter((s) => s.estourado).length;
  const assunto = [
    estourados ? `${estourados} chamado(s) fora do SLA` : sla.length ? `${sla.length} chamado(s) em risco de SLA` : "",
    itens.length ? `${itens.length} onboarding(s) em até ${dias} dia(s)` : "",
  ].filter(Boolean).join(" · ");
  return {
    ok: true, itens, sla,
    enviar: itens.length > 0 || sla.length > 0,
    assunto,
    resumo_texto: partes.join("\n\n————\n\n"),
  };
}

/* chamados abertos com relógio (v29+) que estão estourados ou já usaram 80% da meta */
async function slaEmAlerta(sb: SupabaseClient) {
  const { data, error } = await sb.from("tickets")
    .select("id, titulo, prioridade, tipo, status, historico_status")
    .in("status", ["aberto", "andamento", "aguardando", "escalado", "agendado"]);
  if (error) throw error;
  return (data ?? [])
    .map((t) => ({ t, s: slaDe({ ...t, historico_status: (t.historico_status ?? []) as Historico }) }))
    .filter(({ s }) => s && (s.estourado || (s.risco && !s.pausado)))
    .map(({ t, s }) => ({ id: t.id as string, titulo: t.titulo as string, prioridade: t.prioridade as string, ...s! }))
    .sort((a, b) => a.restante - b.restante);
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return resposta({ erro: "use POST" }, 405);
  if (!TOKEN || !DONO) return resposta({ erro: "configure ONBOARDING_TOKEN e ONBOARDING_USER_ID nos segredos da função" }, 500);
  if (!mesmoToken(req.headers.get("x-onboarding-token") ?? "", TOKEN)) return resposta({ erro: "não autorizado" }, 401);

  let corpo: Record<string, unknown>;
  try {
    corpo = await req.json();
  } catch {
    return resposta({ erro: "corpo inválido" }, 400);
  }

  const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
    auth: { persistSession: false },
  });

  try {
    if (corpo.acao === "lembretes") return resposta(await lembretes(sb, Math.min(Math.max(Number(corpo.dias) || 2, 0), 30)));
    if (corpo.acao === "criar") return resposta(await criar(sb, corpo));
    return resposta({ erro: "acao deve ser 'criar' ou 'lembretes'" }, 400);
  } catch (erro) {
    return resposta({ ok: false, erro: (erro as Error).message }, 500);
  }
});
