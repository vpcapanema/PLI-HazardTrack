/**
 * Camada persistente de cameras DER-SP (overlay visual, sem auto-refresh).
 */
(function (global) {
  "use strict";

  const CLIENT_CACHE_MS = 24 * 60 * 60 * 1000;
  const CAMERA_SVG = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    + '<path d="M17 10.5V7a2 2 0 0 0-2-2H5A2 2 0 0 0 3 7v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3.5l4 2.5v-8l-4 2.5z"/>'
    + "</svg>"
  );

  let hlsInstance = null;
  let clientCache = null;
  let clientCacheAt = 0;
  let deps = null;

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function cameraIcon(maintenance) {
    const cls = maintenance ? " is-maintenance" : "";
    return L.divIcon({
      className: "der-camera-icon",
      html: `<span class="der-camera-marker${cls}">${CAMERA_SVG}</span>`,
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    });
  }

  function destroyHlsPlayer() {
    if (hlsInstance) {
      try {
        hlsInstance.destroy();
      } catch {
        /* ignore */
      }
      hlsInstance = null;
    }
  }

  function showLoaderError(loader, message) {
    if (!loader) return;
    loader.textContent = message;
    loader.classList.remove("hidden");
  }

  function initHlsInPopup(popupEl) {
    const root = popupEl?.querySelector?.(".der-camera-popup");
    const video = root?.querySelector("video");
    const loader = root?.querySelector(".der-camera-loader");
    const streamPath = root?.dataset?.streamPath;
    if (!video || !streamPath || !deps?.apiUrl) {
      showLoaderError(loader, "Player indisponivel");
      return;
    }

    const src = deps.apiUrl(`/api/der/hls/${streamPath}`);
    let ready = false;
    const onReady = () => {
      if (ready) return;
      ready = true;
      loader?.classList.add("hidden");
      video.classList.add("ready");
      video.play().catch(() => {});
    };
    video.addEventListener("playing", onReady, { once: true });
    video.addEventListener("loadeddata", onReady, { once: true });

    if (global.Hls?.isSupported()) {
      destroyHlsPlayer();
      hlsInstance = new global.Hls({
        maxBufferLength: 8,
        liveSyncDurationCount: 3,
        fragLoadingMaxRetry: 8,
        manifestLoadingMaxRetry: 4,
        levelLoadingMaxRetry: 4,
      });
      hlsInstance.loadSource(src);
      hlsInstance.attachMedia(video);
      hlsInstance.on(global.Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });
      hlsInstance.on(global.Hls.Events.ERROR, (_, data) => {
        if (!data.fatal) return;
        if (data.type === global.Hls.ErrorTypes.NETWORK_ERROR) {
          hlsInstance.startLoad();
          return;
        }
        if (data.type === global.Hls.ErrorTypes.MEDIA_ERROR) {
          hlsInstance.recoverMediaError();
          return;
        }
        showLoaderError(loader, "Stream indisponivel");
        destroyHlsPlayer();
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      video.addEventListener("error", () => {
        showLoaderError(loader, "Stream indisponivel");
      }, { once: true });
    } else {
      showLoaderError(loader, "HLS indisponivel neste navegador");
    }
  }

  function openDerCameraPopup(map, cam) {
    if (!map || !cam) return;

    if (cam.maintenance) {
      L.popup({ maxWidth: 340, className: "der-camera-popup-wrap" })
        .setLatLng([cam.lat, cam.lng])
        .setContent(
          `<div class="der-camera-maintenance">`
          + `<strong>${escapeHtml(cam.label)}</strong><br>`
          + `Camera em manutencao — stream indisponivel.`
          + `</div>`,
        )
        .openOn(map);
      return;
    }

    const nome = cam.nome
      ? `<div>${escapeHtml(cam.nome)}</div>`
      : "";
    const html = (
      `<div class="der-camera-popup" data-stream-path="${escapeHtml(cam.stream_path)}">`
      + `<header><strong>${escapeHtml(cam.label)}</strong>${nome}</header>`
      + `<div class="der-camera-video-wrap">`
      + `<div class="der-camera-loader">Conectando...</div>`
      + `<video muted playsinline autoplay preload="auto"></video>`
      + `<span class="der-camera-live">AO VIVO</span>`
      + `</div>`
      + `<div class="der-camera-meta">`
      + `<div>Rodovia: ${escapeHtml(cam.rodovia)} · ${escapeHtml(cam.km)}</div>`
      + `<div>Local: ${escapeHtml(cam.local)}</div>`
      + `<div>Sentido: ${escapeHtml(cam.sentido || "Ambos")}</div>`
      + `</div>`
      + `</div>`
    );

    const popup = L.popup({
      maxWidth: 360,
      className: "der-camera-popup-wrap",
      closeButton: true,
    })
      .setLatLng([cam.lat, cam.lng])
      .setContent(html);

    popup.on("add", () => {
      initHlsInPopup(popup.getElement());
    });
    popup.on("remove", destroyHlsPlayer);
    popup.openOn(map);
  }

  async function fetchCameras() {
    const now = Date.now();
    if (clientCache && (now - clientCacheAt) < CLIENT_CACHE_MS) {
      return clientCache;
    }
    const res = await fetch(deps.apiUrl("/api/der/cameras"));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    if (!body.success) throw new Error(body.error || "falha DER cameras");
    clientCache = body.cameras || [];
    clientCacheAt = now;
    return clientCache;
  }

  async function loadCamerasLayer(state) {
    if (!state?.layers?.cameras) return;
    if (state.layers.cameras.getLayers().length > 0) return;

    const cameras = await fetchCameras();
    cameras.forEach((cam) => {
      if (!Number.isFinite(cam.lat) || !Number.isFinite(cam.lng)) return;
      const marker = L.marker([cam.lat, cam.lng], {
        icon: cameraIcon(cam.maintenance),
        title: cam.label,
      });
      marker._pliLayerKind = "cameras";
      marker._pliLayerProps = cam;
      marker.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        openDerCameraPopup(state.map, cam);
      });
      marker.addTo(state.layers.cameras);
    });
  }

  function attachEvents(state, options) {
    deps = options;
    const cb = document.getElementById("layer-cameras");
    if (!cb) return;

    cb.addEventListener("change", async (e) => {
      const on = e.target.checked;
      options.MAP_LAYER_STATE.cameras = on;
      options.saveMapLayerState();
      if (on) {
        try {
          await loadCamerasLayer(state);
          state.map.addLayer(state.layers.cameras);
        } catch (err) {
          console.warn("falha ao carregar cameras DER:", err);
          e.target.checked = false;
          options.MAP_LAYER_STATE.cameras = false;
          options.saveMapLayerState();
        }
      } else {
        state.map.removeLayer(state.layers.cameras);
        destroyHlsPlayer();
      }
    });
  }

  async function restore(state, options) {
    deps = options;
    if (!options.MAP_LAYER_STATE.cameras) {
      state.map.removeLayer(state.layers.cameras);
      return;
    }
    try {
      await loadCamerasLayer(state);
      state.map.addLayer(state.layers.cameras);
    } catch (err) {
      console.warn("falha ao restaurar cameras DER:", err);
    }
  }

  function bringToFront(state) {
    state.layers.cameras?.eachLayer?.((layer) => {
      if (layer.bringToFront) layer.bringToFront();
    });
  }

  global.PLI_DER_CAMERAS = {
    attachEvents,
    restore,
    bringToFront,
    openDerCameraPopup,
    loadCamerasLayer,
  };
}(window));
