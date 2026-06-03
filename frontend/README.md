# Avenue MDP Frontend

This frontend is a Next.js App Router application migrated from the `Hieu123k/MDP-ver1.0` variant repository.

## Local Development

Run the FastAPI backend on `http://localhost:8000`, then run:

```bash
npm install
npm run dev
```

Set:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

With that value, the browser calls FastAPI root routes directly, such as `/auth/login`.

## Production

For production Docker builds, leave `NEXT_PUBLIC_API_URL` empty. The browser will call same-origin `/api/*`, and Caddy strips `/api` before forwarding requests to FastAPI.

```env
NEXT_PUBLIC_API_URL=
```
