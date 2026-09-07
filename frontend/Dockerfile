# Multi-stage so the runtime image carries only the traced dependencies rather
# than the whole node_modules tree.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Baked in at build time: Next.js inlines NEXT_PUBLIC_* into the client bundle,
# so these are the URLs the browser will call.
ARG NEXT_PUBLIC_CRM_URL=http://localhost:8000
ARG NEXT_PUBLIC_ANALYTICS_URL=http://localhost:8081
ENV NEXT_PUBLIC_CRM_URL=$NEXT_PUBLIC_CRM_URL
ENV NEXT_PUBLIC_ANALYTICS_URL=$NEXT_PUBLIC_ANALYTICS_URL
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -g 1001 nodejs && adduser -S -u 1001 -G nodejs nextjs
COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000

# Docker sets HOSTNAME to the container id, and Next's standalone server binds to
# process.env.HOSTNAME -- so without this it listens only on the container's eth0
# address. Port forwarding still works by luck, but nothing inside the container
# (the healthcheck included) can reach it, and the bind is fragile.
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

CMD ["node", "server.js"]
