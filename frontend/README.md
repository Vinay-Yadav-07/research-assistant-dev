# Frontend

Next.js (App Router, TypeScript strict), Tailwind CSS, shadcn/ui. Node version: `.node-version`.

```bash
npm ci
cp .env.example .env.local   # set NEXT_PUBLIC_API_BASE_URL
npm run dev                  # http://localhost:3000
npm run lint && npm run build
npm run gen:api              # regenerate src/lib/api/schema.d.ts from the backend (needs uv)
```

All API calls go through the typed client in `src/lib/api/client.ts`. Run `gen:api` after any backend API change and commit the regenerated schema.
