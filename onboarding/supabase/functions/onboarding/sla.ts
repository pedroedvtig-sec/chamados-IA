// Mesmo cálculo de SLA do site (ticket_sys v29+), para o lembrete das 8h.
// Horas úteis: seg–sex, 9h–18h, horário de Brasília (UTC−3, sem horário de verão desde 2019).

export const SLA_META_HORAS: Record<string, number> = { "crítica": 4, "alta": 8, "média": 16, "baixa": 40 };
const INICIO = 9, FIM = 18, OFFSET_MS = -3 * 3600000;
const PAUSA = new Set(["aguardando", "agendado"]);
const ENCERRADO = new Set(["resolvido", "fechado", "cancelado"]);

export function horasUteis(ini: string | Date, fim: string | Date): number {
  // desloca para o "relógio de Brasília" e trabalha com getUTC*
  const a = new Date(ini).getTime() + OFFSET_MS, b = new Date(fim).getTime() + OFFSET_MS;
  if (!(b > a)) return 0;
  let ms = 0;
  const d = new Date(a); d.setUTCHours(0, 0, 0, 0);
  while (d.getTime() < b) {
    const dia = d.getUTCDay();
    if (dia >= 1 && dia <= 5) {
      const ji = d.getTime() + INICIO * 3600000, jf = d.getTime() + FIM * 3600000;
      const s = Math.max(ji, a), e = Math.min(jf, b);
      if (e > s) ms += e - s;
    }
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return ms / 3600000;
}

export type Historico = { para: string; em: string; criacao?: boolean }[];

export function slaDe(t: { status: string; prioridade: string; tipo: string; historico_status: Historico }, agora = new Date()) {
  const h = t.historico_status ?? [];
  if (!h.length || !h[0].criacao || t.tipo === "problema" || ENCERRADO.has(t.status)) return null;
  const meta = SLA_META_HORAS[t.prioridade] ?? 16;
  let gasto = 0;
  for (let i = 0; i < h.length; i++) {
    if (PAUSA.has(h[i].para) || ENCERRADO.has(h[i].para)) continue;
    gasto += horasUteis(h[i].em, i + 1 < h.length ? h[i + 1].em : agora);
  }
  return {
    meta, gasto, restante: meta - gasto,
    pausado: PAUSA.has(t.status),
    estourado: gasto > meta,
    risco: gasto <= meta && gasto >= meta * 0.8,
  };
}

export function fmtHoras(h: number): string {
  const v = Math.abs(h);
  return v < 1 ? `${Math.round(v * 60)}min` : `${v.toFixed(v < 10 ? 1 : 0).replace(".", ",")}h`;
}
