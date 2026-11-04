import { deepStrictEqual as assertEquals } from "node:assert";
import { horasUteis, slaDe } from "./sla.ts";

Deno.test("horas úteis em horário de Brasília", () => {
  assertEquals(horasUteis("2026-11-04T10:00:00-03:00", "2026-11-04T12:30:00-03:00"), 2.5);
  assertEquals(horasUteis("2026-11-04T17:00:00-03:00", "2026-11-05T10:00:00-03:00"), 2);       // atravessa a noite
  assertEquals(horasUteis("2026-11-06T17:00:00-03:00", "2026-11-09T10:00:00-03:00"), 2);       // atravessa o fim de semana
  assertEquals(horasUteis("2026-11-04T07:00:00-03:00", "2026-11-04T20:00:00-03:00"), 9);       // fora do expediente não conta
});

Deno.test("SLA pausa em aguardando, não em escalado", () => {
  const base = { status: "andamento", prioridade: "alta", tipo: "incidente" };
  const agora = new Date("2026-11-05T16:00:00-03:00");
  const comPausa = slaDe({ ...base, historico_status: [
    { para: "aberto", em: "2026-11-04T09:00:00-03:00", criacao: true },
    { para: "aguardando", em: "2026-11-04T11:00:00-03:00" },
    { para: "andamento", em: "2026-11-05T15:00:00-03:00" },
  ] }, agora)!;
  assertEquals(comPausa.gasto, 3);
  assertEquals(comPausa.estourado, false);
  const escalado = slaDe({ ...base, historico_status: [
    { para: "aberto", em: "2026-11-04T09:00:00-03:00", criacao: true },
    { para: "escalado", em: "2026-11-04T11:00:00-03:00" },
  ] }, agora)!;
  assertEquals(escalado.gasto, 16);
  assertEquals(escalado.estourado, true);
});

Deno.test("sem SLA: chamado antigo, problema ou encerrado", () => {
  assertEquals(slaDe({ status: "aberto", prioridade: "alta", tipo: "incidente", historico_status: [] }), null);
  assertEquals(slaDe({ status: "aberto", prioridade: "alta", tipo: "problema", historico_status: [{ para: "aberto", em: "2026-11-04T09:00:00-03:00", criacao: true }] }), null);
  assertEquals(slaDe({ status: "resolvido", prioridade: "alta", tipo: "incidente", historico_status: [{ para: "resolvido", em: "2026-11-04T09:00:00-03:00", criacao: true }] }), null);
});
