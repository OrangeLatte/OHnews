# OH!News Web（Next.js 构建）
FROM node:22-alpine AS builder
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
# rewrites 在 build 时编译进 routes-manifest，origin 必须构建期注入
ARG OHNEWS_API_ORIGIN=http://127.0.0.1
ENV OHNEWS_API_ORIGIN=${OHNEWS_API_ORIGIN}
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app/web
ENV NODE_ENV=production
COPY --from=builder /app/web ./
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
