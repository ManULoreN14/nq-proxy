import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));

export default function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "s-maxage=300, stale-while-revalidate=60");
  res.setHeader("Content-Type", "application/json");

  if (req.method === "OPTIONS") { res.status(204).end(); return; }

  try {
    const filePath = join(__dirname, "manengis_tactico.json");
    const data = readFileSync(filePath, "utf8");
    res.status(200).send(data);
  } catch (e) {
    res.status(500).json({ error: "JSON no encontrado", detalle: e.message });
  }
}
