FROM node:24.22.3-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:stable-alpine@sha256:3bc3836dc0be3b811f238210360bf8e7ca8a2d0effdae46160bf1f3578710051
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
USER 101:101
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
