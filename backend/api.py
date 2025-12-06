import csv
import shutil
import uuid
from io import BytesIO
from pathlib import Path
from threading import Thread
from typing import Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fpdf import FPDF

from TraficEye import analyze_video, DEFAULT_HOMOGRAPHY_PATH
import cv2
import numpy as np
from numpy import load as np_load
import subprocess

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

for d in (UPLOAD_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# job_id -> status info
JOBS: Dict[str, Dict] = {}

app = FastAPI(title="TrafficEye API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_csv_violations(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    rows = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append(
                    {
                        "timestamp": row.get("timestamp") or "",
                        "frame": int(row.get("frame", 0)),
                        "id": int(row.get("id", 0)),
                        "speed_kmh": float(row.get("speed_kmh", 0.0)),
                        "label": row.get("label") or "",
                        "excess_kmh": None,  # se completa más abajo con el límite
                    }
                )
            except Exception:
                continue
    return rows


def _run_job(job_id: str, video_path: Path, output_video_path: Path, csv_path: Path, speed_limit: float) -> None:
    def update_progress(value: int, message: Optional[str] = None) -> None:
        job = JOBS.get(job_id)
        if not job:
            return
        job["progress"] = int(value)
        if message:
            job["message"] = message

    try:
        JOBS[job_id]["status"] = "processing"
        JOBS[job_id]["message"] = "Procesando video..."
        result = analyze_video(
            str(video_path),
            output_video_path=str(output_video_path),
            speed_limit_kmh=speed_limit,
            use_saved_homography=True,
            interactive_calibration=False,
            display=False,
            homography_path=DEFAULT_HOMOGRAPHY_PATH,
            progress_callback=lambda p: update_progress(p),
            violations_csv_path=str(csv_path),
        )

        infractions = result.get("infractions", [])
        vehicles = result.get("vehicles", [])
        metrics = result.get("metrics", {}) or {}

        # Si hay CSV y la lista de infracciones esta vacia, cargarlo
        if not infractions and csv_path.exists():
            infractions = _read_csv_violations(csv_path)

        # Calcular exceso con el limite de velocidad
        for item in infractions:
            if item.get("excess_kmh") is None:
                item["excess_kmh"] = float(item.get("speed_kmh", 0.0) - speed_limit)

        metrics.setdefault("vehiclesDetected", len(vehicles))
        metrics.setdefault("infractions", len(infractions))

        # Optional: Recode video to browser-friendly codecs (H.264/AAC)
        try:
            if output_video_path.exists() and shutil.which("ffmpeg"):
                recoded_path = output_video_path.with_name("processed_browser.mp4")
                # -y overwrite, -movflags +faststart for streaming, reasonable bitrate
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(output_video_path),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    str(recoded_path),
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # Replace original with recoded for serving
                try:
                    output_video_path.unlink(missing_ok=True)
                except Exception:
                    pass
                recoded_path.rename(output_video_path)
        except Exception:
            # If recode fails, keep original file
            pass

        video_exists = output_video_path.exists()
        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["message"] = "Analisis completado"
        JOBS[job_id]["progress"] = 100
        JOBS[job_id]["result"] = {
            "infractions": infractions,
            "metrics": metrics,
            "speed_limit_kmh": speed_limit,
            "video_name": JOBS[job_id].get("video_name", "video"),
            "video_url": f"/api/result/{job_id}/video" if video_exists else None,
            "csv_url": f"/api/result/{job_id}/csv" if csv_path.exists() else None,
            "pdf_url": f"/api/result/{job_id}/report",
            "video_missing": not video_exists,
        }
        if video_exists:
            JOBS[job_id]["video_path"] = str(output_video_path)
        # Siempre guardar csv_path si el archivo existe (incluso si está vacío)
        if csv_path.exists():
            JOBS[job_id]["csv_path"] = str(csv_path)
        if vehicles:
            JOBS[job_id]["vehicles"] = vehicles
    except Exception as exc:  # noqa: BLE001
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(exc)
        JOBS[job_id]["progress"] = JOBS[job_id].get("progress", 0)


@app.get("/")
async def root():
    return {"status": "ok", "message": "TrafficEye backend listo"}


# ----------------------
# Calibracion via UI
# ----------------------

@app.get("/api/calibration/status")
async def calibration_status():
    exists = Path(DEFAULT_HOMOGRAPHY_PATH).exists()
    return {"homography": "exists" if exists else "missing"}


@app.get("/api/calibration/frame")
async def calibration_frame(video_path: Optional[str] = None, second: float = 1.0):
    """
    Devuelve un frame JPEG del video para permitir seleccionar puntos desde el UI.
    Si no se envia `video_path`, intenta usar el primer video de `backend/videos/`.
    """
    # Seleccionar fuente de video
    src = None
    if video_path:
        src = Path(video_path)
    else:
        # buscar cualquier mp4 en videos/
        vids = list((BASE_DIR / "videos").glob("*.mp4"))
        if vids:
            src = vids[0]
    if not src or not src.exists():
        raise HTTPException(status_code=404, detail="No se encontro un video para la calibracion")

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail="No se pudo abrir el video")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    target_frame = int(max(0, second) * float(fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise HTTPException(status_code=400, detail="No se pudo capturar el frame")

    # Convertir a JPEG en memoria
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise HTTPException(status_code=500, detail="No se pudo codificar la imagen")
    return Response(
        content=buf.tobytes(),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@app.post("/api/calibration/save")
async def calibration_save(
    points: list[list[float]] = Body(..., description="Puntos [x,y] en orden sup-izq, sup-der, inf-der, inf-izq"),
    width_m: float = Body(7.0, description="Ancho ROI en metros"),
    height_m: float = Body(30.0, description="Alto ROI en metros"),
    metric_scale: float = Body(1.0, description="Escala metrica adicional (opcional)"),
):
    """
    Guarda la homografia usando 4 puntos seleccionados desde el UI.
    """
    if len(points) != 4:
        raise HTTPException(status_code=400, detail="Se requieren exactamente 4 puntos para homografia")
    src = np.array(points, dtype=np.float32)
    dst = np.array([[0, 0], [width_m, 0], [width_m, height_m], [0, height_m]], dtype=np.float32)
    H, _ = cv2.findHomography(src, dst, method=0)
    if H is None:
        raise HTTPException(status_code=400, detail="No se pudo calcular la homografia")
    # Guardar archivo homography.npz en BASE_DIR
    np.savez(
        str(BASE_DIR / DEFAULT_HOMOGRAPHY_PATH),
        H=H,
        src=src,
        width_m=width_m,
        height_m=height_m,
        metric_scale=metric_scale,
    )
    return {"status": "saved"}


@app.post("/api/calibration/metric_scale")
async def calibration_metric_scale(
    points: list[list[float]] = Body(..., description="Dos puntos [x,y] en el mismo carril"),
    known_m: float = Body(..., description="Distancia conocida entre los puntos (m)"),
):
    """
    Calcula y guarda la escala métrica (metros por unidad homografiada) usando dos puntos sobre el plano.
    Requiere que `homography.npz` exista previamente (guardado por /api/calibration/save).
    """
    if len(points) != 2:
        raise HTTPException(status_code=400, detail="Se requieren exactamente 2 puntos para la escala métrica")
    if known_m <= 0:
        raise HTTPException(status_code=400, detail="La distancia conocida debe ser mayor a 0")
    hp = BASE_DIR / DEFAULT_HOMOGRAPHY_PATH
    if not hp.exists():
        raise HTTPException(status_code=404, detail="No existe homografia guardada. Guarda primero los 4 puntos.")

    data = np_load(str(hp))
    H = data["H"]
    width_m = float(data["width_m"]) if "width_m" in data.files else 7.0
    height_m = float(data["height_m"]) if "height_m" in data.files else 30.0
    metric_scale_prev = float(data["metric_scale"]) if "metric_scale" in data.files else 1.0

    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    warped = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
    d_units = float(np.linalg.norm(warped[1] - warped[0]))
    if not np.isfinite(d_units) or d_units <= 0:
        raise HTTPException(status_code=400, detail="No se pudo calcular la distancia homografiada")
    metric_scale = known_m / d_units
    # Guardar actualizado
    np.savez(
        str(hp),
        H=H,
        src=data["src"],
        width_m=width_m,
        height_m=height_m,
        metric_scale=metric_scale,
    )
    return {"status": "saved", "metric_scale": metric_scale}


# ----------------------
# Upload previo al analisis
# ----------------------

@app.post("/api/upload")
async def upload_video(video: UploadFile = File(..., description="Video a subir")):
    if not video.filename:
        raise HTTPException(status_code=400, detail="El archivo de video es obligatorio")
    job_id = uuid.uuid4().hex
    upload_path = UPLOAD_DIR / f"{job_id}_{video.filename}"
    with upload_path.open("wb") as buffer:
        shutil.copyfileobj(video.file, buffer)
    return {"job_id": job_id, "video_path": str(upload_path), "video_name": video.filename}


@app.post("/api/analyze")
async def analyze(
    speed_limit: float = Form(..., description="Limite de velocidad en km/h"),
    video: Optional[UploadFile] = File(None, description="Video a procesar"),
    video_path: Optional[str] = Form(None, description="Ruta de video ya subido"),
):
    if video is None and not video_path:
        raise HTTPException(status_code=400, detail="Debe enviar un archivo de video o una ruta de video")

    job_id = uuid.uuid4().hex
    if video is not None:
        if not video.filename:
            raise HTTPException(status_code=400, detail="El archivo de video es obligatorio")
        upload_path = UPLOAD_DIR / f"{job_id}_{video.filename}"
        with upload_path.open("wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
        video_src_path = upload_path
        video_name = video.filename
    else:
        vp = Path(video_path)
        if not vp.exists():
            raise HTTPException(status_code=404, detail="La ruta de video indicada no existe")
        video_src_path = vp
        video_name = vp.name

    output_dir = OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_video_path = output_dir / "processed.mp4"
    csv_path = output_dir / "violations.csv"

    JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Analisis en cola"}
    JOBS[job_id]["video_name"] = video_name

    worker = Thread(
        target=_run_job,
        args=(job_id, video_src_path, output_video_path, csv_path, float(speed_limit)),
        daemon=True,
    )
    worker.start()

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    response = {
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
    }
    if job.get("status") == "completed":
        response["result"] = job.get("result", {})
    return response


def build_pdf(job: Dict) -> bytes:
    result = job.get("result", {})
    infractions = result.get("infractions", [])
    metrics = result.get("metrics", {})
    speed_limit = result.get("speed_limit_kmh", "")
    video_name = result.get("video_name", "video")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Reporte de Infracciones de Velocidad", ln=1)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 8, f"Video analizado: {video_name}", ln=1)
    pdf.cell(0, 8, f"Velocidad maxima configurada: {speed_limit} km/h", ln=1)
    pdf.cell(0, 8, f"Vehiculos detectados: {metrics.get('vehiclesDetected', 0)}", ln=1)
    pdf.cell(0, 8, f"Infracciones: {metrics.get('infractions', 0)}", ln=1)
    pdf.cell(0, 8, f"Velocidad maxima: {metrics.get('maxSpeed', 0):.1f} km/h", ln=1)
    pdf.ln(6)

    if infractions:
        pdf.set_font("Arial", "B", 10)
        headers = ["ID", "Clase", "Velocidad", "Exceso", "Timestamp", "Frame"]
        col_widths = [20, 30, 30, 30, 50, 20]
        for header, width in zip(headers, col_widths):
            pdf.cell(width, 8, header, border=1)
        pdf.ln()

        pdf.set_font("Arial", "", 9)
        for item in infractions:
            pdf.cell(col_widths[0], 8, str(item.get("id", "-")), border=1)
            pdf.cell(col_widths[1], 8, str(item.get("label", "-")), border=1)
            pdf.cell(col_widths[2], 8, f"{item.get('speed_kmh', 0):.1f}", border=1)
            pdf.cell(col_widths[3], 8, f"{item.get('excess_kmh', 0):.1f}", border=1)
            pdf.cell(col_widths[4], 8, str(item.get("timestamp", "-")), border=1)
            pdf.cell(col_widths[5], 8, str(item.get("frame", "-")), border=1)
            pdf.ln()
    else:
        pdf.set_font("Arial", "I", 10)
        pdf.cell(0, 10, "No se registraron infracciones de velocidad.", ln=1)

    out = pdf.output(dest="S")
    # fpdf may return str, bytes, or bytearray depending on version
    if isinstance(out, (bytes, bytearray)):
        pdf_bytes = bytes(out)
    else:
        pdf_bytes = str(out).encode("latin1")
    return pdf_bytes


@app.get("/api/result/{job_id}/video")
async def download_video(job_id: str):
    job = JOBS.get(job_id)
    video_path = None
    if job:
        vp = job.get("video_path")
        if vp:
            video_path = Path(vp)
    # Fallback: buscar directamente en outputs/<job_id>/processed.mp4
    if video_path is None:
        candidate = OUTPUT_DIR / job_id / "processed.mp4"
        if candidate.exists():
            video_path = candidate
    if not video_path or not Path(video_path).exists():
        raise HTTPException(status_code=404, detail="Video procesado no disponible")
    return FileResponse(
        str(video_path),
        media_type="video/mp4",
        filename="analisis.mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache"
        }
    )


@app.get("/api/result/{job_id}/csv")
async def download_csv(job_id: str):
    job = JOBS.get(job_id)
    csv_path = None
    if job:
        cp = job.get("csv_path")
        if cp:
            csv_path = Path(cp)
    # Fallback directo al filesystem
    if csv_path is None:
        candidate = OUTPUT_DIR / job_id / "violations.csv"
        if candidate.exists():
            csv_path = candidate
    if not csv_path or not Path(csv_path).exists():
        raise HTTPException(status_code=404, detail="No hay CSV con infracciones")
    return FileResponse(str(csv_path), media_type="text/csv", filename="violations.csv")


@app.get("/api/result/{job_id}/report")
async def download_report(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="El analisis aun no termina")
    pdf_bytes = build_pdf(job)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="reporte_infracciones.pdf"'},
    )
