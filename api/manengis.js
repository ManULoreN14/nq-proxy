import fs from "fs";
import path from "path";

export default function handler(req, res) {
  try {
    const filePath = path.join(process.cwd(), "api", "manengis_tactico.json");
    const data = fs.readFileSync(filePath, "utf8");
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Cache-Control", "s-maxage=300");
    res.setHeader("Content-Type", "application/json");
    res.status(200).send(data);
  } catch (e) {
    res.status(404).json({ error: "JSON no encontrado", detalle: e.message });
  }
}
