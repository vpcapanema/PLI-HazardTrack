/**
 * Preenche URLs e exemplo de fetch na pagina /docs/api.
 */
(function () {
  "use strict";

  function apiUrl(path) {
    const base = window.APP_BASE || "";
    if (!path.startsWith("/")) path = "/" + path;
    return base + path;
  }

  const paths = {
    "api-url-catalog": "/api/public",
    "api-url-live": "/api/public/ua-layers?hazard=geo",
    "api-url-all": "/api/public/ua-layers",
    "api-url-geo": "/api/public/ua-layers?hazard=geo",
    "api-url-hidro": "/api/public/ua-layers?hazard=hidro",
    "api-url-alerts": "/api/public/ua-layers?min_rd=3",
    "api-url-fire-layers": "/api/public/fire-risk/layers?horizonte=observado",
    "api-url-fire-layers-ref":
      "/api/public/fire-risk/layers?horizonte=observado",
    "api-url-fire-snapshot": "/api/public/fire-risk/snapshot",
  };

  const origin = window.location.origin || "";
  Object.entries(paths).forEach(([id, path]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = origin + apiUrl(path);
  });

  const ex = document.getElementById("api-fetch-example");
  const key = window.PLI_PUBLIC_API_KEY || "";
  if (ex) {
    const authHdr = key
      ? '  headers: { "X-API-Key": "<sua-chave>" },\n'
      : "";
    const geo = origin + apiUrl("/api/public/ua-layers?hazard=geo");
    const hidro = origin + apiUrl("/api/public/ua-layers?hazard=hidro");
    const fogo = origin + apiUrl(
      "/api/public/fire-risk/layers?horizonte=observado",
    );
    ex.textContent =
      `const opts = {${authHdr ? `\n${authHdr}` : ""}};\n\n` +
      `// Risco geologico (movimentos de massa)\n` +
      `const geo = await (await fetch("${geo}", opts)).json();\n\n` +
      `// Risco hidrologico (inundacao)\n` +
      `const hidro = await (await fetch("${hidro}", opts)).json();\n\n` +
      `// Risco de fogo (incendios · INPE)\n` +
      `const fogo = await (await fetch("${fogo}", opts)).json();`;
  }
})();
