# AgriSense Next.js frontend. Build context is the repository root.
FROM node:20-slim

ENV NODE_ENV=development
WORKDIR /app/frontend

# Install dependencies first for better layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy the rest of the frontend (node_modules/.next excluded via .dockerignore).
COPY frontend/ /app/frontend/

EXPOSE 3000

# Dev server is the most robust "just run" path and reads the backend URL at
# runtime. For a production image swap this for: RUN npm run build && npm start.
ENV AGRISENSE_API_BASE_URL=http://backend:8000
CMD ["npm", "run", "dev"]
