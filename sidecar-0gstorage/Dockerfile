FROM node:22-alpine

WORKDIR /app

COPY package.json tsconfig.json ./
RUN npm install --production=false

COPY src ./src
RUN npx tsc

EXPOSE 7000
CMD ["node", "dist/index.js"]
