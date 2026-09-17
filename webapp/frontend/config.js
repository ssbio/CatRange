// CatRange hosted-service frontend configuration.
//
// This file exists so the static frontend (this folder) can be uploaded to
// a plain static-file host (e.g. Hostinger Premium Web Hosting's
// public_html) that is SEPARATE from the machine running the Python
// API/worker backend. Edit CATRANGE_API_BASE below to the backend's full
// URL before uploading.
//
// Leave it as an empty string only if the frontend and backend are served
// from the exact same origin (e.g. both proxied by one nginx instance, as
// in webapp/docker-compose.yml's default single-host layout) — in that
// case relative "/api/..." requests already work.
window.CATRANGE_API_BASE = "";

// Example for a split deployment, where the backend runs on its own server
// or subdomain (e.g. behind api.catrange.sahassbio.com, or a bare IP while
// testing):
//
//   window.CATRANGE_API_BASE = "https://api.catrange.sahassbio.com";
//
// No trailing slash. The backend's FastAPI app already sends permissive
// CORS headers (see webapp/api/app/main.py), so cross-origin requests from
// this static site work without further backend changes.
