import { createRequire } from "module";
const require = createRequire(import.meta.url);

export default function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "s-maxage=300, stale-while-revalidate=60");
  res.setHeader("Content-Type", "application/json");

  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }

  try {
    // require() en Node.js resuelve rutas relativas al archivo actual
    // y funciona en el entorno serverless de Vercel
    const data = require("./manengis_tactico.json");
    res.status(200).json(data);
  } catch (e) {
    res.status(500).json({
      error: "JSON no encontrado",
      detalle: e.message,
      hint: "Asegurate de que manengis_tactico.json esta en api/ y esta commiteado en el repo"
    });
  }
}
