import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

export default function Process() {
  const navigate = useNavigate();

  // Upload state
  const [uploading, setUploading] = useState(false);
  const [uploaded, setUploaded] = useState(null); // { job_id, video_path, video_name }

  // Calibration state
  const canvasRef = useRef(null);
  const imgRef = useRef(new Image());
  const [frameUrl, setFrameUrl] = useState("");
  const [points, setPoints] = useState([]); // perspective 4 points
  const [metricPoints, setMetricPoints] = useState([]); // 2 points
  const [knownMeters, setKnownMeters] = useState(10);
  const [savingCalib, setSavingCalib] = useState(false);
  const [perspectiveSaved, setPerspectiveSaved] = useState(false);
  const [metricSaved, setMetricSaved] = useState(null);
  const [speedLimit, setSpeedLimit] = useState(60);

  // Analyze state
  const [analyzing, setAnalyzing] = useState(false);
  const [status, setStatus] = useState(null);

  // Toast notifications
  const [toast, setToast] = useState({ visible: false, message: "", type: "info", hiding: false });
  const showToast = (message, type = "info", duration = 2500) => {
    // show
    setToast({ visible: true, message, type, hiding: false });
    // clear existing timers
    window.clearTimeout(showToast._hideTimer);
    window.clearTimeout(showToast._removeTimer);
    // start graceful hide after duration
    showToast._hideTimer = window.setTimeout(() => {
      setToast((t) => ({ ...t, hiding: true }));
      // remove after CSS transition (~200ms)
      showToast._removeTimer = window.setTimeout(() => {
        setToast({ visible: false, message: "", type, hiding: false });
      }, 220);
    }, Math.max(500, duration));
  };

  const cacheBust = () => `cb=${Date.now()}`;

  const loadFrame = async (videoPath) => {
    if (!videoPath) return;
    const url = `${API_BASE}/calibration/frame?video_path=${encodeURIComponent(
      videoPath
    )}&${cacheBust()}`;
    setFrameUrl(url);
  };

  // Draw function
  const draw = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    const img = imgRef.current;
    if (!canvas || !ctx || !img || !img.complete) return;

    // Fit image to canvas dimensions
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0);

    // Draw perspective points
    ctx.strokeStyle = "#00ccff";
    ctx.fillStyle = "#00ccff";
    ctx.lineWidth = 2;
    points.forEach((p, i) => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = "14px sans-serif";
      ctx.fillText(`${i + 1}`, p.x + 8, p.y - 8);
    });
    if (points.length === 4) {
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      points.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
      ctx.closePath();
      ctx.stroke();
    }

    // Draw metric points/line
    if (metricPoints.length > 0) {
      ctx.strokeStyle = "#ffcc00";
      ctx.fillStyle = "#ffcc00";
      metricPoints.forEach((p, i) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.font = "14px sans-serif";
        ctx.fillText(i === 0 ? "A" : "B", p.x + 8, p.y - 8);
      });
      if (metricPoints.length === 2) {
        ctx.beginPath();
        ctx.moveTo(metricPoints[0].x, metricPoints[0].y);
        ctx.lineTo(metricPoints[1].x, metricPoints[1].y);
        ctx.stroke();
      }
    }
  };

  useEffect(() => {
    const img = imgRef.current;
    img.onload = draw;
  }, []);

  useEffect(() => {
    draw();
  }, [points, metricPoints]);

  useEffect(() => {
    if (frameUrl) {
      imgRef.current.src = frameUrl;
    }
  }, [frameUrl]);

  // Hydrate previously uploaded video and auto-load calibration frame
  useEffect(() => {
    try {
      const saved = localStorage.getItem("trafficEyeUploaded");
      if (saved) {
        const data = JSON.parse(saved);
        if (data?.video_path) {
          setUploaded(data);
          loadFrame(data.video_path);
        }
      }
    } catch (e) {
      // ignore hydration errors
    }
  }, []);

  const handleCanvasClick = (e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;

    if (points.length < 4) {
      setPoints([...points, { x, y }]);
    } else if (metricPoints.length < 2) {
      setMetricPoints([...metricPoints, { x, y }]);
    }
  };

  const resetPoints = () => {
    setPoints([]);
    setMetricPoints([]);
    setMetricSaved(null);
    setPerspectiveSaved(false);
  };

  const onUpload = async (evt) => {
    const file = evt.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      // Backend expects field name 'video'
      form.append("video", file);
      const res = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      setUploaded(data);
      localStorage.setItem("trafficEyeUploaded", JSON.stringify(data));
      await loadFrame(data.video_path);
    } catch (err) {
      console.error(err);
      showToast("Error al subir el video", "error");
    } finally {
      setUploading(false);
    }
  };

  const savePerspective = async () => {
    if (points.length !== 4 || !uploaded?.video_path) {
      alert("Seleccione 4 puntos primero y suba un video");
      return;
    }
    setSavingCalib(true);
    try {
      // Backend expects: { points: [[x,y],...], width_m?, height_m?, metric_scale? }
      const res = await fetch(`${API_BASE}/calibration/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ points: points.map(p => [p.x, p.y]) }),
      });
      if (!res.ok) throw new Error("No se pudo guardar la calibración");
      const data = await res.json();
      if (data?.status !== "saved") throw new Error("No se pudo guardar la calibración");
      setPerspectiveSaved(true);
      showToast("Calibración de perspectiva guardada", "success");
    } catch (err) {
      console.error(err);
      showToast("Error al guardar la calibración", "error");
    } finally {
      setSavingCalib(false);
    }
  };

  const saveMetric = async () => {
    if (metricPoints.length !== 2 || !uploaded?.video_path) {
      alert("Seleccione 2 puntos y suba un video");
      return;
    }
    try {
      // Backend expects: { points: [[x,y],[x,y]], known_m }
      const res = await fetch(`${API_BASE}/calibration/metric_scale`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          points: metricPoints.map(p => [p.x, p.y]),
          known_m: Number(knownMeters),
        }),
      });
      if (!res.ok) throw new Error("No se pudo guardar métrica");
      const data = await res.json();
      if (data?.status !== "saved") throw new Error("No se pudo guardar métrica");
      setMetricSaved(data.metric_scale || true);
      showToast("Calibración métrica guardada", "success");
    } catch (err) {
      console.error(err);
      showToast("Error al guardar las métricas", "error");
    }
  };

  const startAnalyze = async () => {
    if (!uploaded?.video_path) {
      alert("Suba un video primero");
      return;
    }
    setAnalyzing(true);
    try {
      // Backend expects multipart/form-data (Form) for speed_limit and video_path
      const form = new FormData();
      form.append("speed_limit", String(speedLimit));
      form.append("video_path", uploaded.video_path);
      const res = await fetch(`${API_BASE}/analyze`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`No se pudo iniciar: ${txt}`);
      }
      const data = await res.json();
      const jobId = data.job_id;
      // Poll status
      const poll = async () => {
        try {
          const sres = await fetch(`${API_BASE}/status/${jobId}?${cacheBust()}`);
          const sdata = await sres.json();
          setStatus(sdata);
          if (sdata.status === "completed") {
            const result = sdata.result || {
              job_id: jobId,
              video_url: `/api/result/${jobId}/video`,
              csv_url: `/api/result/${jobId}/csv`,
              pdf_url: `/api/result/${jobId}/report`,
              infractions: [],
              metrics: {},
            };
            localStorage.setItem("trafficEyeResult", JSON.stringify({ result }));
            navigate("/results");
          } else if (sdata.status === "error") {
            alert("Error durante el análisis");
            setAnalyzing(false);
          } else {
            setTimeout(poll, 1500);
          }
        } catch (err) {
          console.error(err);
          setTimeout(poll, 2000);
        }
      };
      poll();
    } catch (err) {
      console.error(err);
      showToast("No se pudo iniciar el análisis", "error");
      setAnalyzing(false);
    }
  };

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: 16 }}>
      {toast.visible && (
        <div className={`toast ${toast.type} ${toast.hiding ? 'hide' : ''}`}>
          <span>{toast.message}</span>
        </div>
      )}
      <h2>Proceso: Subida, Calibración y Análisis</h2>

      <section style={{ marginBottom: 16 }}>
        <div className="section-title"><h3>1. Subir Video</h3></div>
        <div className="section-actions">
          <label className="file-input">
            <span>Seleccionar archivo</span>
            <input type="file" accept="video/*" onChange={onUpload} disabled={uploading} />
          </label>
          {uploaded && (
            <div className="chip">Archivo: {uploaded.video_name}</div>
          )}
        </div>
      </section>

      <section style={{ marginBottom: 16 }}>
        <div className="section-title"><h3>2. Calibración</h3></div>
        <div style={{ display: "flex", gap: 16 }}>
          <div>
            <canvas
              ref={canvasRef}
              onClick={handleCanvasClick}
              className="calib-canvas"
              style={{ cursor: "crosshair" }}
            />
            <div className="section-actions">
              <button className="btn" onClick={() => loadFrame(uploaded?.video_path)} disabled={!uploaded}>Recargar frame</button>
              <button className="btn danger" onClick={resetPoints}>Reiniciar puntos</button>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ marginBottom: 12 }}>
              <strong>Perspectiva:</strong>
              <div>Seleccione 4 puntos en el canvas.</div>
              <div className="section-actions">
                <button className="btn primary" onClick={savePerspective} disabled={savingCalib || points.length !== 4 || !uploaded}>Guardar perspectiva</button>
                {perspectiveSaved && <span className="status-ok status-ok-persp">Listo</span>}
              </div>
            </div>
            <div>
              <strong>Métrica:</strong>
              <div>Seleccione 2 puntos y proporcione distancia conocida.</div>
              <label className="number-input">
                <span>Distancia</span>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={knownMeters}
                  onChange={(e) => setKnownMeters(e.target.value)}
                />
              </label>
              <span style={{ marginLeft: 6 }}>metros</span>
              <div style={{ marginTop: 8 }}>
                <button className="btn primary" onClick={saveMetric} disabled={metricPoints.length !== 2 || !uploaded}>Guardar métrica</button>
                {metricSaved && <span className="status-ok">Listo</span>}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <div className="section-title"><h3>3. Analizar</h3></div>
        <div className="section-actions">
          <label className="number-input">
            <span>Límite (km/h)</span>
            <input type="number" min="1" value={speedLimit} onChange={(e)=>setSpeedLimit(Number(e.target.value||0))} />
          </label>
          <button className="btn primary" onClick={startAnalyze} disabled={analyzing || !uploaded}>Iniciar análisis</button>
        </div>
        {status && (
          <div style={{ marginTop: 8 }}>
            Estado: {status.status} {status.progress ? `(${status.progress}%)` : ""}
          </div>
        )}
      </section>
    </div>
  );
}
