import os
import cv2
import math
import numpy as np
from collections import deque, defaultdict
import csv
import subprocess
import shutil

from ultralytics import YOLO
from norfair import Detection, Tracker


# ==========================
# Configuracion principal
# ==========================
MODEL_PATH = "yolo11n.pt"  # Modelo YOLO en el workspace
INPUT_VIDEO = "videos/Test5.mp4"
OUTPUT_VIDEO = "speed_estimation.mp4"
DEFAULT_HOMOGRAPHY_PATH = "homography.npz"

CONF_THRES = 0.3
IOU_THRES = 0.45

# Clases de vehiculos a rastrear (ajusta segun el modelo YOLO que uses)
VEHICLE_LABELS = {"car", "truck", "bus", "motorbike", "motorcycle", "bicycle"}

# Suavizado EMA para velocidad (0..1)
SPEED_SMOOTHING = 0.6

# Homografia: calibracion siempre al inicio (ventana principal, video pausado en ~1s)
ROI_WIDTH_METERS = 7.0
ROI_HEIGHT_METERS = 30.0
SPEED_MIN_DISPLACEMENT_M = 0.2  # minimo avance longitudinal para considerar (m)
SPEED_MAX_DT_SEC = 1.0          # ignorar intervalos demasiado grandes (s)
SPEED_BASELINE_FRAMES = 5       # diferencia de posiciones separadas por N frames
# Escala metrica adicional (se ajusta con referencia conocida). 1.0 = sin ajuste
METRIC_SCALE_M = 1.0

# Infracciones por exceso de velocidad
SPEED_LIMIT_KMH = 85.0                  # limite de velocidad configurable (km/h)
# Tiempo minimo sostenido sobre el limite para registrar una infraccion (en segundos)
# Reducido para marcar infracciones con menos tiempo sostenido sobre el limite
VIOLATION_MIN_DURATION_SEC = 1.0
VIOLATION_COOLDOWN_FRAMES = 300         # Tiempo minimo entre registros del mismo ID (frames)


def euclidean_distance(detection, tracked_object):
    p1 = detection.points[0]
    p2 = tracked_object.estimate[0]
    return np.linalg.norm(p1 - p2)


def bbox_to_center(xyxy):
    x1, y1, x2, y2 = xyxy
    return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0], dtype=np.float32)


def bbox_to_footpoint(xyxy):
    x1, y1, x2, y2 = xyxy
    # Punto de contacto con el suelo: centro de la base del bbox
    return np.array([(x1 + x2) / 2.0, y2], dtype=np.float32)


