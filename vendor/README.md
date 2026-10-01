# Browser dependencies

The viewer serves these files locally; no CDN or runtime npm installation is required.

- `marked.umd.js`: marked 18.0.14, copied from fragment-view's installed package. License: `marked-LICENSE`.
- `purify.min.js`: DOMPurify 3.4.16, copied from fragment-view's installed package. License: `dompurify-LICENSE`.

When updating, replace the browser distribution and accompanying license together, then run the viewer tests. Node.js and jsdom are used only for tests (`npm ci`, `npm test`).
