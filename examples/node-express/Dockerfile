FROM node:22-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY app.js .
EXPOSE 8001
CMD ["node", "app.js"]
