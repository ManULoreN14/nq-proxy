/**
 * api/ia.js  —  Proxy Vercel SOLO para la IA
 * ============================================
 * Único endpoint que necesita Vercel.
 * Recibe el prompt del frontend y lo reenvía a Anthropic.
 * Nunca hace peticiones externas de datos → nunca da timeout.
 *
 * Variables de entorno requeridas en Vercel:
 *   ANTHROPIC_API_KEY = sk-ant-...
 */

export const config = { maxDuration: 30 };  // 30s suficiente para Claude

export default async function handler(req, res) {
  // CORS — permite peticiones desde cualquier origen (la app en Vercel/GitHub Pages)
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  if (req.method !== "POST") {
    return res.status(405).json({ error: "Método no permitido. Usa POST." });
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return res.status(500).json({
      error: "ANTHROPIC_API_KEY no configurada en las variables de entorno de Vercel."
    });
  }

  let body;
  try {
    body = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
  } catch {
    return res.status(400).json({ error: "Body no es JSON válido." });
  }

  const { messages, max_tokens = 1800, system } = body;

  if (!messages || !Array.isArray(messages)) {
    return res.status(400).json({ error: "Falta el campo 'messages'." });
  }

  // Construir payload para Anthropic
  const payload = {
    model:      "claude-sonnet-4-20250514",
    max_tokens: Math.min(max_tokens, 4096),
    messages,
  };
  if (system) payload.system = system;

  try {
    const upstream = await fetch("https://api.anthropic.com/v1/messages", {
      method:  "POST",
      headers: {
        "Content-Type":      "application/json",
        "x-api-key":         apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(payload),
    });

    const data = await upstream.json();

    if (!upstream.ok) {
      console.error("Anthropic error:", upstream.status, data);
      return res.status(upstream.status).json({
        error:   data?.error?.message || "Error en Anthropic",
        details: data,
      });
    }

    return res.status(200).json(data);

  } catch (err) {
    console.error("Error de red:", err);
    return res.status(500).json({ error: "Error de red al contactar Anthropic: " + err.message });
  }
}
