// Local stand-in for Netlify: bundles netlify/functions/api.mts with esbuild (as Netlify does) and serves
// web/ next to it. Usage: DATABASE_URL=... BRAIN_API_KEY=... node web/dev-server.mjs  → http://localhost:8888
import { build } from "esbuild";
import { createServer } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { pathToFileURL } from "node:url";

const root = new URL("..", import.meta.url).pathname;
const out = join(process.env.TMPDIR || "/tmp", "brain-api.mjs");
await build({ entryPoints: [join(root, "netlify/functions/api.mts")], bundle: true, platform: "node", format: "esm",
              target: "node20", outfile: out, logLevel: "warning" });
const { default: handler } = await import(pathToFileURL(out).href + "?t=" + Date.now());

const TYPES = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".js": "text/javascript", ".png": "image/png" };
const DATA = { "/data/evals.json": "showcase/results.json", "/data/benchmark.json": "benchmark/results.json" };

createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname.startsWith("/api/")) {
    const chunks = []; for await (const c of req) chunks.push(c);
    const body = chunks.length ? Buffer.concat(chunks) : undefined;
    const r = await handler(new Request(url, { method: req.method, headers: req.headers, body: req.method === "GET" ? undefined : body }), {});
    res.writeHead(r.status, Object.fromEntries(r.headers)); res.end(Buffer.from(await r.arrayBuffer()));
    return;
  }
  const file = DATA[url.pathname] ? join(root, DATA[url.pathname]) : join(root, "web", normalize(url.pathname === "/" ? "/index.html" : url.pathname));
  if (!file.startsWith(root) || !existsSync(file)) { res.writeHead(404); res.end("not found"); return; }
  res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
}).listen(8888, () => console.log("http://localhost:8888"));
