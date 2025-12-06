import { useEffect, useMemo, useState } from "react";

function Dashboard({
  analysisDone,
  processing,
  speedLimit,
  videoUrl,
  videoName,
  csvUrl,
  pdfUrl,
  reportData,
  onDownloadReport
}) {
  const [hydrated, setHydrated] = useState(false);
  const [state, setState] = useState({ videoUrl, csvUrl, pdfUrl, reportData, speedLimit });
  const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

  const resolveUrl = useMemo(() => {
    return (u) => {
      if (!u) return "";
      // If backend returned a relative api path, prefix with API_BASE
      if (u.startsWith("/api")) return `${API_BASE}${u}`;
      return u;
    };
  }, [API_BASE]);

  // Robust PDF download via fetch + Blob (avoids popup issues and ensures download)
  const handlePdfDownload = async () => {
    try {
      const url = state.pdfUrl || pdfUrl;
      if (!url) return;
      const res = await fetch(url, { method: "GET" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = "reporte_infracciones.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objUrl);
    } catch (e) {
      console.error("Error descargando PDF:", e);
    }
  };
  useEffect(() => {
    // hydrate from localStorage if navigated to /results
    try {
      const raw = localStorage.getItem("trafficEyeResult");
      if (raw) {
        const data = JSON.parse(raw);
        const result = data?.result || {};
        setState({
          videoUrl: resolveUrl(result.video_url) || videoUrl,
          csvUrl: resolveUrl(result.csv_url) || csvUrl,
          pdfUrl: resolveUrl(result.pdf_url) || pdfUrl,
          reportData: {
            infractions: result.infractions || reportData?.infractions || [],
            metrics: result.metrics || reportData?.metrics || { vehiclesDetected: 0, infractions: 0, maxSpeed: 0, avgSpeed: 0 },
            speed_limit_kmh: result.speed_limit_kmh || reportData?.speed_limit_kmh || speedLimit || null
          },
          speedLimit: result.speed_limit_kmh || speedLimit
        });
      }
    } catch {}
    setHydrated(true);
  }, []);
  const [videoError, setVideoError] = useState(false);
  const [videoLoading, setVideoLoading] = useState(false);
  const infractions = (state.reportData?.infractions) || (reportData.infractions) || [];
  const metrics = (state.reportData?.metrics) || (reportData.metrics) || {};
  const limitToShow = state.reportData?.speed_limit_kmh ?? state.speedLimit ?? reportData.speed_limit_kmh ?? speedLimit;
  const videoMissing = state.reportData?.video_missing || false;

  return (
    <section className="dashboard">
      <div className="card">
        <div className="card-header">
          <div>
            <p className="eyebrow">Pantalla 2 · Visualizacion</p>
            <h3>Dashboard y video</h3>
          </div>
          <span className="badge muted">
            {analysisDone || hydrated ? "Analisis listo" : processing ? "Procesando..." : "Esperando datos"}
          </span>
        </div>

        <div className="grid two">
          <div className="card nested">
            <div className="card-header slim">
              <p>Video procesado</p>
              <small>{videoName || "Aun no has cargado un video."}</small>
            </div>
            <div className="video-wrapper">
              {(analysisDone || hydrated) && (state.videoUrl || videoUrl) ? (
                <>
                  {videoLoading && <div className="placeholder"><p>Cargando video procesado...</p></div>}
                  {videoError && <div className="placeholder"><p style={{color: "red"}}>Error al cargar el video. Verifica que el backend esté corriendo y el video se haya generado correctamente.</p></div>}
                  <video
                    key={state.videoUrl || videoUrl}
                    src={state.videoUrl || videoUrl}
                    controls
                    controlsList="nodownload"
                    style={{display: videoLoading || videoError ? "none" : "block"}}
                    onLoadStart={() => {
                      setVideoLoading(true);
                      setVideoError(false);
                    }}
                    onLoadedData={() => setVideoLoading(false)}
                    onError={() => {
                      setVideoLoading(false);
                      setVideoError(true);
                      console.error("Error al cargar el video desde:", state.videoUrl || videoUrl);
                    }}
                  />
                </>
              ) : (
                <div className="placeholder">
                  <p>
                    {videoMissing
                      ? "El análisis se completó sin generar video. Descarga el CSV para revisar infracciones. Revisa la configuración de codecs o instala FFmpeg."
                      : "Sube el video y presiona \"Procesar\" para habilitar la reproducción y los resultados. Aquí se mostrará el video devuelto por el backend."}
                  </p>
                </div>
              )}
            </div>
            <div className="chips">
              <span className="chip">Velocidad maxima: {limitToShow || "--"} km/h</span>
              <span className="chip">Formato aceptado: mp4, avi, mov, mkv</span>
            </div>
          </div>

          <div className="card nested">
            <div className="card-header slim">
              <p>Metricas generales</p>
              <small>Datos retornados por el backend al finalizar el analisis.</small>
            </div>
            {analysisDone || hydrated ? (
              <div className="metrics-grid">
                <div className="metric">
                  <span className="label">Vehículos detectados</span>
                  <strong>{metrics.vehiclesDetected || 0}</strong>
                </div>
                <div className="metric">
                  <span className="label">Infracciones</span>
                  <strong>{metrics.infractions || 0}</strong>
                </div>
                <div className="metric">
                  <span className="label">Velocidad promedio</span>
                  <strong>{metrics.avgSpeed ? `${Number(metrics.avgSpeed).toFixed(1)} km/h` : "--"}</strong>
                </div>
              </div>
            ) : (
              <div className="placeholder">
                <p>Procesa el video para ver las metricas.</p>
              </div>
            )}
            <ul className="logic">
              <li> </li>
              <li> </li>
              <li> </li>
            </ul>
          </div>
        </div>

        <div className="card nested full">
          <div className="table-header">
            <div>
              <p className="eyebrow">Tabla de datos procesados</p>
              <h4>Vehiculos con exceso de velocidad</h4>
            </div>
            <div className="table-actions">
              {(state.csvUrl || csvUrl) ? (
                <a className="secondary-btn" href={state.csvUrl || csvUrl} download>
                  Descargar CSV
                </a>
              ) : null}
              {(state.pdfUrl || pdfUrl) ? (
                <button className="primary-btn" type="button" onClick={handlePdfDownload}>
                  Descargar PDF
                </button>
              ) : null}
            </div>
          </div>
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Clase</th>
                  <th>Velocidad</th>
                  <th>Limite</th>
                  <th>Exceso</th>
                  <th>Timestamp</th>
                  <th>Frame</th>
                </tr>
              </thead>
              <tbody>
                {(analysisDone || hydrated) && infractions.length > 0 ? (
                  infractions.map((infraction) => (
                    <tr key={infraction.id}>
                      <td>{infraction.id}</td>
                      <td>{infraction.label || "-"}</td>
                      <td>{infraction.speed_kmh?.toFixed?.(1) || infraction.speed_kmh || "-"} km/h</td>
                      <td>{limitToShow ? `${limitToShow} km/h` : "--"}</td>
                      <td>+{infraction.excess_kmh?.toFixed?.(1) || infraction.excess_kmh || 0} km/h</td>
                      <td>{infraction.timestamp || "--"}</td>
                      <td>{infraction.frame ?? "--"}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="7" className="empty">
                      Aun no hay datos. Ejecuta el analisis para poblar la tabla.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}

export default Dashboard;
