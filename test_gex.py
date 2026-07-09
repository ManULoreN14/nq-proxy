import os, time, json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
gex_manual_path = BASE_DIR / "gex_manual.json"

print("--- PROBANDO LECTURA DE GEX MANUAL ---")

try:
    if gex_manual_path.exists():
        with open(gex_manual_path, "r") as _f:
            _gm = json.load(_f)
        
        # Comprobamos la edad del archivo
        _mtime = os.path.getmtime(gex_manual_path)
        _age_h = (time.time() - _mtime) / 3600
        
        if _age_h < 24:
            gex_real_total = _gm.get("valor_total")
            gamma_flip_level = _gm.get("gamma_flip_level")
            print(f"[EXITO] Cargado desde gex_manual.json | total={gex_real_total} | flip={gamma_flip_level} | generado hace {_age_h:.1f}h")
        else:
            print(f"[AVISO] El archivo es demasiado antiguo ({_age_h:.1f}h > 24h).")
    else:
        print("[ERROR] No se encuentra el archivo gex_manual.json en la carpeta.")
except Exception as e:
    print(f"[ERROR FATAL] {e}")