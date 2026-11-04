import { deepStrictEqual as assertEquals } from "node:assert";
import { acesso, checklist, dataDeInicio, equipamentosPedidos, esconder, nomeDoEmail, semAssinatura, setorDoTexto } from "./extrair.ts";

const HOJE = new Date(Date.UTC(2026, 9, 31));

Deno.test("nome pelo assunto", () => {
  assertEquals(nomeDoEmail("Solicitação de máquina - Maria Clara Souza", ""), "Maria Clara Souza");
  assertEquals(nomeDoEmail("RE: ENC: solicitacao de maquina + joão da silva", ""), "João da Silva");
  assertEquals(nomeDoEmail("Solicitação de máquina para a colaboradora Ana Lima (início 03/11)", ""), "Ana Lima");
  assertEquals(nomeDoEmail("Solicitação de máquina", "Oi, tudo bem?"), null);
});

Deno.test("nome pela linha Nome: tem prioridade", () => {
  assertEquals(nomeDoEmail("Solicitação de máquina", "Nome completo: Pedro Henrique Alves\nSetor: OP"), "Pedro Henrique Alves");
});

Deno.test("data de início", () => {
  assertEquals(dataDeInicio("Setor: fiscal\nInício: 05/11", HOJE), "2026-11-05");
  assertEquals(dataDeInicio("Ela começa dia 10/01/2027.", HOJE), "2027-01-10");
  assertEquals(dataDeInicio("Enviado em 30/10\nAdmissão: 12/11/2026", HOJE), "2026-11-12");
  assertEquals(dataDeInicio("Começa dia 15/01", HOJE), "2027-01-15");
  assertEquals(dataDeInicio("sem data", HOJE), null);
});

Deno.test("setor", () => {
  assertEquals(setorDoTexto("Setor: Operacional"), "OP");
  assertEquals(setorDoTexto("Área: Jurídico"), "jurídico");
  assertEquals(setorDoTexto("vai trabalhar no financeiro com a equipe"), "financeiro");
  assertEquals(setorDoTexto("favor pedir para a TI preparar"), null);
});

Deno.test("anonimização antes da IA", () => {
  const { texto, trocas } = esconder(
    "Maria Clara Souza começa dia 05/11. CPF 123.456.789-00, celular (11) 98765-4321, maria@gmail.com. Pedido da Juliana pela Acme.",
    "Maria Clara Souza", ["Juliana Prado"], ["Acme"]);
  assertEquals(texto, "[COLABORADOR] começa dia 05/11. CPF [CPF], celular [TELEFONE], [EMAIL]. Pedido da [PESSOA] pela [EMPRESA].");
  assertEquals(trocas.colaborador, 1);
});

Deno.test("assinatura é cortada", () => {
  assertEquals(semAssinatura("Favor preparar.\n\nAtenciosamente,\nJuliana Prado\nRH - (11) 3333-4444"), "Favor preparar.");
});

Deno.test("login e aviso de login repetido", () => {
  const a = acesso("Maria Clara Souza", "empresa.com", ["Marcos Souza", "Usuário 3"]);
  assertEquals(a?.usuario, "msouza");
  assertEquals(a?.email, "maria.souza@empresa.com");
  assertEquals(a?.avisos.length, 1);
});

Deno.test("checklist", () => {
  const passos = checklist("msouza", "maria.souza@empresa.com", "OP", ["segundo monitor"], ["pasta do financeiro"]);
  assertEquals(passos[0], "Criar o usuário msouza no AD e colocar no grupo do setor OP");
  assertEquals(passos.includes("Providenciar: segundo monitor"), true);
  assertEquals(passos.includes("Liberar acesso: pasta do financeiro"), true);
});

Deno.test("celular de contato não vira pedido de aparelho", () => {
  const contato = "Setor: fiscal\nCelular: (11) 98765-4321\nInício: 10/11";
  assertEquals(equipamentosPedidos(["celular", "segundo monitor"], contato), ["segundo monitor"]);
  assertEquals(equipamentosPedidos(["Celular"], "Telefone: [TELEFONE]"), []);
  const pedido = "Setor: comercial\nCelular: (11) 98765-4321\nVai precisar de um celular corporativo.";
  assertEquals(equipamentosPedidos(["celular corporativo"], pedido), ["celular corporativo"]);
});
