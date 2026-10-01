// NVIDIA NIM (OpenAI-compatible). Same models and settings as brain/providers.py.
const BASE = process.env.NVIDIA_BASE_URL || "https://integrate.api.nvidia.com/v1";
const KEY = process.env.NVIDIA_API_KEY || "";
export const CHAT_MODEL = process.env.NVIDIA_CHAT_MODEL || "nvidia/nemotron-3-super-120b-a12b";
export const EMBED_MODEL = process.env.NVIDIA_EMBED_MODEL || "nvidia/llama-nemotron-embed-vl-1b-v2";
export const EMBED_DIM = 1024;
export const hasModel = () => KEY.length > 0;

export type Usage = { prompt_tokens: number; completion_tokens: number };

async function post(path: string, payload: unknown): Promise<any> {
  // The hosted endpoints return 429/5xx under load; back off instead of failing the request.
  for (let attempt = 0; attempt < 4; attempt++) {
    const r = await fetch(`${BASE}/${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${KEY}`, "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (r.ok) return r.json();
    if (![429, 500, 502, 503, 504].includes(r.status) || attempt === 3) {
      throw new Error(`NVIDIA ${path} ${r.status}: ${(await r.text()).slice(0, 200)}`);
    }
    await new Promise((res) => setTimeout(res, 2 ** attempt * 500));
  }
}

export async function embed(texts: string[], task: "passage" | "query"): Promise<number[][] | null> {
  if (!hasModel()) return null;
  const out: number[][] = [];
  for (let i = 0; i < texts.length; i += 50) {
    const data = await post("embeddings", {
      model: EMBED_MODEL, input: texts.slice(i, i + 50), input_type: task,
      encoding_format: "float", truncate: "END", dimensions: EMBED_DIM,
    });
    out.push(...data.data.sort((a: any, b: any) => a.index - b.index).map((d: any) => d.embedding));
  }
  return out;
}

export async function complete(system: string, user: string, maxTokens = 600): Promise<{ text: string; usage: Usage } | null> {
  if (!hasModel()) return null;
  const data = await post("chat/completions", {
    model: CHAT_MODEL, temperature: 0, max_tokens: maxTokens,
    chat_template_kwargs: { enable_thinking: false },   // grounded answers need the answer, not the scratchpad
    messages: [{ role: "system", content: system }, { role: "user", content: user }],
  });
  return { text: data.choices[0].message.content ?? "", usage: data.usage ?? { prompt_tokens: 0, completion_tokens: 0 } };
}