def draw_box_with_id_speed(img, bbox, track_id, label, speed_kmh=None, color=(0, 255, 0)):
    x1, y1, x2, y2 = map(int, bbox)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    text = f"ID {track_id} - {label}"
    if speed_kmh is not None:
        text += f" | {speed_kmh:.1f} km/h"
    else:
        text += " | N/A"
    cv2.putText(img, text, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


def _mouse_collect_points(event, x, y, flags, param):
    # param: [pts, img_disp]
    pts, img_disp = param
    if event == cv2.EVENT_LBUTTONDOWN:
        pts.append((x, y))
        cv2.circle(img_disp, (x, y), 5, (0, 255, 255), -1)
        if len(pts) > 1:
            cv2.line(img_disp, pts[-2], pts[-1], (0, 255, 255), 2)


def calibrate_homography_interactive(frame, window_name="TrafficEye", dst_size_m=(ROI_WIDTH_METERS, ROI_HEIGHT_METERS)):
    # Usar la ventana principal del video (pausada) para seleccionar los 4 puntos del suelo
    show_disp = frame.copy()
    pts = []
    msg = (
        "Calibracion Homografia: clic 4 puntos (suelo) en orden sup-izq, sup-der, inf-der, inf-izq. ENTER confirma, ESC cancela."
    )
    overlay = show_disp.copy()
    cv2.putText(overlay, msg, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.85, show_disp, 0.15, 0, show_disp)
    cv2.imshow(window_name, show_disp)
    cv2.setMouseCallback(window_name, _mouse_collect_points, [pts, show_disp])
    while True:
        cv2.imshow(window_name, show_disp)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            cv2.setMouseCallback(window_name, lambda *args: None)
            return None, None
        if key in (13, 10):  # ENTER
            if len(pts) == 4:
                break
    cv2.setMouseCallback(window_name, lambda *args: None)
    src = np.array(pts, dtype=np.float32)
    Wm, Hm = dst_size_m
    dst = np.array([[0, 0], [Wm, 0], [Wm, Hm], [0, Hm]], dtype=np.float32)
    H, _ = cv2.findHomography(src, dst, method=0)
    return H, src


def _mouse_two_points(event, x, y, flags, param):
    pts, img_disp = param
    if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 2:
        pts.append((x, y))
        cv2.circle(img_disp, (x, y), 6, (0, 255, 0), -1)
        if len(pts) == 2:
            cv2.line(img_disp, pts[0], pts[1], (0, 255, 0), 2)


def calibrate_metric_scale(frame, H, window_name="TrafficEye"):
    # Permite seleccionar dos puntos sobre el mismo carril con distancia conocida en metros
    # Para corregir errores de conversion px->m por configuracion incorrecta de ROI.
    disp = frame.copy()
    msg = (
        "Referencia metrica: clic en 2 puntos sobre el mismo carril con distancia conocida. "
        "Luego introduce la distancia en metros en la consola. ENTER para confirmar."
    )
    overlay = disp.copy()
    cv2.putText(overlay, msg, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.85, disp, 0.15, 0, disp)
    pts = []
    cv2.imshow(window_name, disp)
    cv2.setMouseCallback(window_name, _mouse_two_points, [pts, disp])
    while True:
        cv2.imshow(window_name, disp)
        key = cv2.waitKey(1) & 0xFF
        if key in (13, 10):  # ENTER
            if len(pts) == 2:
                break
        if key == 27:  # ESC
            cv2.setMouseCallback(window_name, lambda *args: None)
            return 1.0
    cv2.setMouseCallback(window_name, lambda *args: None)
    # Warp ambos puntos y medir distancia en unidades homografiadas
    warped = warp_points_to_meters(H, pts)
    d_units = float(np.linalg.norm(warped[1] - warped[0]))
    try:
        known_m = float(input("Introduce la distancia conocida entre los dos puntos (m): ").strip())
        if known_m > 0 and d_units > 0:
            scale = known_m / d_units
            return scale
    except Exception:
        pass
    return 1.0


def load_homography_from_file(path=DEFAULT_HOMOGRAPHY_PATH, fallback_scale=1.0):
    if not os.path.exists(path):
        raise FileNotFoundError(f"No se encontro el archivo de homografia en {path}")
    data = np.load(path)
    H = data["H"]
    src_pts = data["src"]
    width_m = float(data["width_m"]) if "width_m" in data.files else float(ROI_WIDTH_METERS)
    height_m = float(data["height_m"]) if "height_m" in data.files else float(ROI_HEIGHT_METERS)
    metric_scale = float(data["metric_scale"]) if "metric_scale" in data.files else float(fallback_scale)
    return H, src_pts, (width_m, height_m), metric_scale


def save_homography(path, H, src_pts, dst_size_m, metric_scale=1.0):
    np.savez(
        path,
        H=H,
        src=src_pts,
        width_m=dst_size_m[0],
        height_m=dst_size_m[1],
        metric_scale=metric_scale,
    )


def warp_points_to_meters(H, points):
    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    warped = cv2.perspectiveTransform(pts, H)
    return warped.reshape(-1, 2)


def point_in_polygon(pt, poly):
    if poly is None:
        return True
    return cv2.pointPolygonTest(poly.astype(np.float32), (float(pt[0]), float(pt[1])), False) >= 0


def format_timestamp_from_frame(frame_idx, fps):
    secs = frame_idx / float(fps)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = secs % 60.0
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def analyze_video(
    input_video_path,
    output_video_path=OUTPUT_VIDEO,
    speed_limit_kmh=SPEED_LIMIT_KMH,
    use_saved_homography=True,
    interactive_calibration=False,
    display=False,
    homography_path=DEFAULT_HOMOGRAPHY_PATH,
    progress_callback=None,
    violations_csv_path=None,
):
    """
    Ejecuta el pipeline de deteccion + tracking + estimacion de velocidad.

    - Si `use_saved_homography` es True, se intentara cargar la homografia desde `homography_path`.
    - Si no existe y `interactive_calibration` es True, se abrira la ventana para calibrar.
    - `display` controla si se muestran ventanas de OpenCV durante el procesamiento.
    - `progress_callback` recibe enteros 0..100 con el avance aproximado.
    """
    model = YOLO(MODEL_PATH)

    cap = cv2.VideoCapture(input_video_path)
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video de entrada: {input_video_path}")

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_count <= 0:
        frame_count = None
    if not fps or math.isclose(fps, 0.0):
        fps = 60  # valor por defecto si el video no reporta FPS
    fps = float(fps)

    # Intentar codecs compatibles con navegadores en orden de preferencia
    codec_options = [
        ("avc1", "H.264 - avc1"),
        ("H264", "H.264 - H264"),
        ("X264", "H.264 - X264"),
        ("mp4v", "MPEG-4 - mp4v (fallback)")
    ]

    writer = None
    codec_used = None

    for codec, desc in codec_options:
        fourcc = cv2.VideoWriter_fourcc(*codec)
        temp_writer = cv2.VideoWriter(output_video_path, fourcc, fps, (w, h))
        if temp_writer.isOpened():
            writer = temp_writer
            codec_used = codec
            print(f"Usando codec: {desc}")
            break
        temp_writer.release()

    if writer is None or not writer.isOpened():
        raise RuntimeError("No se pudo inicializar VideoWriter con ningún codec disponible")

    # Homografia: usar archivo guardado o calibrar si se solicita.
    global METRIC_SCALE_M
    H_img_to_m = None
    src_poly = None
    if use_saved_homography and os.path.exists(homography_path):
        H_img_to_m, src_poly, _, loaded_scale = load_homography_from_file(
            homography_path, fallback_scale=METRIC_SCALE_M
        )
        METRIC_SCALE_M = loaded_scale
        print(f"✓ Homografía cargada desde {homography_path}")
        print(f"  ROI definido: {src_poly.shape if src_poly is not None else 'None'}")
    if H_img_to_m is None:
        if not interactive_calibration:
            raise RuntimeError(
                "No hay homografia guardada. Ejecuta la calibracion interactiva "
                "o proporciona un archivo homography.npz valido."
            )
        target_frame = int(fps * 1.0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok_first, frame_first = cap.read()
        if not ok_first:
            raise RuntimeError("No se pudo capturar frame de referencia para la calibracion")
        cv2.imshow("TrafficEye", frame_first)
        H_img_to_m, src_poly = calibrate_homography_interactive(
            frame_first, window_name="TrafficEye", dst_size_m=(ROI_WIDTH_METERS, ROI_HEIGHT_METERS)
        )
        if H_img_to_m is None or src_poly is None:
            raise RuntimeError("Calibracion cancelada: se requiere homografia para calcular velocidad")
        METRIC_SCALE_M = calibrate_metric_scale(frame_first, H_img_to_m, window_name="TrafficEye")
        save_homography(
            homography_path,
            H_img_to_m,
            src_poly,
            (ROI_WIDTH_METERS, ROI_HEIGHT_METERS),
            metric_scale=METRIC_SCALE_M,
        )
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # Norfair tracker
    tracker = Tracker(distance_function=euclidean_distance, distance_threshold=30)

    # Historial en coordenadas metricas (m) por ID (guardar indice de frame)
    center_history_m = defaultdict(lambda: deque(maxlen=50))  # id -> deque[(frame_idx, (X_m, Y_m))]
    # Historial de velocidades para suavizado por ventana (ultimos 10)
    speed_history_kmh = defaultdict(lambda: deque(maxlen=20))  # id -> deque[kmh]

    # Indice de frame para usar tiempo exacto del video
    frame_idx = 0

    # Estructuras para registro de infracciones
    violations = []  # lista de dicts {timestamp, frame, id, speed_kmh, label}
    # Inicio del periodo "por encima del limite" por ID (frame en el que supero el limite)
    above_start_frame = {}
    last_violation_frame = {}

    vehicle_stats = defaultdict(lambda: {"label": "veh", "max_speed": 0.0})

    speed_limit_value = float(speed_limit_kmh)

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        # 1) Detecciones con YOLO
        results = model.predict(frame, conf=CONF_THRES, iou=IOU_THRES, verbose=False)[0]
        if results.boxes is None or len(results.boxes) == 0:
            if src_poly is not None:
                cv2.polylines(frame, [src_poly.astype(np.int32)], isClosed=True, color=(255, 200, 0), thickness=2)
            writer.write(frame)
            if display:
                cv2.imshow("TrafficEye", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
            frame_idx += 1
            if progress_callback and frame_count:
                progress_callback(min(100, int((frame_idx / frame_count) * 100)))
            continue

        boxes_xyxy = results.boxes.xyxy.cpu().numpy()
        confs = results.boxes.conf.cpu().numpy()
        clss = results.boxes.cls.cpu().numpy().astype(int)
        labels = [model.names[c] if c in model.names else str(c) for c in clss]

        # 2) Filtrar solo vehiculos y crear detecciones Norfair (usando centro)
        dets = []
        for bbox, score, lab, cls_idx in zip(boxes_xyxy, confs, labels, clss):
            if lab.lower() not in VEHICLE_LABELS:
                continue
            center = bbox_to_center(bbox)
            dets.append(
                Detection(
                    points=np.expand_dims(center, axis=0),
                    scores=np.array([float(score)], dtype=np.float32),
                    data={"bbox": bbox, "label": lab, "cls": int(cls_idx)},
                )
            )

        # 3) Actualizar tracker Norfair
        tracked_objects = tracker.update(detections=dets)

        frame_idx += 1

        # 4) Calcular velocidad (solo homografia) y dibujar
        for tobj in tracked_objects:
            tid = tobj.id
            if tobj.last_detection is None:
                continue
            bbox = tobj.last_detection.data.get("bbox")
            lab = tobj.last_detection.data.get("label", "veh")
            if bbox is None:
                continue

            vehicle_stats[tid]["label"] = lab

            # Usar el punto de contacto con el suelo para evitar errores de perspectiva
            foot = bbox_to_footpoint(bbox)
            speed_kmh = None

            # Calcular en coordenadas metricas si el footpoint esta dentro de ROI
            if H_img_to_m is not None and src_poly is not None and point_in_polygon(foot, src_poly):
                warped = warp_points_to_meters(H_img_to_m, [foot])[0]
                if np.isfinite(warped).all():
                    center_history_m[tid].append((frame_idx, warped * METRIC_SCALE_M))
                    hist_m = center_history_m[tid]
                    # usar baseline de varios frames para evitar jitter
                    if len(hist_m) > SPEED_BASELINE_FRAMES:
                        f0, p0 = hist_m[-1 - SPEED_BASELINE_FRAMES]
                        f1, p1 = hist_m[-1]
                        dt_local = (f1 - f0) / fps
                        if dt_local <= SPEED_MAX_DT_SEC and dt_local > 0:
                            # Usar solo el eje longitudinal (Y) del plano metrico
                            delta_y = float(p1[1] - p0[1])
                            if abs(delta_y) >= SPEED_MIN_DISPLACEMENT_M:
                                m_per_sec = abs(delta_y) / dt_local
                            else:
                                m_per_sec = 0.0
                        else:
                            m_per_sec = 0.0
                        kmh = m_per_sec * 3.6
                        speed_history_kmh[tid].append(kmh)
                        speed_kmh = float(np.mean(list(speed_history_kmh[tid])))
            else:
                # Vehículo fuera del ROI - contar para diagnóstico
                if tid not in vehicle_stats:
                    vehicle_stats[tid] = {"label": lab, "max_speed": 0.0, "outside_roi": True}

            # Detectar infraccion si hay velocidad valida: requiere tiempo sostenido sobre el limite
            is_violation = False
            if speed_kmh is not None and speed_kmh > speed_limit_value:
                # Marcar inicio del periodo sobre el limite si no existia
                if tid not in above_start_frame or above_start_frame[tid] is None:
                    above_start_frame[tid] = frame_idx
                # Duracion actual sobre el limite en segundos
                duration_sec = (frame_idx - above_start_frame[tid]) / fps
                if duration_sec >= VIOLATION_MIN_DURATION_SEC:
                    last_f = last_violation_frame.get(tid, -10**9)
                    if frame_idx - last_f >= VIOLATION_COOLDOWN_FRAMES:
                        is_violation = True
                        last_violation_frame[tid] = frame_idx
                        violations.append({
                            "timestamp": format_timestamp_from_frame(frame_idx, fps),
                            "frame": frame_idx,
                            "id": int(tid),
                            "speed_kmh": float(speed_kmh),
                            "label": str(lab),
                        })
            else:
                # Reiniciar el periodo sobre el limite si baja o no hay velocidad
                above_start_frame[tid] = None

            if speed_kmh is not None:
                vehicle_stats[tid]["max_speed"] = max(vehicle_stats[tid]["max_speed"], float(speed_kmh))

            # Resaltar caja en rojo si esta en infraccion
            color = (0, 0, 255) if is_violation else (0, 255, 0)
            draw_box_with_id_speed(frame, bbox, tid, lab, speed_kmh, color=color)

        # Dibujar poligono de ROI
        if src_poly is not None:
            cv2.polylines(frame, [src_poly.astype(np.int32)], isClosed=True, color=(255, 200, 0), thickness=2)

        writer.write(frame)
        if display:
            cv2.imshow("TrafficEye", frame)
            if cv2.waitKey(1) & 0xFF == 27:  # ESC para salir
                break

        if progress_callback and frame_count:
            progress_callback(min(100, int((frame_idx / frame_count) * 100)))

    cap.release()
    writer.release()
    if display:
        cv2.destroyAllWindows()

    # Si se usó mp4v, recodificar con FFmpeg para compatibilidad con navegadores
    if codec_used == "mp4v":
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            try:
                temp_output = output_video_path + ".temp.mp4"
                os.rename(output_video_path, temp_output)
                subprocess.run(
                    [
                        ffmpeg_path,
                        "-i", temp_output,
                        "-c:v", "libx264",
                        "-preset", "medium",
                        "-crf", "23",
                        "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart",
                        "-y",
                        output_video_path
                    ],
                    check=True,
                    capture_output=True,
                    text=True
                )
                os.remove(temp_output)
                print(f"✓ Video recodificado a H.264 con FFmpeg: {output_video_path}")
                codec_used = "libx264"  # Actualizar codec usado
            except subprocess.CalledProcessError as e:
                print(f"✗ Error al recodificar con FFmpeg: {e.stderr}")
                # Si falla, restaurar el archivo original
                if os.path.exists(temp_output):
                    os.rename(temp_output, output_video_path)
            except Exception as e:
                print(f"✗ Error inesperado al recodificar: {e}")
                if os.path.exists(temp_output):
                    os.rename(temp_output, output_video_path)
        else:
            print("⚠ ADVERTENCIA: Video generado con codec mp4v, puede no reproducirse en navegadores.")
            print("  Para mejor compatibilidad, instala FFmpeg:")
            print("  - Windows: choco install ffmpeg  o  winget install FFmpeg")
            print("  - Linux: sudo apt install ffmpeg")
            print("  - macOS: brew install ffmpeg")

    # Guardar infracciones en CSV (incluso si está vacío)
    csv_path = violations_csv_path or "violations.csv"
    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer_csv = csv.DictWriter(f, fieldnames=["timestamp", "frame", "id", "speed_kmh", "label"])
            writer_csv.writeheader()
            if violations:
                writer_csv.writerows(violations)

    # Preparar salida estructurada para consumir desde API/frontend
    # Calcular velocidad maxima de forma robusta para evitar outliers:
    # usar el percentil 95 de cada historial de velocidad por vehiculo y luego tomar el maximo global.
    vehicles_out = []
    robust_max_speeds = []
    per_vehicle_mean_speeds = []
    for tid, stats in vehicle_stats.items():
        hist = list(speed_history_kmh.get(tid, []))
        if hist:
            perc95 = float(np.percentile(hist, 95))
            robust_max_speeds.append(perc95)
            per_vehicle_mean_speeds.append(float(np.mean(hist)))
            vehicles_out.append({"id": int(tid), "label": stats["label"], "max_speed": perc95})
        else:
            vehicles_out.append({"id": int(tid), "label": stats["label"], "max_speed": float(stats.get("max_speed", 0.0))})
    max_speed = max(robust_max_speeds or [0.0])
    # Media de velocidad global (promedio de las medias por vehiculo con historial)
    avg_speed = float(np.mean(per_vehicle_mean_speeds)) if per_vehicle_mean_speeds else 0.0
    infractions_out = [
        {
            "id": v["id"],
            "label": v["label"],
            "speed_kmh": v["speed_kmh"],
            "excess_kmh": float(v["speed_kmh"] - speed_limit_value),
            "timestamp": v["timestamp"],
            "frame": v["frame"],
        }
        for v in violations
    ]

    # Diagnóstico: contar vehículos fuera del ROI
    vehicles_outside_roi = sum(1 for stats in vehicle_stats.values() if stats.get("outside_roi", False))
    print(f"\n{'='*60}")
    print(f"RESUMEN DEL ANÁLISIS:")
    print(f"  Vehículos detectados: {len(vehicles_out)}")
    print(f"  Vehículos fuera del ROI: {vehicles_outside_roi}")
    print(f"  Vehículos con velocidad medida: {len(vehicles_out) - vehicles_outside_roi}")
    print(f"  Velocidad máxima: {max_speed:.1f} km/h")
    print(f"  Infracciones registradas: {len(infractions_out)}")
    if vehicles_outside_roi > 0 and max_speed == 0.0:
        print(f"\n⚠ ADVERTENCIA: Todos los vehículos están fuera del ROI.")
        print(f"  Recomendación: Recalibra la homografía para este video.")
        print(f"  Ejecuta: python TraficEye.py (modo interactivo)")
    print(f"{'='*60}\n")

    result = {
        "output_video_path": output_video_path,
        "violations_csv": csv_path if violations else None,
        "speed_limit_kmh": speed_limit_value,
        "vehicles": vehicles_out,
        "infractions": infractions_out,
        "metrics": {
            "vehiclesDetected": len(vehicles_out),
            "infractions": len(infractions_out),
            "maxSpeed": max_speed,
            "avgSpeed": avg_speed,
        },
    }
    if progress_callback:
        progress_callback(100)
    return result


def main():
    analyze_video(
        INPUT_VIDEO,
        output_video_path=OUTPUT_VIDEO,
        speed_limit_kmh=SPEED_LIMIT_KMH,
        use_saved_homography=False,
        interactive_calibration=True,
        display=True,
        homography_path=DEFAULT_HOMOGRAPHY_PATH,
        violations_csv_path="violations.csv",
    )


if __name__ == "__main__":
    main()
