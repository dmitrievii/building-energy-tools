import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = __dirname;
const port = Number(process.env.PORT || 5173);
const buildId = '20260705TCS120';

const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8'
};

function noStoreHeaders(contentType = 'text/plain; charset=utf-8') {
  return {
    'Content-Type': contentType,
    'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, s-maxage=0',
    'Pragma': 'no-cache',
    'Expires': '0',
    'Surrogate-Control': 'no-store',
    'X-TCS-Build': buildId
  };
}

function resolveInside(base, requestPath) {
  const resolved = path.resolve(base, requestPath);
  if (!resolved.startsWith(base)) return null;
  return resolved;
}

function safePath(urlPath) {
  const clean = decodeURIComponent(urlPath.split('?')[0]).replace(/^\/+/, '');
  if (!clean) return path.join(root, 'index.html');

  // Vite convention: files inside ./public are served from the web root.
  // The avatar metadata intentionally uses /assets/avatars/... while the
  // physical files live in thermal_comfort_studio_web/public/assets/avatars/....
  if (clean.startsWith('assets/') || clean.startsWith('reference/') || clean === 'asset_audit.json') {
    return resolveInside(path.join(root, 'public'), clean);
  }

  return resolveInside(root, clean);
}

const server = http.createServer(async (req, res) => {
  try {
    const url = req.url || '/';
    if (url.startsWith('/__health')) {
      res.writeHead(200, noStoreHeaders('application/json; charset=utf-8'));
      res.end(JSON.stringify({ app: 'thermal-comfort-studio', status: 'ok', buildId }));
      return;
    }

    const cleanPath = decodeURIComponent(url.split('?')[0]).replace(/^\/+/, '');
    const isPublicAssetRequest = cleanPath.startsWith('assets/') || cleanPath.startsWith('reference/') || cleanPath === 'asset_audit.json';

    let resolved = safePath(url);
    if (!resolved) throw new Error('Invalid path');
    let fileStat;
    try {
      fileStat = await stat(resolved);
      if (fileStat.isDirectory()) resolved = path.join(resolved, 'index.html');
    } catch {
      if (isPublicAssetRequest) {
        res.writeHead(404, noStoreHeaders('text/plain; charset=utf-8'));
        res.end(`Missing public asset: ${cleanPath}\nExpected under: ${path.join(root, 'public', cleanPath)}`);
        return;
      }
      resolved = path.join(root, 'index.html');
    }
    const ext = path.extname(resolved).toLowerCase();
    const body = await readFile(resolved);
    res.writeHead(200, noStoreHeaders(types[ext] || 'application/octet-stream'));
    res.end(body);
  } catch (error) {
    res.writeHead(500, noStoreHeaders());
    res.end(String(error?.stack || error));
  }
});

server.on('error', error => {
  if (error.code === 'EADDRINUSE') {
    console.error(`Port ${port} is already in use. If Thermal Comfort Studio is already running, open http://127.0.0.1:${port}/?clearCache=1&cacheBust=${buildId}`);
  } else {
    console.error(error);
  }
  process.exit(1);
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Thermal Comfort Studio running at http://127.0.0.1:${port}/?clearCache=1&cacheBust=${buildId}`);
  console.log(`Build: ${buildId}`);
  console.log('Cache-control is disabled for all local responses to avoid stale browser builds.');
});
