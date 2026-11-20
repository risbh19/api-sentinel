# Use one application and a separate worker process

FastAPI owns the HTTP contract. PostgreSQL is the persistence boundary. The API
checks readiness with a bounded SELECT 1 under a dedicated login. Liveness
works during a database outage. Neither check reads tenant data.

The browser fetches readiness on page load and on request. Nginx serves the
built React application and proxies the fixed readiness path inside Compose.
This keeps database credentials on the server and makes cross-origin access
unnecessary. Vite provides a loopback proxy during frontend development.

The worker uses the API image with a separate entry point. At this stage it
waits for shutdown and has no database credentials. Durable job storage,
claiming and recovery require migrations in subsequent slices.
